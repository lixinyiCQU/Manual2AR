# Manual2AR Qwen model selection — 2026-08-17

## Decision

Use Alibaba Cloud Model Studio as the main vision provider.

- Main high-capability baseline: `qwen3.8-max`.
- Reproducible dated comparison: `qwen3.7-plus-2026-05-26`.
- Fast/cost ablation: `qwen3.7-flash-2026-07-15`.
- Local hardware ablation only: `minicpm-v4.6:q4_0` through Ollama.

The default is not a claim that Qwen3.8-Max is already accurate on A1 mini
states. It is the strongest currently documented Qwen tier that accepts image
input and structured output. Task-specific accuracy must be measured on the
same labelled before/after pairs before any paper claim or automatic-advance
threshold is changed.

## Why this model family fits

The closed loop needs multiple ordered images, conservative state reasoning,
JSON output, and occasional component boxes. Alibaba Cloud documents all three
selected cloud models as accepting text, image, and video with a 1M-token
context. Qwen3.8-Max is the high-capability tier; Qwen3.7-Plus is the balanced
tier; Qwen3.7-Flash is the lightweight tier. All three support structured
output. Qwen3.7-Plus and Flash also have dated snapshots, which makes them
appropriate for reproducible comparisons.

The Qwen3-VL technical report motivates the family for multi-image reasoning,
2D/3D grounding, fine-grained perception, and embodied/spatial understanding.
Those public benchmarks are useful screening evidence, but they do not test
our exact PTFE routing and step-completion states.

## Engineering boundary

Qwen receives one explicit semantic check, not every camera frame:

1. Before image plus after image plus the current manual-grounded condition.
2. Qwen returns observable evidence, status, confidence, and candidate boxes.
3. Pydantic validates the JSON and the server applies deterministic safety
   gates; the model cannot advance the state machine by itself.
4. SAM2 and optical flow maintain the visual highlight between semantic checks.

Mac support is therefore sufficient for the first cloud baseline. An NVIDIA
machine is optional for the GroundingDINO and SAM2 comparison service or later
fine-tuning, not for calling Qwen.

## Evaluation before model freezing

Run each frozen image pair through all three Qwen models with the same prompt
and JSON schema. Report state macro-F1, wrong-operation recall, unsafe-advance
rate, coverage, latency, token use, and cost. Human overrides stay separate and
do not count as model success. Select the production model by the lowest unsafe
error subject to useful coverage, not by generic benchmark rank or price.

## Cross-provider sanity check

Qwen is the operational default, not a pre-declared scientific winner. It is
the most convenient first provider for this project because the China-region
service can be invoiced, it supports image input and structured JSON, and it
offers dated model snapshots for reproducibility.

Keep these challengers for the same labelled-pair benchmark:

- `gpt-5.6-sol`: high-capability challenger. OpenAI documents GPT-5.6 Sol as
  its flagship model and documents image input plus structured outputs for the
  current family. The backend already has an OpenAI Responses adapter.
- `gemini-3.7-flash`: optional localization challenger. Google documents this
  as a stable current Flash model and documents object-detection-style box
  output for Gemini image understanding. Add its adapter only after the frozen
  evaluation set exists, so integration work cannot be mistaken for accuracy.

No provider should replace Qwen because of a generic leaderboard. Freeze the
A1 mini test pairs first, run every candidate without prompt changes, and
choose using unsafe-advance rate, wrong-operation recall, and coverage in that
order. A stronger generic model that advances incorrectly is worse for this
workflow than a conservative model that requests another photo.

## Primary sources

- Alibaba Cloud visual model guide:
  https://help.aliyun.com/zh/model-studio/vision-model
- Alibaba Cloud model catalog and OpenAI-compatible endpoints:
  https://help.aliyun.com/en/model-studio/models
- Alibaba Cloud structured JSON output:
  https://help.aliyun.com/zh/model-studio/qwen-structured-output
- Qwen3-VL technical report:
  https://arxiv.org/abs/2511.21631
- OpenAI official model catalog:
  https://developers.openai.com/api/docs/models
- Google Gemini official model catalog:
  https://ai.google.dev/gemini-api/docs/models
- Google Gemini image-understanding guide:
  https://ai.google.dev/gemini-api/docs/generate-content/image-understanding
