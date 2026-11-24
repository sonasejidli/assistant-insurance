"""Assemble indexed provisions into request-local, provenance-preserving evidence."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
import re
from urllib.parse import quote

from App.azerbaijani import surface_tokens
from App.legal_documents import date_value, title_key
from App.observability import event, retrieval_trace, stage_timing
from App.query_plan import passage_key
from App.system import distinct_evidence, surrounding_evidence


@dataclass(frozen=True)
class EvidencePackage:
    hits: list[dict]
    items: list[dict]
    relationships: list[dict]
    conflicts: list[dict]
    missing_parts: set[str]
    required_part_passages: dict[str, set[str]] = field(default_factory=dict)


BENEFICIARY_IDENTITY = re.compile(r"faydalanan şəxs.*?şəxsiyyət vəsiqə", re.I)


def qualification_groups(primary, by_id, associations, questions, budget=6, *, scoped=False):
    """Follow verified clause numbering for requested document lists and controlling exclusions."""
    by_clause = defaultdict(dict)
    for point_id, (hit, _) in by_id.items():
        info = hit.get("metadata") or {}
        if clause := info.get("clause"):
            by_clause[hit["doc"]].setdefault(clause, []).append(point_id)
    added, required, attributed = [], {}, defaultdict(set)
    primary_ids = {(hit.get("metadata") or {}).get("chunk_id") for hit in primary}
    for part, question in questions.items():
        text = question.casefold()
        documents = bool(re.search(r"\bhansı\b[^?]{0,36}\bsənəd\w*", text))
        exclusion = bool(re.search(r"\b(?:imtina|istisna)\w*", text))
        identity = scoped and documents and bool(re.search(r"şəxsiyyət sənəd", text))
        if not (documents or exclusion):
            continue
        for hit in primary:
            if part not in associations.get(passage_key(hit), ()):
                continue
            info = hit.get("metadata") or {}
            if ("auditor" in text and "auditor" not in (info.get("law_name") or "").casefold()
                    or re.search(r"\b(?:iş qəza|istehsalat)", text) and info.get("insurance_type") != "occupational"):
                continue
            number = info.get("clause") or ""
            parent, _, _ = number.rpartition(".")
            indexed = by_clause[hit["doc"]]
            for root in (number, parent):
                roots = indexed.get(root, ())
                if identity:
                    roots = [key for key in roots if by_id[key][0]["text"].lstrip().startswith(f"{root}. ")]
                if not roots:
                    continue
                root_text = " ".join(by_id[key][0]["text"].casefold() for key in roots)
                if "aşağıdakı" not in root_text or not ((documents and "sənəd" in root_text)
                                                         or (exclusion and "imtina" in root_text)):
                    continue
                # A targeted document question needs only its matched item, not the complete list.
                children = [key for clause, keys in indexed.items() if clause.rpartition(".")[0] == root for key in keys]
                subject = re.search(r"\b(?:şəxsiyyət|etibarnamə|arayış|qəsdən)\w*", text)
                pattern = subject[0] if subject else None
                if exclusion and re.search(r"\bhaqq\w*\s+ödənilmə", text):
                    pattern = r"haqq\w*\s+(?:ödəmə|ödənilmə)"
                if identity:
                    children = [key for key in children if BENEFICIARY_IDENTITY.search(by_id[key][0]["text"])]
                    if not children:
                        continue
                elif pattern:
                    children = [key for key in children if re.search(pattern, by_id[key][0]["text"], re.I)]
                    if not children:
                        continue
                ids = set(roots) | set(children)
                required[part] = ids
                for key in sorted(ids, key=lambda key: by_id[key][1]):
                    if key in primary_ids or key in added:
                        attributed[key].add(part)
                    elif len(added) < budget:
                        added.append(key)
                        attributed[key].add(part)
                break
            if part in required:
                break
    return [by_id[key][0] for key in added], required, attributed


def evidence_tokens(text):
    return {token for token in surface_tokens(text) if len(token) >= 5 and token not in {
        "sığorta", "qanunun", "maddənin", "haqqında", "edilir", "olunur", "edilməsi", "hansı",
    }}


def expand_references(question, primary, by_id, *, max_depth=2, max_hits=4):
    query_terms = evidence_tokens(question)
    query_numbers = set(re.findall(r"\d+(?:[.-]\d+)*", question))
    seen = {(hit.get("metadata") or {}).get("chunk_id") for hit in primary}
    queue = deque((hit, 0) for hit in primary)
    additions, relationships = [], []
    while queue and len(additions) < max_hits:
        source, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for ref in source.get("legal_references", ()):
            if ref.get("resolution_status") != "verified":
                continue
            for target_id in ref.get("target_passage_ids", ()):
                if target_id not in by_id or target_id == ref["source_passage_id"]:
                    continue
                target = by_id[target_id][0]
                number = ref.get("referenced_article_id")
                if not (ref["reference_type"] == "documented_amendment" or number in query_numbers
                        or query_terms & evidence_tokens(target["text"])):
                    continue
                if target_id in seen:
                    if (link := {**ref, "included_target_passage_id": target_id}) not in relationships:
                        relationships.append(link)
                    continue
                if len(additions) >= max_hits:
                    continue
                seen.add(target_id)
                additions.append(target)
                relationships.append({**ref, "included_target_passage_id": target_id})
                queue.append((target, depth + 1))
    return additions, relationships


def disjoint_periods(a, b):
    for old, new in ((a, b), (b, a)):
        end, start = date_value(old.get("valid_until")), date_value(new.get("effective_date"))
        if end and start and end < start:
            return True
    return False


def version_conflicts(items):
    provisions = defaultdict(list)
    conflicts = []
    for item in items:
        identity = item.get("law_number") or (title_key(item["document_title"]) if item.get("legal_document_type") else None)
        provision = item.get("clause") or item.get("article")
        if not identity or not provision:
            continue
        for previous in provisions[identity, provision]:
            if (item["document_id"] != previous["document_id"] and not disjoint_periods(previous, item)
                    and surface_tokens(item["original_text"]) != surface_tokens(previous["original_text"])):
                conflicts.append({"kind": "potential_version_conflict", "article": provision,
                                  "passage_ids": [previous["passage_id"], item["passage_id"]]})
        provisions[identity, provision].append(item)
    return conflicts


@stage_timing("evidence_assembly")
def assemble_evidence(question, hits, documents, *, associations=None, part_ids=(), part_questions=None, expand=True,
                      critical_groups=False, multipart_coverage=False, filters=None):
    by_id = {}
    for doc in documents:
        for i, hit in enumerate(doc["chunks"]):
            if point_id := (hit.get("metadata") or {}).get("chunk_id"):
                by_id[point_id] = hit, i
    primary = [hit for _, hit in distinct_evidence(hits)]
    associations = associations or {}
    grouped, required, grouped_parts = (qualification_groups(primary, by_id, associations, part_questions or {},
                                                              scoped=multipart_coverage)
                                        if expand and critical_groups else ([], {}, {}))
    extras, links = expand_references(question, primary, by_id) if expand else ([], [])
    combined = surrounding_evidence([*primary, *grouped, *extras], documents, references=False) if expand else primary
    unresolved = set()
    if expand and multipart_coverage and part_questions:
        from App.text_search import matches_filters, scoped_obligations

        corpus = [hit for hit, _ in by_id.values()]
        eligible = [i for i, hit in enumerate(corpus) if matches_filters(hit, filters)]
        for part, text in part_questions.items():
            matches = scoped_obligations(text, corpus, eligible)
            if matches == []:
                unresolved.add(part)
            if matches:
                ids = {corpus[i]["metadata"]["chunk_id"] for i in matches}
                required.setdefault(part, set()).update(ids)
                for point_id in ids:
                    grouped_parts.setdefault(point_id, set()).add(part)
                    combined.append(by_id[point_id][0])
            if re.search(r"\bistinad\b", text, re.I) and re.search(r"şəxsiyyət sənəd", text, re.I):
                targets = {}
                seeds = set().union(*(ids for key, ids in required.items() if key != part))
                for seed in seeds:
                    for ref in by_id[seed][0].get("legal_references", ()):
                        if ref["resolution_status"] != "verified":
                            continue
                        for point_id in ref["target_passage_ids"]:
                            if (point_id in by_id and matches_filters(by_id[point_id][0], filters)
                                    and BENEFICIARY_IDENTITY.search(by_id[point_id][0]["text"])):
                                targets[point_id] = {**ref, "included_target_passage_id": point_id}
                if len(targets) == 1:
                    point_id, relationship = next(iter(targets.items()))
                    required.setdefault(part, set()).add(point_id)
                    grouped_parts.setdefault(point_id, set()).add(part)
                    combined.append(by_id[point_id][0])
                    if relationship not in links:
                        links.append(relationship)
                else:
                    unresolved.add(part)
        unresolved.update(set(part_questions) - required.keys())
        nominated = set().union(*required.values())
        ordered = [hit for _, hit in distinct_evidence(combined)]
        # Keep candidate evidence when a requested obligation could not be resolved.
        # Fully resolved groups need no unrelated passages to fill the context slots.
        if not unresolved and nominated:
            scoped_versions = {(hit["metadata"].get("law_name"), hit["metadata"].get("clause") or hit["metadata"].get("article"))
                               for hit in ordered if hit["metadata"]["chunk_id"] in nominated}
            ordered = [hit for hit in ordered if hit["metadata"]["chunk_id"] in nominated or (
                (hit["metadata"].get("law_name"), hit["metadata"].get("clause") or hit["metadata"].get("article")) in scoped_versions
                and any(other["doc"] != hit["doc"] and other["metadata"].get("law_name") == hit["metadata"].get("law_name")
                        and other["metadata"].get("clause") == hit["metadata"].get("clause") for other in ordered
                        if other["metadata"]["chunk_id"] in nominated)
            )]
        combined = sorted(ordered, key=lambda hit: hit["metadata"]["chunk_id"] not in nominated)[:10]
    combined_ids = {(hit.get("metadata") or {}).get("chunk_id") for hit in combined}
    links = [link for link in links if {link["source_passage_id"], link["included_target_passage_id"]} <= combined_ids]
    ref_targets = {(hit.get("metadata") or {}).get("chunk_id") for hit in extras}
    trace = retrieval_trace.get() or {}
    primary_keys = {passage_key(hit) for hit in primary}
    items = []
    covered_parts = set()
    reference_parts = {key: evidence_tokens(text) for key, text in (part_questions or {}).items()
                       if re.search(r"\b(?:istinad|göstərilən maddə|həmin müddəa)\b", text, re.I)}
    for hit in combined:
        info = hit.get("metadata") or {}
        point_id = info.get("chunk_id")
        key = passage_key(hit)
        parts = set(associations.get(key, ()))
        parts.update(grouped_parts.get(point_id, ()))
        for link in links:
            if link["included_target_passage_id"] == point_id:
                parts.update(associations.get(passage_key(by_id[link["source_passage_id"]][0]), ()) if link["source_passage_id"] in by_id else ())
                parts.update(key for key, tokens in reference_parts.items() if tokens & evidence_tokens(hit["text"]))
        if multipart_coverage:
            owners = {part for part, ids in required.items() if point_id in ids}
            if owners:
                parts = owners
        covered_parts.update(parts)
        items.append({
            "document_id": info.get("document_id"), "document_title": info.get("document_title") or info.get("law_name") or hit["doc"],
            "document_type": info.get("document_type"), "legal_document_type": info.get("legal_document_type"),
            "legal_hierarchy": info.get("legal_hierarchy"), "law_number": info.get("law_number"),
            "article": info.get("article_number") or info.get("article"), "paragraph": info.get("paragraph_number") or info.get("clause"),
            "clause": info.get("clause"), "subparagraph": info.get("subparagraph_number"), "passage_id": point_id,
            "parent_passage_id": info.get("parent_passage_id") or point_id,
            "original_text": info.get("original_text") or hit["text"], "verbatim_extraction": info.get("original_text_verbatim"),
            "effective_date": info.get("effective_from") or info.get("effective_date"),
            "amendment_date": info.get("amended_at") or info.get("amendment_date"),
            "valid_until": info.get("effective_until") or info.get("valid_until"), "declared_validity": info.get("declared_validity"),
            "version_id": info.get("version_id"), "official_source_url": info.get("source_url"),
            "version_is_current": info.get("is_current"),
            "temporal_basis": ("period_documented" if info.get("effective_date") and info.get("valid_until") else
                               "source_status_declared" if info.get("declared_validity") else "unknown"),
            "document_reference": hit["doc"], "source_url": f"/documents/{quote(hit['doc'], safe='')}/preview/{by_id[point_id][1]}" if point_id in by_id else None,
            "retrieval_source": "cross_reference" if point_id in ref_targets else "retrieval" if key in primary_keys else "surrounding",
            "retrieval_scores": trace.get(key, []), "subquestions": sorted(parts),
            "cross_references": hit.get("legal_references", []),
        })
    conflicts = version_conflicts(items)
    event("evidence_context", passage_ids=[item["passage_id"] for item in items],
          links=[(link["source_passage_id"], link["included_target_passage_id"]) for link in links], conflicts=len(conflicts))
    lacking = {part for part, ids in required.items() if not ids <= combined_ids}
    return EvidencePackage(combined, items, links, conflicts, (set(part_ids) - covered_parts) | lacking | unresolved, required)
