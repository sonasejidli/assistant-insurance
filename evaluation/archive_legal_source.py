"""Stage a source revision under a content-addressed name without overwriting files."""

import argparse
import hashlib
import re
from pathlib import Path


def archive(source, directory, family):
    if not re.fullmatch(r"[^/\\:@]+", family) or family in {".", ".."} or source.suffix.lower() not in {".pdf", ".txt"}:
        raise ValueError("Use a plain source family and a PDF or text file")
    contents = source.read_bytes()
    version_id = hashlib.sha256(contents).hexdigest()
    target = directory / f"{family}@{version_id}{source.suffix.lower()}"
    try:
        with target.open("xb") as file:
            file.write(contents)
    except FileExistsError:
        if target.read_bytes() != contents:
            raise
    return target, version_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--family", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(*archive(args.source, args.directory, args.family))
