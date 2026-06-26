"""RAG evaluation harness (PRD §5.2.6).

Loads `tests/rag/golden_set.jsonl` and computes:
  * recall@5 — fraction of expected sources present in top-5 retrieved chunks
  * component_f1 — F1 over expected vs. generated component types
  * hallucination_rate — fraction of generated components not in the adapter whitelist
  * mean_latency_ms — mean end-to-end generation latency

If `--no-llm` is passed, only retrieval is exercised; component_f1 and
hallucination_rate are reported as -1 to signal "not measured".

Exit code:
  0 if hallucination_rate <= --max-hallucination (default 0.05)
  1 otherwise — for CI gating.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from ...rag.retriever import retrieve
from ...rag.validators import PHASE_1_COMPONENT_TYPES, build_adapter_whitelist
from ...services.iflow_generator import GeneratorError, generate as run_generate

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "tests" / "rag" / "golden_set.jsonl"


def load_golden(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _recall_at_k(retrieved_sources: list[str], expected_sources: list[str]) -> float:
    if not expected_sources:
        return 1.0
    hits = sum(1 for s in expected_sources if s in retrieved_sources)
    return hits / len(expected_sources)


def _f1(predicted: list[str], expected: list[str]) -> float:
    pset = set(predicted)
    eset = set(expected)
    if not pset and not eset:
        return 1.0
    tp = len(pset & eset)
    if tp == 0:
        return 0.0
    precision = tp / len(pset)
    recall = tp / len(eset)
    return 2 * precision * recall / (precision + recall)


async def _evaluate_row(row: dict, *, do_llm: bool, whitelist: set[str]) -> dict[str, Any]:
    started = time.perf_counter()
    retrieved, _ = await retrieve(row["prompt"])
    retrieved_sources = [c.source for c in retrieved]
    recall = _recall_at_k(retrieved_sources, row.get("expected_sources", []))

    component_types: list[str] = []
    hallucinations = 0
    error: str | None = None

    if do_llm:
        try:
            result = await run_generate(row["prompt"])
            component_types = [c.type for c in result.iflow.components]
            hallucinations = sum(1 for t in component_types if t not in whitelist)
        except GeneratorError as exc:
            error = str(exc)
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "id": row["id"],
        "recall_at_5": recall,
        "component_f1": _f1(component_types, row.get("expected_components", [])) if do_llm else -1.0,
        "hallucinated": hallucinations,
        "component_total": len(component_types),
        "latency_ms": latency_ms,
        "error": error,
    }


async def run_eval(*, do_llm: bool = True) -> dict[str, Any]:
    rows = load_golden()
    whitelist = build_adapter_whitelist() or set(PHASE_1_COMPONENT_TYPES)

    per_row = []
    for row in rows:
        per_row.append(await _evaluate_row(row, do_llm=do_llm, whitelist=whitelist))

    total_components = sum(r["component_total"] for r in per_row) or 1
    total_hallucinated = sum(r["hallucinated"] for r in per_row)

    aggregate = {
        "n": len(per_row),
        "recall_at_5_mean": statistics.fmean(r["recall_at_5"] for r in per_row) if per_row else 0.0,
        "component_f1_mean": (
            statistics.fmean(r["component_f1"] for r in per_row if r["component_f1"] >= 0)
            if do_llm else -1.0
        ),
        "hallucination_rate": total_hallucinated / total_components if do_llm else -1.0,
        "mean_latency_ms": statistics.fmean(r["latency_ms"] for r in per_row) if per_row else 0.0,
        "errors": [r for r in per_row if r["error"]],
    }
    return {"aggregate": aggregate, "rows": per_row}


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Run the IntelliFlow RAG evaluation harness.")
    parser.add_argument("--no-llm", action="store_true", help="Skip generation, evaluate retrieval only.")
    parser.add_argument("--max-hallucination", type=float, default=0.05)
    parser.add_argument("--out", type=Path, default=None, help="Write JSON report to this path.")
    args = parser.parse_args()

    report = asyncio.run(run_eval(do_llm=not args.no_llm))
    print(json.dumps(report["aggregate"], indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    rate = report["aggregate"]["hallucination_rate"]
    if rate >= 0 and rate > args.max_hallucination:
        raise SystemExit(1)


if __name__ == "__main__":
    _cli()
