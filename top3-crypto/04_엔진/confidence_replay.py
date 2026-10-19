"""가까운 과거 확신도 점검(기획안 v5 8절, 참고 · 보정 전). 사용: python3 confidence_replay.py [--days 365] [--per-day 6]

정미님(10-13 40:49–41:07): 정성 자료가 들어간 확신도로 먼 과거를 재현하면 맞지 않는다(기록이 짧은 자료가 있음). 그래서 가까운 과거만 본다.
- 최근 days 일의 4시간봉 마감마다(per_day 2 이면 09·21시 KST 마감만) ai_analysis.build_input(conn, 코인, t) → confidence.compute
  (conf_v2, 뉴스 방향은 과거 AI 분석이 없어 '자료 없음'). DB 는 읽기 전용, AI 는 부르지 않는다.
- 결과: 다음 4시간 · 24시간 종가 방향이 확신도의 우세 쪽(side)과 같은 비율을 Long 확률 구간(≤22, 23–34, 35–45, 46–54, 55–65,
  66–77, ≥78)별로 n 과 함께. 같은 기간 '항상 Long'(오른 비율)을 기준선으로 함께 적는다. 보합(종가 같음)은 뺀다.
- 확률 보정에 쓰지 않는다. 4시간마다의 판정은 서로 겹치는 시장 상태를 공유해 독립 시행이 아니다.
→ reports/confidence_replay.json · .md (검증 화면에만 '참고(보정 전)'로)
"""
from __future__ import annotations

import json
import sys
import time

import ai_analysis
import confidence
import db

H4 = db.PERIOD_MS["4h"]
DAY = 86_400_000
BUCKETS = [("≤22", None, 22), ("23–34", 23, 34), ("35–45", 35, 45), ("46–54", 46, 54), ("55–65", 55, 65), ("66–77", 66, 77),
           ("≥78", 78, None)]


def bucket(p: int) -> str:
    for name, lo, hi in BUCKETS:
        if (lo is None or p >= lo) and (hi is None or p <= hi):
            return name
    return "?"


def _close_at(conn, symbol: str, t: int) -> float | None:
    """마감 시각 t 인 15분봉 종가(없으면 None)."""
    r = conn.execute("SELECT close FROM candles WHERE source='binance' AND symbol=? AND period='15m' AND ts=?",
                     (symbol, t - db.PERIOD_MS["15m"])).fetchone()
    return float(r[0]) if r and r[0] else None


def run(days: int = 365, per_day: int = 6, symbols=None) -> dict:
    conn = db.connect(readonly=True)
    rules = db.load_json("rules_v3.json")
    symbols = symbols or rules["symbols"]
    last = conn.execute("SELECT MAX(ts) FROM candles WHERE source='binance' AND period='15m'").fetchone()[0]
    end = (int(last) + db.PERIOD_MS["15m"]) // H4 * H4 - DAY          # 24시간 뒤 종가까지 있는 마지막 4시간 마감
    start = end - days * DAY
    utc_hours = {0, 12} if per_day == 2 else None                       # 09·21시 KST = 00·12시 UTC
    rows, t0 = [], time.time()
    for sym in symbols:
        for t in range(start, end + 1, H4):
            if utc_hours is not None and (t // 3_600_000) % 24 not in utc_hours:
                continue
            inp = ai_analysis.build_input(conn, sym, t)
            if inp is None or inp["_ref_t"] != t:
                continue                                                 # 그 시각 봉이 없음(수집 공백)
            c = confidence.compute(dict(inp, _news=None, _news_why="과거 AI 분석 없음"))
            if not c or c["p_long"] is None:
                continue
            px, p4, p24 = _close_at(conn, sym, t), _close_at(conn, sym, t + H4), _close_at(conn, sym, t + DAY)
            if px is None:
                continue
            rows.append({"symbol": sym, "t": t, "p": c["p_long"], "side": c["side"],
                         "r4": None if p4 is None else p4 / px - 1, "r24": None if p24 is None else p24 / px - 1,
                         "market_used": c["groups"]["market"]["used"]})
    secs = round(time.time() - t0, 1)
    conn.close()

    def agg(sel) -> dict:
        out = {}
        for h in ("r4", "r24"):
            v = [r for r in sel if r[h] not in (None, 0)]
            hit = sum(1 for r in v if (r[h] > 0) == (r["side"] == "Long"))
            up = sum(1 for r in v if r[h] > 0)
            out[h] = {"n": len(v), "hit_pct": round(100 * hit / len(v), 1) if v else None,
                      "up_pct": round(100 * up / len(v), 1) if v else None}
        return out
    table = {}
    for sym in list(symbols) + ["ALL"]:
        sel = rows if sym == "ALL" else [r for r in rows if r["symbol"] == sym]
        table[sym] = {"all": agg(sel), "buckets": {b: agg([r for r in sel if bucket(r["p"]) == b]) for b, _, _ in BUCKETS}}
    return {"generated_at": db.utc_iso(db.now_ms()), "version": confidence.VERSION, "rules_version": db.rules_version(rules),
            "from": db.kst_text(start, "%Y-%m-%d %H:%M"), "to": db.kst_text(end, "%Y-%m-%d %H:%M"), "days": days,
            "per_day": per_day, "n_points": len(rows), "seconds": secs,
            "market_used_pct": round(100 * sum(r["market_used"] for r in rows) / len(rows), 1) if rows else None,
            "table": table}


def write(res: dict) -> None:
    rep = db.ENGINE / "reports"
    rep.mkdir(exist_ok=True)
    (rep / "confidence_replay.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    short = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP", "ALL": "합계"}
    L = ["# 가까운 과거 확신도 점검(참고 · 보정 전)", "",
         f"- 확신도 {res['version']} · 규칙 {res['rules_version']} · {res['from']} – {res['to']} KST · 4시간 마감 하루 {res['per_day']}번 · "
         f"계산한 시점 {res['n_points']}개(코인 합) · 만든 시각 {res['generated_at']}",
         "- 뉴스 방향은 과거 AI 분석이 없어 빠졌다(시장 자료 = OI · 코인베이스 프리미엄 · 공포탐욕). "
         f"시장 자료 묶음이 쓰인 시점 {res['market_used_pct']}%.",
         "- 적중 = 다음 4시간 · 24시간 종가 방향이 확신도의 우세 쪽과 같은 비율(보합 제외). '오른 비율'은 같은 시점들에서 '항상 Long'의 적중.",
         "- 확률 보정에 쓰지 않는다. 4시간마다의 판정은 서로 겹치는 시장 상태를 공유해 독립 시행이 아니다. 46–54%(중립)의 우세 쪽은 50 이상이면 Long.",
         ""]
    for sym, t in res["table"].items():
        a = t["all"]
        L += [f"## {short.get(sym, sym)}", "",
              f"전체: 4시간 적중 {a['r4']['hit_pct']}%(n {a['r4']['n']}, 오른 비율 {a['r4']['up_pct']}%) · "
              f"24시간 적중 {a['r24']['hit_pct']}%(n {a['r24']['n']}, 오른 비율 {a['r24']['up_pct']}%)", "",
              "| Long 확률 | 4시간 적중 | n | 오른 비율 | 24시간 적중 | n | 오른 비율 |", "|---|---|---|---|---|---|---|"]
        for b, v in t["buckets"].items():
            L.append(f"| {b}% | {v['r4']['hit_pct'] if v['r4']['hit_pct'] is not None else '-'}% | {v['r4']['n']} | "
                     f"{v['r4']['up_pct'] if v['r4']['up_pct'] is not None else '-'}% | "
                     f"{v['r24']['hit_pct'] if v['r24']['hit_pct'] is not None else '-'}% | {v['r24']['n']} | "
                     f"{v['r24']['up_pct'] if v['r24']['up_pct'] is not None else '-'}% |")
        L.append("")
    (rep / "confidence_replay.md").write_text("\n".join(L), encoding="utf-8")


def main(argv) -> int:
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 365
    per_day = int(argv[argv.index("--per-day") + 1]) if "--per-day" in argv else 6
    res = run(days, per_day)
    write(res)
    a = res["table"]["ALL"]["all"]
    print(f"확신도 점검 {res['n_points']}개 시점, {res['seconds']}초 · 4시간 적중 {a['r4']['hit_pct']}%(오른 비율 {a['r4']['up_pct']}%) · "
          f"24시간 적중 {a['r24']['hit_pct']}%(오른 비율 {a['r24']['up_pct']}%) → reports/confidence_replay.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
