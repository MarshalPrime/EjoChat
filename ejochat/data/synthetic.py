"""Synthetic Kinyarwanda text for the CMS mixture.

AfriqueLLM translated English web text and math reasoning with a strong
translator, then kept about 12.7M Gemma tokens for Kinyarwanda. This stage
prepares those English sources and translates them through any
OpenAI-compatible server, including vLLM on the training machine.

The paper's prompts are copied here so markup, formulas, and the math XML
schema stay intact.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

WEB_PROMPT = """You are a professional translator.
Translate the user text from {source_lang} into {target_lang}.
Preserve meaning, tone, formatting, inline markup, numerals, and named entities exactly.
For long texts, ensure the translation is fluent, coherent and complete. Make sure to translate all parts of the text.
Return only the translation without additional commentary."""

MATH_PROMPT = """You are a {source_lang}-to-{target_lang} translator for mathematical content.
Translate the provided math problem, reasoning, and answer while preserving:
- All numbers, formulas, and formatting
- Mathematical notation and markup
- Named entities and tone
Input structure:
<problem>[Original Problem]</problem>
<think>[Original Reasoning]</think>
[Final Answer]<eos>
Output structure:
<problem>[Translated problem]</problem>
<think>[Translated reasoning]</think>
[Translated Final Answer]<eos>
Ensure translations are fluent, coherent, and complete. Return only the translation without additional commentary."""

KIN_SYNTHETIC_TOKENS = 12_707_048


def format_math(problem: str, reasoning: str, answer: str) -> str:
    return (
        f"<problem>\n{problem.strip()}\n</problem>\n"
        f"<think>\n{reasoning.strip()}\n</think>\n"
        f"{answer.strip()}<eos>"
    )


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


# Table 9 domain sizes. Kinyarwanda receives the same proportions, scaled to 12.7M tokens.
DOMAIN_TOKENS = {
    "Math": 32_284_225,
    "Science_Tech": 37_461_084,
    "Politics": 35_256_194,
    "Health": 31_213_028,
    "Travel": 29_751_012,
    "History": 28_386_610,
    "Food_Dining": 27_556_953,
    "Education_Jobs": 27_469_250,
    "Software_Dev": 26_446_379,
    "Entertainment": 25_148_472,
    "Industrial": 22_996_479,
}
WEB_DOMAIN_INDEX = {
    2: "Software_Dev",
    4: "Education_Jobs",
    6: "Entertainment",
    10: "Food_Dining",
    12: "Health",
    13: "History",
    15: "Industrial",
    17: "Politics",
    19: "Science_Tech",
    23: "Travel",
}


def domain_budgets(total_tokens: int) -> dict[str, int]:
    weight = sum(DOMAIN_TOKENS.values())
    return {name: int(total_tokens * tokens / weight) for name, tokens in DOMAIN_TOKENS.items()}


def prepare_sources(output: Path, total_tokens: int, seed: int, status=None) -> Path:
    """Sample English web and math text up to the Kinyarwanda synthetic budget."""
    from datasets import load_dataset

    from ejochat.data.build_cms import TokenCounter

    budgets = domain_budgets(total_tokens)
    filled = {name: 0 for name in budgets}
    counter = TokenCounter("gemma", "google/gemma-3-4b-pt")
    rows: list[dict] = []
    last_report = 0.0

    def report(message: str) -> None:
        nonlocal last_report
        if status is None:
            return
        import time

        now = time.monotonic()
        if now - last_report < 15 and rows:
            return
        last_report = now
        status.update(
            stage="prepare",
            message=message,
            tokens=sum(filled.values()),
            target=total_tokens,
            documents=len(rows),
            job_tokens=sum(filled.values()),
            job_target=total_tokens,
        )

    report("Sampling English web text")
    web = load_dataset(
        "WebOrganizer/TopicAnnotations-Llama-3.1-8B",
        split="train",
        streaming=True,
    )
    for item in web:
        if all(filled[name] >= budgets[name] for name in budgets if name != "Math"):
            break
        domain = WEB_DOMAIN_INDEX.get(item.get("top_choice_index"))
        if domain is None or filled[domain] >= budgets[domain]:
            continue
        if float(item.get("top_choice_prob") or 0) < 0.3:
            continue
        text = str(item.get("text") or "").strip()
        if not 200 <= len(text) <= 20_000:
            continue
        filled[domain] += counter.count(text)
        rows.append({"text": text, "domain": domain, "source": "WebOrganizer/TopicAnnotations-Llama-3.1-8B"})
        report(f"Sampling English web text ({domain})")

    report("Sampling English math reasoning")
    math = load_dataset("nvidia/OpenMathReasoning", split="cot", streaming=True)
    math = math.shuffle(seed=seed, buffer_size=10_000)
    for item in math:
        if filled["Math"] >= budgets["Math"]:
            break
        problem = str(item.get("problem") or "").strip()
        reasoning = str(item.get("generated_solution") or "").strip()
        answer = str(item.get("expected_answer") or "").strip()
        if not problem or not reasoning:
            continue
        text = format_math(problem, reasoning, answer)
        filled["Math"] += counter.count(text)
        rows.append({"text": text, "domain": "Math", "source": "nvidia/OpenMathReasoning"})
        report("Sampling English math reasoning")

    path = output / "all.jsonl"
    write_jsonl(path, rows)
    (output / "budgets.json").write_text(json.dumps({"budgets": budgets, "filled": filled}, indent=2) + "\n")
    if status is not None:
        status.update(
            stage="prepare",
            message="English source text is ready to translate",
            tokens=sum(filled.values()),
            target=total_tokens,
            documents=len(rows),
            job_tokens=sum(filled.values()),
            job_target=total_tokens,
        )
    return path


def translate_gemini(
    path: Path,
    output: Path,
    api_key: str,
    max_tokens: int,
    status=None,
    model: str = "gemini-2.5-flash",
    workers: int = 4,
) -> int:
    """Translate prepared English rows into Kinyarwanda with the Gemini API."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from ejochat.data.build_cms import TokenCounter

    counter = TokenCounter("gemma", "google/gemma-3-4b-pt")
    output.mkdir(parents=True, exist_ok=True)
    out_path = output / "part-00001.jsonl"
    done = 0
    if out_path.exists():
        with out_path.open(encoding="utf-8") as handle:
            done = sum(1 for line in handle if line.strip())

    rows = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < done:
                continue
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    written = 0
    if done and out_path.exists():
        with out_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    written += counter.count(json.loads(line)["text"])
    errors = 0
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def one(record: dict) -> str:
        prompt = MATH_PROMPT if record.get("domain") == "Math" else WEB_PROMPT
        system = prompt.format(source_lang="English", target_lang="Kinyarwanda")
        body = json.dumps(
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": record["text"]}]}],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 16384,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }
        ).encode()
        delay = 2
        last_error = "no response"
        for _attempt in range(6):
            request = Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                method="POST",
            )
            try:
                with urlopen(request, timeout=300) as response:
                    payload = json.loads(response.read().decode())
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:180].replace("\n", " ")
                last_error = f"HTTP {exc.code} {detail}"
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            parts = ((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            text = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
            if text:
                return text
            last_error = "empty translation"
            time.sleep(delay)
        raise RuntimeError(last_error)

    sink = out_path.open("a", encoding="utf-8")
    try:
        cursor = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while cursor < len(rows) and written < max_tokens:
                chunk = rows[cursor : cursor + workers]
                cursor += len(chunk)
                futures = [pool.submit(one, record) for record in chunk]
                for future in futures:
                    try:
                        text = future.result()
                    except Exception as exc:
                        errors += 1
                        if status is not None:
                            status.update(
                                stage="kin_synthetic",
                                message=f"Translation error {errors}: {exc}",
                                tokens=written,
                                target=max_tokens,
                                documents=done,
                                errors=errors,
                            )
                        continue
                    sink.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
                    sink.flush()
                    written += counter.count(text)
                    done += 1
                    if status is not None:
                        status.update(
                            stage="kin_synthetic",
                            message=f"Translating with {model}",
                            tokens=written,
                            target=max_tokens,
                            documents=done,
                            errors=errors,
                            job_tokens=written,
                            job_target=max_tokens,
                        )
    finally:
        sink.close()

    info_path = output.parent / "dataset_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    info["kin_synthetic"] = {"file_name": "kin_synthetic/", "columns": {"prompt": "text"}}
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def translate_file(
    path: Path,
    output: Path,
    base_url: str,
    model: str,
    api_key: str,
    max_tokens: int,
) -> int:
    from urllib.request import Request, urlopen

    from ejochat.data.build_cms import TokenCounter

    counter = TokenCounter("gemma", "google/gemma-3-4b-pt")
    written = 0
    output.mkdir(parents=True, exist_ok=True)
    out_path = output / "part-00001.jsonl"
    with path.open(encoding="utf-8") as source, out_path.open("w", encoding="utf-8") as sink:
        for line in source:
            if written >= max_tokens:
                break
            record = json.loads(line)
            prompt = MATH_PROMPT if record.get("domain") == "Math" else WEB_PROMPT
            system = prompt.format(source_lang="English", target_lang="Kinyarwanda")
            body = json.dumps(
                {
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": record["text"]},
                    ],
                }
            ).encode()
            request = Request(
                base_url.rstrip("/") + "/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode())
            text = payload["choices"][0]["message"]["content"].strip()
            if not text:
                continue
            sink.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            written += counter.count(text)
    info_path = output.parent / "dataset_info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
    info["kin_synthetic"] = {"file_name": "kin_synthetic/", "columns": {"prompt": "text"}}
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def self_check() -> None:
    text = format_math("2+2", "Add the numbers.", "4")
    assert "<problem>" in text and "<think>" in text and text.endswith("<eos>")
    assert "English" in WEB_PROMPT.format(source_lang="English", target_lang="Kinyarwanda")
    budgets = domain_budgets(KIN_SYNTHETIC_TOKENS)
    assert abs(sum(budgets.values()) - KIN_SYNTHETIC_TOKENS) < 20
    print("synthetic self-check ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or translate synthetic Kinyarwanda.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("self-check")
    check.set_defaults(func=lambda args: self_check())

    prep = sub.add_parser("prepare")
    prep.add_argument("--output", type=Path, default=Path("data/synthetic/source"))
    prep.add_argument("--max-tokens", type=int, default=KIN_SYNTHETIC_TOKENS)
    prep.add_argument("--seed", type=int, default=2026)
    prep.add_argument("--status", type=Path)
    prep.set_defaults(func=lambda args: args)

    gemini = sub.add_parser("gemini")
    gemini.add_argument("--input", type=Path, required=True)
    gemini.add_argument("--output", type=Path, default=Path("data/mixture/kin_synthetic"))
    gemini.add_argument("--max-tokens", type=int, default=KIN_SYNTHETIC_TOKENS)
    gemini.add_argument("--model", default=os.environ.get("TRANSLATION_MODEL", "gemini-2.5-flash"))
    gemini.add_argument("--workers", type=int, default=4)
    gemini.add_argument("--status", type=Path)
    gemini.set_defaults(func=lambda args: args)

    trans = sub.add_parser("translate")
    trans.add_argument("--input", type=Path, required=True)
    trans.add_argument("--output", type=Path, default=Path("data/mixture/kin_synthetic"))
    trans.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"))
    trans.add_argument("--model", default=os.environ.get("TRANSLATION_MODEL", "gpt-4.1"))
    trans.add_argument("--max-tokens", type=int, default=KIN_SYNTHETIC_TOKENS)
    trans.set_defaults(
        func=lambda args: print(
            translate_file(
                args.input,
                args.output,
                args.base_url,
                args.model,
                os.environ.get("OPENAI_API_KEY", "EMPTY"),
                args.max_tokens,
            )
        )
    )
    return parser.parse_args()


def main() -> None:
    from ejochat.data.build_cms import StatusWriter

    args = parse_args()
    if args.command == "prepare":
        status = StatusWriter(args.status, job_target=args.max_tokens) if args.status else None
        try:
            print(prepare_sources(args.output, args.max_tokens, args.seed, status))
        finally:
            if status is not None:
                status.close()
        return
    if args.command == "gemini":
        status = StatusWriter(args.status, job_target=args.max_tokens) if args.status else None
        try:
            written = translate_gemini(
                args.input,
                args.output,
                os.environ["GEMINI_API_KEY"],
                args.max_tokens,
                status,
                args.model,
                args.workers,
            )
            print(written)
        finally:
            if status is not None:
                status.close()
        return
    args.func(args)


if __name__ == "__main__":
    main()
