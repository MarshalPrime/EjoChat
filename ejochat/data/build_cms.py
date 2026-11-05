"""Build the Kinyarwanda CMS continued-pre-training mixture.

Token budgets follow AfriqueLLM Table 8. Counts use the Gemma 3 tokenizer,
which is what the paper used, including when the model being trained is Qwen.
Run this on the cloud machine that will store the mixture. A full build is
about 5.3B tokens and does not belong on a 16 GB laptop.
"""

from __future__ import annotations

import argparse
import calendar
import gzip
import json
import logging
import threading
import time
from pathlib import Path
from typing import Iterable, Iterator
from urllib.request import urlopen

import yaml

LOG = logging.getLogger("ejochat.data")
MADLAD_URL = (
    "https://huggingface.co/datasets/allenai/MADLAD-400/resolve/"
    "ecd71297d60c1eb996cd3d7c44c60ad5b55adfc6/data/"
    "{language}/{language}_{split}_{index:04d}.jsonl.gz"
)
CALIBRATION_CHARS = 1_000_000


class TokenCounter:
    """Estimate Gemma tokens from a character ratio, after an exact sample.

    AfriqueLLM calibrated a token/character ratio on 1M characters and then
    estimated the rest. `char` mode is only for the local self-check.
    """

    def __init__(self, mode: str, model_name: str | None = None) -> None:
        self.mode = mode
        self.model_name = model_name
        self._encode = self._load_encoder()
        self._seen_chars = 0
        self._seen_tokens = 0
        self.ratio: float | None = None

    def _load_encoder(self):
        if self.mode == "char":
            return lambda text: max(1, len(text) // 4)
        if self.mode != "gemma":
            raise ValueError(f"Unknown tokenizer mode: {self.mode}")
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        path = hf_hub_download(self.model_name, "tokenizer.json")
        tokenizer = Tokenizer.from_file(path)

        def encode(text: str) -> int:
            return len(tokenizer.encode(text).ids)

        return encode

    def count(self, text: str) -> int:
        if self.ratio is None:
            tokens = self._encode(text)
            self._seen_chars += len(text)
            self._seen_tokens += tokens
            if self._seen_chars >= CALIBRATION_CHARS and self._seen_chars:
                self.ratio = self._seen_tokens / self._seen_chars
                LOG.info("Token/char ratio fixed at %.4f", self.ratio)
            return tokens
        estimated = int(len(text) * self.ratio)
        return estimated if estimated > 0 else 1


class ShardWriter:
    def __init__(self, directory: Path, shard_docs: int) -> None:
        self.directory = directory
        self.shard_docs = shard_docs
        self.directory.mkdir(parents=True, exist_ok=True)
        self._shard_index = 1
        self._docs_in_shard = 0
        self._handle = None
        self.documents = 0
        self.tokens = 0
        self.files: list[Path] = []

    def write(self, text: str, tokens: int) -> None:
        if self._handle is None or self._docs_in_shard >= self.shard_docs:
            self._open_next()
        self._handle.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        self._docs_in_shard += 1
        self.documents += 1
        self.tokens += tokens

    def _open_next(self) -> None:
        self.close()
        path = self.directory / f"part-{self._shard_index:05d}.jsonl"
        self._shard_index += 1
        self._docs_in_shard = 0
        self._handle = path.open("w", encoding="utf-8")
        self.files.append(path)

    def flush(self) -> None:
        if self._handle is not None:
            self._handle.flush()

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def _human(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class StatusWriter:
    """Small JSON file synced to S3 so the build can be watched from a laptop."""

    def __init__(self, path: Path | None, job_target: int = 5_247_330_357) -> None:
        self.path = path
        self.started = time.time()
        self.stage_started = self.started
        self.fields = {
            "stage": "starting",
            "message": "Starting",
            "tokens": 0,
            "target": 0,
            "documents": 0,
            "job_tokens": 0,
            "job_target": job_target,
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        if path is not None and path.exists():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                stamp = previous.get("started_at")
                if stamp:
                    self.started = calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.update()
            threading.Thread(target=self._beat, daemon=True).start()

    def update(self, **kwargs) -> None:
        with self._lock:
            if "stage" in kwargs and kwargs["stage"] != self.fields.get("stage"):
                self.stage_started = time.time()
            self.fields.update(kwargs)
            self._write()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._write()

    def _beat(self) -> None:
        while not self._stop.wait(15):
            with self._lock:
                self._write()

    def _write(self) -> None:
        if self.path is None:
            return
        now = time.time()
        payload = dict(self.fields)
        payload["elapsed_seconds"] = int(now - self.started)
        payload["elapsed"] = _human(now - self.started)
        payload["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started))
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        tokens = int(payload.get("tokens") or 0)
        target = int(payload.get("target") or 0)
        stage_elapsed = max(now - self.stage_started, 1)
        if 0 < tokens < target:
            remaining = (target - tokens) / (tokens / stage_elapsed)
            payload["stage_eta_seconds"] = int(remaining)
            payload["stage_eta"] = _human(remaining)
        else:
            payload["stage_eta_seconds"] = None
            payload["stage_eta"] = None
        job_tokens = int(payload.get("job_tokens") or 0)
        job_target = int(payload.get("job_target") or 0)
        job_elapsed = max(now - self.started, 1)
        if 0 < job_tokens < job_target:
            remaining = (job_target - job_tokens) / (job_tokens / job_elapsed)
            payload["job_eta_seconds"] = int(remaining)
            payload["job_eta"] = _human(remaining)
        else:
            payload["job_eta_seconds"] = None
            payload["job_eta"] = None
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def iter_json_lines(path_or_url: str) -> Iterator[dict]:
    remote = path_or_url.startswith("https://") or path_or_url.startswith("http://")
    raw = urlopen(path_or_url, timeout=120) if remote else open(path_or_url, "rb")
    stream = gzip.GzipFile(fileobj=raw) if path_or_url.endswith(".gz") else raw
    try:
        for raw_line in stream:
            line = raw_line.decode("utf-8").strip()
            if line:
                yield json.loads(line)
    finally:
        stream.close()
        if stream is not raw:
            raw.close()


def document_text(record: dict, fields: list[str] | None) -> str:
    if fields:
        parts = [str(record.get(field) or "").strip() for field in fields]
        return "\n\n".join(part for part in parts if part)
    return str(record.get("text") or "").strip()


def iter_source(source: dict, cache_dir: Path) -> Iterator[dict]:
    kind = source["kind"]
    if kind == "jsonl":
        yield from iter_json_lines(source["url"])
        return
    if kind == "local_jsonl":
        yield from iter_json_lines(source["path"])
        return
    if kind == "madlad":
        url = MADLAD_URL.format(
            language=source["language"],
            split=source.get("split", "clean"),
            index=int(source.get("index", 0)),
        )
        cached = cache_dir / f"madlad-{source['language']}-{source.get('split', 'clean')}.jsonl.gz"
        if not cached.exists():
            LOG.info("Downloading %s", url)
            cached.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(url, timeout=120) as remote, cached.open("wb") as local:
                while True:
                    chunk = remote.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    local.write(chunk)
        yield from iter_json_lines(str(cached))
        return
    if kind in {"fineweb", "fineweb2", "finemath"}:
        yield from iter_hf(source)
        return
    if kind == "cornstack":
        yield from iter_cornstack(source)
        return
    raise ValueError(f"Unknown source kind: {kind}")


def iter_hf(source: dict) -> Iterator[dict]:
    from datasets import load_dataset

    kwargs = {
        "path": source["dataset"],
        "split": source.get("split", "train"),
        "streaming": True,
    }
    if source.get("config"):
        kwargs["name"] = source["config"]
    dataset = load_dataset(**kwargs)
    yield from dataset


def iter_cornstack(source: dict) -> Iterator[dict]:
    from huggingface_hub import hf_hub_url, list_repo_files

    repo = source["dataset"]
    files = sorted(
        path
        for path in list_repo_files(repo, repo_type="dataset")
        if path.endswith(".jsonl.gz") and "shard-" in path
    )
    odd = []
    for path in files:
        stem = Path(path).name.replace(".jsonl.gz", "").replace("shard-", "")
        try:
            index = int(stem)
        except ValueError:
            continue
        if index % 2 == 1:
            odd.append(path)
    if not odd:
        raise RuntimeError(f"No CornStack shards found in {repo}")
    for path in odd:
        LOG.info("Streaming %s", path)
        for record in iter_json_lines(hf_hub_url(repo, path, repo_type="dataset")):
            query = str(record.get("query") or "").strip()
            document = str(record.get("document") or "").strip()
            text = f"{query}\n\n{document}".strip()
            if text:
                yield {"text": text}


def write_until(
    records: Iterable[dict],
    writer: ShardWriter,
    counter: TokenCounter,
    budget: int,
    fields: list[str] | None,
    on_progress=None,
) -> int:
    added = 0
    last_report = time.monotonic()
    for record in records:
        if added >= budget:
            break
        text = document_text(record, fields)
        if not text:
            continue
        tokens = counter.count(text)
        writer.write(text, tokens)
        added += tokens
        now = time.monotonic()
        if on_progress is not None and now - last_report >= 15:
            writer.flush()
            on_progress(added)
            last_report = now
    return added


def replay_until(
    files: list[Path],
    writer: ShardWriter,
    counter: TokenCounter,
    budget: int,
    on_progress=None,
) -> int:
    added = 0
    last_report = time.monotonic()
    if not files or budget <= 0:
        return 0
    while added < budget:
        progressed = False
        for path in files:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    if added >= budget:
                        return added
                    text = json.loads(line)["text"]
                    tokens = counter.count(text)
                    writer.write(text, tokens)
                    added += tokens
                    progressed = True
                    now = time.monotonic()
                    if on_progress is not None and now - last_report >= 15:
                        writer.flush()
                        on_progress(added)
                        last_report = now
        if not progressed:
            break
    return added


def update_dataset_info(output: Path, name: str) -> None:
    info_path = output / "dataset_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    info[name] = {"file_name": f"{name}/", "columns": {"prompt": "text"}}
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_component(
    component: dict,
    output: Path,
    counter: TokenCounter,
    shard_docs: int,
    fraction: float,
    cache_dir: Path,
    status: StatusWriter | None = None,
    job_done: int = 0,
) -> dict:
    name = component["name"]
    target = int(component["target_tokens"] * fraction)
    if not component.get("sources"):
        LOG.info("Skipping %s; it is produced by the synthetic stage", name)
        if status is not None:
            status.update(
                stage=name,
                message="Waiting for the translation stage",
                tokens=0,
                target=target,
                documents=0,
                job_tokens=job_done,
            )
        return {"name": name, "tokens": 0, "documents": 0, "skipped": True}

    directory = output / name
    if directory.exists() and any(directory.glob("*.jsonl")):
        raise FileExistsError(f"{directory} already has shards. Remove it to rebuild.")

    writer = ShardWriter(directory, shard_docs)
    base_files: list[Path] = []
    written = 0

    def report(stage_message: str) -> None:
        if status is None:
            return
        status.update(
            stage=name,
            message=stage_message,
            tokens=writer.tokens,
            target=target,
            documents=writer.documents,
            job_tokens=job_done + writer.tokens,
        )

    try:
        for source in component["sources"]:
            remaining = target - written
            if remaining <= 0:
                break
            source_budget = min(int(source["max_tokens"] * fraction), remaining)
            before = len(writer.files)
            report(f"Reading {source['kind']}")
            got = write_until(
                iter_source(source, cache_dir),
                writer,
                counter,
                source_budget,
                source.get("text_fields"),
                on_progress=lambda _added, kind=source["kind"]: report(f"Reading {kind}"),
            )
            base_files.extend(writer.files[before:])
            written += got
            LOG.info("%s source %s: %s tokens", name, source["kind"], f"{got:,}")
        if component.get("upsample") and written < target:
            writer.close()
            report("Repeating Kinyarwanda text up to its cap")
            extra = replay_until(
                list(base_files),
                writer,
                counter,
                target - written,
                on_progress=lambda _added: report("Repeating Kinyarwanda text up to its cap"),
            )
            written += extra
            LOG.info("%s upsampled by %s tokens", name, f"{extra:,}")
    finally:
        writer.close()

    update_dataset_info(output, name)
    summary = {"name": name, "tokens": written, "documents": writer.documents, "target": target}
    (directory / "manifest.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    LOG.info("Finished %s: %s / %s tokens", name, f"{written:,}", f"{target:,}")
    return summary


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def build(
    config: dict,
    output: Path,
    fraction: float,
    only: set[str] | None,
    cache_dir: Path,
    status_path: Path | None = None,
) -> list[dict]:
    selected = [
        component
        for component in config["components"]
        if not only or component["name"] in only
    ]
    job_target = int(sum(component["target_tokens"] for component in selected) * fraction)
    status = StatusWriter(status_path, job_target=job_target)
    status.update(stage="tokenizer", message="Loading the Gemma tokenizer", target=job_target)
    mode = "char" if config.get("tokenizer") == "char" else "gemma"
    model_name = None if mode == "char" else config["tokenizer"]
    counter = TokenCounter(mode, model_name)
    summaries = []
    job_done = 0
    try:
        for component in selected:
            summary = build_component(
                component,
                output,
                counter,
                int(config.get("shard_docs", 100000)),
                fraction,
                cache_dir,
                status,
                job_done,
            )
            summaries.append(summary)
            job_done += int(summary.get("tokens") or 0)
            status.update(
                stage=summary["name"],
                message=f"Finished {summary['name']}",
                tokens=summary.get("tokens") or 0,
                target=int(component["target_tokens"] * fraction),
                documents=summary.get("documents") or 0,
                job_tokens=job_done,
            )
    finally:
        status.close()
    return summaries


def self_check() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.jsonl"
        rows = [{"text": "Kinyarwanda " * 20} for _ in range(20)]
        source.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )
        config = {
            "tokenizer": "char",
            "shard_docs": 5,
            "components": [
                {
                    "name": "kin_mono",
                    "target_tokens": 400,
                    "upsample": True,
                    "sources": [
                        {
                            "kind": "local_jsonl",
                            "path": str(source),
                            "max_tokens": 80,
                        }
                    ],
                }
            ],
        }
        summaries = build(config, root / "mixture", 1.0, None, root / "cache", None)
        assert summaries[0]["tokens"] >= 400, summaries
        shards = list((root / "mixture" / "kin_mono").glob("*.jsonl"))
        assert len(shards) > 1
        info = json.loads((root / "mixture" / "dataset_info.json").read_text(encoding="utf-8"))
        assert info["kin_mono"]["columns"]["prompt"] == "text"
    print("self-check ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Kinyarwanda CMS mixture.")
    parser.add_argument("--config", type=Path, default=Path("data/kin_cms.yaml"))
    parser.add_argument("--output", type=Path, default=Path("data/mixture"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/ejochat"))
    parser.add_argument("--fraction", type=float, default=1.0, help="Scale every token budget.")
    parser.add_argument("--only", nargs="+", help="Component names to build.")
    parser.add_argument("--status", type=Path, help="JSON file updated while the build runs.")
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    if args.self_check:
        self_check()
        return
    config = load_config(args.config)
    summaries = build(
        config,
        args.output,
        args.fraction,
        set(args.only) if args.only else None,
        args.cache_dir,
        args.status,
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
