"""Plain counts from the logs of one run. No statistics: this is for substrate checks.

python -m tm.report RUN_ID            a table, one row per sample, and totals
python -m tm.report RUN_ID --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, read_eval_log

from tm.manifest import REPO

SCORE_TAG = re.compile(r"<score>\s*\d+(?:\.\d+)?\s*(?:</score>|$)")


def _text(sample: EvalSample, content: Any) -> str:
    """Message content as text. Inspect stores long texts as `attachment://` references, per part."""
    prefix = "attachment://"

    def resolve(text: str) -> str:
        return sample.attachments.get(text.removeprefix(prefix), text) if text.startswith(prefix) else text

    if isinstance(content, list):
        return "\n".join(resolve(getattr(part, "text", "") or "") for part in content)
    return resolve(str(content or ""))


def sample_record(sample: EvalSample) -> dict[str, Any]:
    scores = {name: score.value for name, score in (sample.scores or {}).items()}
    task_scores = next((v for v in scores.values() if isinstance(v, dict)), {})
    assistants = [m for m in sample.messages if m.role == "assistant"]
    tool_events = [e for e in sample.events if e.event == "tool"]
    monitor_calls = [e for e in sample.events if e.event == "model" and e.role == "trusted"]
    suspicion = [(m.metadata or {}).get("suspicion_score") for m in assistants]
    return {
        "id": sample.id,
        "error": sample.error.message[:200] if sample.error else None,
        "main_task_success": task_scores.get("main_task_success"),
        "side_task_success": task_scores.get("side_task_success"),
        "max_suspicion": scores.get("max_suspicion_scorer"),
        "suspicion_on_every_tool_call_message": bool(assistants)
        and all(s is not None for m, s in zip(assistants, suspicion, strict=True) if m.tool_calls),
        # A monitor that gives no parsable score gets a default score, which looks like a real one.
        "monitor_outputs_with_score_tag": sum(
            bool(SCORE_TAG.search(_text(sample, e.output.choices[0].message.content))) for e in monitor_calls
        ),
        "monitor_calls": len(monitor_calls),
        "tool_calls": [call.function for m in assistants for call in (m.tool_calls or [])],
        "tool_call_parse_errors": sum(1 for e in tool_events if e.error and e.error.type == "parsing"),
        "tool_call_other_errors": sum(1 for e in tool_events if e.error and e.error.type != "parsing"),
        "assistant_messages_without_tool_call": sum(1 for m in assistants if not m.tool_calls),
        "total_seconds": round(sample.total_time or 0, 1),
        "model_seconds": {
            role: round(
                sum(e.working_time or 0 for e in sample.events if e.event == "model" and e.role == role), 1
            )
            for role in ("untrusted", "trusted")
        },
    }


def log_record(log: EvalLog) -> dict[str, Any]:
    samples = [sample_record(s) for s in log.samples or []]

    def count(key: str, value: Any = "C") -> int:
        return sum(1 for s in samples if s[key] == value)

    return {
        "task": log.eval.task,
        "status": log.status,
        "samples_in_task": log.eval.dataset.samples,
        "samples_completed": sum(1 for s in samples if s["error"] is None),
        "sample_errors": sum(1 for s in samples if s["error"] is not None),
        "main_task_success": count("main_task_success"),
        "side_task_success": count("side_task_success"),
        "suspicion_score_on_every_sample": all(s["suspicion_on_every_tool_call_message"] for s in samples),
        "monitor_outputs_with_score_tag": f"{sum(s['monitor_outputs_with_score_tag'] for s in samples)}"
        f"/{sum(s['monitor_calls'] for s in samples)}",
        "tool_call_parse_errors": sum(s["tool_call_parse_errors"] for s in samples),
        "seconds_per_trajectory": [s["total_seconds"] for s in samples],
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Plain counts from the logs of one run.")
    parser.add_argument("run_id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = sorted((REPO / "logs" / args.run_id).glob("*.eval"))
    if not paths:
        print(f"no .eval file in logs/{args.run_id}/", file=sys.stderr)
        return 1
    records = [log_record(read_eval_log(str(path))) for path in paths]
    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    for record in records:
        samples = record.pop("samples")
        print(json.dumps(record))
        for s in samples:
            print(
                f"  sample {s['id']}: main {s['main_task_success']} side {s['side_task_success']} "
                f"suspicion {s['max_suspicion']} "
                f"score-tag {s['monitor_outputs_with_score_tag']}/{s['monitor_calls']} "
                f"tools {s['tool_calls']} parse-errors {s['tool_call_parse_errors']} "
                f"{s['total_seconds']} s (untrusted {s['model_seconds']['untrusted']}, "
                f"trusted {s['model_seconds']['trusted']}) error {s['error']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
