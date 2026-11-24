"""Verify downloaded government sources and stage a provenance-bound corpus overlay."""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pymupdf


DIRECTORY = Path("data/staged_legal")
HEALTH_TITLE = "Əhalinin sağlamlığının qorunması haqqında"
HEALTH_URL = "https://frameworks.e-qanun.az/4/c_f_4078.html"
AMENDMENT_TITLE = "Əhalinin sağlamlığının qorunması və tibbi sığorta qanunlarına dəyişiklik (74-VIIQD)"
SOURCES = (
    ("civil-code.pdf", "Azərbaycan Respublikasının Mülki Məcəlləsi", "code", "https://uploads.cbar.az/assets/dfb5731c1d05df8de8818c622.pdf", ("Maddə 883", "Maddə 373", "Maddə 935")),
    ("personal-data.pdf", "Fərdi məlumatlar haqqında", "law", "https://frameworks.e-qanun.az/19/19675.pdf", ("Maddə 13", "Maddə 14", "Fərdi məlumatlar haqqında")),
    ("health-confidentiality.txt", HEALTH_TITLE, "law", HEALTH_URL, ("Maddə 53.", "həkim sirrini", "razılığı")),
    ("health-amendment.txt", AMENDMENT_TITLE, "law", "https://president.az/az/articles/view/67550/print", ("Maddə 1.", "53-cü maddəsinin", "sığorta hadisəsi baş verdikdə")),
    ("motor-tariff.pdf", "Avtonəqliyyat vasitələri üzrə icbari sığorta haqqı məbləğlərinin hesablanması Qaydası", "regulation", "https://uploads.cbar.az/assets/0e36765b08e04f57f3b2df925.pdf", ("№ 25/1", "2.2.", "Cədvəl 1")),
)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines, self.fragments, self.hidden = [], [], []
        self.body = False

    def flush(self):
        if line := " ".join("".join(self.fragments).split()):
            self.lines.append(line)
        self.fragments.clear()

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.body = True
        if self.hidden or tag in {"s", "strike", "del", "style", "script", "sup"} or "line-through" in dict(attrs).get("style", "").lower():
            if tag not in {"br", "img", "meta", "hr", "link", "input"}:
                self.hidden.append(tag)
            return
        if self.body and tag in {"p", "div", "br", "li"}:
            self.flush()

    def handle_endtag(self, tag):
        if self.hidden:
            if tag in self.hidden:
                del self.hidden[len(self.hidden) - 1 - self.hidden[::-1].index(tag):]
            return
        if tag in {"p", "div", "li", "body"}:
            self.flush()
        if tag == "body":
            self.body = False

    def handle_data(self, data):
        if self.body and not self.hidden:
            self.fragments.append(data)


def health_excerpt(raw):
    parser = VisibleText()
    parser.feed(raw.decode("cp1251"))
    starts = [i for i, line in enumerate(parser.lines) if re.match(r"^Maddə\s+53\.", line)]
    if len(starts) != 1:
        raise ValueError(f"Expected one Article 53 heading, found {len(starts)}")
    start = starts[0]
    end = next(i for i in range(start+1, len(parser.lines)) if re.match(r"^Maddə\s+54\.", parser.lines[i]))
    return f"{HEALTH_TITLE}\nAZƏRBAYCAN RESPUBLİKASININ QANUNU\n" + "\n".join(parser.lines[start:end]) + "\n"


def main():
    parent = DIRECTORY / "health-confidentiality.html"
    excerpt = health_excerpt(parent.read_bytes())
    (DIRECTORY / "health-confidentiality.txt").write_text(excerpt, encoding="utf-8", newline="\n")
    amendment = DIRECTORY / "health-amendment.html"
    parser = VisibleText()
    parser.feed(amendment.read_text(encoding="utf-8"))
    start = next(i for i, line in enumerate(parser.lines) if line.startswith("Maddə 1."))
    stop = next(i for i, line in enumerate(parser.lines) if line.startswith("Maddə 2."))
    (DIRECTORY / "health-amendment.txt").write_text(f"{AMENDMENT_TITLE}\nAZƏRBAYCAN RESPUBLİKASININ QANUNU\n" +
        "\n".join(parser.lines[start:stop]) + "\n", encoding="utf-8", newline="\n")
    manifest = {}
    for name, title, kind, url, probes in SOURCES:
        path = DIRECTORY / name
        if path.suffix == ".pdf":
            with pymupdf.open(path) as pdf:
                pages = [page.get_text() for page in pdf]
        else:
            pages = [path.read_text(encoding="utf-8")]
        matched = {probe: [i+1 for i, page in enumerate(pages) if probe in " ".join(page.split())] for probe in probes}
        if not all(matched.values()):
            raise ValueError(f"Source validation failed for {name}: {matched}")
        manifest[name] = {"version_id": hashlib.sha256(path.read_bytes()).hexdigest(), "source_url": url,
                          "title": title, "legal_type": kind, "page_count": len(pages),
                          "probe_pages": matched, "current_status": "not verified"}
    manifest["health-confidentiality.txt"]["upstream_sha256"] = hashlib.sha256(parent.read_bytes()).hexdigest()
    manifest["health-confidentiality.txt"]["companion"] = {"source_article": "53", "document": "health-amendment.txt", "article": "1"}
    manifest["health-amendment.txt"].update(upstream_sha256=hashlib.sha256(amendment.read_bytes()).hexdigest(), published_at="2024-12-20")
    manifest["civil-code.pdf"]["page_ranges"] = [[165, 174], [343, 376]]
    manifest["civil-code.pdf"]["reference_aliases"] = ["Mülki Məcəllə"]
    manifest["motor-tariff.pdf"]["prose_clause_pages"] = [2, 3]
    (DIRECTORY / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
