"""트리거와 채점(2026-10-12 리팩토링, 정미님 10-07·10-11 답, 호연 10-12 결정).

- Core Condition(기술 조건) = judge.strong_sequence: 4시간 MACD 와 1시간 Stochastic·StochRSI 가 같은 방향으로 맞춰진 뒤
  15분 VPCI 가 그 방향으로 돈 상태. strong15.py 가 15분마다 상태가 바뀐 봉을 strong15 표에 남긴다(사건 = on·flip).
- 트리거 = 사건 중 아래를 통과한 것. 트랙 둘을 따로 센다.
  - tech(기술 조건만, 비교용): 사건이면 트리거.
  - ai(공식): 그 순간 AI 분석(ai_analysis, 정미님 6절)의 Trend Direction 이 같은 방향일 때만. 디스코드로 보낸다.
  - 공통: 같은 코인·트랙의 직전 트리거 뒤 ban_hours(12시간) 안의 사건은 보지 않는다.
  - V5(10-14, rules_v3.json trigger.same_direction_filter): 직전 트리거와 같은 방향의 사건은 트리거가 아니라 '반복'(repeat)으로
    기록만 남긴다. 12시간 기준 시각도 바꾸지 않는다. 첫 트리거는 방향 제한이 없다(정미님 구상 "같은 방향이 이어지는 신호는 알리지 않음").
- 채점: 트리거 뒤 같은 트랙의 다음 트리거까지 최대수익률(MFE). 왕복 수수료를 빼고 코인별 success_pct 이상이면 성공
  (값은 conf/trigger.json, 공개 저장소의 값은 예시). 참고 열: 진입 뒤 24시간 고정 창의 최대수익률(fix24).
  같이 남기는 것: 최대 손실폭(MAE), 다음 트리거 때 실제 손익, 같은 구간 '항상 Long'의 최대수익률(기준선).
  다음 트리거가 없으면 '진행 중'(status open)이고 MFE 는 지금까지의 값이다. 성공률은 끝난 것(closed)만으로 센다.
- 운영 트리거는 사건을 제때(봉 마감 뒤 on_time_min 안) 잡은 것만 쓴다. 맥이 잠들어 늦게 잡힌 사건은 트리거가 아니다.
- 재현(replay)은 tech 트랙만(과거 시점의 AI 판단이 없다). 전 기간 상태를 같은 함수로 계산해 트리거·채점한다.

사용: python3 trigger.py --replay   (재현을 다시 계산해 reports/trigger_replay.json·md 를 쓴다)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

import db
import judge
import pipeline

M15 = db.PERIOD_MS["15m"]
HOUR = 3_600_000
TRACKS = ("ai", "tech")
SHORT = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP"}
DEFAULTS = {"enabled": True, "ban_hours": 12, "success_pct": 1.0, "fee_pct_per_side": 0.05, "on_time_min": 30,
            "ai_gate": {"enabled": True, "fresh_hours": 4, "on_demand": True}, "ai_schedule_kst_hours": [9, 21],
            "discord": {"send_official": True},
            "replay": {"reference_period": ["2018-01-01", "2023-12-31"], "check_period_start": "2024-01-01"}}


def load_conf() -> dict:
    try:
        c = db.load_json("trigger.json")
    except (OSError, ValueError):
        c = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in c.items() if not k.startswith("_")})
    return out


def fee_rt(conf: dict) -> float:
    """왕복 수수료(비율)."""
    return 2 * float(conf["fee_pct_per_side"]) / 100


def success_pct(conf: dict, symbol: str | None = None) -> float:
    """순수익 기준(%). success_pct 가 {코인: %} 이면 그 코인 값(없으면 default), 숫자 하나면 세 코인 공통(하위 호환)."""
    sp = conf["success_pct"]
    if isinstance(sp, dict):
        v = sp.get(symbol) if symbol is not None else None
        return float(v if v is not None else sp.get("default", 1.0))
    return float(sp)


def threshold(conf: dict, symbol: str | None = None) -> float:
    """성공에 필요한 수수료 전 최대수익률(비율) = 코인별 기준 + 왕복 수수료."""
    return success_pct(conf, symbol) / 100 + fee_rt(conf)


def threshold_text(conf: dict, symbols) -> str:
    """보고서 머리말: 'BTC x% · ETH y% · XRP z%(수수료 포함)'."""
    return " · ".join(f"{SHORT.get(s, s)} {100 * threshold(conf, s):g}%" for s in symbols) + "(수수료 포함)"


def scoring_fingerprint(conf: dict) -> str:
    """채점 설정 지문: 성공 기준 · 수수료 · 금지 시간이 같아야 재현 보고서를 보드에 그대로 쓴다."""
    import hashlib
    core = {k: conf.get(k) for k in ("success_pct", "fee_pct_per_side", "ban_hours")}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def same_direction_filter(rules: dict | None) -> bool:
    """V5 같은 방향 거르기. 규칙 버전 해시에 들어가도록 rules_v3.json 의 trigger.same_direction_filter 로 켠다."""
    return bool(((rules or {}).get("trigger") or {}).get("same_direction_filter", False))


# ---------------------------------------------------------------- 순수 함수(운영·재현 공용)

@dataclass
class Event:
    t: int        # 15분봉 마감(UTC ms)
    dir: int      # +1 / −1
    kind: str     # on | flip
    close: float  # 그 봉 종가


def events_from_states(states: pd.Series, closes: pd.Series) -> list[Event]:
    """상태 시계열(+1/−1/0)에서 사건(on: 0 → ±1, flip: ±1 → ∓1)을 뽑는다. 첫 값은 기준이라 사건이 아니다."""
    if states.empty:
        return []
    s = states.astype(int)
    prev = s.shift(1)
    ch = s.ne(prev) & prev.notna() & s.ne(0)
    out = []
    for t in s.index[ch.values]:
        p, d = int(prev.loc[t]), int(s.loc[t])
        c = closes.get(t)
        if c is None or c != c:
            continue
        out.append(Event(int(t), d, "on" if p == 0 else "flip", float(c)))
    return out


def apply_ban(events: list[Event], ban_ms: int, last_t: int | None = None, last_dir: int | None = None,
              same_dir: bool = False, repeats: list | None = None) -> list[Event]:
    """직전 트리거(last_t) 뒤 ban_ms 안의 사건을 버린다. same_dir 이면 그 밖이라도 직전 트리거(last_dir)와 같은 방향은
    '반복'으로 버리고(repeats 목록이 있으면 거기에 담음) 기준 시각 · 방향을 바꾸지 않는다. 받아들인 사건이 새 기준이 된다.
    events 는 시각 오름차순. 첫 사건(last_dir 없음)은 방향 제한이 없다."""
    out = []
    for e in events:
        if last_t is not None and e.t < last_t + ban_ms:
            continue
        if same_dir and last_dir is not None and e.dir == last_dir:
            if repeats is not None:
                repeats.append(e)
            continue
        out.append(e)
        last_t, last_dir = e.t, e.dir
    return out


def excursions(entry: float, d: int, highs: np.ndarray, lows: np.ndarray) -> tuple[float, float, float] | None:
    """(MFE, MAE, 항상 Long MFE). 봉이 없으면 None. 비율, 수수료 빼기 전. Short 은 하락 폭이 이익."""
    if len(highs) == 0:
        return None
    hi, lo = float(np.max(highs)), float(np.min(lows))
    base = hi / entry - 1
    if d > 0:
        return base, 1 - lo / entry, base
    return 1 - lo / entry, hi / entry - 1, base


def realized(entry: float, d: int, exit_close: float) -> float:
    """진입가 → 청산가 손익(비율, 무레버리지). Short 은 1 − 청산/진입."""
    return exit_close / entry - 1 if d > 0 else 1 - exit_close / entry


FIX24_MS = 24 * HOUR
FIX24_BARS = FIX24_MS // M15     # 96


def fix24(entry: float, d: int, t: int, bars: pd.DataFrame, now: int | None = None,
          log: bool = True) -> tuple[float | None, float | None]:
    """24시간 고정 창 (MFE, MAE). 구간 = 마감이 진입 봉 마감(t)보다 뒤이고 t + 24시간 이하인 15분봉. 그 구간이 아직 다
    마감되지 않았으면(now < t + 24시간) 진행 중이라 (None, None). 다 마감됐는데 봉이 96개가 아니면(결측) (None, None)."""
    lim = now if now is not None else (int(bars.index[-1]) if len(bars) else t)
    if lim < t + FIX24_MS:
        return None, None
    ts = bars.index.values.astype("int64")
    s, j = np.searchsorted(ts, t, side="right"), np.searchsorted(ts, t + FIX24_MS, side="right")
    if j - s != FIX24_BARS:
        if log:                       # 재현에서만 남긴다(운영 재채점은 15분마다 같은 행을 다시 보므로 조용히)
            print(f"24시간 창 봉 {j - s}개(96 아님) · 진입 {db.kst_text(t)} → 비움")
        return None, None
    ex = excursions(float(entry), int(d), bars["high"].values[s:j], bars["low"].values[s:j])
    return (None, None) if ex is None else (ex[0], ex[1])


def score_rows(trigs: pd.DataFrame, bars: pd.DataFrame, now: int | None = None, log: bool = True) -> pd.DataFrame:
    """한 코인·트랙의 트리거(t_bar 오름차순)를 채점. bars: index=15분봉 마감, 열 high·low·close.
    각 트리거의 구간 = t_bar 다음 봉부터 다음 트리거의 봉까지(포함). 다음 트리거가 없으면 지금(now)까지 → open.
    참고 열 fix24_mfe · fix24_mae: 다음 트리거와 상관없이 진입 뒤 24시간 고정 창(fix24)."""
    out = trigs.copy()
    ts = bars.index.values.astype("int64")
    hi, lo, cl = bars["high"].values, bars["low"].values, bars["close"].values
    tb = out["t_bar"].values.astype("int64")
    nxt = np.r_[tb[1:], -1]
    cols = {k: [] for k in ("end_t", "end_close", "last_bar_t", "mfe", "mae", "ret_end", "base_mfe", "status",
                            "fix24_mfe", "fix24_mae")}
    for i, (t, d, e) in enumerate(zip(tb, out["dir"].values, out["entry"].values)):
        f24 = fix24(float(e), int(d), int(t), bars, now, log)
        cols["fix24_mfe"].append(f24[0])
        cols["fix24_mae"].append(f24[1])
        end = int(nxt[i])
        s = np.searchsorted(ts, t, side="right")
        if end > 0:
            j = np.searchsorted(ts, end, side="right")
        else:
            lim = now if now is not None else (int(ts[-1]) if len(ts) else t)
            j = np.searchsorted(ts, lim, side="right")
        ex = excursions(float(e), int(d), hi[s:j], lo[s:j])
        cols["mfe"].append(None if ex is None else ex[0])
        cols["mae"].append(None if ex is None else ex[1])
        cols["base_mfe"].append(None if ex is None else ex[2])
        cols["last_bar_t"].append(int(ts[j - 1]) if j > s else None)
        if end > 0:
            k = np.searchsorted(ts, end, side="left")
            ec = float(cl[k]) if k < len(ts) and ts[k] == end else None
            cols["end_t"].append(end)
            cols["end_close"].append(ec)
            cols["ret_end"].append(None if ec is None else realized(float(e), int(d), ec))
            cols["status"].append("closed")
        else:
            for k in ("end_t", "end_close", "ret_end"):
                cols[k].append(None)
            cols["status"].append("open")
    for k, v in cols.items():
        out[k] = v
    return out


def _thr_series(rows: pd.DataFrame, conf: dict) -> pd.Series | float:
    """행마다 그 코인의 성공 기준(비율). 코인 열이 없으면 공통 기준."""
    if "symbol" in rows:
        return rows["symbol"].map(lambda s_: threshold(conf, s_)).astype(float)
    return threshold(conf)


def summarize(rows: pd.DataFrame, conf: dict) -> dict:
    """트리거 표 → 요약. 성공률은 끝난(closed) 것만. 진행 중에서 이미 기준을 넘은 수는 따로.
    코인이 섞인 표는 행마다 그 코인의 기준으로 판정하고, 전체 성공률은 코인별 성공 건수의 합 ÷ 끝난 건수의 합이다.
    24시간 고정 창(fix24)은 주 채점 상태와 상관없이 그 열이 채워진 행으로 센다."""
    fee = fee_rt(conf)
    if rows is None or rows.empty:
        return {"n": 0, "closed": 0, "open": 0, "success": 0, "success_pct": None, "open_reached": 0,
                "avg_mfe_pct": None, "avg_mae_pct": None, "avg_ret_pct": None, "base_success_pct": None,
                "opp_success_pct": None, "both_pct": None, "avg_hours": None,
                "fix24_n": 0, "fix24_success_pct": None, "fix24_opp_pct": None,
                "long": 0, "short": 0, "small_sample": True}
    thr = _thr_series(rows, conf)
    mfe = pd.to_numeric(rows["mfe"], errors="coerce")
    closed = rows["status"].eq("closed") & mfe.notna()
    op = rows["status"].eq("open")
    succ = closed & (mfe >= thr)
    base = pd.to_numeric(rows["base_mfe"], errors="coerce")
    mae = pd.to_numeric(rows["mae"], errors="coerce")
    ret = pd.to_numeric(rows["ret_end"], errors="coerce")
    nc = int(closed.sum())
    f24 = pd.to_numeric(rows["fix24_mfe"], errors="coerce") if "fix24_mfe" in rows else pd.Series(np.nan, index=rows.index)
    f24m = pd.to_numeric(rows["fix24_mae"], errors="coerce") if "fix24_mae" in rows else pd.Series(np.nan, index=rows.index)
    n24 = int(f24.notna().sum())

    def pct(x):
        return None if x is None or x != x else round(100 * float(x), 2)

    def rate(mask, n):
        return round(100 * float(mask.sum()) / n, 1) if n else None
    return {
        "n": int(len(rows)), "closed": nc, "open": int(op.sum()),
        "success": int(succ.sum()), "success_pct": rate(succ, nc),
        "open_reached": int((op & (mfe >= thr)).sum()),
        "avg_mfe_pct": pct(mfe[closed].mean() - fee) if nc else None,       # 수수료 뺀 값(홈 표와 같은 기준)
        "avg_mae_pct": pct(mae[closed].mean()) if nc else None,
        "avg_ret_pct": pct((ret[closed] - fee).mean()) if nc else None,       # 수수료 뺀 실제 손익 평균
        "base_success_pct": rate(closed & (base >= thr), nc),
        # 검토 H1: 같은 구간에 반대 방향으로 들어갔다면의 성공(= 최대 손실폭이 기준 이상)과 양쪽 다 기준을 넘은 비율.
        # Long 트리거는 '항상 Long'이 트리거 자신과 같아서, 방향 정보의 효과는 반대 방향과 비교해야 보인다.
        "opp_success_pct": rate(closed & (mae >= thr), nc),
        "both_pct": rate(closed & (mfe >= thr) & (mae >= thr), nc),
        "avg_hours": (round(float(((pd.to_numeric(rows["end_t"], errors="coerce") - rows["t_bar"])[closed]).mean()) / HOUR, 1)
                      if nc and "end_t" in rows else None),
        # V5 참고 열: 진입 뒤 24시간 고정 창(다음 트리거와 무관). 같은 창의 반대 방향 성공률과 함께
        "fix24_n": n24, "fix24_success_pct": rate(f24.notna() & (f24 >= thr), n24),
        "fix24_opp_pct": rate(f24m.notna() & (f24m >= thr), n24),
        "long": int((rows["dir"] > 0).sum()), "short": int((rows["dir"] < 0).sum()),
        "small_sample": nc < 30,
    }


# ---------------------------------------------------------------- 운영(live)

def _prompt_events(conn, version: str, on_time_ms: int, symbol: str) -> list[Event]:
    """strong15 의 on·flip 중 제때(봉 마감 뒤 on_time_ms 안) 잡은 사건."""
    rows = conn.execute("SELECT t_close, dir, kind, close FROM strong15 WHERE symbol=? AND rules_version=? "
                        "AND kind IN ('on','flip') AND close IS NOT NULL AND created_at - t_close <= ? ORDER BY t_close",
                        (symbol, version, on_time_ms)).fetchall()
    return [Event(int(t), int(d), k, float(c)) for t, d, k, c in rows]


def _created_at(conn, symbol, version, t) -> int:
    r = conn.execute("SELECT created_at FROM strong15 WHERE symbol=? AND rules_version=? AND t_close=?",
                     (symbol, version, t)).fetchone()
    return int(r[0]) if r else int(t)


def _insert(conn, symbol, track, mode, version, e: Event, issued_at, ai_created_at=None) -> bool:
    cur = conn.execute("INSERT OR IGNORE INTO triggers (symbol, track, mode, rules_version, t_bar, dir, kind, entry, issued_at, "
                       "ai_created_at, status) VALUES (?,?,?,?,?,?,?,?,?,?, 'open')",
                       (symbol, track, mode, version, e.t, e.dir, e.kind, e.close, int(issued_at), ai_created_at))
    return bool(cur.rowcount)


def _last_trigger(conn, symbol, track, mode, version, before: int | None = None) -> tuple[int, int] | None:
    """같은 코인 · 트랙 · 규칙 버전의 직전 트리거 (t_bar, dir). 없으면 None."""
    sql = "SELECT t_bar, dir FROM triggers WHERE symbol=? AND track=? AND mode=? AND rules_version=?"
    p = [symbol, track, mode, version]
    if before is not None:
        sql += " AND t_bar < ?"
        p.append(before)
    r = conn.execute(sql + " ORDER BY t_bar DESC LIMIT 1", p).fetchone()
    return None if r is None else (int(r[0]), int(r[1]))


def _last_trigger_t(conn, symbol, track, mode, version, before: int | None = None):
    got = _last_trigger(conn, symbol, track, mode, version, before)
    return None if got is None else got[0]


def detect_live(conn, rules: dict, version: str, conf: dict | None = None, now: int | None = None,
                ai_fn=None) -> dict:
    """운영 트리거를 만든다. 반환 {"tech": [새 tech 트리거], "ai": [새 공식 트리거], "checks": [게이트 결과]}.
    ai_fn(symbol, now) → (ai_created_at, trend_dir) 또는 None(실패). 없으면 ai_analysis.for_gate 를 쓴다."""
    conf = conf or load_conf()
    now = now if now is not None else db.now_ms()
    ban = int(conf["ban_hours"] * HOUR)
    on_time = int(conf["on_time_min"] * 60_000)
    gate = conf.get("ai_gate", {})
    # AI 게이트는 사건 봉 마감 뒤 ai_window 안에서만 본다. 사이클 하나를 건너뛰어도(긴 AI 호출로 잠금) 놓치지 않게 on_time 보다 길게.
    ai_window = int(float(gate.get("max_delay_min", 45)) * 60_000)
    same = same_direction_filter(rules)
    real = ai_fn is None
    if ai_fn is None:
        import ai_analysis
        fresh = int(float(gate.get("fresh_hours", 4)) * HOUR)
        od = {"tries": int(gate.get("on_demand_tries", 1)), "timeout_sec": int(gate.get("on_demand_timeout_sec", 120)),
              "fallback_timeout_sec": int(gate.get("on_demand_fallback_timeout_sec", 90))}
        ai_fn = lambda sym, at: ai_analysis.for_gate(conn, sym, at, fresh, bool(gate.get("on_demand", True)), **od)  # noqa: E731
    new = {"tech": [], "ai": [], "checks": []}
    for sym in rules["symbols"]:
        evs = _prompt_events(conn, version, on_time, sym)
        # tech: 처음부터 다시 걸러도 같은 결과(사건은 뒤에만 붙는다) → 없는 것만 넣는다
        for e in apply_ban(evs, ban, same_dir=same):
            if _insert(conn, sym, "tech", "live", version, e, _created_at(conn, sym, version, e.t)):
                new["tech"].append({"symbol": sym, "t_bar": e.t, "dir": e.dir})
        # ai(공식): 사건마다 한 번 게이트를 본다(이미 본 사건은 건너뜀)
        if not gate.get("enabled", True):
            continue
        # 이미 본 사건은 건너뛴다. 단 AI 분석 실패(ai_error)는 창(ai_window) 안이면 다음 사이클에 다시 본다(검토 M1)
        done = {t for t, r in conn.execute("SELECT t_bar, result FROM trigger_checks WHERE symbol=? AND rules_version=?",
                                           (sym, version)) if not (r == "ai_error" and now - t <= ai_window)}
        for e in evs:
            if e.t in done:
                continue
            last = _last_trigger(conn, sym, "ai", "live", version, before=e.t)
            if last is not None and e.t < last[0] + ban:
                res, ai_at, ai_dir = "banned", None, None
            elif same and last is not None and e.dir == last[1]:
                res, ai_at, ai_dir = "repeat", None, None          # V5: 직전 공식 트리거와 같은 방향 → AI 를 부르지 않는다
            elif now - e.t > ai_window:
                res, ai_at, ai_dir = "late", None, None
            else:
                got = ai_fn(sym, now)
                if got is None:
                    res, ai_at, ai_dir = "ai_error", None, None
                else:
                    ai_at, ai_dir = got
                    res = "pass" if ai_dir == e.dir else ("neutral" if ai_dir == 0 else "mismatch")
            checked = db.now_ms() if real else now
            conn.execute("INSERT OR REPLACE INTO trigger_checks (symbol, t_bar, rules_version, dir, checked_at, ai_created_at, "
                         "ai_dir, result) VALUES (?,?,?,?,?,?,?,?)", (sym, e.t, version, e.dir, checked, ai_at, ai_dir, res))
            new["checks"].append({"symbol": sym, "t_bar": e.t, "dir": e.dir, "result": res, "ai_dir": ai_dir})
            issued = db.now_ms() if real else now           # 디스코드 시각 = 실제로 확정한 시각(검토 M2)
            if res == "pass" and _insert(conn, sym, "ai", "live", version, e, issued, ai_at):
                new["ai"].append({"symbol": sym, "t_bar": e.t, "dir": e.dir, "entry": e.close, "issued_at": issued})
    conn.commit()
    return new


def bars_15m(conn, symbol: str, start_close_ms: int | None = None) -> pd.DataFrame:
    c = db.load_candles(conn, symbol, "15m", start_close_ms=start_close_ms)
    return c[["high", "low", "close"]]


def rescore(conn, mode: str, version: str, now: int | None = None, symbols=None, tracks=TRACKS) -> int:
    """채점 칸을 다시 채운다(진행 중인 것과 새로 다음 트리거가 생긴 것). 반환: 고친 행 수."""
    now = now if now is not None else db.now_ms()
    syms = symbols or [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM triggers WHERE mode=? AND rules_version=?",
                                                  (mode, version))]
    n = 0
    for sym in syms:
        for tr in tracks:
            t = pd.read_sql_query("SELECT t_bar, dir, entry, status, end_t FROM triggers WHERE symbol=? AND track=? AND mode=? "
                                  "AND rules_version=? ORDER BY t_bar", conn, params=[sym, tr, mode, version])
            if t.empty:
                continue
            # 다시 계산할 범위: 첫 open 트리거의 바로 앞 트리거부터(그 트리거의 end_t 가 바뀔 수 있음)
            op = np.flatnonzero(t["status"].values == "open")
            first = max(int(op[0]) - 1, 0) if len(op) else len(t)
            if first >= len(t):
                continue
            sub = t.iloc[first:].reset_index(drop=True)
            bars = bars_15m(conn, sym, start_close_ms=int(sub["t_bar"].iloc[0]))
            sc = score_rows(sub, bars, now, log=False)
            rows = [(r.end_t, r.end_close, r.last_bar_t, r.mfe, r.mae, r.ret_end, r.base_mfe, r.status, now,
                     sym, tr, mode, version, int(r.t_bar)) for r in sc.itertuples()]
            conn.executemany("UPDATE triggers SET end_t=?, end_close=?, last_bar_t=?, mfe=?, mae=?, ret_end=?, base_mfe=?, "
                             "status=?, scored_at=? WHERE symbol=? AND track=? AND mode=? AND rules_version=? AND t_bar=?",
                             [tuple(_py(v) for v in row) for row in rows])
            n += len(rows)
    n += rescore_fix24(conn, mode, version, now, syms, tracks)
    conn.commit()
    return n


def rescore_fix24(conn, mode: str, version: str, now: int, symbols, tracks=TRACKS) -> int:
    """24시간 고정 창은 주 채점 상태와 따로: fix24_mfe 가 비었고 진입 뒤 24시간이 지난 행을 사이클마다 다시 계산한다
    (다음 트리거가 12시간 뒤에 나와 주 채점이 닫혀도, 마지막 진행 중 행도 24시간이 지나면 채워진다)."""
    n = 0
    for sym in symbols:
        for tr in tracks:
            # 최근 7일만 다시 본다: 봉 결측으로 영영 비는 행을 15분마다 끝없이 읽지 않게(Fable 검토 지적 9)
            todo = conn.execute("SELECT t_bar, dir, entry FROM triggers WHERE symbol=? AND track=? AND mode=? AND rules_version=? "
                                "AND fix24_mfe IS NULL AND t_bar + ? <= ? AND t_bar >= ? ORDER BY t_bar",
                                (sym, tr, mode, version, FIX24_MS, now, now - 7 * 24 * HOUR)).fetchall()
            if not todo:
                continue
            bars = bars_15m(conn, sym, start_close_ms=int(todo[0][0]))
            upd = []
            for t, d, e in todo:
                a, b = fix24(float(e), int(d), int(t), bars, now, log=False)
                if a is not None:
                    upd.append((_py(a), _py(b), sym, tr, mode, version, int(t)))
            conn.executemany("UPDATE triggers SET fix24_mfe=?, fix24_mae=? WHERE symbol=? AND track=? AND mode=? AND rules_version=? "
                             "AND t_bar=?", upd)
            n += len(upd)
    return n


def _py(v):
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    return v


def run_live(conn, rules: dict, version: str, now: int | None = None, conf: dict | None = None, ai_fn=None) -> dict:
    """15분 사이클 한 번(strong15.run 다음): 트리거를 만들고 운영 트리거를 다시 채점."""
    conf = conf or load_conf()
    if not conf.get("enabled", True):
        return {"tech": [], "ai": [], "checks": [], "scored": 0, "enabled": False}
    now = now if now is not None else db.now_ms()
    new = detect_live(conn, rules, version, conf, now, ai_fn)
    new["scored"] = rescore(conn, "live", version, now)
    # 운영 시작 시각은 규칙 버전마다(V5: 버전이 바뀌면 새로 잡는다. 재현의 '확인 기간' 끝이 된다).
    # V4 까지는 버전을 적지 않았으므로 버전 기록이 없으면 옛 버전의 시작으로 보고 새로 잡는다
    if db.kv_get(conn, "trigger_live_start") is None or db.kv_get(conn, "trigger_live_start_version") != version:
        db.kv_set(conn, "trigger_live_start", db.utc_iso(now))
        db.kv_set(conn, "trigger_live_start_version", version)
    return new


def summary(conn, mode: str, version: str, track: str, conf: dict | None = None,
            since: int | None = None, until: int | None = None, symbol: str | None = None) -> dict:
    conf = conf or load_conf()
    sql = ("SELECT symbol, t_bar, dir, mfe, mae, ret_end, base_mfe, status, end_t, fix24_mfe, fix24_mae FROM triggers "
           "WHERE mode=? AND track=? AND rules_version=?")
    p: list = [mode, track, version]
    if since is not None:
        sql += " AND t_bar >= ?"
        p.append(since)
    if until is not None:
        sql += " AND t_bar < ?"
        p.append(until)
    if symbol is not None:
        sql += " AND symbol = ?"
        p.append(symbol)
    return summarize(pd.read_sql_query(sql, conn, params=p), conf)


def recent(conn, version: str, track: str = "ai", mode: str = "live", limit: int = 20, conf: dict | None = None) -> list[dict]:
    """화면용 최근 트리거(새것 먼저). result: success | fail | open_success | open."""
    conf = conf or load_conf()
    fee = fee_rt(conf)
    rows = conn.execute("SELECT symbol, t_bar, dir, kind, entry, issued_at, end_t, end_close, mfe, mae, ret_end, base_mfe, status, "
                        "ai_created_at, fix24_mfe, fix24_mae FROM triggers WHERE mode=? AND track=? AND rules_version=? "
                        "ORDER BY t_bar DESC LIMIT ?", (mode, track, version, limit)).fetchall()
    out = []
    for sym, t, d, kind, entry, issued, end_t, end_close, mfe, mae, ret, base, st, ai_at, f24, f24m in rows:
        thr = threshold(conf, sym)
        reached = mfe is not None and mfe >= thr
        res = ("success" if reached else "fail") if st == "closed" else ("open_success" if reached else "open")
        out.append({"symbol": sym, "short": SHORT.get(sym, sym), "t_bar": int(t), "issued_at": int(issued), "dir": int(d),
                    "kind": kind, "entry": entry, "end_t": end_t, "end_close": end_close, "status": st, "result": res,
                    "ai_created_at": ai_at,
                    "mfe_net_pct": None if mfe is None else round(100 * (mfe - fee), 2),
                    "mae_pct": None if mae is None else round(100 * mae, 2),
                    "ret_net_pct": None if ret is None else round(100 * (ret - fee), 2),
                    "thr_pct": round(100 * thr, 2),
                    "fix24_net_pct": None if f24 is None else round(100 * (f24 - fee), 2),
                    "fix24_result": None if f24 is None else ("success" if f24 >= thr else "fail")})
    return out


CHECK_LABEL = {"pass": "AI 일치 → 트리거", "mismatch": "AI 반대 방향", "neutral": "AI 중립", "ai_error": "AI 분석 실패",
               "banned": "12시간 금지", "late": "늦게 잡힘", "off": "게이트 꺼짐", "repeat": "같은 방향 반복"}


def recent_checks(conn, version: str, limit: int = 12) -> list[dict]:
    rows = conn.execute("SELECT c.symbol, c.t_bar, c.dir, c.checked_at, c.ai_dir, c.result, c.ai_created_at, a.ref_t "
                        "FROM trigger_checks c LEFT JOIN ai_analyses a ON a.symbol=c.symbol AND a.created_at=c.ai_created_at "
                        "WHERE c.rules_version=? ORDER BY c.t_bar DESC LIMIT ?", (version, limit)).fetchall()
    return [{"symbol": s, "short": SHORT.get(s, s), "t_bar": int(t), "dir": int(d), "checked_at": int(c),
             "ai_dir": a, "result": r, "label": CHECK_LABEL.get(r, r), "ai_created_at": ac, "ai_ref_t": ref}
            for s, t, d, c, a, r, ac, ref in rows]


def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — 부가 정보 하나가 보드 전체를 막지 않게
        print(f"보드 부가 정보 실패: {type(e).__name__} {e}")
        return default


def export_board(conn, rules: dict, version: str, conf: dict | None = None, path=None) -> dict:
    """화면용 JSON(reports/trigger_board.json): 트리거 성적·최근 목록·AI 분석·Core Condition. 보드 API 가 그대로 내려준다
    (백엔드는 pandas 없이 돌기 때문에 계산은 엔진에서 한 번만 한다)."""
    import ai_analysis
    import confidence
    conf = conf or load_conf()
    syms = rules["symbols"]
    now = db.now_ms()
    rep = None
    try:
        rep = json.loads((db.ENGINE / "reports" / "trigger_replay.json").read_text(encoding="utf-8"))
        if rep.get("rules_version") != version or rep.get("scoring_fp") != scoring_fingerprint(conf):
            rep = None                     # V5: 규칙 버전과 채점 설정(성공 기준 · 수수료 · 금지 시간)이 모두 같을 때만
    except (OSError, ValueError):
        rep = None
    core = db.kv_get(conn, "core_now")
    core = json.loads(core) if core else {}
    if core.get("version") != version:
        core = {}
    live_start = db.kv_get(conn, "trigger_live_start")
    out = {
        "generated_at": db.utc_iso(now), "rules_version": version, "live_start": live_start,
        "conf": {k: conf[k] for k in ("success_pct", "fee_pct_per_side", "ban_hours", "on_time_min")}
                | {"ai_fresh_hours": conf.get("ai_gate", {}).get("fresh_hours"), "ai_schedule_kst_hours": conf.get("ai_schedule_kst_hours"),
                   # V5: 코인별 성공 기준(수수료 포함, %)과 그 글, 같은 방향 거르기 여부
                   "thr_pct": {s_: round(100 * threshold(conf, s_), 2) for s_ in syms},
                   "thr_text": threshold_text(conf, syms), "same_direction_filter": same_direction_filter(rules)},
        "stats": {
            "official": summary(conn, "live", version, "ai", conf),
            "tech": summary(conn, "live", version, "tech", conf),
            "official_by_symbol": [dict(summary(conn, "live", version, "ai", conf, symbol=s), symbol=s, short=SHORT.get(s, s)) for s in syms],
            "tech_by_symbol": [dict(summary(conn, "live", version, "tech", conf, symbol=s), symbol=s, short=SHORT.get(s, s)) for s in syms],
            "replay": None if rep is None else {k: {"from": v["from"], "to_exclusive": v["to_exclusive"], "all": v["all"], "rows": v["rows"]}
                                                 for k, v in rep.get("periods", {}).items()},
        },
        "recent": {"official": recent(conn, version, "ai", "live", 20, conf), "tech": recent(conn, version, "tech", "live", 20, conf),
                   "checks": recent_checks(conn, version)},
        "ai": ai_analysis.board_view(conn, syms),
        "core": {s: core.get("symbols", {}).get(s) for s in syms} | {"_at": core.get("at")},
        # 확신도(대시보드 KPI): conf_v2(기획안 v5 1절, 기술 지표 50 + 시장 자료 50 → Long 확률). 15분마다 계산, AI 호출 없음
        "confidence": confidence.board(conn, syms, now) | {"_at": now},
        # 공포탐욕지수가 크게 움직인 날(기획안 v5 6절 1). 뉴스 제목은 보드 API 가 켜진 뉴스 출처로 붙인다
        "fng_events": _safe(lambda: ai_analysis.fng_events(conn, now), []),
    }
    target = path or (db.ENGINE / "reports" / "trigger_board.json")
    target.parent.mkdir(exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return out


# ---------------------------------------------------------------- 재현(replay, tech 트랙만)

def state_series_full(conn, symbol: str, rules: dict) -> tuple[pd.Series, pd.Series]:
    """전 기간 15분봉 마감마다 기술 조건 상태(+1/−1/0)와 종가. strong15.state_series 와 같은 규칙(봉 누락 구간은 0)."""
    p4, p1, p15 = rules["macd"]["period"], rules["stoch_pair"]["period"], rules["vpci"]["period"]
    c4, c1, c15 = (db.load_candles(conn, symbol, p) for p in (p4, p1, p15))
    if c4.empty or c1.empty or c15.empty:
        return pd.Series(dtype="int64"), pd.Series(dtype="float64")
    m = judge.macd_frame(c4, rules["macd"])
    pr = judge.pair_frame(c1, rules["stoch_pair"], db.PERIOD_MS[p1])
    vp = judge.vpci_frame(c15, rules["vpci"], db.PERIOD_MS[p15])
    seq = judge.strong_sequence(m["macd_dir"], pr["pair_dir"], vp["vpci_dir"], vp["vpci_last_cross"])
    idx = seq.index
    lb = pipeline.lookback_bars(rules)
    gap = pd.Series(False, index=idx)
    for c, per, n in ((c4, p4, lb["4h"]), (c1, p1, lb["1h"]), (c15, p15, lb["15m"])):
        g = pipeline._recent_gap(c, per, n).astype(float).reindex(idx, method="ffill").fillna(0.0)
        gap |= g.values.astype(bool)
    return seq.where(~gap, 0).astype(int), c15["close"]


def replay(conn, rules: dict, version: str, conf: dict | None = None, until_ms: int | None = None) -> dict:
    """전 기간 tech 트리거를 다시 계산해 triggers(mode=replay)를 바꾸고 기간별 요약을 돌려준다."""
    conf = conf or load_conf()
    ban = int(conf["ban_hours"] * HOUR)
    same = same_direction_filter(rules)
    created = db.now_ms()
    per_sym, rep_sym, data_end = {}, {}, {}
    for sym in rules["symbols"]:
        states, closes = state_series_full(conn, sym, rules)
        if until_ms is not None:
            states, closes = states[states.index <= until_ms], closes[closes.index <= until_ms]
        reps: list = []
        evs = apply_ban(events_from_states(states, closes), ban, same_dir=same, repeats=reps)
        rep_sym[sym] = len(reps)
        conn.execute("DELETE FROM triggers WHERE symbol=? AND mode='replay' AND rules_version=?", (sym, version))
        if not evs:
            per_sym[sym] = 0
            continue
        t = pd.DataFrame({"t_bar": [e.t for e in evs], "dir": [e.dir for e in evs], "kind": [e.kind for e in evs],
                          "entry": [e.close for e in evs]})
        bars = bars_15m(conn, sym)
        if until_ms is not None:
            bars = bars[bars.index <= until_ms]
        end = until_ms or int(bars.index[-1])
        data_end[sym] = end
        sc = score_rows(t, bars, end)
        conn.executemany(
            "INSERT INTO triggers (symbol, track, mode, rules_version, t_bar, dir, kind, entry, issued_at, end_t, end_close, "
            "last_bar_t, mfe, mae, ret_end, base_mfe, status, scored_at, fix24_mfe, fix24_mae) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [tuple(_py(v) for v in (sym, "tech", "replay", version, r.t_bar, r.dir, r.kind, r.entry, r.t_bar, r.end_t,
                                    r.end_close, r.last_bar_t, r.mfe, r.mae, r.ret_end, r.base_mfe, r.status, created,
                                    r.fix24_mfe, r.fix24_mae))
             for r in sc.itertuples()])
        per_sym[sym] = len(sc)
    conn.commit()
    return {"rules_version": version, "per_symbol": per_sym, "repeats": rep_sym, "same_direction_filter": same,
            "data_end": {s_: db.utc_iso(v) for s_, v in data_end.items()},
            "periods": replay_periods(conn, version, conf)}


def _ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)


def replay_periods(conn, version: str, conf: dict | None = None) -> dict:
    conf = conf or load_conf()
    rp = conf["replay"]
    ref_from, ref_to = _ms(rp["reference_period"][0]), _ms(rp["reference_period"][1]) + 86_400_000
    chk_from = _ms(rp["check_period_start"])
    # 확인 기간의 끝 = 이 규칙 버전의 운영 시작. 다른 버전이 남긴 시작 시각은 쓰지 않는다(Fable 검토 지적 3)
    live = db.kv_get(conn, "trigger_live_start") if db.kv_get(conn, "trigger_live_start_version") == version else None
    chk_to = int(pd.Timestamp(live).timestamp() * 1000) if live else None
    syms = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM triggers WHERE mode='replay' AND rules_version=? "
                                       "ORDER BY symbol", (version,))]
    out = {}
    for name, a, b in (("reference", ref_from, ref_to), ("check", chk_from, chk_to)):
        to_txt = rp["reference_period"][1] if name == "reference" else (db.kst_text(b, "%Y-%m-%d %H:%M") if b else None)
        out[name] = {"from": db.kst_text(a, "%Y-%m-%d"), "to_exclusive": to_txt,
                     "all": summary(conn, "replay", version, "tech", conf, a, b),
                     "rows": [dict(summary(conn, "replay", version, "tech", conf, a, b, s), symbol=s) for s in syms]}
    return out


def _commit() -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(db.REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def write_replay_report(res: dict, conf: dict) -> None:
    rep = db.ENGINE / "reports"
    rep.mkdir(exist_ok=True)
    syms = list(res.get("per_symbol") or [])
    meta = {"generated_at": db.utc_iso(db.now_ms()), "success_pct": conf["success_pct"],
            "fee_pct_per_side": conf["fee_pct_per_side"], "ban_hours": conf["ban_hours"],
            "scoring_fp": scoring_fingerprint(conf), "commit": _commit(), "thr_text": threshold_text(conf, syms)}
    (rep / "trigger_replay.json").write_text(json.dumps(meta | res, ensure_ascii=False, indent=1), encoding="utf-8")
    ends = sorted((res.get("data_end") or {}).values())
    lines = ["# 트리거 재현(기술 조건 트랙, 과거 데이터)", "",
             f"- 규칙 {res['rules_version']} · 채점 설정 {meta['scoring_fp']} · 커밋 {meta['commit'] or '-'} · 자료 끝 "
             f"{ends[-1] if ends else '-'} (UTC) · 만든 시각 {meta['generated_at']}",
             f"- 성공 = 다음 트리거까지 최대수익률이 코인별 기준 {meta['thr_text']} 이상 · 트리거 뒤 {conf['ban_hours']}시간 재신호 금지"
             + (" · 직전 트리거와 같은 방향은 '반복'으로 빼고 12시간 기준도 바꾸지 않음" if res.get("same_direction_filter") else "")
             + " · 진입가는 15분봉 종가(바이낸스 현물)",
             "- 24시간 창: 다음 트리거와 상관없이 진입 뒤 24시간 고정 창의 최대수익률로 같은 기준을 넘은 비율(참고 열). "
             "다음 트리거까지 창이 길수록 성공률이 방향과 상관없이 높아지므로 함께 본다.",
             "- AI 게이트(공식 트리거)는 과거 판단이 없어 재현하지 않는다. 운영 기록에서만 센다.",
             "- 읽는 법: Long 트리거는 '같은 구간 항상 Long'이 트리거 자신과 같은 값이라 차이는 Short 트리거에서만 생긴다. "
             "방향 정보의 효과는 '같은 구간 반대 방향'(반대로 들어갔다면의 성공률)과 비교해야 보인다.",
             "- 이 표로 규칙을 고르지 않는다."]
    if res.get("repeats"):
        lines.append("- 같은 방향 반복으로 뺀 사건(전 기간): " + " · ".join(f"{SHORT.get(k, k)} {v}건" for k, v in res["repeats"].items()))
    lines.append("")
    for name, ko in (("reference", "참고 기간"), ("check", "확인 기간")):
        p = res["periods"][name]
        lines += [f"## {ko} ({p['from']} – {p['to_exclusive'] or '지금'})", "",
                  "| 코인 | 트리거 | 끝난 것 | 성공률 | 같은 구간 항상 Long | 같은 구간 반대 방향 | 양쪽 다 | 24시간 창 성공률 | 24시간 창 반대 방향 | 평균 창(시간) | 평균 최대수익률(수수료 뺌) | 평균 최대손실 | 평균 실제 손익(수수료 뺌) | Long/Short |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in p["rows"] + [dict(p["all"], symbol="합계")]:
            lines.append(f"| {SHORT.get(r['symbol'], r['symbol'])} | {r['n']} | {r['closed']} | {r['success_pct']}% | "
                         f"{r['base_success_pct']}% | {r['opp_success_pct']}% | {r['both_pct']}% | {r.get('fix24_success_pct')}% | "
                         f"{r.get('fix24_opp_pct')}% | {r['avg_hours']} | "
                         f"{r['avg_mfe_pct']}% | {r['avg_mae_pct']}% | {r['avg_ret_pct']}% | {r['long']}/{r['short']} |")
        lines.append("")
    (rep / "trigger_replay.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv) -> int:
    if "--replay" not in argv:
        print(__doc__)
        return 0
    rules = db.load_json("rules_v3.json")
    version = db.rules_version(rules)
    conf = load_conf()
    conn = db.connect()
    db.save_rules_snapshot(conn, version, rules)
    res = replay(conn, rules, version, conf)
    write_replay_report(res, conf)
    for name in ("reference", "check"):
        a = res["periods"][name]["all"]
        print(f"{name}: 트리거 {a['n']} · 끝난 것 {a['closed']} · 성공률 {a['success_pct']}% · 항상 Long {a['base_success_pct']}% "
              f"· 반대 방향 {a['opp_success_pct']}% · 양쪽 다 {a['both_pct']}% · 평균 창 {a['avg_hours']}시간 "
              f"· 24시간 창 {a['fix24_success_pct']}%(반대 {a['fix24_opp_pct']}%)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
