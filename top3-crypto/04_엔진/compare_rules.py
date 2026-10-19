"""대안 규칙 비교(참고 기간만). 정미님 질문과 가중치 판단을 돕는 참고표.

- 확인 기간(2024년 이후)은 계산하지 않는다(과최적화 방지). 운영 DB 에도 쓰지 않는다(읽기 전용).
- 이 표로 규칙을 고르지 않는다. "방향이 뒤집히는지, 신호가 얼마나 드물어지는지"를 보는 용도.
- Stochastic·StochRSI 판정 일치율: 둘이 같은 신호를 두 번 세는지(실행기획안 §6 '판정 상관표').

사용: python3 compare_rules.py   → reports/rule_variants_reference.md
"""
from __future__ import annotations

import copy

import numpy as np

import db
import pipeline
import track
from replay import ms

OUT = db.ENGINE / "reports" / "rule_variants_reference.md"


def variants(base):
    def v(name, f):
        r = copy.deepcopy(base)
        f(r)
        return name, r
    # 10-04 e4: 지금 규칙(정미님 조건서)과 정미님께 묻는 질문에 맞춘 비교 항목(옛 80·20 구간 방식 항목은 지금 규칙에서 효과가 없어 바꿈)
    return [
        v("기본(현재): %K·%D 위치·기울기(Stochastic만 교차 예외) · VPCI 0선 또는 SMA 신호선 · 4:2:1", lambda r: None),
        v("StochRSI도 교차 예외(e3까지의 방식)", lambda r: r["stoch_pair"]["stochrsi"].update(cross_exception=True)),
        v("이전 규칙: 80·20 구간 교차(10-02 필기)", lambda r: r["stoch_pair"].update(mode="zone_event")),
        v("VPCI 신호선 교차만", lambda r: r["vpci"].update(cross_target="signal")),
        v("VPCI 0선 교차만", lambda r: r["vpci"].update(cross_target="zero")),
        v("가중치 3:2:2(1시간·VPCI가 모두 반대면 방향이 바뀜)", lambda r: r["weights"].update(macd=3, vpci=2)),
    ]


def main() -> int:
    base = db.load_json("rules_v3.json")
    conn = db.connect(readonly=True)
    lo = ms(base["replay"]["reference_period"][0])
    hi = ms(base["replay"]["reference_period"][1]) + 86_400_000
    rows, agree_rows = [], []
    for name, r in variants(base):
        for sym in r["symbols"]:
            full = pipeline.compute(conn, sym, r)
            f = full[(full.index >= lo) & (full.index < hi) & (full["status"] == "ok")]
            nxt = full["close"].reindex(f.index + track.FOUR_H).values
            _, _, hit, sh, bh = track.outcome_fields(f["close"], nxt, f["score"], f["strong"], f["strong_dir"])
            called, sc, bc = ~np.isnan(hit), ~np.isnan(sh), ~np.isnan(bh)
            rows.append({
                "rule": name, "sym": sym.replace("USDT", ""), "n": int(called.sum()),
                "hit": 100 * np.nansum(hit) / called.sum(), "strong_rate": 100 * f["strong"].mean(),
                "strong_n": int(sc.sum()), "strong_hit": (100 * np.nansum(sh) / sc.sum()) if sc.sum() else None,
                "base": 100 * np.nansum(bh) / bc.sum(),
            })
            if name.startswith("기본"):
                s, q = f["sto_state"], f["srsi_state"]
                both = (s != 0) & (q != 0)
                agree_rows.append({
                    "sym": sym.replace("USDT", ""), "n": len(f),
                    "both_dir": 100 * both.mean(),
                    "agree_given_both": 100 * ((s == q) & both).sum() / max(1, both.sum()),
                    "pair_nonzero": 100 * (f["pair_dir"] != 0).mean(),
                })
    conn.close()
    L = ["# 대안 규칙 비교 (참고 기간 2018-01-01 – 2023-12-31만)", "",
         f"생성: {db.utc_iso(db.now_ms())} · 계산 로직 {db.ENGINE_LOGIC} · `python3 compare_rules.py`로 다시 만들 수 있습니다.", "",
         "정미님께 확인 중인 규칙(StochRSI 교차 예외, 80·20 구간, VPCI 교차 대상)과 가중치 판단을 돕는 참고표입니다. 과최적화를 피하려고 확인 기간(2024년 이후)은 계산하지 않았고, "
         "이 표로 규칙을 고르지 않습니다. 운영 DB에는 쓰지 않았습니다. 채점은 다음 4시간봉 종가, 점수 0과 보합 제외, "
         "워밍업·봉 누락 구간 제외.", "",
         "| 규칙 | 종목 | 방향 판정 n | 방향 적중 | 확실한 신호가 켜진 비율 | 확실한 신호 n | 확실한 신호 적중 | 기준 '항상 Long' |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        sh = "-" if r["strong_hit"] is None else f"{r['strong_hit']:.1f}%"
        L.append(f"| {r['rule']} | {r['sym']} | {r['n']} | {r['hit']:.1f}% | {r['strong_rate']:.1f}% | "
                 f"{r['strong_n']} | {sh} | {r['base']:.1f}% |")
    L += ["", "## Stochastic과 StochRSI는 같은 신호를 두 번 세나 (기본 규칙, 참고 기간)", "",
          "| 종목 | 분석 n | 둘 다 방향이 있는 비율 | 그때 둘의 방향이 같은 비율 | ②(AND)가 성립한 비율 |", "|---|---|---|---|---|"]
    for a in agree_rows:
        L.append(f"| {a['sym']} | {a['n']} | {a['both_dir']:.1f}% | {a['agree_given_both']:.1f}% | {a['pair_nonzero']:.1f}% |")
    L += ["", "## 읽는 법", "",
          "- **가중치 4:2:1에서는 방향 적중이 규칙 변형과 상관없이 거의 같습니다.** 점수의 부호(Long/Short)를 MACD 혼자 정하기 "
          "때문입니다(MACD 4 > 나머지 합 3). Stochastic·StochRSI와 VPCI는 확실한 신호와 점수 크기에만 영향을 줍니다. "
          "3:2:2로 바꾸면 하위 둘이 함께 반대할 때 방향이 바뀌는데, 참고 기간에서는 방향 적중이 오히려 0.6–1.5%p 낮아졌습니다(규칙을 고르는 근거로 쓰지 않음).",
          "- 같은 데이터에 여러 규칙을 비교하면 가장 좋아 보이는 것이 우연일 수 있습니다. 규칙은 정미님의 도메인 판단으로 정합니다.",
          "- 4시간마다의 판정은 서로 독립이 아니어서 n이 커 보여도 실제 정보량은 그보다 적습니다.", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
