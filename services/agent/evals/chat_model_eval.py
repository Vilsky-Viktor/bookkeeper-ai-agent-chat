"""Chat-model eval: replays the agent's known failure modes (the ones SYSTEM_PROMPT's
clauses exist to prevent) plus core behaviors against candidate models, to decide
whether a cheaper model can run the chat controller.

Each case is built with the production context builder, system prompt and compact
tool schemas; tool calls are answered with canned results, so nothing touches the
transactions service or real data. Only the model under test is called.

Run inside the agent container (it has LLM_API_KEY and TRANSACTIONS_URL set, and
mounts this folder):
    docker compose exec agent uv run python -m evals.chat_model_eval \\
        --models gpt-4o gpt-4.1-mini --runs 3
"""

import argparse
import asyncio
import json

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.context import build_context
from app.helpers.tool_schema import compact_tool_schema
from app.integrations import llm
from app.prompts.assistant import RECEIPT_FOLLOWUP_PROMPT
from app.tools import MUTATING_TOOLS, build_tools, transactions_client

from .chat_cases import CASES
from .chat_fixtures import PRICES, fake_result
from .chat_models import Case, Run


async def _invoke_with_rate_limit_retry(model, messages) -> AIMessage:
    # Tier limits are low (e.g. 30k tokens/min on gpt-4o) and the SDK's own 2 retries
    # give up quickly; a 429 is the account's limit, not the model's answer.
    for attempt in range(8):
        try:
            return await model.ainvoke(messages)
        except Exception as e:
            if "429" not in str(e) or attempt == 7:
                raise
            await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


async def run_case(model_name: str, case: Case) -> Run:
    # Only the tool schemas are used (results are canned), so no categorize graph.
    tools = build_tools(transactions_client("eval-jwt"), None)

    if case.workflow_messages:  # runs as receipt_followup does (workflows/main.py)
        tools = [t for t in tools if t.name not in MUTATING_TOOLS]
    model = llm.build_chat_model(model_name).bind_tools([compact_tool_schema(t) for t in tools])
    thread = {"working_set": case.working_set, "summary": case.summary}
    messages = build_context(thread, {"language": case.language}, case.history, case.message)
    messages += case.workflow_messages

    if case.workflow_messages:
        messages.append(SystemMessage(content=RECEIPT_FOLLOWUP_PROMPT))
    run = Run(calls=[], text="")

    for _ in range(6):
        ai = await _invoke_with_rate_limit_retry(model, messages)
        usage: dict = dict(ai.usage_metadata or {})
        run.input_tokens += usage.get("input_tokens", 0)
        run.cached_tokens += (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
        run.output_tokens += usage.get("output_tokens", 0)
        messages.append(ai)

        if not ai.tool_calls:
            run.text = ai.content if isinstance(ai.content, str) else str(ai.content)

            return run

        for tc in ai.tool_calls:
            run.calls.append((tc["name"], tc["args"]))
            messages.append(
                ToolMessage(json.dumps(fake_result(tc["name"], tc["args"])), tool_call_id=tc["id"], name=tc["name"])
            )

    return run


def cost(model: str, runs: list[Run]) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_cached, p_out = PRICES[model]
    uncached = sum(r.input_tokens - r.cached_tokens for r in runs)
    cached = sum(r.cached_tokens for r in runs)
    out = sum(r.output_tokens for r in runs)

    return (uncached * p_in + cached * p_cached + out * p_out) / 1_000_000


async def main(models: list[str], runs: int, only: list[str] | None, concurrency: int) -> None:
    cases = [c for c in CASES if not only or c.name in only]
    sem = asyncio.Semaphore(concurrency)

    async def one(model: str, case: Case) -> tuple[str, str, Run | None, str | None]:
        async with sem:
            try:
                run = await run_case(model, case)
            except Exception as e:  # a crashed run is a failed run, not a crashed eval
                return model, case.name, None, f"error: {e}"

            return model, case.name, run, case.check(run)

    jobs = [one(m, c) for m in models for c in cases for _ in range(runs)]
    results = await asyncio.gather(*jobs)

    width = max(len(c.name) for c in cases)
    print(f"\n{'case':<{width}}  " + "  ".join(f"{m:>13}" for m in models))

    for c in cases:
        cells = []

        for m in models:
            rs = [r for r in results if r[0] == m and r[1] == c.name]
            passed = sum(1 for r in rs if r[3] is None)
            cells.append(f"{passed}/{len(rs)}".rjust(13))
        print(f"{c.name:<{width}}  " + "  ".join(cells))

    print()

    for m in models:
        rs = [r for r in results if r[0] == m]
        passed = sum(1 for r in rs if r[3] is None)
        ok_runs = [r[2] for r in rs if r[2] is not None]
        total = cost(m, ok_runs)
        per_turn = f"${total / len(ok_runs):.5f}/turn" if total is not None and ok_runs else "n/a"
        print(
            f"{m}: {passed}/{len(rs)} passed ({100 * passed / len(rs):.0f}%), eval cost "
            f"{'$%.4f' % total if total is not None else 'n/a'}, avg {per_turn}"
        )

    failures = [r for r in results if r[3] is not None]

    if failures:
        print("\nFailures:")

        for m, name, _, reason in failures:
            print(f"- [{m}] {name}: {(reason or '')[:300]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["gpt-4o", "gpt-4.1-mini"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="case names to run (default: all)")
    parser.add_argument("--concurrency", type=int, default=2, help="parallel runs; keep low on low rate-limit tiers")
    args = parser.parse_args()
    asyncio.run(main(args.models, args.runs, args.only, args.concurrency))
