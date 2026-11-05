# Data

The training files are not in this repository. They are large, and anyone can rebuild them from the public sources below. Exact counts, book titles, and news sites are in [`docs/article.md`](../docs/article.md).

Token counts use the Gemma 3 tokenizer, `google/gemma-3-4b-pt`, so they match AfriqueLLM. The trained models are Qwen3.

## What the mixture contains

| Name | What it is | Where it is built |
|---|---|---|
| `kin_mono` | Kinyarwanda web text, repeated up to the paper's cap, plus local books and news | `data/kin_cms.yaml`, then the local-book scripts |
| `kin_gazette` | Kinyarwanda column of the Rwandan Official Gazette | `python -m ejochat.data.add_written_kin` |
| `kin_health` | Health sentences from the Rwanda Biomedical Center | `python -m ejochat.data.add_written_kin` |
| `kin_synthetic` | English web text and math translated into Kinyarwanda, 12,707,048 tokens | `python -m ejochat.data.synthetic` |
| `eng_replay` | English replay, so continued pre-training does not wipe English | `data/kin_cms.yaml` |
| `fra_replay` | French replay | `data/kin_cms.yaml` |
| `finemath` | FineMath-4+ | `data/kin_cms.yaml` |
| `cornstack` | CornStack Python | `data/kin_cms.yaml` |

EjoChat questions and answers are not in this mixture. They are for a later stage that teaches the model to answer.

## Public sources

Kinyarwanda web text, from AfriqueLLM Table 8:

| Source | Hugging Face data | Gemma tokens kept |
|---|---|---:|
| FineWeb2, `kin_Latn` | `HuggingFaceFW/fineweb-2` | 136,010,710 |
| WURA documents, `kin` | `castorini/wura` | 69,028,912 |
| MADLAD-400, language `rw`, clean split | `allenai/MADLAD-400` | 275,720,285 |

Those 480,759,907 tokens are repeated until Kinyarwanda reaches 1,070,793,848. English and French are each filled to the same cap. WURA is read first, then FineWeb. FineMath-4+ is 1,067,549,046 tokens. CornStack Python is 967,399,767 tokens.

The Gazette is `DigitalUmuganda/NMT_Rwandan-Gazette_parallel_data_en_kin`. Only the Kinyarwanda column is used. The health sentences are `DigitalUmuganda/Monolingual_health_dataset`.

Synthetic English comes from `WebOrganizer/TopicAnnotations-Llama-3.1-8B` and `nvidia/OpenMathReasoning`. Domain shares follow AfriqueLLM Table 9, scaled to the 12.7 million token Kinyarwanda budget.

## Build it

From the repository root, with a Hugging Face token that can read the Gemma 3 tokenizer:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-data.txt
export HF_TOKEN=...

python -m ejochat.data.build_cms \
  --config data/kin_cms.yaml \
  --output data/mixture
```

`--fraction 0.001` builds a small sample. The full mixture is about 5.3 billion tokens and does not belong on a laptop.

Gazette and health sentences:

```bash
python -m ejochat.data.add_written_kin
```

That writes `data/mixture-written/`. Copy `kin_gazette/` and `kin_health/` into `data/mixture/` and add both names to `data/mixture/dataset_info.json` before training.

Synthetic Kinyarwanda:

```bash
python -m ejochat.data.synthetic prepare \
  --output data/synthetic/source

export GEMINI_API_KEY=...
python -m ejochat.data.synthetic gemini \
  --input data/synthetic/source/all.jsonl \
  --output data/mixture/kin_synthetic
```

`translate` is the same step through any OpenAI-compatible server instead of Gemini.

## Local books and news

`python -m ejochat.data.clean_local_books` reads a private collection at `data/Datasets/raw_data`, drops exact copies, and writes a clean copy under `data/Datasets/clean/`. `python -m ejochat.data.prepare_local_kin` turns the books and articles into `{"text": "..."}` rows that fit the 16,384-token window. Those files are not part of this repository. The kinds of books and the news sites are listed in [`docs/article.md`](../docs/article.md).
