# EjoChat

Open Kinyarwanda continued pre-training. This repository is the public recipe: the data budgets, the commands that rebuild the mixture, and the LLaMA-Factory configs. The datasets themselves are not stored here.

The recipe follows [AfriqueLLM](https://arxiv.org/abs/2601.06395) (ACL 2026) and keeps one language, Kinyarwanda, instead of the paper's twenty. Training is full-parameter continued pre-training of Qwen3-Base at 16,384 tokens, learning rate 5e-5, and a global batch of 4,194,304 tokens.

The counts and the list of books and news sites are in [`docs/article.md`](docs/article.md). Folder-level commands are in [`data/README.md`](data/README.md).

## Repository layout

| Path | Purpose |
|---|---|
| `data/kin_cms.yaml` | Token budgets for the Kinyarwanda CMS mixture |
| `data/README.md` | Sources and the commands that rebuild them |
| `ejochat/data/` | Builders for the web mixture, Gazette, health text, local books, and synthetic translation |
| `train/configs/` | One LLaMA-Factory config per Qwen3 size |
| `train/deepspeed/` | ZeRO-1 and ZeRO-2 configs |
| `train/run_cpt.sh` | Launch continued pre-training once `data/mixture/` exists |
| `scripts/aws/` | How this project built the mixture and trained on AWS |
| `infra/` | Terraform for the S3 bucket and the GPU machine |
| `docs/article.md` | The record of every source, count, and training decision |

Run commands from the repository root.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-data.txt
```

Training also needs LLaMA-Factory, DeepSpeed, FlashAttention, and the Liger kernel:

```bash
pip install -r requirements-train.txt
```

Accept the Gemma 3 license on the Hugging Face account that will count tokens, then export `HF_TOKEN`. The Gemma tokenizer is only the measuring tool. The trained weights are Qwen3.

## Data

`data/kin_cms.yaml` is the mixture. It pulls public text and writes `{"text": "..."}` JSONL under `data/mixture/`:

```bash
python -m ejochat.data.build_cms \
  --config data/kin_cms.yaml \
  --output data/mixture
```

Then add the Gazette, the health sentences, and the synthetic Kinyarwanda. The commands, the Hugging Face dataset names, and the token caps are in [`data/README.md`](data/README.md).

Generated files under `data/mixture/`, `data/synthetic/`, and `data/Datasets/` are gitignored. A fresh clone has the recipe and none of the text.

## Training

Each config trains one Qwen3 base model on the same mixture:

| Config | Base model | DeepSpeed | This project's GPU plan |
|---|---|---|---|
| `train/configs/qwen3-4b-kin-cms.yaml` | `Qwen/Qwen3-4B-Base` | ZeRO-1 | 16 H100s for the full run. The 2-step smoke test uses 8 H100s and accumulation 16. |
| `train/configs/qwen3-8b-kin-cms.yaml` | `Qwen/Qwen3-8B-Base` | ZeRO-2 | Chosen after the 4B bill. The file currently describes 8 H100s. |
| `train/configs/qwen3-14b-kin-cms.yaml` | `Qwen/Qwen3-14B-Base` | ZeRO-2 | Chosen after the 4B bill. The file currently describes 8 H100s. |

AfriqueLLM trained these sizes on 32 GPUs (4B) and 64 GPUs (8B and 14B). These configs keep the same 4,194,304-token update on fewer GPUs by accumulating gradients. The comment at the top of each file is the batch math.

Once `data/mixture/` contains `kin_mono` and `kin_synthetic`:

```bash
bash train/run_cpt.sh train/configs/qwen3-4b-kin-cms.yaml
```

Smoke-test with `max_steps=2` before a full run. On an H100 machine, override `flash_attn=fa3`.

## AWS

Terraform creates the bucket and, only when asked, the GPU machine. `launch_trainer` stays false until a training run is requested.

```bash
cd infra
terraform init
terraform apply
```

From the repository root, after the bucket exists:

```bash
./scripts/aws/push_code.sh
```

`scripts/aws/build_on_cpu.sh` builds the web mixture on a CPU machine. `scripts/aws/build_synthetic.sh` translates the synthetic set. `scripts/aws/on_trainer.sh` pulls the mixture onto the GPU machine and starts training. Checkpoints belong in the bucket, not in git.

## Citation

This project uses the CMS recipe from:

```bibtex
@misc{yu2026afriquellmdatamixingmodel,
      title={AfriqueLLM: How Data Mixing and Model Architecture Impact Continued Pre-training for African Languages},
      author={Hao Yu and Tianyi Xu and Michael A. Hedderich and Wassim Hamidouche and Syed Waqas Zamir and David Ifeoluwa Adelani},
      year={2026},
      eprint={2601.06395},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2601.06395},
}
```
