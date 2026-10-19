"""E3: 정미님 조건서(10-03) 순차 진입 재현. 거래 단위 성적(참고 기간이 주 결과, 확인 기간은 보고만).

조건서 순서: (1) 4시간 MACD Long 상태 → (2) 1시간 Stochastic·StochRSI 모두 상승 모멘텀 →
(3) (1)(2)가 모두 충족된 상태에서 15분 VPCI 0선 상향 돌파 또는 신호선(SMA) 골든크로스 → 진입. Short는 거울상.
청산 규칙은 조건서에 없어 X1–X5를 모두 계산한다(성적을 보고 고르지 않음).

- 판정은 엔진 함수(judge.macd_frame·pair_frame)를 그대로 쓴다. VPCI 사건은 judge.vpci_frame(zero_or_signal) 안의
  사건 정의를 그대로 따른 vpci_events 로 뽑는다(tests/test_sequential.py 에서 judge 결과와 같은지 확인).
- 봉 누락: pipeline 의 data_short 와 같은 기준(지표 계산 구간 안에 빠진 봉)이면 그 봉의 방향·사건을 0으로 본다.
- 운영 DB 는 읽기 전용(mode=ro)으로만 연다. 아무것도 쓰지 않는다.

사용: python3 sequential_entry.py   → reports/sequential_entry_reference.md
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys

import numpy as np
import pandas as pd

import db
import indicators as ind
import judge
import pipeline

OUT = db.ENGINE / "reports" / "sequential_entry_reference.md"
P15, P1, P4 = db.PERIOD_MS["15m"], db.PERIOD_MS["1h"], db.PERIOD_MS["4h"]
HOUR = 3_600_000
FEE_RT = 0.002            # 왕복 수수료 0.2%(진입 0.1% + 청산 0.1%), 건별 수익률에서 뺀다
EXITS = ["X1", "X2", "X3", "X4", "X5"]
HOLD_MS = {"X4": 4 * HOUR, "X5": 24 * HOUR}
VARIANTS = ["A", "B"]
N_RAND = 200
SEED = 20261004
CHECK_END = "2026-10-02T20:00:00Z"   # 확인 기간 끝(이 시각에 마감한 봉 포함) = 10-03 05:00 KST

EXIT_TEXT = {
    "X1": "MACD 4h 방향이 진입 방향이 아니게 되면",
    "X2": "상위 조건 U가 진입 방향이 아니게 되면",
    "X3": "반대 방향 진입 사건이 나면(그 봉에서 반대로 진입)",
    "X4": "4시간 보유",
    "X5": "24시간 보유",
    "c1": "보드 확실한 신호가 꺼지거나 바뀌면(4시간마다)",
    "c2": "MACD 4h 반전(4시간마다)",
}


def ms(s: str) -> int:
    t = pd.Timestamp(s)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int(t.timestamp() * 1000)


# ---------------------------------------------------------------- 신호 시계열

def vpci_events(c15: pd.DataFrame, p: dict, period_ms: int | None = None) -> pd.DataFrame:
    """VPCI 사건(+1 상향 / −1 하향 / 0 없음). judge.vpci_frame 안의 사건 정의를 그대로 따른다.
    zero_or_signal: 0선 돌파 또는 신호선 교차. 같은 봉에서 반대 방향 사건이 함께 나면 사건 아님.
    바로 앞 봉이 빠졌거나 값이 없으면 사건 아님.
    열 hold_invalid·brk 는 judge._hold_events 에 그대로 넣으면 vpci_frame 의 vpci_dir 가 나오도록 둔다(시험용)."""
    v = ind.vpci(c15["close"], c15["volume"], p["short"], p["long"], p["signal"], p.get("signal_ma", "vwma"))
    vp, vs = v["vpci"], v["vpcis"]
    brk = judge.bar_breaks(vp.index, period_ms) if period_ms else pd.Series(False, index=vp.index)
    if p["cross_target"] == "zero_or_signal":
        v1, s1 = vp.shift(1), vs.shift(1)
        up = ((v1 <= 0) & (vp > 0)) | ((v1 <= s1) & (vp > vs))
        dn = ((v1 >= 0) & (vp < 0)) | ((v1 >= s1) & (vp < vs))
        ev = pd.Series(up.astype(int) - dn.astype(int), index=vp.index)
        ev[vp.isna() | vs.isna() | v1.isna() | s1.isna() | brk] = 0
    else:
        # signal·zero: 상태(위·아래)가 실제로 바뀐 봉을 사건으로 본다(judge.change_points 정의)
        d = judge.vpci_frame(c15, p, period_ms)["vpci_dir"]
        ev = judge.change_points(d)
    return pd.DataFrame({"event": ev.astype(int), "hold_invalid": vp.isna() | vs.isna(), "brk": brk})


def _gap_masked(s: pd.Series, c: pd.DataFrame, period: str, window: int) -> pd.Series:
    """pipeline 의 data_short 기준: 최근 window 봉 안에 빠진 봉이 있으면 그 봉의 값은 0(알 수 없음)."""
    gap = pipeline._recent_gap(c, period, window).reindex(s.index).fillna(False).astype(bool)
    return s.where(~gap, 0).astype(int)


def asof(s: pd.Series, times: np.ndarray, period_ms: int) -> np.ndarray:
    """각 시각 t 에 이미 닫힌 마지막 봉(마감 ≤ t)의 값. 그 봉이 기대한 최신 봉이 아니면(마감이 t − 봉 길이 이하,
    즉 사이에 빠진 봉) 0. 미래 봉(마감 > t)은 쓰지 않는다."""
    times = np.asarray(times, dtype="int64")
    if len(s) == 0:
        return np.zeros(len(times), dtype=int)
    idx = np.asarray(s.index, dtype="int64")
    pos = np.searchsorted(idx, times, side="right") - 1
    pc = np.clip(pos, 0, None)
    fresh = (pos >= 0) & (times - idx[pc] < period_ms)
    return np.where(fresh, np.asarray(s.values)[pc], 0).astype(int)


def build_frame(c4: pd.DataFrame, c1: pd.DataFrame, c15: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """15분봉 시간축(index = 15분봉 마감 UTC ms).
    close: 15분 종가 / ev: VPCI 사건 / macd: 그 시각에 닫힌 마지막 4h 봉의 MACD 방향 / pair: 마지막 1h 봉의 두 지표 방향 /
    U: macd == pair ≠ 0 이면 그 방향, 아니면 0 / U_prev: 15분 전 시각(t − 15분)의 U."""
    p4, p1, p15 = rules["macd"]["period"], rules["stoch_pair"]["period"], rules["vpci"]["period"]
    per4, per1, per15 = db.PERIOD_MS[p4], db.PERIOD_MS[p1], db.PERIOD_MS[p15]
    lb = pipeline.lookback_bars(rules)
    m = _gap_masked(judge.macd_frame(c4, rules["macd"])["macd_dir"], c4, p4, lb["4h"])
    pr = (_gap_masked(judge.pair_frame(c1, rules["stoch_pair"], per1)["pair_dir"], c1, p1, lb["1h"])
          if len(c1) else pd.Series(dtype=int))
    ev = _gap_masked(vpci_events(c15, rules["vpci"], per15)["event"], c15, p15, lb["15m"])
    t = np.asarray(c15.index, dtype="int64")

    def upper(times):
        a, b = asof(m, times, per4), asof(pr, times, per1)
        return a, np.where((a == b) & (a != 0), a, 0).astype(int)

    macd_now, U = upper(t)
    _, U_prev = upper(t - per15)
    return pd.DataFrame({"close": c15["close"].values, "ev": ev.values, "macd": macd_now,
                         "pair": asof(pr, t, per1), "U": U, "U_prev": U_prev}, index=t)


def entry_dirs(ev, U, U_prev, variant: str) -> np.ndarray:
    """진입 사건 방향. A: 사건 방향 d 와 U(t) == d. B: 여기에 U(t − 15분) == d 도(조건이 먼저 갖춰진 뒤의 교차만)."""
    ev, U, U_prev = (np.asarray(x) for x in (ev, U, U_prev))
    ok = (ev != 0) & (U == ev)
    if variant == "B":
        ok &= (U_prev == ev)
    elif variant != "A":
        raise ValueError(variant)
    return np.where(ok, ev, 0).astype(int)


# ---------------------------------------------------------------- 거래 시뮬레이션

def simulate(times, close, entry, macd, upper, rule: str) -> list[dict]:
    """종목 하나, 포지션은 하나. 매 봉에서 (1) 보유 중이면 청산 조건을 보고 닫고 (2) 비어 있으면 진입 사건에 진입.
    그래서 청산한 봉에서 진입 사건이 나면 같은 종가로 새로 진입한다. 보유 중 같은 방향 사건은 무시.
    마지막 봉에서는 새로 진입하지 않는다. 끝까지 열린 포지션은 마지막 종가로 닫고 forced=True.
    rule: X1(macd 가 방향이 아니게 됨) X2(upper 가 방향이 아니게 됨) X3(반대 방향 진입 사건) X4·X5(보유 시간)."""
    t = np.asarray(times, dtype="int64").tolist()
    c = np.asarray(close, dtype=float).tolist()
    e = np.asarray(entry).astype(int).tolist()
    mc = np.asarray(macd).astype(int).tolist()
    up = np.asarray(upper).astype(int).tolist()
    hold = HOLD_MS.get(rule)
    if rule not in ("X1", "X2", "X3") and hold is None:
        raise ValueError(rule)
    n = len(t)
    trades: list[dict] = []
    pos, i0 = 0, -1

    def close_at(i, forced):
        g = (c[i] / c[i0] - 1) * pos
        trades.append({"dir": pos, "t_in": t[i0], "t_out": t[i], "p_in": c[i0], "p_out": c[i],
                       "gross": g, "forced": forced})

    for i in range(n):
        if pos:
            if rule == "X1":
                out = mc[i] != pos
            elif rule == "X2":
                out = up[i] != pos
            elif rule == "X3":
                out = e[i] == -pos
            else:
                out = t[i] - t[i0] >= hold
            if out:
                close_at(i, False)
                pos = 0
        if not pos and e[i] and i < n - 1:
            pos, i0 = e[i], i
    if pos:
        close_at(n - 1, True)
    return trades


def window(fr: pd.DataFrame, lo: int, hi: int) -> pd.DataFrame:
    """봉 마감 lo ≤ t ≤ hi 인 구간."""
    return fr[(fr.index >= lo) & (fr.index <= hi)]


def seq_trades(fr: pd.DataFrame, variant: str, rule: str) -> list[dict]:
    e = entry_dirs(fr["ev"], fr["U"], fr["U_prev"], variant)
    return simulate(fr.index, fr["close"], e, fr["macd"], fr["U"], rule)


def board_trades(bf: pd.DataFrame, rule: str) -> list[dict]:
    """보드 '확실한 신호' 거래(4시간봉 시간축). 진입: 분석 시각 T 에 확실한 신호가 켜져 있고 포지션이 없으면 T 종가로.
    c1: 확실한 신호 방향이 진입 방향이 아니게 되면(꺼짐·반대·데이터 부족) 청산. c2: MACD 4h 방향이 바뀌면 청산."""
    sd = bf["strong_dir"].fillna(0).astype(int)
    md = bf["macd_dir"].fillna(0).astype(int)
    if rule == "c1":
        return simulate(bf.index, bf["close"], sd, md, sd, "X2")
    if rule == "c2":
        return simulate(bf.index, bf["close"], sd, md, sd, "X1")
    raise ValueError(rule)


# ---------------------------------------------------------------- 지표

def metrics(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    g = np.array([x["gross"] for x in trades])
    net = g - FEE_RT
    wins, losses = g[g > 0], g[g < 0]
    eq = np.cumprod(1 + net)
    curve = np.r_[1.0, eq]
    dd = 1 - curve / np.maximum.accumulate(curve)
    hold = np.array([x["t_out"] - x["t_in"] for x in trades]) / HOUR
    aw = wins.mean() if len(wins) else np.nan
    al = losses.mean() if len(losses) else np.nan
    return {
        "n": n, "win": len(wins) / n, "win_net": float((net > 0).mean()),
        "avg_win": aw, "avg_loss": al, "payoff": (aw / -al) if len(wins) and len(losses) else np.nan,
        "exp": g.mean(), "exp_net": net.mean(), "cum_net": eq[-1] - 1, "mdd": dd.max(),
        "hold_h": hold.mean(), "hold_sum_h": hold.sum(), "forced": int(sum(x["forced"] for x in trades)),
    }


def random_baseline(trades: list[dict], times, close, rng: np.random.Generator, n_rep: int = N_RAND) -> dict | None:
    """실제 거래와 같은 수·같은 방향·같은 보유 시간을 구간 안 무작위 15분봉 시각에 놓은 가상 거래 n_rep 번.
    청산가는 진입 + 보유 시간 이후 첫 15분봉 종가. 수수료 전 건당 기대값의 분포와 실제 값의 백분위
    (= 무작위 값이 실제보다 작은 비율, 같으면 절반)."""
    if not trades:
        return None
    t = np.asarray(times, dtype="int64")
    c = np.asarray(close, dtype=float)
    d = np.array([x["dir"] for x in trades])
    h = np.array([x["t_out"] - x["t_in"] for x in trades], dtype="int64")
    actual = float(np.mean([x["gross"] for x in trades]))
    maxi = np.searchsorted(t, t[-1] - h, side="right") - 1   # 진입 + 보유가 구간 끝을 넘지 않는 마지막 위치
    maxi = np.clip(maxi, 0, None)
    vals = np.empty(n_rep)
    for r in range(n_rep):
        i = (rng.random(len(d)) * (maxi + 1)).astype("int64")
        j = np.minimum(np.searchsorted(t, t[i] + h, side="left"), len(t) - 1)
        vals[r] = np.mean(d * (c[j] / c[i] - 1))
    pct = 100 * (np.sum(vals < actual) + 0.5 * np.sum(vals == actual)) / n_rep
    return {"actual": actual, "pct": pct, "med": float(np.median(vals)),
            "p5": float(np.percentile(vals, 5)), "p95": float(np.percentile(vals, 95))}


# ---------------------------------------------------------------- 실행·보고서

def load_symbol(conn, sym: str, rules: dict):
    c4 = db.load_candles(conn, sym, rules["macd"]["period"])
    c1 = db.load_candles(conn, sym, rules["stoch_pair"]["period"])
    c15 = db.load_candles(conn, sym, rules["vpci"]["period"])
    return c4, c1, c15


def periods(rules: dict) -> list[tuple[str, int, int]]:
    ref_from, ref_to = rules["replay"]["reference_period"]
    return [("참고", ms(ref_from), ms(ref_to) + 86_400_000 - 1),
            ("확인", ms(rules["replay"]["check_period_start"]), ms(CHECK_END))]


def _rng(*key) -> np.random.Generator:
    """설정마다 고정된 난수(계산 순서와 무관하게 같은 설정이면 같은 무작위 거래). 시드 = SEED + 설정 이름의 해시."""
    h = int.from_bytes(hashlib.sha256("|".join(map(str, key)).encode("utf-8")).digest()[:8], "big")
    return np.random.default_rng([SEED, h])


def run_all(conn, rules: dict) -> dict:
    res = {"rows": [], "counts": [], "bh": {}, "span": {}, "trades": {}}
    for sym in rules["symbols"]:
        c4, c1, c15 = load_symbol(conn, sym, rules)
        fr = build_frame(c4, c1, c15, rules)
        bfull = pipeline.compute(conn, sym, rules)
        for pname, lo, hi in periods(rules):
            w = window(fr, lo, hi)
            if len(w) < 2:
                continue
            times, close = w.index.values, w["close"].values
            res["bh"][(sym, pname)] = close[-1] / close[0] - 1
            res["span"][(sym, pname)] = (int(times[0]), int(times[-1]))
            evn = int((w["ev"] != 0).sum())
            ea = entry_dirs(w["ev"], w["U"], w["U_prev"], "A")
            eb = entry_dirs(w["ev"], w["U"], w["U_prev"], "B")
            res["counts"].append({"sym": sym, "period": pname, "bars": len(w), "ev": evn,
                                  "A": int((ea != 0).sum()), "B": int((eb != 0).sum()),
                                  "A_only": int(((ea != 0) & (eb == 0)).sum()),
                                  "U_on": float((w["U"] != 0).mean())})
            jobs = [(v, x, seq_trades(w, v, x)) for v in VARIANTS for x in EXITS]
            bw = bfull[(bfull.index >= lo) & (bfull.index <= hi)]
            jobs += [("보드", x, board_trades(bw, x)) for x in ("c1", "c2")]
            for v, x, tr in jobs:
                res["trades"][(sym, pname, v, x)] = tr
                for dname, dv in (("합계", 0), ("Long", 1), ("Short", -1)):
                    sub = tr if dv == 0 else [z for z in tr if z["dir"] == dv]
                    res["rows"].append({"sym": sym, "period": pname, "variant": v, "exit": x, "dir": dname,
                                        **metrics(sub), "rand": random_baseline(sub, times, close, _rng(sym, pname, v, x, dname)),
                                        "exposure": (sum(z["t_out"] - z["t_in"] for z in sub) / (times[-1] - times[0]))})
    return res


def _p(x, nd=1, sign=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    s = f"{100 * x:+.{nd}f}" if sign else f"{100 * x:.{nd}f}"
    return s.replace("-", "−") + "%"


def _f(x, nd=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:.{nd}f}".replace("-", "−")


HEAD = ("| 종목 | 청산 | 거래 n | 승률 | 평균 이익 | 평균 손실 | 손익비 | 기대값(전) | 기대값(뒤) | 누적(뒤, 복리) "
        "| 최대 낙폭 | 평균 보유 | 보유 비율 | 그냥 보유 | 무작위 백분위 |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")


def _row(r, bh):
    if r["n"] == 0:
        return f"| {r['sym'][:3]} | {r['exit']} | 0 | – | – | – | – | – | – | – | – | – | – | {_p(bh, 0, True)} | – |"
    rb = r.get("rand")
    forced = f" (끝 {r['forced']})" if r["forced"] else ""
    return (f"| {r['sym'][:3]} | {r['exit']} | {r['n']:,}{forced} | {_p(r['win'])} | {_p(r['avg_win'], 2, True)} "
            f"| {_p(r['avg_loss'], 2, True)} | {_f(r['payoff'])} | {_p(r['exp'], 3, True)} | {_p(r['exp_net'], 3, True)} "
            f"| {_p(r['cum_net'], 0, True)} | {_p(r['mdd'], 0)} | {_f(r['hold_h'], 1)}시간 | {_p(r['exposure'], 0)} "
            f"| {_p(bh, 0, True)} | {_f(rb['pct'], 0) if rb else '–'} |")


def table(res, period, variants, direction="합계", exits=None) -> str:
    lines = [HEAD]
    for r in res["rows"]:
        if r["period"] != period or r["variant"] not in variants or r["dir"] != direction:
            continue
        if exits and r["exit"] not in exits:
            continue
        lines.append(_row(r, res["bh"][(r["sym"], period)]))
    return "\n".join(lines)


def rand_table(res, period, direction="합계") -> str:
    lines = ["| 종목 | 변형 | 청산 | 거래 n | 실제 기대값(전) | 무작위 중앙값 | 무작위 5–95% | 백분위 |",
             "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in res["rows"]:
        if r["period"] != period or r["dir"] != direction or not r.get("rand"):
            continue
        rb = r["rand"]
        lines.append(f"| {r['sym'][:3]} | {r['variant']} | {r['exit']} | {r['n']:,} | {_p(rb['actual'], 3, True)} "
                     f"| {_p(rb['med'], 3, True)} | {_p(rb['p5'], 3, True)} – {_p(rb['p95'], 3, True)} | {_f(rb['pct'], 0)} |")
    return "\n".join(lines)


def pooled_table(res, all_trades, direction: int = 0) -> str:
    """3종목 거래를 합친 건당 평균(수수료 뒤)과 종목별 무작위 백분위. direction=1 이면 Long 거래만
    (백분위도 Long 거래만, 같은 보유 시간의 무작위 Long 거래와 비교 → 상승장 덕은 걸러짐)."""
    lines = ["| 변형 | 청산 | 참고 n | 참고 승률 | 참고 기대값(뒤) | 참고 백분위(BTC·ETH·XRP) | 수수료 뒤 플러스 종목 "
             "| 확인 n | 확인 승률 | 확인 기대값(뒤) | 확인 백분위(BTC·ETH·XRP) |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    keys = [(v, x) for v in VARIANTS for x in EXITS] + [("보드", "c1"), ("보드", "c2")]
    for v, x in keys:
        cells = []
        for period in ("참고", "확인"):
            g = np.array([z["gross"] for (s, p, vv, xx), tr in all_trades.items()
                          if p == period and vv == v and xx == x for z in tr if direction == 0 or z["dir"] == direction])
            rows = [r for r in res["rows"] if r["period"] == period and r["variant"] == v and r["exit"] == x
                    and r["dir"] == ("합계" if direction == 0 else "Long")]
            pct = "·".join(_f(r["rand"]["pct"], 0) if r.get("rand") else "–" for r in rows)
            plus = sum(1 for r in rows if r["n"] and r["exp_net"] > 0)
            if len(g):
                cells.append((f"{len(g):,}", _p((g > 0).mean()), _p(g.mean() - FEE_RT, 3, True), pct, f"{plus}/{len(rows)}"))
            else:
                cells.append(("0", "–", "–", pct, "–"))
        (rn, rw, re_, rp, rplus), (cn, cw, ce, cp, _) = cells
        lines.append(f"| {v} | {x} | {rn} | {rw} | {re_} | {rp} | {rplus} | {cn} | {cw} | {ce} | {cp} |")
    return "\n".join(lines)


def board_note(res) -> str:
    """보드 c1·c2 확인 기간 범위를 Fable 진단(10-04) 값과 나란히 적는다(정의가 같게 재현됐는지 보는 용도)."""
    rows = [r for r in res["rows"] if r["period"] == "확인" and r["variant"] == "보드" and r["dir"] == "합계" and r["n"]]
    if not rows:
        return ""
    w = [r["win"] for r in rows]
    e = [r["exp_net"] for r in rows]
    return (f"보드 c1·c2(확인 기간, 종목 3 × 2 = {len(rows)}개): 승률 {_p(min(w))} – {_p(max(w))}, 수수료 뒤 기대값 "
            f"{_p(min(e), 3, True)} – {_p(max(e), 3, True)}. 외부 진단 값과의 비교는 팀 내부 보고서에 있다.")


def count_table(res) -> str:
    lines = ["| 종목 | 기간 | 15분봉 수 | VPCI 사건 | U ≠ 0 비율 | A 진입 사건 | B 진입 사건 | A에만 있는 사건(조건이 같은 봉에 갖춰짐) |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for c in res["counts"]:
        lines.append(f"| {c['sym'][:3]} | {c['period']} | {c['bars']:,} | {c['ev']:,} | {_p(c['U_on'], 0)} | {c['A']:,} "
                     f"| {c['B']:,} | {c['A_only']:,} ({_p(c['A_only'] / c['A'] if c['A'] else np.nan, 0)}) |")
    return "\n".join(lines)


def render(res, rules) -> str:
    ver = db.rules_version(rules)
    now = db.now_ms()
    (rn, rlo, rhi), (cn, clo, chi) = periods(rules)
    span = "; ".join(f"{s[:3]} {db.utc_iso(a)} – {db.utc_iso(b)}" for (s, p), (a, b) in res["span"].items() if p == "참고")
    span_c = "; ".join(f"{s[:3]} {db.utc_iso(a)} – {db.utc_iso(b)}" for (s, p), (a, b) in res["span"].items() if p == "확인")
    vp = rules["vpci"]
    out = [
        "# E3 조건서 순차 진입 재현 (참고표)",
        "",
        f"- 규칙 버전: `{ver}` (conf/rules_v3.json 현재 값, 계산 로직 {db.ENGINE_LOGIC})",
        f"- 생성: {db.kst_text(now, '%Y-%m-%d %H:%M')} KST ({db.utc_iso(now)}), `python3 sequential_entry.py`",
        "- 데이터: 바이낸스 현물 BTC·ETH·XRP USDT 4시간·1시간·15분봉(운영 DB를 읽기 전용으로 읽음). 운영 DB에 쓰지 않는다.",
        "- 이 표로 규칙을 고르지 않는다. 변형(A·B), 청산(X1–X5), 수수료 0.2%, 무작위 기준 200회, 기간은 스크립트를 처음 돌리기 전에 정했다(작업 지시문 E3).",
        "- 확인 기간 결과는 보고만 한다. 어떤 변형도 확인 기간(또는 참고 기간) 성적을 보고 고르지 않았다.",
        "- 첫 실행 뒤에 더한 것: 3종목 합친 요약표(Long만 포함), 방향별 무작위 기준, 무작위 난수를 설정마다 고정(계산 순서에 따라 백분위가 몇 점씩 달라지던 것). "
        "보는 방식과 재현성을 위한 것이며 진입·청산 규칙은 바꾸지 않았다.",
        "",
        "## 1. 정의",
        "",
        "### 상위 조건 U(t)",
        "",
        "15분봉 마감 시각 t 에 이미 닫힌 마지막 4시간봉의 MACD 방향(judge.macd_frame, MACD선이 신호선 위면 +1)과 "
        "마지막 1시간봉의 두 지표 방향(judge.pair_frame, Stochastic·StochRSI 모두 같은 방향이면 그 방향)이 같고 0이 아니면 그 방향, 아니면 0. "
        "마감이 t 보다 늦은 봉은 쓰지 않는다(t 와 같은 시각에 마감한 1시간·4시간봉은 씀). "
        "그 시각에 기대한 최신 봉이 빠졌거나, 지표 계산 구간 안에 빠진 봉이 있으면(운영 보드의 data_short 기준) 그 값은 0.",
        "",
        "### 진입",
        "",
        f"VPCI 사건: judge.vpci_frame 과 같은 정의(cross_target={vp['cross_target']}, 신호선 {vp.get('signal_ma')} {vp['signal']}, "
        f"기간 {vp['short']}·{vp['long']}). 0선 또는 신호선을 위로 넘으면 +1, 아래로 넘으면 −1, 같은 봉에 반대 사건이 겹치면 사건 아님, "
        "바로 앞 15분봉이 빠졌으면 사건 아님.",
        "",
        "- 변형 A(기본): 15분봉 t 에서 사건 방향 d 가 났고 U(t) = d 이고 포지션이 없으면 t 의 15분 종가로 d 방향 진입.",
        "- 변형 B: 여기에 U(t − 15분) = d 도 요구한다(상위 조건이 교차보다 먼저 갖춰진 경우만).",
        "- 포지션은 종목당 하나. 보유 중 같은 방향 사건은 무시. 청산한 봉에서 진입 사건이 나면 같은 종가로 새로 진입. 구간 마지막 봉에서는 진입하지 않는다.",
        "",
        "### 청산(조건서에 없음, 다섯 가지 모두 계산)",
        "",
        "| 이름 | 청산 시점(그 15분봉 종가) |",
        "|---|---|",
        *[f"| {k} | {EXIT_TEXT[k]} |" for k in EXITS],
        "",
        "X4·X5는 진입 뒤 보유 시간이 지난 첫 15분봉. 보유 중에는 반대 사건도 무시한다. "
        "구간 끝까지 열린 포지션은 마지막 종가로 닫고 표에 '(끝 n)'으로 표시한다.",
        "",
        "### 보드 '확실한 신호' 거래(비교용, 같은 표 형식)",
        "",
        "pipeline.compute 의 4시간 분석(운영·재현과 같은 계산). 분석 시각 T 에 확실한 신호가 켜져 있고 포지션이 없으면 T 종가로 진입. "
        "c1: 확실한 신호 방향이 진입 방향이 아니게 되면(꺼짐·반대·데이터 부족) 그 T 종가로 청산, 반대로 켜져 있으면 같은 종가로 반대 진입. "
        "c2: MACD 4h 방향이 바뀐 T 종가로 청산. 이 정의는 이 스크립트의 것이며 Fable 진단의 c1·c2 정의와 세부가 다를 수 있다(미확인).",
        "",
        "### 수익과 지표",
        "",
        "- 건별 수익률(수수료 전): Long = 청산가/진입가 − 1, Short = −(청산가/진입가 − 1). 수수료 뒤 = 수수료 전 − 0.2%(왕복).",
        "- 승률·평균 이익·평균 손실·손익비는 수수료 전 기준(수익률 0인 거래는 승도 패도 아니며 분모에는 들어감). 손익비 = 평균 이익 ÷ |평균 손실|.",
        "- 기대값 = 건당 평균 수익률. 누적 = 수수료 뒤 수익률을 거래 순서대로 복리로 곱한 것. 최대 낙폭 = 그 누적 곡선(청산 시점 기준, 보유 중 평가손은 반영 안 함)의 고점 대비 최대 하락.",
        "- 보유 비율 = 보유 시간 합 ÷ 구간 길이. 그냥 보유 = 구간 첫 15분 종가 → 끝 15분 종가(Long만).",
        f"- 무작위 백분위: 실제 거래와 같은 수·방향·보유 시간을 구간 안 무작위 15분봉 시각에 놓은 가상 거래 {N_RAND}번(시드 {SEED}). "
        "수수료 전 건당 기대값이 실제보다 작은 비율(%). 50 근처면 무작위와 구별되지 않음, 95 이상이면 무작위보다 나은 쪽 끝. "
        "난수는 설정(종목·기간·변형·청산·방향)마다 고정. 200번이라 백분위 자체에 ±3–4점 정도의 추출 오차가 있다.",
        "",
        "### 기간(봉 마감 시각, UTC)",
        "",
        f"- 참고 기간(주 결과): {db.utc_iso(rlo)} – {db.utc_iso(rhi + 1)} 전. 실제 첫·끝 15분봉: {span}",
        f"- 확인 기간(보고만): {db.utc_iso(clo)} – {db.utc_iso(chi)}(포함, = 2026-10-03 05:00 KST). 실제 첫·끝 15분봉: {span_c}",
        "- 지표는 전 구간 데이터로 계산(인과적, 미래 봉 미사용)하고 거래만 구간 안에서 시작·종료한다. 구간을 넘는 거래는 구간 끝에서 닫는다.",
        "",
        "## 2. 한계",
        "",
        "- Short 수익은 현물에서 그대로 실행할 수 없다(빌려 팔기·선물 필요, 그 비용과 펀딩은 넣지 않음). Long만 실제 현물 거래로 해석할 수 있다.",
        "- 슬리피지 0, 사건이 난 15분봉 종가에 바로 체결된다고 가정한다(실제로는 종가 확인 뒤 다음 가격). 수수료는 왕복 0.2% 고정.",
        "- 15분 해상도: 청산 조건과 보유 시간을 15분봉 마감에서만 본다. 봉 안의 가격 경로(손절·익절 선도달)는 보지 않는다.",
        "- 겹치는 표본: 한 종목 안에서는 포지션이 하나라 거래가 겹치지 않지만, 세 종목은 같은 시장 흐름을 타서 서로 독립이 아니다. 무작위 기준의 가상 거래는 서로 겹칠 수 있다.",
        "- 무작위 기준은 방향과 보유 시간을 실제와 같게 두므로, 구간 전체의 상승·하락 흐름(예: Long이 많으면 상승장 덕)은 걸러지지만 '언제 들어갔나'의 효과만 본다.",
        "- 청산 규칙·VPCI 사건의 유효 기간·'오르는 중'의 뜻은 정미님 확인 전이다(조건서에 없음). 여기의 X1–X5는 후보일 뿐이다.",
        "- 여러 번 비교: 한 기간에 백분위가 종목 3 × 변형·청산 12개 = 36개다. 아무 효과가 없어도 각각 5% 확률로 5 이하·95 이상이 나오므로 "
        "한두 개의 극단값은 우연으로도 생긴다. 무작위 기준은 수수료 전 값만 비교한다(수수료는 실제·무작위에 똑같이 빠짐).",
        "- 거래소 데이터가 빠진 구간(예: 2018-02-08–09 바이낸스 점검, 4시간봉이 하루 넘게 없음) 직후에는 방향을 알 수 없음(0)으로 보아 "
        "X1·X2 포지션이 닫히고 진입도 막힌다. 누락은 종목마다 4시간봉 7–8곳, 15분봉 26–33곳(전 기간)이라 영향은 작다.",
        "- 규칙 버전이 바뀌면(메인 세션의 수정 등) 다시 돌려야 같은 결과다.",
        "",
        "## 3. 한눈 요약(3종목 거래를 합친 건당 평균)",
        "",
        "참고 n·승률·기대값은 세 종목 거래를 한데 모은 값이다(종목마다 거래 수가 비슷해 가중치 차이는 작음). "
        "'수수료 뒤 플러스 종목'은 참고 기간에 수수료 뒤 건당 기대값이 0보다 큰 종목 수. 누적·낙폭·그냥 보유는 종목별 표(5–8절)에 있다.",
        "",
        pooled_table(res, res["trades"]),
        "",
        board_note(res),
        "",
        "Long 거래만(현물에서 실제로 할 수 있는 쪽). 같은 진입·청산에서 Short 거래만 뺀 것이라 그 사이 비어 있는 시간이 생긴다. "
        "백분위는 같은 수·같은 보유 시간의 무작위 Long 거래와 비교한 것이라, 기간 전체가 올라서 생긴 이익(상승장 덕)은 걸러진다:",
        "",
        pooled_table(res, res["trades"], 1),
        "",
        "## 4. 진입 사건 수와 조건서 순서(변형 A·B)",
        "",
        "진입 사건 수는 포지션 여부와 무관하게 센 것이다(실제 거래 수는 보유 중 무시된 사건 때문에 더 적다).",
        "",
        count_table(res),
        "",
        "## 5. 참고 기간(주 결과) · 변형 A · Long+Short 합계",
        "",
        table(res, "참고", ["A"]),
        "",
        "보드 '확실한 신호' 거래(같은 기간·같은 형식):",
        "",
        table(res, "참고", ["보드"]),
        "",
        "## 6. 참고 기간 · 변형 B · 합계",
        "",
        table(res, "참고", ["B"]),
        "",
        "## 7. 확인 기간(보고만) · 변형 A · 합계",
        "",
        table(res, "확인", ["A"]),
        "",
        "보드 '확실한 신호' 거래(같은 기간·같은 형식):",
        "",
        table(res, "확인", ["보드"]),
        "",
        "## 8. 확인 기간(보고만) · 변형 B · 합계",
        "",
        table(res, "확인", ["B"]),
        "",
        "## 9. 방향별(Long / Short)",
        "",
        "무작위 백분위는 그 방향 거래만, 같은 방향·같은 보유 시간의 무작위 거래와 비교한 것이다. 그냥 보유 칸은 방향과 무관하게 같은 값이다.",
        "",
    ]
    for period in ("참고", "확인"):
        for v in ("A", "B", "보드"):
            for dname in ("Long", "Short"):
                out += [f"### {period} 기간 · {'변형 ' + v if v != '보드' else '보드 확실한 신호'} · {dname}", "",
                        table(res, period, [v], dname), ""]
    out += ["## 10. 무작위 기준 상세(수수료 전 건당 기대값)", ""]
    for period, pl in (("참고", "참고 기간"), ("확인", "확인 기간(보고만)")):
        for dname, dl in (("합계", "Long+Short"), ("Long", "Long만")):
            out += [f"### {pl} · {dl}", "", rand_table(res, period, dname), ""]
    return "\n".join(out)


def main() -> int:
    rules = db.load_json("rules_v3.json")
    conn = sqlite3.connect("file:" + str(db.DB_PATH) + "?mode=ro", uri=True)
    try:
        res = run_all(conn, rules)
    finally:
        conn.close()
    OUT.write_text(render(res, rules), encoding="utf-8")
    print(f"규칙 {db.rules_version(rules)} → {OUT}")
    for r in res["rows"]:
        if r["dir"] == "합계" and r["n"]:
            rb = r["rand"]
            print(f"{r['period']} {r['sym'][:3]} {r['variant']:>2} {r['exit']}: n={r['n']:>5} 승률 {100 * r['win']:.1f}% "
                  f"기대값 전 {100 * r['exp']:+.3f}% 뒤 {100 * r['exp_net']:+.3f}% 누적 {100 * r['cum_net']:+.0f}% "
                  f"백분위 {rb['pct'] if rb else float('nan'):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
