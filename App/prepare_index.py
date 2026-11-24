"""Prepare the packaged corpus in an explicitly selected local Qdrant directory."""

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path

from App.settings import QDRANT_PATH, QDRANT_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", action="store_true", help="Validate an existing index and emit its manifest")
    args = parser.parse_args()
    if QDRANT_URL or not QDRANT_PATH or not Path(QDRANT_PATH).is_absolute():
        raise SystemExit("Set an absolute local QDRANT_PATH and leave QDRANT_URL unset.")
    if args.manifest:
        os.environ["RAG_REQUIRE_PREPARED_INDEX"] = "1"
    elif os.getenv("RAG_REQUIRE_PREPARED_INDEX") == "1":
        raise SystemExit("Unset RAG_REQUIRE_PREPARED_INDEX during index preparation.")
    from App.observability import startup_stage
    from App.text_search import TextRetriever

    logging.basicConfig(level=logging.INFO)
    with startup_stage("prepare_index"):
        retriever = TextRetriever()
        try:
            if args.manifest:
                from App.vector_store import fingerprint

                index = retriever.vector_index
                manifest = {
                    "schema_version": 1, "collection": index.collection, "validated_points": len(index.index_by_id),
                    "embedding_fingerprint": index.embedding_fingerprint,
                    "corpus_sha256": fingerprint(retriever.documents),
                    "point_ids_sha256": fingerprint(sorted(index.index_by_id)),
                }
                encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
                manifest["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
                print(json.dumps(manifest, sort_keys=True))
        finally:
            retriever.close()


if __name__ == "__main__":
    main()
