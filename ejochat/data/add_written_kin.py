"""Add human-written Kinyarwanda beside the web crawl.

The Official Gazette contributes its Kinyarwanda column. The Rwanda
Biomedical Center file contributes health sentences a person wrote.
Model-written text and EjoChat chats stay out of continued pre-training.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.request import urlopen

GAZETTE_FILES = [
    "gazette_train.tsv",
    "gazette_val.tsv",
    "gazette_test.tsv",
]
GAZETTE_URL = (
    "https://huggingface.co/datasets/DigitalUmuganda/"
    "NMT_Rwandan-Gazette_parallel_data_en_kin/resolve/main/{name}"
)
RBC_URL = (
    "https://huggingface.co/datasets/DigitalUmuganda/"
    "Monolingual_health_dataset/resolve/main/rbc_kinyarwanda_health_dataset.txt"
)
TOKEN_PER_CHAR = 0.396


def download(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as remote, path.open("wb") as local:
        while True:
            chunk = remote.read(1024 * 1024)
            if not chunk:
                break
            local.write(chunk)


def write_jsonl(path: Path, texts: list[str]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    tokens = 0
    with path.open("w", encoding="utf-8") as handle:
        for text in texts:
            tokens += max(1, int(len(text) * TOKEN_PER_CHAR))
            handle.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
    summary = {"name": path.parent.name, "documents": len(texts), "tokens": tokens}
    (path.parent / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def gazette_texts(cache: Path) -> list[str]:
    texts = []
    seen = set()
    for name in GAZETTE_FILES:
        path = cache / name
        download(GAZETTE_URL.format(name=name), path)
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                text = " ".join((row.get("kin") or "").split())
                if len(text) < 40 or text in seen:
                    continue
                seen.add(text)
                texts.append(text)
    return texts


def health_texts(cache: Path) -> list[str]:
    path = cache / "rbc_kinyarwanda_health_dataset.txt"
    download(RBC_URL, path)
    texts = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = " ".join(line.split())
        if len(text) < 20 or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts


def update_dataset_info(output: Path, names: list[str]) -> None:
    info_path = output / "dataset_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    for name in names:
        info[name] = {"file_name": f"{name}/", "columns": {"prompt": "text"}}
    info.pop("kin_synthetic", None)
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    cache = root / ".cache" / "ejochat" / "written-kin"
    output = root / "data" / "mixture-written"
    gazette = write_jsonl(output / "kin_gazette" / "part-00001.jsonl", gazette_texts(cache))
    health = write_jsonl(output / "kin_health" / "part-00001.jsonl", health_texts(cache))
    update_dataset_info(output, ["kin_gazette", "kin_health"])
    print(json.dumps({"kin_gazette": gazette, "kin_health": health}, indent=2))


if __name__ == "__main__":
    main()
