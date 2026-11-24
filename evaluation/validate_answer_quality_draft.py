"""Validate the Phase 1 draft against the indexed corpus without retrieving or generating."""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
import json
from pathlib import Path

from App.azerbaijani import normalize_az
from App.document_processing import load_documents
from App.source_authority import NORMATIVE, load_catalog, passage_ref
from evaluation.gold_framework import HERE, MODES, digest, indexed_sources, read, verify_source

DRAFT = HERE / "answer_quality_draft_v1.json"
INDEX = HERE.parent / "data" / "index"
CATEGORIES = ("simple", "condition", "multipart", "multidoc", "abstention")
DRAFT_MODES = {MODES[category] for category in ("answerable", "partially_answerable", "unanswerable")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalize(question):
    return " ".join(normalize_az(question).split())


def historical_questions():
    with (HERE / "insurance_queries.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    rows.extend(read(HERE / "latest_seven_dataset.json")["queries"])
    rows.extend(read(HERE / "legal_answer_quality_v1.json")["cases"])
    return {normalize(row["query"]) for row in rows}


def corpus_content_hash(hits):
    return digest(sorted((pid, hit["text"]) for pid, hit in hits.items()))


def validate(dataset, documents, *, index=INDEX):
    require(dataset.get("schema_version") == 1 and dataset.get("dataset_version") == "1.0.0"
            and dataset.get("gold") is False and dataset.get("status") == "draft_engineering", "Draft version/status")
    hits = indexed_sources(documents)
    require(len(documents) == dataset["corpus_document_count"] == 12 and
            len(hits) == dataset["corpus_parent_count"] == 4405, "Corpus inventory")
    require(corpus_content_hash(hits) == dataset["corpus_content_sha256"], "Indexed corpus content differs")
    authority = load_catalog()["documents"]
    references = dataset["passages"]
    for pid, ref in references.items():
        hit = hits.get(pid)
        require(hit is not None and ref["passage_id"] == pid and verify_source(hit, ref),
                f"Passage text or identity mismatch {pid}")
        meta = hit["metadata"]
        exact = passage_ref(hit)
        require(all(ref[key] == exact[key] for key in ("document", "document_id", "article", "clause", "page")),
                f"Passage metadata mismatch {pid}")
        require(ref["section"] == meta.get("section_title") and ref["law_name"] == meta.get("law_name")
                and ref["article_title"] == meta.get("article_title")
                and ref["adoption_date"] == meta.get("adoption_date"), f"Source metadata mismatch {pid}")
        doc = authority.get(ref["document_id"])
        require(doc and ref["source_type"] == doc["source_type"] and
                ref["source_version_sha256"] == doc["version_id"] and ref["version_id"] in (None, doc["version_id"])
                and exact["version_id"] in (None, doc["version_id"])
                and ref["source_url"] in (None, doc.get("source_url"))
                and exact["source_url"] in (None, doc.get("source_url")), f"Source authority mismatch {pid}")
    source_files = {ref["document"]: ref["source_version_sha256"] for ref in references.values()}
    for name, expected in source_files.items():
        require(sha256((index / name).read_bytes()).hexdigest() == expected, f"Source file version mismatch {name}")

    cases = dataset["cases"]
    ids = {case["question_id"] for case in cases}
    questions = {normalize(case["question"]) for case in cases}
    require(len(cases) == len(ids) == len(questions) == 25 and "" not in questions, "Duplicate, empty, or missing cases")
    require(not questions & historical_questions(), "Exact overlap with a frozen benchmark")
    require(Counter(case["category"] for case in cases) == dict.fromkeys(CATEGORIES, 5), "Category counts")
    used = set()
    by_split = defaultdict(set)
    for case in cases:
        cid = case["question_id"]
        require(cid.startswith(f"AQ-{case['category'].upper()}-")
                and cid.rsplit("-", 1)[-1] in {f"{i:03}" for i in range(1, 6)}, f"Invalid ID {cid}")
        require(case["dataset_version"] == dataset["dataset_version"]
                and case["source_verification_status"] == "snapshot_matched"
                and case["expert_review_status"] in {"pending_domain_expert", "needs_expert_review"}
                and case["origin"] in {"source_derived", "synthetic_scenario"}
                and case["proposed_split"] in {"dev", "test"}, f"Draft status {cid}")
        require(case["expected_mode"] in DRAFT_MODES and case["expected_answer"].strip()
                and case["evaluation_notes"].strip() and case["applicable_insurance_types"]
                and case["temporal_requirements"].get("kind"), f"Answer fields {cid}")
        parts = case["sub_questions"]
        part_ids = {part["part_id"] for part in parts}
        require((case["category"] == "multipart") == bool(parts), f"Unexpected parts {cid}")
        if parts:
            require(2 <= len(parts) <= 3 and len(part_ids) == len(parts) and
                    all(part["expected_mode"] in DRAFT_MODES and part["question"].strip() and
                        part["question"] in case["question"] for part in parts), f"Malformed multipart {cid}")
            modes = {part["expected_mode"] for part in parts}
            overall = next(iter(modes)) if len(modes) == 1 else "PARTIAL"
            require(case["expected_mode"] == overall, f"Multipart mode mismatch {cid}")

        claims = case["required_claims"]
        supporting, related = map(set, (case["supporting_passages"], case["related_passages"]))
        require(bool(supporting or related) and not supporting & related
                and (supporting | related) <= references.keys(), f"Unknown or overlapping evidence {cid}")
        used.update(supporting | related)
        docs = {references[pid]["document_id"] for pid in supporting}
        require(docs == set(case["supporting_sources"]), f"Document mapping {cid}")
        if case["category"] == "simple":
            require(len(supporting) == 1, f"Simple evidence count {cid}")
        if case["category"] == "multidoc":
            require(len(docs) >= 2 and docs <= {references[pid]["document_id"] for claim in claims if claim["essential"]
                                               for pid in claim["passage_ids"] if pid in references},
                    f"Missing necessary document {cid}")
        require((case["category"] == "abstention") == (case["expected_mode"] == "NOT_FOUND"), f"Abstention mode {cid}")
        require(len(claims) == len({claim["claim_id"] for claim in claims}), f"Duplicate claim {cid}")
        for claim in claims:
            require(claim["text"].strip() and claim["passage_ids"] and set(claim["passage_ids"]) <= supporting and
                    any(references[pid]["source_type"] in NORMATIVE for pid in claim["passage_ids"]) and
                    type(claim["essential"]) is bool and isinstance(claim["conditions"], list) and
                    isinstance(claim["exceptions"], list), f"Claim without grounded evidence {cid}")
            require(claim["part"] in (part_ids or {None}), f"Claim part mapping {cid}")
        require(supporting == {pid for claim in claims for pid in claim["passage_ids"]}, f"Unused supporting evidence {cid}")
        require(not claims if case["expected_mode"] == "NOT_FOUND" else any(c["essential"] for c in claims),
                f"Claim/mode mismatch {cid}")
        if parts:
            for part in parts:
                require(any(c["essential"] and c["part"] == part["part_id"] for c in claims) ==
                        (part["expected_mode"] != "NOT_FOUND"), f"Multipart coverage {cid}")
        missing = case["expected_abstention_reason"]
        if case["expected_mode"] != "FULL":
            require(missing and all(missing.get(key) for key in ("code", "missing_evidence", "answer", "corpus_review")),
                    f"Missing abstention rationale {cid}")
            if parts:
                require(missing.get("part") in {p["part_id"] for p in parts if p["expected_mode"] != "FULL"},
                        f"Missing abstention part {cid}")
        else:
            require(missing is None, f"Unexpected abstention rationale {cid}")
        expected = [claim["text"] for claim in claims] + ([missing["answer"]] if missing else [])
        require(case["expected_answer"] == " ".join(expected), f"Answer text without a claim or gap mapping {cid}")
        for key in ("conditions", "exceptions"):
            require(set(case["required_conditions" if key == "conditions" else key]) ==
                    {item for c in claims for item in c[key]}, f"Lost qualification {cid}")
        for pid in supporting | related:
            ref = references[pid]
            by_split[case["proposed_split"]].add((ref["document_id"], ref["article"], ref["clause"], ref["page"]
                                                 if ref["clause"] is None else None))

    require(used == references.keys(), "Unused passage registry entries")
    require(not by_split["dev"] & by_split["test"], "Shared provision across splits")
    require(Counter(case["proposed_split"] for case in cases) == {"dev": 10, "test": 15}, "Split counts")
    require(Counter(case["category"] for case in cases if case["proposed_split"] == "dev") ==
            dict.fromkeys(CATEGORIES, 2), "Split category counts")
    for left in (case for case in cases if case["proposed_split"] == "dev"):
        a = set(normalize(left["question"]).split())
        for right in (case for case in cases if case["proposed_split"] == "test"):
            b = set(normalize(right["question"]).split())
            require(len(a & b) / len(a | b) < 0.80, f"Near duplicate {left['question_id']}/{right['question_id']}")
    return {"cases": len(cases), "categories": dict(Counter(case["category"] for case in cases)),
            "modes": dict(Counter(case["expected_mode"] for case in cases)),
            "origins": dict(Counter(case["origin"] for case in cases)),
            "splits": dict(Counter(case["proposed_split"] for case in cases)),
            "documents_referenced": len(source_files), "passages": len(references), "gold": False,
            "expert_review_required": [case["question_id"] for case in cases
                                       if case["expert_review_status"] == "needs_expert_review"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Optional frozen full index export")
    args = parser.parse_args()
    dataset = read(DRAFT)
    documents = read(args.snapshot) if args.snapshot else load_documents(INDEX, 1200)
    if args.snapshot:
        ordered = [(h["metadata"]["chunk_id"], h["text"]) for doc in documents for h in doc["chunks"]]
        require(digest(ordered) == dataset["corpus_sha256"], "Frozen snapshot ordering/hash differs")
    print(json.dumps(validate(dataset, documents), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
