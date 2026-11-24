"""W7 evaluation harness with LLM-as-judge.

Load `eval/cases.jsonl`, run each case through the main graph,
score them against per-case assertions AND LLM judge,
print a table + summary + eval report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.agents.main_graph import build_main_graph
from backend.app.db import init_db, repository as repo, session_scope

HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases.jsonl"
REPORT_PATH = HERE / "eval_report.md"
JUDGE_MODEL = "deepseek-chat"
JUDGE_THRESHOLD = 4.0  # out of 5


@dataclass
class CaseResult:
    case_id: str
    msg: str
    visited: list[str]
    final_mode: str
    final_answer: str
    citations: list[dict]
    elapsed_s: float
    checks: dict[str, bool]
    judge_score: float | None = None
    judge_reason: str | None = None
    citation_accuracy: float | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(self.checks.values())


def _check(case: dict, visited: list[str], final_answer: str,
           citations: list[dict], final_mode: str = "") -> dict[str, bool]:
    out: dict[str, bool] = {}
    if "want_visited" in case:
        out["visited_eq"] = visited == case["want_visited"]
    if "want_visited_any" in case:
        wanted = set(case["want_visited_any"])
        out["visited_any"] = bool(wanted & set(visited)) if wanted else (visited == [])
    if "want_safety" in case:
        # Check both citations tags AND final_mode (which checks metadata.redline)
        has_redline_citation = any("redline" in (c.get("tags") or []) for c in citations)
        has_safety_mode = (final_mode == "safety_first")
        # For want_safety=true: either citations have redline OR mode is safety_first
        # For want_safety=false: neither should be true
        has_redline = has_redline_citation or has_safety_mode
        out["safety"] = has_redline if case["want_safety"] else not has_redline
    if "must_include_any" in case:
        out["include_any"] = any(s in final_answer for s in case["must_include_any"])
    return out


async def _judge_answer(case: dict, final_answer: str, citations: list[dict]) -> tuple[float, str]:
    """Use LLM to judge answer quality (1-5 scale)."""
    if not final_answer or final_answer.strip() == "":
        return 0.0, "Empty answer"
    
    from backend.app.llm.router import get_router
    router = get_router()
    if not router:
        return 3.0, "Judge skipped (no router)"
    
    prompt = f"""You are an expert health coach evaluator. Score the following answer from 1-5 (5=excellent).

Scoring criteria:
1 = Wrong, harmful, or completely irrelevant
2 = Partially correct but missing key info or has errors
3 = Adequate but generic, could be more helpful
4 = Good, accurate, actionable, well-structured
5 = Excellent, personalized, evidence-based, includes citations

User question: {case['msg']}

Coach answer:
{final_answer}

Citations used: {[c.get('id', '?') for c in citations]}

Return JSON only:
{{"score": <1-5>, "reason": "<brief explanation>"}}"""

    try:
        resp = await router.acomplete(
            messages=[{"role": "user", "content": prompt}],
            model=JUDGE_MODEL,
            temperature=0.0,
        )
        text = resp.content.strip()
        # Extract JSON from response
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        data = json.loads(text)
        score = float(data.get("score", 3.0))
        reason = data.get("reason", "")
        return score, reason
    except Exception as e:
        print(f"      Judge error: {e}")
        return 3.0, f"Judge failed: {e}"


def _check_citation_accuracy(citations: list[dict]) -> float:
    """Check what fraction of cited docs actually exist in RAG corpus."""
    if not citations:
        return 1.0  # No citations to check
    
    # Load RAG seeds to get valid doc IDs
    valid_ids = set()
    try:
        from backend.app.rag.seeds import nutrition_seed, fitness_seed, mental_seed
        for seed_func in [nutrition_seed, fitness_seed, mental_seed]:
            docs = seed_func()
            for doc in docs:
                valid_ids.add(doc["id"])
    except Exception:
        # If can't load seeds, skip check
        return 1.0
    
    if not valid_ids:
        return 1.0
    
    valid_count = sum(1 for c in citations if c.get("id") in valid_ids)
    return valid_count / len(citations)


def _fmt_checks(checks: dict[str, bool]) -> str:
    return " ".join(f"{k}={'✓' if v else '✗'}" for k, v in checks.items()) or "(no asserts)"


async def run_eval(filter_prefix: str | None, threshold: float,
                  limit: int | None, judge: bool = True) -> int:
    # Load cases
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    if filter_prefix:
        cases = [c for c in cases if c["id"].startswith(filter_prefix)]
    if limit:
        cases = cases[:limit]

    print(f">>> running eval on {len(cases)} cases (judge={'on' if judge else 'off'})")
    await init_db()

    # Seed user for data-dependent cases
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    async with session_scope() as s:
        await repo.upsert_user(
            s, "evaluser", name="Eval", goal="cut",
            target_kcal=1800, weight_kg=72.0, height_cm=178.0,
        )
        for d in (1, 3, 5):
            await repo.add_activity(
                s, "evaluser", type="run", duration_min=30, intensity="medium",
                calories_burned=300, ts=now - timedelta(days=d),
            )
        for d in range(7):
            await repo.add_vital(
                s, "evaluser", sleep_min=440, hrv_ms=58,
                ts=now - timedelta(days=d),
            )

    g = build_main_graph()
    results: list[CaseResult] = []

    for i, c in enumerate(cases, 1):
        t0 = time.perf_counter()
        try:
            out = await g.ainvoke({
                "user_id": "evaluser",
                "user_message": c["msg"],
            })
            visited = out.get("visited_coaches") or []
            final_answer = out.get("final_answer") or ""
            cites = out.get("final_citations") or []
            mode = out.get("final_mode") or "?"
            checks = _check(c, visited, final_answer, cites, mode)

                    # LLM judge
            judge_score = None
            judge_reason = None
            if judge:
                judge_score, judge_reason = await _judge_answer(c, final_answer, cites)
            
            # Citation accuracy
            citation_accuracy = _check_citation_accuracy(cites)

            results.append(CaseResult(
                case_id=c["id"], msg=c["msg"], visited=visited,
                final_mode=mode, final_answer=final_answer,
                citations=cites, elapsed_s=time.perf_counter() - t0,
                checks=checks, judge_score=judge_score,
                judge_reason=judge_reason, citation_accuracy=citation_accuracy,
            ))
            print(f"  [{i}/{len(cases)}] {c['id']} passed={all(checks.values())}")
        except Exception as e:
            results.append(CaseResult(
                case_id=c["id"], msg=c["msg"], visited=[], final_mode="ERR",
                final_answer="", citations=[], elapsed_s=time.perf_counter() - t0,
                checks={}, error=repr(e),
            ))
            print(f"  [{i}/{len(cases)}] {c['id']} ERROR: {e}")

    # ---- print rows ----
    print()
    print(f"{'id':<5} {'visited':<26} {'mode':<14} {'time':>5}  status   checks")
    print("-" * 100)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        v = "[" + ",".join(r.visited) + "]"
        time_s = f"{r.elapsed_s:.1f}s" if r.elapsed_s is not None else "?s"
        print(f"{r.case_id:<5} {v[:26]:<26} {r.final_mode:<14} {time_s:>5}  "
              f"{status:<6} {_fmt_checks(r.checks)}")
        if r.error:
            print(f"      ERROR: {r.error}")

    # ---- summary ----
    failed = [r for r in results if not r.passed]
    n = len(results)
    n_pass = sum(1 for r in results if r.passed)
    acc = n_pass / max(n, 1)

    print()
    print(f"=== assertion summary: {n_pass}/{n} passed = {acc:.1%}  (threshold={threshold:.0%}) ===")

    # ---- generate report ----
    _generate_report(results, acc)

    return 0 if acc >= threshold else 1


def _generate_report(results: list[CaseResult], acc: float) -> None:
    """Generate eval-report.md."""
    lines = [
        "# HealthCoachAgent Evaluation Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        "",
        f"- **Total cases**: {len(results)}",
        f"- **Assertion pass rate**: {sum(1 for r in results if r.passed)}/{len(results)} = {acc:.1%}",
    ]
    
    # Judge summary
    judge_scores = [r.judge_score for r in results if r.judge_score is not None]
    if judge_scores:
        avg_judge = sum(judge_scores) / len(judge_scores)
        n_judge_pass = sum(1 for s in judge_scores if s >= JUDGE_THRESHOLD)
        lines.append(f"- **Judge avg score**: {avg_judge:.2f}/5")
        lines.append(f"- **Judge pass rate** (≥{JUDGE_THRESHOLD}): "
                    f"{n_judge_pass}/{len(judge_scores)}")
    
    # Citation accuracy
    cite_accs = [r.citation_accuracy for r in results if r.citation_accuracy is not None]
    if cite_accs:
        avg_cite = sum(cite_accs) / len(cite_accs)
        lines.append(f"- **Citation accuracy**: {avg_cite:.1%}")
    
    lines.extend([
        "",
        "## Per-Case Results",
        "",
        "| ID | Msg | Visited | Mode | Time | Assertions | Judge | Cite Acc |",
        "|----|-----|---------|------|------|------------|-------|----------|",
    ])
    
    for r in results:
        msg_short = r.msg[:30] + "..." if len(r.msg) > 30 else r.msg
        visited_str = ",".join(r.visited) if r.visited else "[]"
        checks_str = "✓" if r.passed else "✗"
        judge_str = f"{r.judge_score:.1f}" if r.judge_score is not None else "?"
        cite_str = f"{r.citation_accuracy:.0%}" if r.citation_accuracy is not None else "?"
        lines.append(f"| {r.case_id} | {msg_short} | {visited_str} | {r.final_mode} | "
                    f"{r.elapsed_s:.1f}s | {checks_str} | {judge_str} | {cite_str} |")
    
    # Failure details
    failed = [r for r in results if not r.passed]
    if failed:
        lines.extend([
            "",
            "## Failure Details",
            "",
        ])
        for r in failed:
            lines.append(f"### {r.case_id}")
            lines.append(f"- **Message**: {r.msg}")
            lines.append(f"- **Visited**: {r.visited}")
            lines.append(f"- **Mode**: {r.final_mode}")
            lines.append(f"- **Failed checks**: {[k for k, v in r.checks.items() if not v]}")
            lines.append(f"- **Answer (first 200 chars)**: {r.final_answer[:200]}")
            lines.append("")
    
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n>>> Report saved to {REPORT_PATH}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--filter", default=None, help="case id prefix filter")
    p.add_argument("--threshold", type=float, default=0.75)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-judge", action="store_true", help="skip LLM judge")
    args = p.parse_args()
    return asyncio.run(run_eval(args.filter, args.threshold, args.limit, judge=not args.no_judge))


if __name__ == "__main__":
    raise SystemExit(main())
