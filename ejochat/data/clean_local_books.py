"""Review the scattered local Kinyarwanda books and news, then write one clean copy.

The raw tree at data/Datasets/raw_data is left as it is. Exact copies are
collapsed after whitespace is ignored. Extracts shorter than 200 characters
are stubs and are recorded, not kept. Homepage dumps (five or more dates)
are kept apart from single articles.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "Datasets" / "raw_data"
CLEAN = ROOT / "data" / "Datasets" / "clean"
MIN_CHARS = 200
DATE_RE = re.compile(r"\d{1,2}-\d{1,2}-\d{4}")
# PDF names that do not match the extracted text filename.
PDF_HAS_TEXT = {
    "ikinyarwanda-s4-sb": "kinyarwanda-s4-sbpdf",
    "ikinyarwanda-s5-sb": "kinyarwanda-s5",
    "kinyarwanda-core-s6-sb": "secondary-6-students-bookindb",
    "igitabo-cyurukundo": "microsoft-word-igitabo-cy-urukundo-mt-tereza-w-umwana-yezu-010-20230508",
    "igitabo-cy-imigani-ya-bakame": "imigani-tima-ngiro-yu-rwanda",
    "imivugire-yemewe-y-ikinyarwanda": "microsoft-word-imfashanyigisho-yhp-imivugire-yikinyarwanda-ralc",
    "quran-mu-ikinyarwanda": "ibisobanuro-bya-quran-ntagatifu-mu-rurimi-rwikinyarwanda-wwwislamic-invitationcom-kinyarwanda-rwandian",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", "")).strip().lower()


def tidy(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    collapsed: list[str] = []
    blank = 0
    for line in lines:
        if line.strip():
            collapsed.append(line)
            blank = 0
        else:
            blank += 1
            if blank == 1:
                collapsed.append("")
    return "\n".join(collapsed).strip() + "\n"


def slug(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"^book_", "", stem, flags=re.IGNORECASE)
    stem = stem.lower().replace("_", " ").replace("-", " ")
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem or "document"


def kind_of(path: Path) -> str:
    rel = path.relative_to(RAW).as_posix()
    if rel.startswith("root/News/"):
        return "news"
    if "/Books/" in f"/{rel}" or rel.startswith("root/Books/"):
        return "book"
    return "other"


def prefer(paths: list[str]) -> str:
    def rank(item: str) -> tuple[int, int, str]:
        if "/books raw/" in item:
            return (0, len(item), item)
        if "/Others/" in item:
            return (1, len(item), item)
        return (2, len(item), item)

    return sorted(paths, key=rank)[0]


def main() -> None:
    texts = [path for path in RAW.rglob("*.txt") if path.is_file()]
    groups: dict[str, list[Path]] = defaultdict(list)
    dropped: list[dict] = []
    for path in texts:
        raw = path.read_text(encoding="utf-8", errors="replace")
        key = normalize(raw)
        if len(key) < MIN_CHARS:
            dropped.append(
                {
                    "status": "dropped",
                    "reason": "shorter than 200 characters",
                    "source": path.relative_to(RAW).as_posix(),
                    "chars": len(key),
                }
            )
            continue
        digest = hashlib.sha256(key.encode()).hexdigest()
        groups[digest].append(path)

    pdf_hashes: dict[str, list[str]] = defaultdict(list)
    for path in RAW.rglob("*.pdf"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pdf_hashes[digest].append(path.relative_to(RAW).as_posix())

    if CLEAN.exists():
        for path in CLEAN.rglob("*"):
            if path.is_file():
                path.unlink()
    (CLEAN / "books").mkdir(parents=True, exist_ok=True)
    (CLEAN / "news" / "articles").mkdir(parents=True, exist_ok=True)
    (CLEAN / "news" / "indexes").mkdir(parents=True, exist_ok=True)

    catalog: list[dict] = []
    used_names: set[str] = set()
    totals = defaultdict(int)
    book_slugs: set[str] = set()

    for digest, paths in sorted(groups.items(), key=lambda item: prefer([p.relative_to(RAW).as_posix() for p in item[1]])):
        rels = [path.relative_to(RAW).as_posix() for path in paths]
        source = prefer(rels)
        path = RAW / source
        text = tidy(path.read_text(encoding="utf-8", errors="replace"))
        base = slug(path.name)
        name = base
        suffix = 2
        while name in used_names:
            name = f"{base}-{suffix}"
            suffix += 1
        used_names.add(name)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            repeated, count = Counter(lines).most_common(1)[0]
            if repeated.lower() == "camscanner" and count / len(lines) > 0.5:
                dropped.append(
                    {
                        "status": "dropped",
                        "reason": "scan with no extracted words",
                        "source": source,
                        "copies": rels,
                        "chars": len(normalize(text)),
                    }
                )
                continue
        kind = kind_of(path)
        dates = len(DATE_RE.findall(text))
        if kind == "news" and dates >= 5:
            folder = CLEAN / "news" / "indexes"
            split = "news_index"
        elif kind == "news":
            folder = CLEAN / "news" / "articles"
            split = "news_article"
        else:
            folder = CLEAN / "books"
            split = "book"
            book_slugs.add(base)
        out = folder / f"{name}.txt"
        out.write_text(text, encoding="utf-8")
        chars = len(normalize(text))
        totals[split] += 1
        totals[f"{split}_chars"] += chars
        record = {
            "status": "kept",
            "split": split,
            "file": out.relative_to(CLEAN).as_posix(),
            "title": path.stem,
            "chars": chars,
            "source": source,
            "copies": rels,
        }
        catalog.append(record)
        for extra in rels:
            if extra == source:
                continue
            catalog.append(
                {
                    "status": "duplicate",
                    "split": split,
                    "source": extra,
                    "same_as": source,
                    "chars": chars,
                }
            )

    catalog.extend(dropped)
    pdf_rows = []
    for digest, rels in sorted(pdf_hashes.items(), key=lambda item: item[1][0]):
        stems = {slug(Path(rel).name) for rel in rels}

        def link_one(stem: str) -> str | None:
            if stem in book_slugs:
                return stem
            alias = PDF_HAS_TEXT.get(stem)
            if alias in book_slugs:
                return alias
            hits = [
                name
                for name in book_slugs
                if name.startswith(stem) and name[len(stem) :].strip("-") in {"", "pdf"}
            ]
            return hits[0] if len(hits) == 1 else None

        linked = next((match for stem in stems if (match := link_one(stem))), None)
        pdf_rows.append(
            {
                "file": sorted(rels, key=len)[0],
                "copies": rels,
                "text_file": f"books/{linked}.txt" if linked else None,
                "has_text": linked is not None,
            }
        )

    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        for row in pdf_rows:
            if row["has_text"]:
                continue
            source = row["file"]
            reader = PdfReader(str(RAW / source))
            text = tidy("\n".join(page.extract_text() or "" for page in reader.pages))
            key = normalize(text)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                repeated, count = Counter(lines).most_common(1)[0]
                if repeated.lower() == "camscanner" and count / len(lines) > 0.5:
                    record = {
                        "status": "dropped",
                        "reason": "scan with no extracted words",
                        "source": source,
                        "copies": row["copies"],
                        "chars": len(key),
                    }
                    dropped.append(record)
                    catalog.append(record)
                    continue
            if len(key) < MIN_CHARS:
                continue
            base = slug(Path(source).name)
            name = base
            suffix = 2
            while name in used_names:
                name = f"{base}-{suffix}"
                suffix += 1
            used_names.add(name)
            out = CLEAN / "books" / f"{name}.txt"
            out.write_text(text, encoding="utf-8")
            chars = len(key)
            totals["book"] += 1
            totals["book_chars"] += chars
            row["text_file"] = out.relative_to(CLEAN).as_posix()
            row["has_text"] = True
            catalog.append(
                {
                    "status": "kept",
                    "split": "book",
                    "file": row["text_file"],
                    "title": Path(source).stem,
                    "chars": chars,
                    "source": source,
                    "copies": row["copies"],
                    "note": "text read from the PDF; an earlier extract had skipped this file",
                }
            )
            for extra in row["copies"]:
                if extra == source:
                    continue
                catalog.append(
                    {
                        "status": "duplicate",
                        "split": "book",
                        "source": extra,
                        "same_as": source,
                        "chars": chars,
                    }
                )

    (CLEAN / "catalog.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in catalog),
        encoding="utf-8",
    )
    (CLEAN / "pdfs.json").write_text(json.dumps(pdf_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "raw_text_files": len(texts),
        "kept": sum(totals[key] for key in ("book", "news_article", "news_index")),
        "books": totals["book"],
        "book_chars": totals["book_chars"],
        "news_articles": totals["news_article"],
        "news_article_chars": totals["news_article_chars"],
        "news_indexes": totals["news_index"],
        "news_index_chars": totals["news_index_chars"],
        "duplicate_text_files": sum(1 for row in catalog if row["status"] == "duplicate"),
        "dropped": len(dropped),
        "unique_pdfs": len(pdf_rows),
        "pdf_copies": sum(len(row["copies"]) for row in pdf_rows),
        "pdfs_without_text": [row["file"] for row in pdf_rows if not row["has_text"]],
        "epubs_without_text": [path.relative_to(RAW).as_posix() for path in RAW.rglob("*.epub")],
        "rough_gemma_tokens": round(
            (totals["book_chars"] + totals["news_article_chars"] + totals["news_index_chars"]) * 0.396
        ),
        "left_untouched": "data/Datasets/raw_data",
        "excluded": [
            "Consolidated_jsonl/consolidated.jsonl is a second copy of the books, split into paragraphs",
            "Consolidated_jsonl/tokenized_tinyllama.pt is a training artifact, not text",
        ],
    }
    (CLEAN / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
