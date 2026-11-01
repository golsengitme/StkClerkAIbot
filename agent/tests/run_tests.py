"""Run the clerk test questions against the agent locally (calls Bedrock).

    cd agent && uv run --no-project --with-requirements requirements.txt python tests/run_tests.py
    ... python tests/run_tests.py quarterly-deadline audit-deadlines   # run a subset

Each check passes when at least one alternative in every must_include group
appears in the answer (case-insensitive) and no must_not_include term does.
Full answers are written to tests/results/<timestamp>.md for reading.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))

from clerk_agent import answer  # noqa: E402


def check(case: dict, text: str) -> list[str]:
    low = text.lower()
    problems = []
    for group in case.get("must_include", []):
        if not any(term.lower() in low for term in group):
            problems.append("missing: " + " | ".join(group))
    for term in ("training manual", "the manual"):
        if term in low:
            problems.append(f"calls the source '{term}' (should be the stake knowledge base)")
    for term in case.get("must_not_include", []):
        if term.lower() in low:
            problems.append(f"should not mention: {term}")
    return problems


def main() -> int:
    cases = json.loads((TESTS / "questions.json").read_text(encoding="utf-8"))
    wanted = set(sys.argv[1:])
    if wanted:
        cases = [c for c in cases if c["id"] in wanted]

    out_dir = TESTS / "results"
    out_dir.mkdir(exist_ok=True)
    report = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    lines = [f"# Clerk agent test run {datetime.now():%Y-%m-%d %H:%M}\n"]
    passed = 0

    for case in cases:
        start = time.time()
        try:
            text = answer(case["question"], asker=case.get("asker"))
            problems = check(case, text)
        except Exception as error:  # surface the real error, unlike the old version
            text, problems = "", [f"error: {type(error).__name__}: {error}"]
        seconds = time.time() - start
        ok = not problems
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<22} {seconds:5.1f}s  {'; '.join(problems)}")
        lines += [
            f"## {'PASS' if ok else 'FAIL'} {case['id']} ({case['kind']}, {seconds:.1f}s)\n",
            f"**Q:** {case['question']}\n",
            *( [f"**Asker:** {case['asker']}\n"] if case.get("asker") else [] ),
            *(f"- {p}" for p in problems),
            "",
            text,
            "\n---\n",
        ]

    print(f"\n{passed}/{len(cases)} passed. Full answers: {report}")
    report.write_text("\n".join(lines), encoding="utf-8")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
