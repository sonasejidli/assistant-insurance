"""Compare exact dense rankings against the pre-split Qdrant snapshot."""

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch

import numpy as np
from qdrant_client import models

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from App import embedding
from App.text_search import TextRetriever


BOOK = "Sığorta kitab.pdf"
CASES = (
    ("tail", 945, BOOK, 279, "Yaşam sığortasında sığorta haqqı illik ödənəndə bütün netto-stavka ehtiyata daxil olurmu?"),
    ("tail", 687, BOOK, 196, "Sığortaçı sığorta olunmuş risklərin siyahısını tərtib etməlidirmi?"),
    ("tail", 812, BOOK, 239, "Yol hadisəsinə şərait yaratmayan və intizamlı sürücülərə hansı güzəştlər tətbiq edilir?"),
    ("tail", 634, BOOK, 179, "Sığorta olunmuş şəxslər üçün məhkəmə xərcləri sığorta təminatında nəzərdə tutula bilərmi?"),
    ("tail", 1008, BOOK, 297, "Bir risk üzrə təkrarsığortaçının iştirakı hansı məsuliyyət limiti ilə məhdudlaşdırılır?"),
    ("control", None, "sığorta 2.pdf", "56.1.2", "Maşınla başqasının malına ziyan vursam, ən çox nə qədər qarşılanır?"),
    ("control", None, "sığorta 2.pdf", "25.2", "Subroqasiya hüququ kimə qarşı tələb irəli sürməyə imkan verir?"),
    ("control", None, "sığorts 4.pdf", "15-10.1.2", "İcbari tibbi sığortada əməkhaqqının 8000 manatdan yuxarı hissəsinə neçə faiz tətbiq edilir?"),
)


def rank(order, relevant):
    return next((i for i, index in enumerate(order, start=1) if index in relevant), None)


def check_synthetic_exception():
    """Use a fictional Latin-script clause to isolate the effect of truncation."""
    filler = (
        "Müqavilənin nüsxəsi tərəflərin elektron arxivinə yerləşdirilir. "
        "Arxivdə müraciətin nömrəsi, qeydiyyat tarixi və təsdiqləyən şəxsin adı saxlanılır. "
    ) * 21
    exception = ("İstisna: sel nəticəsində zirzəmidəki avadanlığa dəyən zərər yalnız su səviyyəsi "
                 "40 santimetri keçdikdə, 7500 manat həddində qarşılanır.")
    texts = [
        filler + exception,
        "Sel nəticəsində zirzəmidəki avadanlığa dəyən zərər barədə iddia yazılı şəkildə qeydə alınır.",
        "Sığortaçının 7500 manat həddi yalnız üst mərtəbədəki soyuduculara şamil edilir.",
        "Zirzəmidəki avadanlığa dəyən zərər elektrik qəzası ilə bağlı olduqda istisna edilir.",
        "Su səviyyəsi 40 santimetri keçdikdə su nasosuna texniki baxış aparılır.",
        "Arxivdə qeydiyyat tarixi və təsdiqləyən şəxsin adı saxlanılır.",
    ]
    model = embedding.get_model()
    limit = embedding.input_limit(model)
    assert embedding.token_counts(model, [embedding.model_input(texts[0], "passage")])[0] > limit
    # Reproduce the old encoder call intentionally allowing tokenizer truncation.
    before = model.encode([embedding.model_input(text, "passage") for text in texts],
                          normalize_embeddings=True)
    questions = [
        "Sel zirzəmidəki avadanlığa zərər vursa, su səviyyəsi hansı həddi keçməlidir?",
        "Zirzəmi avadanlığı üçün sel zərərinin ödəniş limiti neçə manatdır?",
    ]
    queries = embedding.embed(questions, kind="query")
    chunks = [{"doc": "synthetic", "text": text} for text in texts]
    result = {"baseline": [rank(np.argsort(-(before @ query)), {0}) for query in queries]}
    for target in (limit, 480, 448):
        with patch.object(embedding, "EMBED_TARGET_TOKENS", target):
            parts = embedding.plan_passages(chunks, texts)[0]
        vectors = embedding.embed([part.text for part in parts])
        result[target] = [rank(np.argsort(-np.r_[max(vectors @ query), before[1:] @ query]), {0})
                          for query in queries]
    print(json.dumps({"synthetic_exception_ranks": result}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="Existing Qdrant collection with one vector per parent")
    args = parser.parse_args()
    retriever = TextRetriever()
    try:
        index = retriever.vector_index
        client = index.client
        parents = retriever.chunks
        baseline_config = client.get_collection(args.baseline)
        if args.baseline == index.collection or baseline_config.points_count != len(parents):
            raise ValueError("Expected the original one-vector-per-parent collection for this corpus")
        eligible = list(range(len(parents)))
        queries = embedding.embed([case[-1] for case in CASES], kind="query")
        results = []
        for (group, parent, doc, marker, question), query in zip(CASES, queries, strict=True):
            if parent is not None:
                chunk = parents[parent]
                if chunk["doc"] != doc or chunk["metadata"].get("page_number") != marker:
                    raise ValueError(f"Tail judgment no longer matches parent {parent}")
                relevant = {parent}
            else:
                relevant = {i for i, item in enumerate(parents)
                            if item["doc"] == doc and item["metadata"].get("clause") == marker}
            if not relevant:
                raise ValueError(f"Missing judgment for {doc} {marker}")
            vector = query.tolist()
            start = perf_counter()
            before = client.query_points(
                args.baseline, query=vector, limit=len(parents), score_threshold=retriever.settings.similarity_threshold,
                search_params=models.SearchParams(exact=True), with_payload=["index"],
            ).points
            before_ms = (perf_counter() - start) * 1000
            start = perf_counter()
            after = index.search(vector, eligible, len(parents), exact=True,
                                 score_threshold=retriever.settings.similarity_threshold)
            after_ms = (perf_counter() - start) * 1000
            result = {
                "group": group, "query": question, "source": doc, "page_or_clause": marker,
                "before_rank": rank([p.payload["index"] for p in before], relevant),
                "after_rank": rank([i for i, _ in after], relevant),
                "before_ms_full_rank": round(before_ms, 1), "after_ms_full_rank": round(after_ms, 1),
            }
            results.append(result)
            print(json.dumps(result), flush=True)
        print(json.dumps({"parent_count": len(parents), "point_count": len(index.index_by_id),
                          "model_limit": embedding.input_limit(embedding.get_model()),
                          "collection": index.collection}), flush=True)
        for group in ("tail", "control", "all"):
            records = [result for result in results if group in ("all", result["group"])]
            scores = {}
            for phase in ("before", "after"):
                ranks = [record[f"{phase}_rank"] or 51 for record in records]
                scores[phase] = {
                    "recall@5": sum(r <= 5 for r in ranks) / len(records),
                    "recall@50": sum(r <= 50 for r in ranks) / len(records),
                    "mrr@50": sum(1 / r for r in ranks if r <= 50) / len(records),
                }
            print(json.dumps({"group": group, **scores}), flush=True)
        check_synthetic_exception()
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
