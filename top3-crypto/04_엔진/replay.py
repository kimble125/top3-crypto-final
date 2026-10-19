"""과거 재현: 운영(live)과 같은 계산을 과거 모든 4h 마감 T 에 적용해 mode=replay 로 저장하고 요약한다.

기획서 ver3 AI학습용 §1-7.
- 참고 기간(reference): '같은 점수일 때 4시간 뒤 상승 비율' 표를 여기서만 만든다(근거 칸 보조 정보).
- 확인 기간(check): 성적 보고용. 결과를 보고 규칙·가중치를 바꾸면 rules_v3.json 의 tries_log 에 남긴다.
- 운영 시작(engine.json live_start) 이후 T 는 재현하지 않는다(운영 기록과 섞지 않음).

사용: python3 replay.py            # 현재 규칙으로 재현·채점·요약
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import db
import pipeline
import track

REPORTS = db.ENGINE / "reports"

# 확실한 신호가 켜진 시점에 "직전 24시간 동안 신호 방향으로 이미 얼마나 움직였나"(%) 구간.
# 10-04 재현(e4)의 구간별 결과는 팀 내부 보고서에 있다(공개 저장소 제외).
# 화면의 "추격 주의" 표시(E2)와 그 근거 숫자를 여기서 만든다. 경계는 보드(board.py)가 이 JSON에서 읽어 같은 값을 쓴다.
CHASE_BUCKETS = [(None, -2.0, "반대로 2% 넘게 움직인 뒤"), (-2.0, 0.0, "반대로 0–2%"), (0.0, 2.0, "같은 방향 0–2%"),
                 (2.0, 5.0, "같은 방향 2–5%"), (5.0, None, "같은 방향 5% 이상")]
CHASE_WARN_PCT = 5.0
DAY4 = 6  # 4시간봉 6개 = 24시간


def chase_frame(full: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """확실한 신호마다: move = 직전 24시간 신호 방향 움직임(%), r4·r24 = 다음 4·24시간 신호 방향 수익률.
    종가는 걸러지지 않은 원본 4h 봉(full)에서 시각으로 찾는다(빠진 봉이면 NaN)."""
    s = f[f["strong"] == 1]
    c = full["close"]
    d = s["strong_dir"].astype(float).values
    px = s["close"].values
    prev = c.reindex(s.index - DAY4 * track.FOUR_H).values
    n4 = c.reindex(s.index + track.FOUR_H).values
    n24 = c.reindex(s.index + DAY4 * track.FOUR_H).values
    return pd.DataFrame({"move": 100 * (px / prev - 1) * d, "r4": (n4 / px - 1) * d, "r24": (n24 / px - 1) * d},
                        index=s.index)


def chase_stats(frames: dict, lo: int, hi: int) -> list[dict]:
    """구간별·종목별 n, 다음 4·24시간 방향대로 간 비율(보합 제외)."""
    out = []
    for a, b, label in CHASE_BUCKETS:
        row = {"lo": a, "hi": b, "label": label, "by_symbol": {}}
        for sym, cf in frames.items():
            x = cf[(cf.index >= lo) & (cf.index < hi)].dropna(subset=["move"])
            m = x["move"]
            x = x[((m >= a) if a is not None else True) & ((m < b) if b is not None else True)]
            def pct(r):
                r = r.dropna()
                r = r[r != 0]
                return (round(100 * float((r > 0).mean()), 1), int(len(r))) if len(r) else (None, 0)
            h4, n4 = pct(x["r4"])
            h24, n24 = pct(x["r24"])
            row["by_symbol"][sym] = {"n": int(len(x)), "hit4_pct": h4, "n4": n4, "hit24_pct": h24, "n24": n24}
        out.append(row)
    return out


def ms(date_str: str) -> int:
    t = pd.Timestamp(date_str)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int(t.timestamp() * 1000)


def run(conn, rules: dict, live_start_ms: int | None) -> dict:
    version = db.rules_version(rules)
    db.save_rules_snapshot(conn, version, rules)
    now = db.now_ms()
    ref_from, ref_to = rules["replay"]["reference_period"]
    ref_lo, ref_hi = ms(ref_from), ms(ref_to) + 86_400_000  # 끝날 포함
    chk_lo = ms(rules["replay"]["check_period_start"])
    end = live_start_ms if live_start_ms else now  # 이 시각(운영 시작) 전의 T 만 재현

    # 재현은 다시 계산할 수 있는 파생 데이터라 이 버전의 기존 행을 지우고 처음부터 만든다
    # (운영 시작 전에 돌린 재현이 운영 구간과 겹친 경우도 함께 정리됨)
    removed = 0
    for tbl in ("outcomes", "analyses"):
        removed += conn.execute(f"DELETE FROM {tbl} WHERE mode='replay' AND rules_version=?", (version,)).rowcount
    conn.commit()

    total_rows = 0
    chase_frames = {}
    for sym in rules["symbols"]:
        full = pipeline.compute(conn, sym, rules)
        f = full[(full.index < end) & (full["status"] == "ok")]
        chase_frames[sym] = chase_frame(full, f)
        rows = pipeline.to_rows(f, sym, version, "replay", now)
        conn.executemany(pipeline.INSERT_SQL, rows)
        # 채점: 다음 4h 봉 종가는 걸러지지 않은 원본 4h 봉에서(운영 채점과 같은 기준)
        nxt = full["close"].reindex(f.index + track.FOUR_H).values
        ret, call, hit, sh, bh = track.outcome_fields(f["close"], nxt, f["score"], f["strong"], f["strong_dir"])
        keep = ~np.isnan(ret)
        orows = [(sym, int(t), version, "replay", float(n), float(r), int(c), track._n(h), track._n(s), track._n(b), now)
                 for t, n, r, c, h, s, b, k in zip(f.index, nxt, ret, call, hit, sh, bh, keep) if k]
        conn.executemany(
            "INSERT OR IGNORE INTO outcomes (symbol, t_close, rules_version, mode, next_close, ret, call_dir, hit, "
            "strong_hit, base_hit, scored_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", orows)
        conn.commit()
        total_rows += len(rows)

    tries = rules.get("tries_log", [])
    check_reused = any(t.get("saw_check_period") for t in tries if isinstance(t, dict))
    periods = {
        "reference": {"from": ref_from, "to": ref_to,
                      "rows": track.summary(conn, "replay", ref_lo, ref_hi, version)},
        "check": {"from": rules["replay"]["check_period_start"], "to_exclusive_kst": db.kst_text(end, "%Y-%m-%d %H:%M"),
                  "to": db.kst_text(end - 1, "%Y-%m-%d"), "reused": check_reused,
                  "rows": track.summary(conn, "replay", chk_lo, end, version)},
    }
    # 참고 기간: 점수별 4시간 뒤 상승 비율 (보합 제외)
    hint = {}
    q = ("SELECT a.symbol, a.score, COUNT(*), SUM(o.ret > 0) FROM analyses a JOIN outcomes o "
         "ON o.symbol=a.symbol AND o.t_close=a.t_close AND o.rules_version=a.rules_version AND o.mode=a.mode "
         "WHERE a.mode='replay' AND a.rules_version=? AND a.t_close>=? AND a.t_close<? AND o.ret != 0 "
         "GROUP BY a.symbol, a.score")
    for sym, score, n, up in conn.execute(q, (version, ref_lo, ref_hi)).fetchall():
        hint.setdefault(sym, {})[str(int(score))] = {"n": int(n), "up_pct": round(100 * up / n, 1)}

    notes = [
        "4시간마다의 판정은 서로 겹치는 시장 상태를 공유하므로 독립 시행이 아닙니다.",
        "BTC·ETH·XRP 세 종목만 본 결과이며 코인 전체로 일반화하지 않습니다.",
        "매매 규칙이 아니므로 수수료·슬리피지를 반영하지 않았습니다.",
        "지표 계산 구간에 봉 누락이 있거나 워밍업 중인 시각은 빼고 셉니다.",
    ]
    if check_reused:
        notes.append("확인 기간 결과를 본 뒤 규칙을 바꾼 기록이 있어(rules_v3.json tries_log), 확인 기간 성적은 독립된 검증이 아닙니다.")
    else:
        notes.append("규칙은 이 데이터에 맞춰 고르지 않았습니다(정미님 규칙 + 임시값). 바꾸면 tries_log 에 기록합니다.")
    summary = {
        "rules_version": version,
        "rules_status": rules.get("status"),
        "generated_at": db.utc_iso(now),
        "live_start": db.utc_iso(live_start_ms) if live_start_ms else None,
        "end_exclusive": db.utc_iso(end),
        "replaced_rows": removed,
        "tries_log_len": len(tries),
        "check_reused": check_reused,
        "periods": periods,
        "score_hint_reference": hint,
        "chase": {"warn_pct": CHASE_WARN_PCT,
                  "reference": chase_stats(chase_frames, ref_lo, ref_hi),
                  "check": chase_stats(chase_frames, chk_lo, end)},
        "notes": notes,
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "replay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    (REPORTS / "replay_summary.md").write_text(to_markdown(summary), encoding="utf-8")
    summary["_inserted"] = total_rows
    return summary


def _pct(a):
    return "-" if a is None else f"{a:.1f}%"


def _ci95(hit: int, n: int) -> str:
    """방향 적중의 95% 구간(정규 근사, 판정이 서로 독립이라고 가정). 실제로는 판정이 겹쳐 더 넓다."""
    if not n:
        return "-"
    p = hit / n
    h = 1.96 * (p * (1 - p) / n) ** 0.5
    return f"{100 * (p - h):.1f}–{100 * (p + h):.1f}%"   # 범위는 '–'(마크다운에서 '~' 두 개는 취소선)


def to_markdown(s: dict) -> str:
    L = [f"# 과거 재현 요약 (규칙 {s['rules_version']}, {s['generated_at']})", "",
         "운영 기록과 별개입니다. 같은 규칙을 과거 4시간봉 마감 시각마다 적용하고 다음 4시간봉 종가로 채점했습니다.", ""]
    for key, name in (("reference", "참고 기간"), ("check", "확인 기간")):
        p = s["periods"][key]
        span = f"{p['from']} – {p['to']}" if key == "reference" else f"{p['from']} – {p['to_exclusive_kst']} KST 전까지"
        L += [f"## {name} ({span}){' · 재사용' if p.get('reused') else ''}", "",
              "| 종목 | 분석 n | 방향 판정 n | 방향 적중 | 95% 구간* | 기준 '항상 Long'(전체) | 확실한 신호 n | 확실한 신호 적중 | 기준 '항상 Long'(같은 시점)** |",
              "|---|---|---|---|---|---|---|---|---|"]
        for r in p["rows"]:
            L.append(f"| {r['symbol']} | {r['n']} | {r['called']} | {_pct(r['hit_pct'])} | {_ci95(r['hit'], r['called'])} | "
                     f"{_pct(r['base_pct'])} | {r['strong_n']} | {_pct(r['strong_pct'])} ({r['strong_hit']}/{r['strong_scored']}) | "
                     f"{_pct(r.get('strong_base_pct'))} ({r.get('strong_base_hit', 0)}/{r.get('strong_base_scored', 0)}) |")
        L += ["", "*판정이 서로 독립이라고 가정한 정규 근사. 다음 4시간 수익률은 서로 겹치지 않아 이 근사가 크게 틀리지 않습니다"
              "(10-04 GPT-6.1 Sol 계산: 시간 의존을 반영한 구간과 비슷). 24·72시간처럼 채점 구간이 겹치면 실제 구간이 훨씬 넓어지고, "
              "세 종목은 같은 시각에 함께 움직이므로(적중 여부의 상관이 높아) 세 종목 n을 합쳐 독립 표본으로 셀 수 없습니다.",
              "**확실한 신호와 비교할 기준은 그 신호가 난 같은 시점들에서 '항상 Long'이었다면의 적중률입니다(전체 기간 기준과 비교하지 않음).", ""]
    L += ["## 참고 기간: 점수별 4시간 뒤 상승 비율", "", "| 종목 | 점수 | n | 상승 비율 |", "|---|---|---|---|"]
    for sym, d in s["score_hint_reference"].items():
        for sc in sorted(d, key=lambda x: int(x)):
            L.append(f"| {sym} | {int(sc):+d} | {d[sc]['n']} | {d[sc]['up_pct']:.1f}% |")
    ch = s.get("chase")
    if ch:
        L += ["", "## 확실한 신호가 켜지기 전 24시간 움직임별 성적 (추격 주의 표시의 근거)", "",
              f"신호 방향 기준으로 직전 24시간에 이미 얼마나 움직였는지 나눠, 다음 4시간·24시간 뒤 신호 방향대로 간 비율(보합 제외)을 셉니다. "
              f"화면은 같은 방향 {ch['warn_pct']:.0f}% 이상이면 '추격 주의'를 붙입니다. 24시간 채점은 이웃 신호끼리 구간이 겹쳐 실제 표본은 n보다 작습니다.", ""]
        for key, name in (("reference", "참고 기간"), ("check", "확인 기간 · 보고만")):
            L += [f"### {name}", "", "| 직전 24시간 | 종목 | n | 4시간 뒤 방향대로 | 24시간 뒤 방향대로 |", "|---|---|---|---|---|"]
            for b in ch[key]:
                for sym, v in b["by_symbol"].items():
                    L.append(f"| {b['label']} | {sym} | {v['n']} | {_pct(v['hit4_pct'])} | {_pct(v['hit24_pct'])} |")
            L.append("")
    L += ["", "## 한계", ""] + [f"- {n}" for n in s["notes"]] + [""]
    return "\n".join(L)


def main() -> int:
    rules = db.load_json("rules_v3.json")
    eng = db.load_json("engine.json")
    conn = db.connect()
    ls = eng.get("live_start") or db.kv_get(conn, "live_start")  # 설정값 우선, 없으면 첫 운영 분석 시각
    live_start = ms(ls) if ls else None
    s = run(conn, rules, live_start)
    print(f"규칙 {s['rules_version']} 재현 행 {s['_inserted']}건")
    print(to_markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
