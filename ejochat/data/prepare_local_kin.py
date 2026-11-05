"""Turn the reviewed local books and news into training documents.

Keeps Kinyarwanda spelling. Drops the broken Arabic and control characters in
the Quran file, drops news that is not Kinyarwanda, and splits long books
into pieces that fit a 16,384-token training window.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "Datasets" / "clean" / "like_kin_mono"
OUT = ROOT / "data" / "Datasets" / "clean" / "for_training"
MAX_CHARS = 30_000
MIN_CHARS = 200
ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def letters_of(text: str) -> list[str]:
    return [char for char in text if char.isalpha()]


def kinyarwanda_letter(char: str) -> bool:
    if char.isascii():
        return True
    name = unicodedata.name(char, "")
    return name.startswith("LATIN")


def foreign_share(text: str) -> float:
    letters = letters_of(text)
    if not letters:
        return 1.0
    foreign = sum(1 for char in letters if not kinyarwanda_letter(char))
    return foreign / len(letters)


def tidy_kinyarwanda(text: str, drop_arabic: bool) -> str:
    cleaned = CONTROLS.sub("", text)
    if drop_arabic:
        cleaned = ARABIC.sub("", cleaned)
    lines = []
    for line in cleaned.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line or line.isdigit():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def chunks(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        if len(line) > MAX_CHARS:
            if current:
                parts.append("\n".join(current))
                current, size = [], 0
            for start in range(0, len(line), MAX_CHARS):
                parts.append(line[start : start + MAX_CHARS])
            continue
        extra = len(line) + 1
        if current and size + extra > MAX_CHARS:
            parts.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += extra
    if current:
        parts.append("\n".join(current))
    return [part.strip() for part in parts if len(part.strip()) >= MIN_CHARS]


def load_jsonl(path: Path) -> list[str]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line)["text"])
    return rows


def write_jsonl(path: Path, texts: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps({"text": text}, ensure_ascii=False) + "\n" for text in texts)
    path.write_text(payload, encoding="utf-8")


def main() -> None:
    books: list[str] = []
    book_report = []
    for path in sorted((SOURCE / "books").glob("*.jsonl")):
        drop_arabic = path.name.startswith("ibisobanuro")
        for text in load_jsonl(path):
            cleaned = tidy_kinyarwanda(text, drop_arabic=drop_arabic)
            pieces = chunks(cleaned)
            books.extend(pieces)
            book_report.append({"file": path.name, "pieces": len(pieces), "chars": len(cleaned)})

    news: list[str] = []
    dropped_news = []
    for path in sorted((SOURCE / "news").glob("*.jsonl")):
        for index, text in enumerate(load_jsonl(path), start=1):
            cleaned = tidy_kinyarwanda(text, drop_arabic=False)
            replacement = cleaned.count("\ufffd")
            if (
                len(cleaned) < MIN_CHARS
                or foreign_share(cleaned) > 0.3
                or replacement > 80
            ):
                dropped_news.append(
                    {
                        "line": index,
                        "chars": len(cleaned),
                        "foreign_share": round(foreign_share(cleaned), 3),
                        "replacement_chars": replacement,
                    }
                )
                continue
            news.extend(chunks(cleaned))

    write_jsonl(OUT / "kin_books" / "part-00001.jsonl", books)
    write_jsonl(OUT / "kin_news" / "part-00001.jsonl", news)
    info = {
        "kin_books": {"file_name": "kin_books/", "columns": {"prompt": "text"}},
        "kin_news": {"file_name": "kin_news/", "columns": {"prompt": "text"}},
    }
    (OUT / "dataset_info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    summary = {
        "book_pieces": len(books),
        "book_chars": sum(len(text) for text in books),
        "books": book_report,
        "news_pieces": len(news),
        "news_chars": sum(len(text) for text in news),
        "news_dropped": len(dropped_news),
        "news_dropped_detail": dropped_news,
        "max_piece_chars": max((len(text) for text in books + news), default=0),
        "left_out": [
            "news_indexes are headline lists and are not included",
            "KINYARWANDA P4 SB.pdf and Amazi.epub have no extracted words",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in summary if key != "news_dropped_detail"}, indent=2))


if __name__ == "__main__":
    main()
