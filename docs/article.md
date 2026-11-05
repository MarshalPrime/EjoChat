# EjoChat: Kinyarwanda continued pre-training

Working draft, 1 November 2026. This file is the place to keep the resources, the mixture, and the training decisions. The results section stays empty until a run finishes. When there are scores, this draft moves into the ACL long-paper LaTeX template, the same format as AfriqueLLM.

Token counts are Gemma 3 tokens from `google/gemma-3-4b-pt`, the unit used in AfriqueLLM, unless a row says it was estimated at 0.396 tokens per character. The training models are Qwen3, and a Qwen tokenizer will count the same text differently.

## 1. Data and resources

The pre-training mixture follows the AfriqueLLM CMS recipe for Kinyarwanda only. CMS is monolingual text, code, math, and synthetic translation. Parallel bitext stays out. EjoChat chats stay out.

### 1.1 Kinyarwanda web text in `kin_mono`

`kin_mono` is the Kinyarwanda monolingual set. Its main body is web text, the paper's Kinyarwanda column in Table 8. All three sources are scrapes of public web pages, filtered down to Kinyarwanda. Raw text is 480,759,907 Gemma tokens. The builder repeats it up to the UniMax cap of 1,070,793,848 tokens, about 2.2 times. That repeated web text is `mixture/kin_mono/` parts `part-00001` through `part-00011`.

| Source | What it is | Hugging Face data | Gemma tokens |
|---|---|---|---:|
| FineWeb2, `kin_Latn` | Filtered web crawl, Kinyarwanda in Latin script | `HuggingFaceFW/fineweb-2` | 136,010,710 |
| WURA documents v1.0, `kin` | African web documents, Kinyarwanda portion | `castorini/wura` | 69,028,912 |
| MADLAD-400, language `rw`, clean split | Web crawl, Kinyarwanda documents in the clean split | `allenai/MADLAD-400` | 275,720,285 |
| Raw total | | | 480,759,907 |
| Trained cap after repeat | | | 1,070,793,848 |

### 1.2 Books and scraped news, also in `kin_mono`

A local collection of books and scraped news articles was deduplicated and saved under `data/Datasets/clean/`. The raw tree at `data/Datasets/raw_data` was left untouched. The review kept 90 books and 1,902 news articles, and set aside 177 news index pages. Two files had no usable words: `Nicole/KINYARWANDA P4 SB.pdf` and `root/Books/books pdf/Amazi.epub`.

The training copy is `data/Datasets/clean/for_training/part-00012.jsonl`. It was uploaded to `s3://ejochat-cpt-682975283852/mixture/kin_mono/part-00012.jsonl`, so these documents are part of `kin_mono`, beside the repeated web parts. They are seen once. They were not folded back into a rebuild of the 1.07B cap.

The 90 books are published Kinyarwanda books and booklets, not web pages. The largest are the two Bibles and a Quran commentary. The rest are school books, culture and heritage books, children's readers, language lessons, issues of Igazeti Umurage, and a few official and policy texts.

| Kind | What is in the set |
|---|---|
| Bibles | Bibiliya Yera, Bible Society of Rwanda, 2001. Bibiliya Ntagatifu, Bible Society of Rwanda Verbum, 2012. These are different books. |
| Quran commentary | Ibisobanuro bya Quran Ntagatifu mu rurimi rw'Ikinyarwanda. A commentary, not a third Bible. Arabic letters and control characters were removed before training. |
| School books | Ikinyarwanda student books and teacher guides for primary school and secondary school, from P1 through S6. |
| Culture and heritage | Proverbs, marriage customs, traditional dance, values, and Alexis Kagame's Inganji Karinga, plus booklets on Rwandan culture and heritage. |
| Children's readers | Short readers and stories, including Uruyuki, Zuba yize koga, and Bakame stories. |
| Language lessons | Lessons on spoken and written Kinyarwanda, including Rwanda Academy of Language and Culture notes. |
| Igazeti Umurage | Several issues of the Umurage cultural gazette. |
| Official and policy text | Special issues of the Official Gazette, the cultural heritage law and policy, a strategic plan, and media-sensitization reports. |

The news articles are scrapes of Kinyarwanda news sites. Of the 1,902 reviewed article files, 1,719 carry the site name in the filename:

| Site in the filename | Reviewed articles |
|---|---:|
| bbc.com | 751 |
| kigalitoday.com | 352 |
| bwiza.com | 296 |
| umuryango.rw | 94 |
| imvahonshya.co.rw | 83 |
| mamaurwagasabo.rw | 57 |
| inyarwanda.com | 45 |
| umuseke.rw | 41 |

The other 183 reviewed articles are saved under the headline, so the site is not in the filename. Another 177 files are ukwezi.rw index pages, lists of headlines with dates. Those indexes stay out of training. Before `part-00012.jsonl` was built, articles in another language and pages of broken characters were dropped, which is why the training file has 1,866 news pieces rather than 1,902.

| Piece | Documents | Characters |
|---|---:|---:|
| Books, including both Bibles and the Quran commentary | 710 | 19,588,424 |
| News articles | 1,866 | 6,578,439 |
| Combined `part-00012.jsonl` | 2,576 | 26,166,863 |

At 0.396 tokens per character this file is about 10.4 million Gemma tokens. Pieces are split at 30,000 characters so each one fits the 16,384-token training window. Apostrophes, accents, and table-of-contents dots stay.

### 1.3 Official Gazette and health sentences

Both are human-written Kinyarwanda, added on top of the web cap. The token counts below use the 0.396 character ratio. The manifests in the bucket are the record.

| Set | Source | Documents | Estimated tokens | Bucket path |
|---|---|---:|---:|---|
| `kin_gazette` | Kinyarwanda column of `DigitalUmuganda/NMT_Rwandan-Gazette_parallel_data_en_kin` | 156,860 | 9,807,464 | `mixture/kin_gazette/` |
| `kin_health` | `DigitalUmuganda/Monolingual_health_dataset`, file `rbc_kinyarwanda_health_dataset.txt` | 26,285 | 955,872 | `mixture/kin_health/` |

The Gazette file is parallel English–Kinyarwanda. Only the Kinyarwanda column is used. The English column is not training text.

### 1.4 Synthetic Kinyarwanda

The paper's Kinyarwanda synthetic budget is 12,707,048 Gemma tokens. English source text is sampled first, then translated into Kinyarwanda with Gemini 2.5 Flash. The translator is told to return only the translation and to keep numbers, names, and math markup.

Web text comes from `WebOrganizer/TopicAnnotations-Llama-3.1-8B`. A document is kept when the topic probability is at least 0.3 and the text is between 200 and 20,000 characters. Math comes from the `cot` split of `nvidia/OpenMathReasoning`, wrapped in the paper's `<problem>` and `<think>` markup.

Domain shares follow AfriqueLLM Table 9, scaled to 12,707,048 tokens. Integer rounding makes the domain rows sum to 12,707,044.

| Domain | Gemma tokens |
|---|---:|
| Science and technology | 1,469,334 |
| Politics | 1,382,852 |
| Math | 1,266,282 |
| Health | 1,224,267 |
| Travel | 1,166,922 |
| History | 1,113,406 |
| Food and dining | 1,080,865 |
| Education and jobs | 1,077,425 |
| Software development | 1,037,305 |
| Entertainment | 986,397 |
| Industrial | 901,989 |

The prepared English side is 17,653 documents and 12,713,639 Gemma tokens. Translation stops at the Kinyarwanda cap of 12,707,048. Output goes to `mixture/kin_synthetic/part-00001.jsonl`. This text is pre-training exposure to topics. It is not the question-and-answer stage.

### 1.5 English and French replay

Replay keeps English and French from being overwritten. Each language is filled to the same 1,070,793,848 Gemma-token cap as Kinyarwanda. WURA is read first. FineWeb fills the rest.

| Language | First source | Then |
|---|---|---|
| English | WURA `eng`, up to 865,600,280 | FineWeb `sample-10BT` |
| French | WURA `fra`, up to 815,336,425 | FineWeb2 `fra_Latn` |

### 1.6 Code and math

| Set | Source | Gemma tokens |
|---|---|---:|
| `finemath` | `HuggingFaceTB/finemath`, config `finemath-4plus` | 1,067,549,046 |
| `cornstack` | `nomic-ai/cornstack-python-v1` | 967,399,767 |

### 1.7 What this pre-training run adds up to

The five large CMS pieces sum to 5,260,037,405 Gemma tokens.

| Piece | Gemma tokens |
|---|---:|
| Kinyarwanda web, after the repeat | 1,070,793,848 |
| English replay | 1,070,793,848 |
| French replay | 1,070,793,848 |
| FineMath-4+ | 1,067,549,046 |
| CornStack Python | 967,399,767 |
| Synthetic Kinyarwanda | 12,707,048 |
| CMS total | 5,260,037,405 |

Gazette, health sentences, and `part-00012.jsonl` sit on top of that total. Together they are roughly 21 million tokens, well under one percent of the run.

### 1.8 Saved for instruction tuning

EjoChat questions and answers stay out of continued pre-training. The export measured 43,268 answers and about 43 million Gemma tokens of answer text, which is larger than the synthetic budget. That text teaches a reply. It joins the model after continued pre-training, when the model is taught to answer a person.

## 2. Mixture

Training reads one JSONL folder per name, each row shaped as `{"text": "..."}`. LLaMA-Factory maps the `text` field to `prompt`. The dataset line in every training config is:

`kin_mono,kin_gazette,kin_health,eng_replay,fra_replay,finemath,cornstack,kin_synthetic`

The durable copy is `s3://ejochat-cpt-682975283852/mixture/`.

Languages other than Kinyarwanda, English, and French are not in this run. Portuguese and Arabic, which the paper included, are not in this run. NLLB parallel data is not in this run. AfriqueLLM found that parallel data hurt the 12B model, and chose CMS over the mixture that added it.

## 3. Models and training

The base models are public Hugging Face checkpoints. The machine downloads them when training starts.

| Run | Checkpoint | Config |
|---|---|---|
| 4B | `Qwen/Qwen3-4B-Base` | `train/configs/qwen3-4b-kin-cms.yaml` |
| 8B | `Qwen/Qwen3-8B-Base` | `train/configs/qwen3-8b-kin-cms.yaml` |
| 14B | `Qwen/Qwen3-14B-Base` | `train/configs/qwen3-14b-kin-cms.yaml` |

AfriqueLLM continued-pretrained Qwen3 at 4B, 8B, and 14B. There is no Qwen3 16B checkpoint. Their best reported model was AfriqueQwen-14B. Their write-up says resource limits stopped the study at 14B.

Shared settings, taken from the paper's CPT recipe:

| Setting | Value |
|---|---|
| Stage | Continued pre-training (`stage: pt`) |
| Objective | Next-token prediction on packed text |
| Parameters | Full model |
| Context | 16,384 tokens |
| Global batch | 4,194,304 tokens |
| Epochs | 1 |
| Learning rate | 5e-5 |
| Schedule | Cosine, minimum learning-rate ratio 0.01, warmup ratio 0.001 |
| Precision | bfloat16 |
| Weight decay | 0.1 |
| Adam betas | 0.9, 0.95 |
| Framework | LLaMA-Factory |
| Attention | FlashAttention 2 in the file, FlashAttention 3 on H100 |
| Extra kernels | Liger |

The 4B run uses DeepSpeed ZeRO-1. The 8B and 14B runs use ZeRO-2. Gradient checkpointing is on.

GPU plan, decided before the first run:

| Run | GPUs | Per-GPU batch | Accumulation | Machines |
|---|---:|---:|---:|---|
| 4B smoke test, 2 steps | 8 | 2 | 16 | 1 `p5.48xlarge` |
| 4B full run | 16 | 2 | 8 | 2 |
| 8B full run | chosen after the 4B bill | 1 | set so the product stays 4,194,304 | |
| 14B full run | chosen after the 4B bill | 1 | set so the product stays 4,194,304 | |

The 8B and 14B config files still describe one 8-GPU machine: batch 1 and accumulation 32. Those two files change after the 4B cost is known. A single `p5.48xlarge` has 8 H100s, so 16 GPUs means two machines and 32 GPUs means four.

Wall-clock estimates scale the paper's Table 13 down to this 5.3 billion-token mixture. They are planning numbers, not measurements.

| Run | 8 GPUs | 16 GPUs | 32 GPUs |
|---|---|---|---|
| 4B | 15–20 hours | 8–10 hours | 4–5 hours |
| 8B | 30–40 hours | 15–20 hours | 8–10 hours |
| 14B | 2–3 days | 25–35 hours | 13–18 hours |

On the paper's 64 H100s, their 8B run took 18.3 hours and their 14B run took 31.1 hours, over a mixture about five times larger than this one.

Order of runs: the 2-step 4B smoke test, then the full 4B run, then 8B, then 14B. Checkpoints go to the bucket. The GPU machines are destroyed after the checkpoints are there.

## 4. Held for later

Instruction tuning uses the EjoChat questions and answers. That stage is separate from this pre-training. A base model after continued pre-training continues Kinyarwanda text. Answering a greeting such as "Amakuru ki?" is the later stage.

## 5. Results

Empty. Fill this after the 4B run with the loss curve, the checkpoint path, the wall-clock time, and the bill. The same block is repeated for 8B and 14B.

## 6. References

- Hao Yu, Tianyi Xu, Michael A. Hedderich, Wassim Hamidouche, Syed Waqas Zamir, and David Ifeoluwa Adelani. AfriqueLLM: How Data Mixing and Model Architecture Impact Continued Pre-training for African Languages. ACL 2026. arXiv:2601.06395. https://arxiv.org/abs/2601.06395
- Qwen team. Qwen3 Technical Report. 2025. https://arxiv.org/abs/2505.09388
- Checkpoints: https://huggingface.co/Qwen/Qwen3-4B-Base , https://huggingface.co/Qwen/Qwen3-8B-Base , https://huggingface.co/Qwen/Qwen3-14B-Base
- FineWeb2: https://huggingface.co/datasets/HuggingFaceFW/fineweb-2
- FineWeb: https://huggingface.co/datasets/HuggingFaceFW/fineweb
- WURA: https://huggingface.co/datasets/castorini/wura
- MADLAD-400: https://huggingface.co/datasets/allenai/MADLAD-400
- FineMath: https://huggingface.co/datasets/HuggingFaceTB/finemath
- CornStack Python: https://huggingface.co/datasets/nomic-ai/cornstack-python-v1
- Rwandan Gazette parallel data: https://huggingface.co/datasets/DigitalUmuganda/NMT_Rwandan-Gazette_parallel_data_en_kin
- RBC Kinyarwanda health sentences: https://huggingface.co/datasets/DigitalUmuganda/Monolingual_health_dataset
- Topic annotations used as synthetic web source: https://huggingface.co/datasets/WebOrganizer/TopicAnnotations-Llama-3.1-8B
- OpenMathReasoning: https://huggingface.co/datasets/nvidia/OpenMathReasoning
- Gemma 3 tokenizer used for counting: https://huggingface.co/google/gemma-3-4b-pt
- Training framework: LLaMA-Factory. https://github.com/hiyouga/LLaMA-Factory
