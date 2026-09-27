# 模型接入 — model providers and the judge

TaoChronos runs without any model: every agent has a deterministic procedure and every study, bridge and audit function
runs on rules.  Models come in two ways:

* **reasoning models** for the judgement roles of a research run (`--provider`, a profile's `routing`);
* **the judge** — the model that reviews what the rules leave uncertain in the study, bridge, vision, audit and workflow
  functions (`--llm provider:model`, or a profile's `judge`).  It never replaces the rules: it adjudicates their
  uncertain items, may add what they missed as validated spans, and writes cited summaries; its answers are checked
  against a schema, against the text and against the presentism guard, and some it may only use to lower a result.

## Providers

| Provider | How | Key | Examples |
|---|---|---|---|
| `minimax` (mainland) | OpenAI-compatible, `https://api.minimax.cn/v1` | `MINIMAX_API_KEY` | `MiniMax-M3`, `MiniMax-M2.7`, `MiniMax-M2.7-highspeed` |
| `minimax-global` | `https://api.minimax.io/v1` | `MINIMAX_API_KEY` | `MiniMax-M3`, `MiniMax-M2.7` |
| `poe` | OpenAI-compatible, `https://api.poe.com/v1` (bot names as models) | `POE_API_KEY` | `claude-sonnet-4.6`, `gpt-5.4`, `qwen3-max-n` |
| `litellm` | the `litellm` package (`pip install -e ".[litellm]"`), `<provider>/<model>` strings | each back end's own variable | `deepseek/deepseek-chat`, `dashscope/qwen-max` |
| `litellm-proxy` | a LiteLLM proxy (`http://localhost:4000/v1`) | `LITELLM_API_KEY` | the proxy's model names |
| `deepseek` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | `deepseek-chat`, `deepseek-reasoner` |
| `qwen` (DashScope) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` | `qwen-max` |
| `moonshot` (Kimi) | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` | |
| `zhipu` (GLM) | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPUAI_API_KEY` | |
| `ark` (Volcengine Doubao) | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_KEY` | endpoint ids |
| `siliconflow` | `https://api.siliconflow.cn/v1` | `SILICONFLOW_API_KEY` | |
| `openrouter`, `openai`, `gemini`, `grok` | OpenAI-compatible | their keys | |
| `local` | vLLM / Ollama at `http://localhost:8000/v1` | none | |
| `anthropic` | the Anthropic SDK (`pip install -e ".[anthropic]"`) | `ANTHROPIC_API_KEY` | Claude Opus 5, Sonnet 5, Haiku 4.5 |

```bash
taochronos llm presets                                  # the presets, their endpoints and whether the key is set
taochronos llm list                                     # the models the configured providers offer
taochronos llm test minimax:MiniMax-M2.7                # one short request
taochronos study entities --input 伤寒论.txt --llm minimax:MiniMax-M2.7
taochronos bridge map --passage jinkui.13.xiaoke1 --llm poe:claude-sonnet-4.6
taochronos ask "…" --llm litellm:deepseek/deepseek-chat --llm-max-calls 60 --llm-max-cost 1
taochronos research "…" --profile minimax               # a profile: reasoning models and the judge together
```

Profiles `minimax`, `poe` and `litellm` (on the full corpus) set the routing, the model list with tiers and the judge;
edit their model lists to what your account offers.  Keys are read from the environment and never logged.  MiniMax's
reasoning (`<think>…</think>`) is split off and dropped; Poe gets no `response_format` (JSON is asked for in the prompt
and extracted); retries respect `Retry-After`.  With the Anthropic provider, server-side refusal fallbacks
(`fallbacks="default"`) are on for Opus 5; a refusal, a schema failure or an exhausted budget falls back to the
deterministic procedure and is recorded as a Decision.

## The judge

Every judge call is cached (the hash of the task, prompt, schema, temperature and any images), budgeted (calls, tokens,
cost: `--llm-max-calls`, `--llm-max-cost`), validated against its JSON schema with one repair turn, and logged (task,
model, tokens, cost, outcome — never the prompt) under `<data>/llm-cache`.  `--llm-refresh` asks again instead of reading
the cache.  The results record who decided each item: `rule`, `model` or `both` (agreement), and the summary gives the
agreement rate.

Where a model is used, by function:

| Function | The rules | The model |
|---|---|---|
| 句读 `study punctuate` | the punctuation model | reviews doubtful breaks |
| 争议 `study disputes`, 集注 `study commentaries` | cue rules | reviews stances; a cited summary |
| 实体 `study entities` (T7) | lexicon, patterns, context rules | types ambiguous spans; adds missed spans (exact, typed) |
| 今译 `study translate` (T10) | four layers | the translation, citing glosses, through the presentism guard |
| 识读 `vision read` (T1) | layout from boxes | a multimodal reading (no marks added), compared with the store |
| 古代表型 `bridge phenotype` (S10) | written forms, bounds, senses | adjudicates uncertain findings; adds validated spans |
| 古今映射 `bridge map` (S12) | levels by rules | may lower a level, never raise; a cited summary through the guard |
| 审计 `audit` (S15) | checks by claim kind | a critic: concerns, may lower a verdict, never raise |
| 规划 `ask` | intent rules | may propose skills (validated; S01 and S15 always) |
| 真实世界 `rwd spec` (S14) | names in the vocabulary | may propose a study spec — never SQL |

Evaluations can measure a model beside the rules: `TAOCHRONOS_EVAL_LLM=minimax:MiniMax-M2.7 taochronos eval entities
bridge` runs the model phases and reports both.
