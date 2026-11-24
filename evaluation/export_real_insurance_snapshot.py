"""Export benchmark inputs using read-only API operations."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def request(origin, path, body=None, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api-key"] = key
    req = Request(origin.rstrip("/") + path, None if body is None else json.dumps(body).encode(), headers)
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def export_corpus(origin, path):
    documents = []
    for item in request(origin, "/documents"):
        filename = item["doc"]
        name = Path(filename).stem.split("@")[0]
        url = f"/documents/{quote(name, safe='')}/versions/{quote(filename, safe='')}"
        documents.append(request(origin, url))
    path.write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")


def export_archives(origin, names, path):
    key = os.getenv("QDRANT_API_KEY")
    with path.open("w", encoding="utf-8") as stream:
        for name in names:
            url = f"/collections/{quote(name, safe='')}"
            info = request(origin, url, key=key)["result"]
            header = {"collection": name, "points": info["points_count"],
                      "vectors": info["config"]["params"]["vectors"]}
            stream.write(json.dumps(header) + "\n")
            offset = None
            while True:
                body = {"offset": offset, "limit": 128, "with_payload": True, "with_vector": True}
                result = request(origin, url + "/points/scroll", body, key=key)["result"]
                for point in result["points"]:
                    stream.write(json.dumps(point, ensure_ascii=False) + "\n")
                offset = result["next_page_offset"]
                if offset is None:
                    break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--qdrant", default="http://qdrant:6333")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--archives", nargs=2, metavar=("BEFORE", "AFTER"))
    args = parser.parse_args()
    if bool(args.vectors) != bool(args.archives):
        parser.error("Vector export requires explicit before and after archives")
    export_corpus(args.api, args.snapshot)
    if args.vectors:
        export_archives(args.qdrant, args.archives, args.vectors)


if __name__ == "__main__":
    main()
