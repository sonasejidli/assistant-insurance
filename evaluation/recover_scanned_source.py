"""Recover an auditable searchable derivative while preserving the source PDF."""

import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pymupdf


def recover_page(task):
    source, number, language, dpi = task
    with pymupdf.open(source) as original:
        page = original[number]
        if page.get_text().strip():
            return number, None, len(page.get_text().strip()), "native"
        pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
        payload = subprocess.run(["tesseract", "stdin", "stdout", "--dpi", str(dpi), "-l", language, "pdf"],
                                 input=pixmap.tobytes("png"), capture_output=True, check=True).stdout
    with pymupdf.open(stream=payload, filetype="pdf") as recovered:
        length = len(recovered[0].get_text().strip())
    return number, payload, length, "ocr" if length else "empty"


def recover(source, output, audit, language, dpi, workers):
    if source.resolve() in {output.resolve(), audit.resolve()} or output.exists() or audit.exists():
        raise ValueError("Use new derivative and audit paths")
    with pymupdf.open(source) as original, pymupdf.open() as derivative, ProcessPoolExecutor(max_workers=workers) as pool:
        records = []
        tasks = [(source, number, language, dpi) for number in range(len(original))]
        for number, payload, length, status in pool.map(recover_page, tasks):
            if payload:
                with pymupdf.open(stream=payload, filetype="pdf") as page:
                    derivative.insert_pdf(page)
            else:
                derivative.insert_pdf(original, from_page=number, to_page=number)
            records.append({"page": number+1, "extracted_chars": length, "status": status})
            if (number+1) % 10 == 0:
                print(f"Processed {number+1}/{len(original)} pages", flush=True)
        derivative.save(output, deflate=True, garbage=4)
    audit.write_text(json.dumps({"source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "derivative_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "dpi": dpi, "languages": language,
        "pymupdf": pymupdf.VersionBind, "review_status": "pending visual/legal review", "pages": records}, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--language", default="aze+aze_cyrl+rus+eng")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    recover(args.source, args.output, args.audit, args.language, args.dpi, args.workers)
