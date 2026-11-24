"""Conservative source annotations and a corpus-local legal reference graph."""

import logging
import re
import unicodedata
import hashlib
from datetime import date
from collections import defaultdict

from App.azerbaijani import normalize_az


log = logging.getLogger(__name__)
ID = r"\d+(?:-\d+)?(?:\.\d+(?:-\d+)?)*"
ARTICLE_HEADING = re.compile(rf"^Maddə\s+({ID})\s*\.", re.I)
SECTION = re.compile(r"^(?:(\d+|[IVXLCDM]+)(?:-c[ıiuü])?\s+)?bölmə\b[.:\s–-]*(.*)$", re.I)
DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4}(?:-c[ıiuü]\s+il)?)"
EFFECTIVE = re.compile(rf"^\s*(?:qüvvəyə minmə tarixi|effective date)\s*:\s*({DATE})\s*\.?\s*$", re.I | re.M)
AMENDED = re.compile(rf"^\s*(?:son dəyişiklik tarixi|amendment date)\s*:\s*({DATE})\s*\.?\s*$", re.I | re.M)
VALID_UNTIL = re.compile(rf"^\s*(?:qüvvədə olma müddətinin sonu|valid until)\s*:\s*({DATE})\s*\.?\s*$", re.I | re.M)
NUMBERED_REF = re.compile(rf"\b(?:article\s+(?P<english>{ID})|(?P<az>{ID})(?:-c[ıiuü])?\s+(?:maddə|bənd|hissə)\w*)\b", re.I)
UNNUMBERED = re.compile(r"\b(?:Məcəllənin|Qanunun)\s+müvafiq\s+(?:maddə|bənd)\w*", re.I)
LOCAL = re.compile(r"\bbu\s+(?:qanunun|məcəllənin|qaydaların|maddənin)\s*$", re.I)
NAMED = re.compile(r"(?:[“«\"]([^”»\"]+)[”»\"](?:\s+[\w-]+){0,4}\s*(?:Qanununun|Məcəlləsinin|Qaydalarının)|"
                   r"\b(Mülki Məcəllə)sinin)\s*$", re.I)
UNKNOWN_SCOPE = re.compile(r"\b(?:qanununun|qanunun|məcəlləsinin|qaydalarının|qanunvericiliyin|məcəllənin|qaydaların|maddənin)\s*$", re.I)

# Kept in application metadata rather than the vector payload so an annotation-only
# change preserves the legacy collection address and the existing vector cache.
APP_METADATA = frozenset({"document_title", "legal_document_type", "legal_hierarchy", "section", "paragraph_number",
                          "subparagraph_number", "effective_date", "amendment_date", "parent_passage_id",
                          "valid_until", "declared_validity"})
VERSION_FIELDS = {"published_at", "effective_from", "effective_until", "amended_at", "version_id", "is_current",
                  "source_url", "retrieved_at"}
APP_METADATA |= VERSION_FIELDS


def date_value(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        months = "yanvar fevral mart aprel may iyun iyul avqust sentyabr oktyabr noyabr dekabr".split()
        parts = value.casefold().split()
        try:
            return date(int(parts[2].split("-")[0]), months.index(parts[1]) + 1, int(parts[0]))
        except (ValueError, IndexError):
            return None


def version_metadata(document, source_bytes, provenance):
    metadata = document["metadata"]
    fields = {key: None for key in VERSION_FIELDS}
    fields.update(version_id=hashlib.sha256(source_bytes).hexdigest(),
                  effective_from=metadata.get("effective_date"), effective_until=metadata.get("valid_until"),
                  amended_at=metadata.get("amendment_date"))
    if provenance.get("version_id") == fields["version_id"]:
        fields.update({key: provenance[key] for key in VERSION_FIELDS - {"version_id"} if key in provenance})
    metadata.update(fields)
    for chunk in document["chunks"]:
        chunk["metadata"].update(fields)


def applies_on(metadata, requested_date):
    when = date_value(requested_date)
    start, end = (date_value(metadata.get(field)) for field in ("effective_from", "effective_until"))
    if end is None and metadata.get("is_current") is True:
        observed = metadata.get("retrieved_at")
        end = date_value(observed[:10]) if observed else None
    return bool(when and start and end and start <= when <= end)


def annotate_document(document, originals, cleaned):
    metadata = document["metadata"]
    raw = "\n".join(originals)
    opening = "\n".join(cleaned)[:1500]
    has_law_title = "respublikasının qanunu" in normalize_az(opening)
    legal_type = "law" if has_law_title else "cabinet_decision" if re.search(
        r"NAZİRLƏR KABİNETİ[\s\S]{0,70}Q\s*Ə\s*R\s*A\s*R", opening, re.I) else None
    metadata.update(document_title=metadata.get("law_name") or document["doc"], legal_document_type=legal_type,
                    legal_hierarchy={"law": "statute", "cabinet_decision": "cabinet_decision"}.get(legal_type),
                    effective_date=explicit_date(EFFECTIVE, raw), amendment_date=explicit_date(AMENDED, raw),
                    valid_until=explicit_date(VALID_UNTIL, raw), declared_validity=explicit_date(
                        re.compile(r"^\s*(?:hüquqi status|legal status)\s*:\s*(qüvvədədir|qüvvədən düşüb|in force|repealed)\s*$", re.I | re.M), raw))
    section = None
    by_article = {}
    for page in cleaned:
        for line in page.splitlines():
            if match := SECTION.fullmatch(line):
                section = {"number": match[1], "title": match[2] or None}
            if match := ARTICLE_HEADING.match(line):
                by_article.setdefault(match[1], section)
    for chunk in document["chunks"]:
        info = chunk["metadata"]
        clause = (info.get("clause") or "").split(".")
        info.update({key: metadata[key] for key in APP_METADATA if key in metadata},
                    section=by_article.get(info.get("article")),
                    paragraph_number=".".join(clause[:2]) if len(clause) > 1 else None,
                    subparagraph_number=".".join(clause) if len(clause) > 2 else None,
                    parent_passage_id=info["chunk_id"])
    document["extraction_audit"] = [page_diagnostics(page) for page in originals]
    document["original_extracted_pages"] = list(originals)
    log.debug("Legal extraction audit", extra={"event": "legal_extraction_audit", "document": document["doc"],
                                                 "pages": document["extraction_audit"]})
    return document


def explicit_date(pattern, text):
    dates = set(pattern.findall(text))
    return next(iter(dates)) if len(dates) == 1 else None


def page_diagnostics(text):
    scripts = {unicodedata.name(char, "").split(" ")[0] for char in set(text) if char.isalpha()}
    note_roles = defaultdict(list)
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*\[\d+\]", line):
            role = "amendment" if re.search(r"dəyişiklik|qüvvədən düş", line, re.I) else (
                "editorial" if re.search(r"redaksiya", line, re.I) else
                "footnote" if re.search(r"haşiyə|footnote", line, re.I) else "numbered_note"
            )
            note_roles[role].append(i)
    return {
        "mixed_latin_cyrillic": {"LATIN", "CYRILLIC"}.issubset(scripts),
        "malformed_characters": len(re.findall(r"\ufffd|\x00|[\ud800-\udfff]", text)),
        "possible_broken_words": len(re.findall(r"[^\W\d_]\s*[-\u00ad]\s*\n\s*[^\W\d_]", text)),
        "suspicious_whitespace_runs": len(re.findall(r"[^\S\r\n]{3,}", text)),
        "possible_page_number_lines": [line for line in text.splitlines() if re.fullmatch(r"\s*\d{1,4}\s*", line)],
        "numbered_legal_lines": sum(bool(re.match(rf"^\s*(?:Maddə\s+)?{ID}\s*\.", line, re.I)) for line in text.splitlines()),
        "numbered_note_lines": sum(bool(re.match(r"^\s*\[\d+\]", line)) for line in text.splitlines()),
        "possible_amendment_lines": sum(bool(re.search(r"dəyişiklik\w*|qüvvədən düşmüş", line, re.I)) for line in text.splitlines()),
        "note_line_roles": dict(note_roles),
    }


def title_key(value):
    return " ".join(re.findall(r"\w+", normalize_az(value).removesuffix(" haqqında")))


def link_references(documents):
    aliases = defaultdict(set)
    provisions = defaultdict(list)
    descendants = defaultdict(list)
    doc_by_name = {document["doc"]: document["metadata"]["document_id"] for document in documents}
    for document in documents:
        meta = document["metadata"]
        doc_id = meta["document_id"]
        if meta.get("legal_document_type") or meta.get("law_name") != document["doc"].rsplit(".", 1)[0]:
            for title in (meta["law_name"], *meta.get("reference_aliases", ())):
                aliases[title_key(title)].add(doc_id)
        for i, chunk in enumerate(document["chunks"]):
            info = chunk["metadata"]
            for number in filter(None, (info.get("article"), info.get("clause"))):
                provisions[doc_id, number].append((i, info["chunk_id"]))
            clause_parts = (info.get("clause") or "").split(".")
            for depth in range(2, len(clause_parts)):
                descendants[doc_id, ".".join(clause_parts[:depth])].append(info["chunk_id"])

    for document in documents:
        doc_id = document["metadata"]["document_id"]
        for chunk in document["chunks"]:
            info = chunk["metadata"]
            references = []
            for match in NUMBERED_REF.finditer(chunk["text"]):
                prefix = chunk["text"][max(0, match.start() - 180):match.start()]
                number = match["english"] or match["az"]
                target_doc, kind, start = doc_id, "local", match.start()
                if explicit := LOCAL.search(prefix):
                    start -= len(prefix) - explicit.start()
                elif named := NAMED.search(prefix):
                    candidates = aliases.get(title_key(named[1] or named[2]), [])
                    target_doc, kind = (next(iter(candidates)) if len(candidates) == 1 else None), "named_source"
                    start -= len(prefix) - named.start()
                elif unknown := UNKNOWN_SCOPE.search(prefix):
                    target_doc, kind = None, "unknown_source"
                    start -= len(prefix) - unknown.start()
                targets = [point_id for _, point_id in provisions.get((target_doc, number), ())]
                if targets:
                    targets.extend(descendants.get((target_doc, number), ()))
                references.append(reference(info, target_doc, number, kind, chunk["text"][start:match.end()], targets))
            for match in UNNUMBERED.finditer(chunk["text"]):
                references.append(reference(info, None, None, "unnumbered", match[0], []))
            companion = document["metadata"].get("companion")
            if companion and info.get("article") == companion["source_article"]:
                target_doc = doc_by_name.get(companion["document"])
                number = companion["article"]
                targets = [point_id for _, point_id in provisions.get((target_doc, number), ())]
                references.insert(0, reference(info, target_doc, number, "documented_amendment", "", targets))
            chunk["legal_references"] = references


def reference(info, target_doc, number, kind, text, targets):
    return {"source_document_id": info["document_id"], "source_article_id": info.get("article"),
            "source_passage_id": info["chunk_id"], "referenced_document_id": target_doc,
            "referenced_article_id": number, "reference_type": kind, "original_reference_text": text,
            "resolution_status": "verified" if targets else "unresolved", "target_passage_ids": targets}


def contextual_header(chunk):
    meta = chunk.get("metadata") or {}
    chapter, section = meta.get("chapter") or {}, meta.get("section") or {}
    hierarchy = lambda item: " ".join(filter(None, (item.get("number"), item.get("title"))))
    title = meta.get("article_title") or ""
    article = " — ".join(filter(None, (meta.get("article_number") or meta.get("article"),
                                       title if len(title) <= 140 else "")))
    fields = (("Sənəd", meta.get("document_title")), ("Fəsil", hierarchy(chapter)), ("Bölmə", hierarchy(section)),
              ("Maddə", article), ("Bənd", meta.get("subparagraph_number") or meta.get("paragraph_number")),
              ("Qüvvəyə minmə", meta.get("effective_date")))
    return "\n".join(f"{label}: {value}" for label, value in fields if value and len(value) <= 180)
