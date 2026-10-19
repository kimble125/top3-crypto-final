"""가드레일 시험 표본의 결과 표(발표 11장 숫자). 사용: python3 guard_demo.py [--db] > reports/guard_demo.md
--db 를 주면 DB 에 모인 실제 뉴스 제목 · 언론사 이름도 읽기 전용으로 검사해 잘못 걸린 수(오탐)를 더한다.

표본은 tests/guard_cases.py(공격 제목 · 평범한 제목). '준비한 시험 표본의 결과'이며 모든 공격을 막는다는 뜻이 아니다."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

import guard  # noqa: E402
from guard_cases import ATTACKS, PLAIN  # noqa: E402


def _cell(t: str) -> str:
    return guard.clean_title(t).replace("|", "\\|") or "(빈 제목)"


def main() -> int:
    caught = [(t, guard.injection_pattern(t)) for t in ATTACKS]
    wrong = [(t, guard.injection_pattern(t)) for t in PLAIN]
    n_block = sum(1 for _, p in caught if p)
    n_fp = sum(1 for _, p in wrong if p)
    lines = ["# 가드레일 시험 표본 결과", "",
             f"- 시험 표본: 공격 제목 {len(ATTACKS)}건 중 차단 {n_block}건 · 평범한 제목 {len(PLAIN)}건 중 잘못 걸린 것(오탐) {n_fp}건",
             "- 처리: 걸린 제목은 AI 입력에서 빼고 뺀 수를 기록한다(ai_analysis.build_input 의 news_filtered).",
             "- 준비한 시험 표본의 결과이며 모든 공격을 막는다는 뜻이 아니다. 표본: 04_엔진/tests/guard_cases.py", "",
             "## 공격 제목", "", "| 제목(정리 뒤) | 걸린 패턴 | 처리 |", "|---|---|---|"]
    lines += [f"| {_cell(t)} | {p or '-'} | {'AI 입력에서 뺌' if p else '통과(놓침)'} |" for t, p in caught]
    lines += ["", "## 평범한 제목(금융 · AI 낱말 포함)", "", "| 제목 | 걸린 패턴 | 처리 |", "|---|---|---|"]
    lines += [f"| {_cell(t)} | {p or '-'} | {'잘못 뺌(오탐)' if p else 'AI 입력에 넣음'} |" for t, p in wrong]
    if "--db" in sys.argv:
        import db
        conn = db.connect(readonly=True)
        rows = conn.execute("SELECT title, publisher, published_at FROM news").fetchall()
        conn.close()
        bad = [(t, guard.injection_pattern(t)) for t, _, _ in rows if guard.is_injection(t)]
        bad += [(p, guard.injection_pattern(p)) for _, p, _ in rows if p and guard.is_injection(p)]
        span = (f"{db.kst_text(min(r[2] for r in rows), '%Y-%m-%d')}–{db.kst_text(max(r[2] for r in rows), '%Y-%m-%d')}"
                if rows else "-")
        lines += ["", "## 실제 수집 뉴스(오탐 점검)", "",
                  f"- 뉴스 {len(rows)}건({span} KST, 제목 · 언론사 이름) 중 걸린 것 {len(bad)}건(이 기간에 지시형 제목은 없다고 보고 모두 오탐으로 센다)."]
        lines += [f"  - {_cell(t)} · {p}" for t, p in bad[:20]]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
