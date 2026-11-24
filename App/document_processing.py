import logging
import json
import hashlib
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from App.legal_documents import annotate_document, link_references, version_metadata

log = logging.getLogger(__name__)
ARTICLE_ID = r"\d+(?:-\d+)?"
CLAUSE_ID = rf"{ARTICLE_ID}(?:\.\d+(?:-\d+)?)+"
ARTICLE = re.compile(rf"^Maddə\s+({ARTICLE_ID})\s*\.\s*(.*)$", re.IGNORECASE)
CHAPTER = re.compile(r"^(?:(\d+)(?:-c[ıiuü])?|([IVXLCDM]+))\s+fəsil\b(.*)$", re.IGNORECASE)
CLAUSE = re.compile(rf"^({CLAUSE_ID})\s*\.\s*(.*)$")
NOTE = re.compile(r"^\[(\d+)\]\s+(.+)$")
REFERENCE = re.compile(rf"\b(?:article\s+({CLAUSE_ID}|{ARTICLE_ID})|({CLAUSE_ID}|{ARTICLE_ID})(?:-c[ıiuü])?\s+maddə\w*)", re.IGNORECASE)
MONTHS = r"yanvar|fevral|mart|aprel|may|iyun|iyul|avqust|sentyabr|oktyabr|noyabr|dekabr"


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00ad", "")
    text = re.sub(r"(?im)\bm\s+a\s+d\s+d\s+ə\b", "Maddə", text)
    text = re.sub(r"(?im)\bf\s+ə\s+s\s+i\s+l\b", "fəsil", text)
    text = re.sub(
        r"(?im)^([ \t]*Maddə[ \t]+)(\d(?:[\d \t-]*\d)?)(?=[ \t]*\.)",
        lambda match: match[1] + re.sub(r"[ \t]+", "", match[2]),
        text,
    )
    text = re.sub(r"(?im)^\s*(\[\d+\])\s+(Maddə\s+[^\n]+)", r"\2 \1", text)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n"))


def join_lines(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(line for line in lines if line)).strip()


def split_text(text: str, max_chars: int) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    parts = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= max_chars:
            parts.append(remaining)
            break
        boundaries = list(re.finditer(r"[.!?](?=\s)", remaining[:max_chars + 1]))
        end = boundaries[-1].end() if boundaries and boundaries[-1].end() >= max_chars // 2 else 0
        if not end:
            end = remaining.rfind(" ", 0, max_chars + 1)
        if end <= 0:
            end = max_chars
        parts.append(remaining[:end].strip())
        remaining = remaining[end:].strip()
    return parts


def read_pdf_pages(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as document:
        pages = [page.get_text(sort=True) for page in document]
    missing = sum(not page.strip() for page in pages)
    if missing:
        log.warning("%s has %s pages without extractable text; OCR is required", path.name, missing)
    return pages


def read_document(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8-sig")
    return "\n\n".join(read_pdf_pages(path))


def infer_category(text: str) -> str | None:
    lower = text.casefold().replace("\u0307", "")
    for category, terms in (
        ("exclusion", ("istisna", "exclusion")),
        ("tariff", ("tarif", "sığorta haqq", "premium")),
        ("payout", ("ödəniş", "payout", "compensation")),
        ("rights and duties", ("hüquq və vəzif", "hüquqları və vəzif", "rights and duties")),
        ("contract", ("müqavilə", "contract")),
    ):
        if any(term in lower for term in terms):
            return category
    return None


def document_metadata(text: str, filename: str) -> dict:
    lines = [line for line in text.splitlines() if line]
    law_line = next((index for index, line in enumerate(lines) if "RESPUBLİKASININ QANUNU" in line.upper()), None)
    name = join_lines(lines[:law_line]) if law_line is not None else Path(filename).stem
    name = re.sub(r"^(?:YÜKLƏ\s+)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\[\d+\]\s*$", "", name)
    footer = text[-3000:]
    footer = re.split(r"(?m)^\[\d+\]\s+", footer, maxsplit=1)[0]
    number = re.search(r"(?:№|No\.?|N[°º])\s*([\d]+\s*[-–]\s*[IVX]+Q\w*)", footer, re.IGNORECASE)
    date = re.search(rf"Bakı\s+şəhəri\s*,?\s*(\d{{1,2}}\s+(?:{MONTHS})\s+\d{{4}}(?:-c[ıiuü])?\s+il)\b", footer, re.IGNORECASE)
    lower = name.casefold().replace("\u0307", "")
    insurance_type = next((kind for keyword, kind in (
        ("tibbi", "medical"), ("sosial", "social"), ("aqrar", "agricultural"),
        ("istehsalat", "occupational"), ("icbari", "compulsory"),
    ) if keyword in lower), None)
    return {"law_name": name, "law_number": re.sub(r"\s+", "", number[1]) if number else None,
            "adoption_date": date[1] if date else None, "insurance_type": insurance_type}


def process_document(text: str, filename: str, max_chars: int = 1200, *,
                     pages: list[str] | None = None, prose_clause_pages: frozenset[int] = frozenset()) -> dict:
    originals = pages if pages is not None else [text]
    cleaned = [clean_text(page) for page in originals]
    text = "\n\n".join(cleaned)
    metadata = document_metadata(text, filename)
    document_id = str(uuid5(NAMESPACE_URL, f"insurance-document:{filename}"))
    source = {"document_id": document_id, "document_name": filename,
              "document_type": Path(filename).suffix.lstrip(".").lower()}
    metadata.update(source)
    lines = [(index, line) for index, page in enumerate(cleaned) for line in page.splitlines()]
    chunks = []
    offsets = [0] * len(originals)

    def add_chunk(part, page_index, info, **fields):
        words = part.split()
        pattern = r"\s+".join(map(re.escape, words))
        raw = originals[page_index]
        match = re.compile(pattern).search(raw, offsets[page_index])
        if not match:
            # Heading repair and soft-hyphen removal can alter the extracted spelling.
            loose_words = [r"[\s\u00ad]*".join(map(re.escape, word)) for word in words]
            match = re.compile(r"\s+".join(loose_words)).search(raw, offsets[page_index])
        if not match and ARTICLE.match(part):
            # The parser moves a leading amendment marker into the heading.
            note = re.search(r"\s+(\[\d+\])(?=\s|$)", part)
            if note:
                source_order = f"{note[1]} {part[:note.start()]}{part[note.end():]}"
                raw_pattern = r"\s+".join(map(re.escape, source_order.split()))
                match = re.compile(raw_pattern).search(raw, offsets[page_index])
        if match:
            offsets[page_index] = match.end()
        chapter = info.get("chapter") or {}
        chunk_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{len(chunks)}"))
        chunks.append({"text": part, "doc": filename, "metadata": {
            **metadata, **info, "chunk_id": chunk_id,
            "page_number": page_index + 1 if pages is not None else None,
            "section_title": info.get("article_title") or chapter.get("title"),
            "article_number": info.get("article"),
            "original_text": match.group() if match else part,
            "original_text_verbatim": match is not None,
        }, **fields})

    if not any(ARTICLE.match(line) for _, line in lines):
        for page_index, page in enumerate(cleaned):
            if page_index + 1 in prose_clause_pages:
                content, clause = [], None

                def record_prose():
                    for part in split_text(join_lines(content), max_chars):
                        add_chunk(part, page_index, {"clause": clause, "category": infer_category(part)})

                for line in page.splitlines():
                    if match := CLAUSE.match(line.replace("–", "-")):
                        record_prose()
                        content.clear()
                        clause = match[1]
                    if line:
                        content.append(line)
                record_prose()
                continue
            for paragraph in re.split(r"\n\s*\n", page):
                for part in split_text(join_lines(paragraph.splitlines()), max_chars):
                    add_chunk(part, page_index, {})
        return annotate_document({"doc": filename, "metadata": metadata, "chunks": chunks,
                                  "amendment_notes": {}, "references": []}, originals, cleaned)

    notes = {}
    chapter = None
    article = None
    clause = None
    content = []
    collecting_notes = False
    current_note = None
    last_article = max(index for index, (_, line) in enumerate(lines) if ARTICLE.match(line))
    active_page = 0

    def flush():
        nonlocal content
        body = join_lines(content)
        if body and article:
            for part in split_text(body, max_chars):
                add_chunk(part, active_page, {
                    "chapter": chapter, "article": article["number"],
                    "article_title": article["title"], "clause": clause,
                    "category": infer_category(article["title"] + " " + part),
                }, note_ids=re.findall(r"\[(\d+)\]", part), references=[])
        content = []

    for line_index, (page_index, line) in enumerate(lines):
        if page_index != active_page:
            flush()
            active_page = page_index
        note_match = NOTE.match(line)
        if note_match and line_index > last_article:
            flush()
            collecting_notes = True
            current_note = note_match[1]
            notes[current_note] = note_match[2]
            continue
        if collecting_notes:
            if line and current_note:
                notes[current_note] += " " + line
            continue
        chapter_match = CHAPTER.match(line)
        article_match = ARTICLE.match(line)
        clause_match = CLAUSE.match(line)
        if chapter_match:
            flush()
            chapter = {"number": chapter_match[1] or chapter_match[2], "title": chapter_match[3].strip() or None}
            article = None
            clause = None
        elif article_match:
            flush()
            article = {"number": article_match[1], "title": article_match[2]}
            clause = None
            content = [line]
        elif clause_match and article and clause_match[1].split(".")[0] == article["number"]:
            flush()
            clause = clause_match[1]
            content = [line]
        elif article:
            content.append(line)
        elif chapter and not chapter["title"] and line:
            chapter = {**chapter, "title": line}
    flush()

    targets = {}
    for index, chunk in enumerate(chunks):
        info = chunk["metadata"]
        targets.setdefault(info["article"], index)
        if info["clause"]:
            targets.setdefault(info["clause"], index)
    references = []
    for index, chunk in enumerate(chunks):
        for match in REFERENCE.finditer(chunk["text"]):
            target = match[1] or match[2]
            preceding = chunk["text"][max(0, match.start() - 150):match.start()]
            external = re.search(r"(?:“[^”]+”|Mülki Məcəllə)[^.;:]{0,100}(?:Qanununun|Məcəlləsinin)\s*$", preceding, re.IGNORECASE)
            reference = {"source_chunk": index, "target": target,
                         "target_chunk": None if external else targets.get(target)}
            chunk["references"].append(reference)
            references.append(reference)
    return annotate_document({"doc": filename, "metadata": metadata, "chunks": chunks,
                              "amendment_notes": notes, "references": references}, originals, cleaned)


def load_documents(directory: Path, max_chars: int = 1200, *, staged: bool = False) -> list[dict]:
    documents = []
    registry = directory / "manifest.json" if staged else directory.parent / "legal_source_versions.json"
    provenance = json.loads(registry.read_text(encoding="utf-8")) if registry.is_file() else {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in {".txt", ".pdf"}:
            if staged and path.name not in provenance:
                continue
            content = path.read_bytes()
            version = provenance.get(path.name, {})
            if staged and hashlib.sha256(content).hexdigest() != version.get("version_id"):
                raise ValueError(f"Staged source bytes do not match its manifest: {path.name}")
            pages = read_pdf_pages(path) if path.suffix.lower() == ".pdf" else None
            if staged and pages is not None and version.get("page_ranges"):
                included = {page for first, last in version["page_ranges"] for page in range(first, last+1)}
                pages = [page if i in included else "" for i, page in enumerate(pages, 1)]
            document = process_document("" if pages is not None else read_document(path), path.name, max_chars, pages=pages,
                                        prose_clause_pages=frozenset(version.get("prose_clause_pages", ())) if staged else frozenset())
            version_metadata(document, content, version)
            if staged:
                identity = {"law_name": version["title"], "document_title": version["title"],
                            "legal_document_type": version["legal_type"], "legal_hierarchy": version["legal_type"]}
                document["metadata"].update(identity)
                if version.get("companion"):
                    document["metadata"]["companion"] = version["companion"]
                if version.get("reference_aliases"):
                    document["metadata"]["reference_aliases"] = version["reference_aliases"]
                for chunk in document["chunks"]:
                    chunk["metadata"].update(identity)
                if not document["chunks"]:
                    raise ValueError(f"Staged source has no extracted passages: {path.name}")
            if document["chunks"]:
                documents.append(document)
    if staged and {document["doc"] for document in documents} != provenance.keys():
        raise ValueError("Incomplete staged legal source manifest")
    link_references(documents)
    return documents
