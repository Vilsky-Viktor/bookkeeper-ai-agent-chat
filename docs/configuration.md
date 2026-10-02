# Configuration and LLMs

## Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `LLM_API_KEY` | yes | API key for the selected provider |
| `LLM_PROVIDER` | no | default `openai` — see "Swapping the LLM provider" below |
| `LLM_MODEL` | no | default `gpt-6-luna` — main chat/tool-calling loop |
| `LLM_FALLBACK_MODEL` | no | default `gpt-4o` — used only when a chat call errors or times out; a different model, so one outage doesn't take both down (sent without `reasoning_effort`) |
| `LLM_SUMMARY_MODEL` | no | default `gpt-6-luna` — rolling chat summary |
| `LLM_VISION_MODEL` | no | default `gpt-6-luna` — receipt reading (structured output) |
| `LLM_CATEGORIZE_MODEL` | no | default `gpt-6-luna` — the categorizer (structured output; see `make eval-categorize`) |
| `LLM_REASONING_EFFORT` | no | default `medium` (at `low` the chat eval missed some tool choices) — `gpt-6-luna` is a reasoning model (`none`, `low`, `medium`, …); OpenAI only. Set it empty when pointing a purpose at a non-reasoning model (e.g. `gpt-4o`), which rejects the parameter |
| `TRANSCRIBE_MODEL` | no | default `gpt-4o-mini-transcribe` — voice-input transcription (needs a speech-to-text model) |
| `LLM_HISTORY_TOKEN_BUDGET` | no | default `6000` — max tokens of conversation history per model call; anything trimmed is folded into the summary |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT` | no | tracing no-ops if unset |

`DAILY_TURN_LIMIT` (default 200) and `DAILY_RECEIPT_LIMIT` (default 50) are also
overridable but aren't in `.env.example` since the defaults are fine for local dev.
Everything else — database URLs, emulator hosts, storage mode — is wired directly in
`docker-compose.yml` and doesn't need to be set by hand.

### Swapping the LLM provider

Every chat model in `services/agent` — the main tool-calling loop, the fallback and
summary models, and the receipt-vision extraction call — is built through a single
factory, `build_chat_model()` in `app/integrations/llm.py`, keyed on `LLM_PROVIDER`. There's no
separate code path for receipt vision anymore (it used to go through its own raw
OpenAI client); it goes through the same factory as everything else, just with
`json_mode=True`.

Supported today: `openai` (default), `anthropic`, `google`. Switching is `LLM_PROVIDER`
+ matching `LLM_API_KEY` + a model name that provider recognizes (e.g. `LLM_MODEL=
claude-haiku-4-5` or `LLM_MODEL=gemini-2.5-flash`) — no code change. Also set
`LLM_FALLBACK_MODEL` and `LLM_VISION_MODEL` for the new provider, since their
defaults are OpenAI model names. The receipt-vision
call's multimodal message (`services/receipts.py`'s `HumanMessage` with an `image_url`
content block) works unchanged across all three; `langchain-anthropic` and
`langchain-google-genai` both translate that OpenAI-shaped block internally. The
receipt reader and the categorizer get their replies through LangChain's
`.with_structured_output()` (a Pydantic model and a JSON schema), which each provider
implements natively: strict JSON schema on OpenAI, tool calling on Anthropic and
Gemini. So the reply always has the expected shape, on any provider.

To add another provider: write one builder function (importing that provider's
LangChain integration package inside the function, not at module level, so an
uninstalled package only breaks if that provider is actually selected), add it to the
`_PROVIDER_BUILDERS` map, add the package to `pyproject.toml`, and set `LLM_PROVIDER`.

Voice-input transcription (`/api/chat/transcribe`) is the one call site that doesn't
go through `build_chat_model()` — LangChain has no unified speech-to-text model
abstraction the way it does `BaseChatModel`. It's centralized the same way, just with
its own registry: `transcribe_client()` and `_TRANSCRIBE_CLIENT_BUILDERS` in
`app/integrations/llm.py`, also keyed on `LLM_PROVIDER`. Adding a provider that supports
transcription means a builder in that registry too.

### Keeping LLM costs down

What the agent does to keep per-turn cost low (measured with the eval below and
LangSmith's per-run token counts):

- **One model, little reasoning.** Everything but the fallback runs on `gpt-6-luna` with
  `LLM_REASONING_EFFORT=medium`: reasoning tokens are billed as output, and each call's
  output cap (`integrations/llm.py`) leaves room for them.
- **No model call when the outcome is fixed.** Routing is plain code, and a receipt
  upload without a note is handled by the deterministic receipt workflow alone, with
  no chat model call.
- **Small fixed overhead, cached.** Tool descriptions hold only what each tool does
  (behavior rules live once, in the system prompt), schemas are compacted
  (`workflows/assistant.py`), and the static prefix (tools + system prompt) comes first so
  OpenAI's automatic prompt caching bills it at a discount on repeat calls.
- **Bounded history and output.** The summary window and `LLM_HISTORY_TOKEN_BUDGET`
  (see "Chat memory" in the [README](../README.md#what-it-does)), plus `max_tokens` caps per purpose in `integrations/llm.py`.
- **Batching and smaller inputs.** One categorize call per receipt, not per item;
  images are downscaled before the vision call.
- **Visibility.** LangSmith tags per purpose (`turn`, `receipt-vision`, `categorize`,
  `summarize`), and each subgraph shows as its own named run in a turn's trace.

### Evaluating a cheaper chat model

Before changing `LLM_MODEL`, run `services/agent/evals/chat_model_eval.py`. It replays
the agent's known failure modes (the ones the system prompt's rules exist for: skipped
tool calls on a `[transaction: …]` marker, invented "not found" replies, bulk deletes
without confirmation, totals quoted from the summary, receipt replies that restate the
card, …) plus core behaviors (parsing an add, filters, reply language). It uses the
production context builder, system prompt and tool schemas, with canned tool results,
so no real data is touched. It reports pass rates and API cost per model:

```bash
docker compose exec agent uv run python -m evals.chat_model_eval \
  --models gpt-6-luna --runs 3
```

Keep `--concurrency` low on low OpenAI rate-limit tiers (the eval retries 429s).

The categorizer has the same kind of eval, `services/agent/evals/categorize_eval.py`:
labeled items (brands, several languages, tobacco/alcohol, ambiguous ones) plus items
judged against a correction history, run through the real `classify()`:

```bash
docker compose exec agent uv run python -m evals.categorize_eval \
  --models gpt-6-luna --runs 3
```
