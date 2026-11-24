"""Materialize reviewed-by-author source locators against a frozen API corpus snapshot."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
FILES = (
    "NK-2022-149.pdf", "NK-2023-156.pdf", "Sığorta kitab.pdf",
    "Trend-4197840-avtomobil-sigortasi-2026.txt", "Trend-4201157-icbari-sigorta-meblegleri-2026.txt",
    "sığorta 1.pdf", "sığorta 2.pdf", "sığorta 3.pdf", "sığorta 5.pdf", "sığorta 6.pdf",
    "sığorta 7.pdf", "sığorts 4.pdf",
)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build(documents, definitions):
    if tuple(document["doc"] for document in documents) != FILES:
        raise ValueError("Source locators require the original source inventory and order")
    snapshot = [(chunk["metadata"]["chunk_id"], chunk["text"]) for doc in documents for chunk in doc["chunks"]]
    result = []
    for line in definitions.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if not 4 <= len(parts) <= 7:
            raise ValueError(f"Invalid query definition: {line}")
        category, style, locators, query, prior, standalone, note = parts + [""] * (7 - len(parts))
        evidence = []
        for location in locators.split(",") if locators else []:
            if ":" in location:
                document, ordinal = (int(value) for value in location.split(":"))
            else:
                ordinal = int(location)
            source = documents[document]
            chunk = source["chunks"][ordinal]
            meta = chunk["metadata"]
            evidence.append({
                "document_id": meta["document_id"], "passage_id": meta["chunk_id"],
                "parent_passage_id": meta["chunk_id"], "document": source["doc"],
                "article": meta.get("article"), "clause": meta.get("clause"), "page": meta.get("page_number"),
                "source_url": f"/documents/{quote(source['doc'], safe='')}/preview/{ordinal}",
                "text": chunk["text"], "relevance": 3,
            })
        if bool(prior) != bool(standalone) or bool(evidence) == (category == "coverage_gap"):
            raise ValueError(f"Incomplete query definition: {query}")
        if not evidence and not note:
            raise ValueError(f"No missing-evidence rationale: {query}")
        result.append({
            "id": f"AZR{len(result) + 1:03d}", "category": category, "style": style, "query": query,
            "history": [prior] if prior else [], "expected_standalone_query": standalone or None,
            "relevant_document_ids": list(dict.fromkeys(item["document_id"] for item in evidence)),
            "relevant_passage_ids": [item["passage_id"] for item in evidence],
            "relevant_parent_passage_ids": [item["parent_passage_id"] for item in evidence],
            "evidence": evidence, "covered": bool(evidence), "multiple_passages_required": len(evidence) > 1,
            "label_rationale": note or "Selected from the source provision before running retrieval.",
            "review_status": "pending_domain_expert",
        })
    if not 150 <= len(result) <= 200 or len({(row["query"], tuple(row["history"])) for row in result}) != len(result):
        raise ValueError("Expected 150–200 unique query/history combinations")
    return {"schema_version": 1, "corpus_sha256": digest(snapshot), "parent_count": len(snapshot),
            "source_inventory": [{"document": row["doc"], "id": row["metadata"]["document_id"],
                                  "passages": len(row["chunks"])} for row in documents],
            "review_status": "pending_domain_expert", "queries": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "real_insurance_dataset.json")
    args = parser.parse_args()
    dataset = build(json.loads(args.snapshot.read_text(encoding="utf-8")),
                    (HERE / "real_insurance_queries.txt").read_text(encoding="utf-8"))
    args.output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(len(dataset["queries"]), Counter(row["category"] for row in dataset["queries"]))


if __name__ == "__main__":
    main()
