"""15분 확실한 신호(2026-10-07, 10-06 인수인계 다음 할 일 1).

4시간 판정(pipeline)은 4시간봉 마감 T 에서만 확실한 신호를 정하지만, 조건서 운영 팁의 "15분 VPCI 가 방향을 트는 순간"은
15분봉마다 생긴다. 이 모듈은 15분마다(run_cycle) 종목별 상태(+1/−1/0)를 `judge.strong_sequence` 로 다시 계산해
**바뀐 때만** `strong15` 표에 한 행 남기고, 켜진 에피소드를 두 가지로 채점한다.

- 상태 계산: chart_export 와 같은 방식으로 워밍업을 넉넉히 두고 세 프레임(4h·1h·15m)을 만든 뒤 strong_sequence.
  지표 계산 구간 안에 봉 누락이 있는 봉(pipeline._recent_gap, 4h 판정의 data_short 와 같은 기준)은 상태 0.
- 기록: 같은 (종목, 15분봉 마감, 규칙 버전)은 INSERT OR IGNORE 라 다시 실행해도 행이 늘지 않는다.
  마지막 기록 뒤의 봉만 본다(이미 지난 봉은 다시 평가하지 않음 → 기록이 흔들리지 않음).
  이 규칙 버전의 첫 기록 때 이미 켜져 있던 상태는 kind=init 으로 남기고 채점하지 않는다(언제 켜졌는지 모름).
- 채점(conf/strong15.json scoring): (가) 에피소드 끝 종가 — episode_end=any_change 면 꺼지거나 방향이 바뀐 봉,
  opposite 면 반대 방향이 켜진 봉(사이의 off 무시). (나) 보조 — 켜진 뒤 aux_horizon_ms(기본 4시간) 뒤 15분봉 종가.
  둘 다 비어 있는 칸만 채우므로 몇 번 돌려도 같다.
- 설정은 conf/strong15.json. rules_v3.json 해시(규칙 버전)에 들어가지 않는다.

사용: python3 strong15.py  (운영 DB 에 한 번 실행. 평소에는 run_cycle 이 부른다)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

import db
import judge
import pipeline

M15 = db.PERIOD_MS["15m"]
DAY_MS = 86_400_000
WARMUP_BARS = {"4h": 1000, "1h": 3000, "15m": 1500}   # chart_export 와 같음
KINDS_SCORED = ("on", "flip")
LABEL = {1: "롱 확실", -1: "숏 확실", 0: "없음"}       # 03_백엔드/app/board.py LABEL15 와 같아야 함(시험으로 확인)


def load_conf() -> dict:
    try:
        return db.load_json("strong15.json")
    except (OSError, ValueError):
        return {"enabled": False}


def state_series(conn, symbol: str, rules: dict, now: int, days: int = 7, core: dict | None = None) -> tuple[pd.Series, pd.Series]:
    """최근 days 일의 15분봉 마감 시각마다 확실한 신호 상태(+1/−1/0)와 그 봉의 종가. 봉이 없으면 빈 Series.
    core 에 dict 를 주면 마지막 15분봉 시점의 시간대별 방향(4시간·1시간·15분)을 채운다(10-12 화면 Core Condition)."""
    p4, p1, p15 = rules["macd"]["period"], rules["stoch_pair"]["period"], rules["vpci"]["period"]
    frames = {}
    for per in (p4, p1, p15):
        plen = db.PERIOD_MS[per]
        start = now - (WARMUP_BARS[per] + days * DAY_MS // plen) * plen
        frames[per] = db.load_candles(conn, symbol, per, end_close_ms=now, start_close_ms=start)
    c4, c1, c15 = frames[p4], frames[p1], frames[p15]
    empty = pd.Series(dtype="int64"), pd.Series(dtype="float64")
    if c4.empty or c1.empty or c15.empty:
        return empty
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
    seq = seq.where(~gap, 0).astype(int)
    if core is not None and len(idx):
        t = idx[-1]
        md = m["macd_dir"].reindex(idx, method="ffill").fillna(0).astype(int)
        pdr = pr["pair_dir"].reindex(idx, method="ffill").fillna(0).astype(int)
        ok = not bool(gap.iloc[-1])
        core.update({"t": int(t), "state": int(seq.iloc[-1]), "ok": ok,
                     "h4": int(md.iloc[-1]) if ok else 0, "h1": int(pdr.iloc[-1]) if ok else 0,
                     "m15": int(vp["vpci_dir"].iloc[-1]) if ok else 0})
    since = now - days * DAY_MS
    keep = idx >= since
    return seq[keep], c15["close"][keep]


def _kind(prev: int, cur: int) -> str:
    return "off" if cur == 0 else ("on" if prev == 0 else "flip")


def record(conn, symbol: str, version: str, states: pd.Series, closes: pd.Series, now: int | None = None) -> list[dict]:
    """상태 Series 를 보고 바뀐 봉을 strong15 에 넣는다. 반환: 이번에 새로 들어간 행(dict) 목록."""
    if states.empty:
        return []
    created = now if now is not None else db.now_ms()
    last = conn.execute("SELECT t_close, dir FROM strong15 WHERE symbol=? AND rules_version=? ORDER BY t_close DESC LIMIT 1",
                        (symbol, version)).fetchone()
    todo = []
    if last is None:
        t0, d0 = int(states.index[0]), int(states.iloc[0])
        prev, after = d0, t0
        if d0 != 0:
            todo.append((t0, 0, d0, "init"))
    else:
        prev, after = int(last[1]), int(last[0])
    for t, d in states[states.index > after].items():
        d = int(d)
        if d != prev:
            todo.append((int(t), prev, d, _kind(prev, d)))
            prev = d
    out = []
    for t, pv, d, kind in todo:
        close = closes.get(t)
        close = None if close is None or close != close else float(close)
        cur = conn.execute("INSERT OR IGNORE INTO strong15 (symbol, t_close, rules_version, dir, prev_dir, kind, close, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?)", (symbol, t, version, d, pv, kind, close, created))
        if cur.rowcount:
            out.append({"symbol": symbol, "t_close": t, "rules_version": version, "dir": d, "prev_dir": pv, "kind": kind,
                        "close": close})
    conn.commit()
    return out


def _hit(ret: float | None, d: int):
    if ret is None or ret != ret or ret == 0:
        return None
    return int(np.sign(ret) == d)


def score_pending(conn, conf: dict | None = None, now: int | None = None) -> int:
    """켜진 에피소드(on·flip)의 비어 있는 채점 칸을 채운다. 반환: 새로 채운 칸(가·나 각각 1) 수."""
    conf = conf if conf is not None else load_conf()
    sc = conf.get("scoring", {})
    end_rule = sc.get("episode_end", "any_change")
    aux_ms = int(sc.get("aux_horizon_ms", db.PERIOD_MS["4h"]))
    now = now if now is not None else db.now_ms()
    q_kinds = ",".join("?" * len(KINDS_SCORED))
    n = 0
    # (가) 에피소드 끝
    rows = conn.execute(f"SELECT symbol, t_close, rules_version, dir, close FROM strong15 WHERE kind IN ({q_kinds}) "
                        "AND end_t IS NULL AND close IS NOT NULL ORDER BY symbol, t_close", KINDS_SCORED).fetchall()
    for sym, t, ver, d, close in rows:
        if end_rule == "opposite":
            nxt = conn.execute("SELECT t_close, close, kind FROM strong15 WHERE symbol=? AND rules_version=? AND t_close>? "
                               "AND dir=? ORDER BY t_close LIMIT 1", (sym, ver, t, -d)).fetchone()
            reason = "opposite"
        else:
            nxt = conn.execute("SELECT t_close, close, kind FROM strong15 WHERE symbol=? AND rules_version=? AND t_close>? "
                               "ORDER BY t_close LIMIT 1", (sym, ver, t)).fetchone()
            reason = nxt[2] if nxt else None
        if not nxt or nxt[1] is None:
            continue
        ret = float(nxt[1]) / float(close) - 1
        conn.execute("UPDATE strong15 SET end_t=?, end_close=?, end_reason=?, ret=?, hit=?, scored_at=? "
                     "WHERE symbol=? AND t_close=? AND rules_version=? AND end_t IS NULL",
                     (int(nxt[0]), float(nxt[1]), reason, ret, _hit(ret, d), now, sym, t, ver))
        n += 1
    # (나) 보조: aux_ms 뒤 15분봉 종가(마감 = t + aux_ms → 시작 ts = 마감 − 15분)
    rows = conn.execute(f"SELECT symbol, t_close, rules_version, dir, close FROM strong15 WHERE kind IN ({q_kinds}) "
                        "AND aux_t IS NULL AND close IS NOT NULL AND t_close + ? <= ? ORDER BY symbol, t_close",
                        (*KINDS_SCORED, aux_ms, now)).fetchall()
    for sym, t, ver, d, close in rows:
        aux_t = int(t) + aux_ms
        bar = pd.read_sql_query("SELECT ts, open, high, low, close, volume FROM candles WHERE source='binance' AND symbol=? "
                                "AND period='15m' AND ts=?", conn, params=[sym, aux_t - M15])
        if bar.empty or not bool(db.good_ohlcv(bar).iloc[0]):
            continue                       # 봉이 아직 없거나 깨짐 → 보류(다음 실행에서 다시)
        ac = float(bar["close"].iloc[0])
        ret = ac / float(close) - 1
        conn.execute("UPDATE strong15 SET aux_t=?, aux_close=?, aux_ret=?, aux_hit=?, scored_at=? "
                     "WHERE symbol=? AND t_close=? AND rules_version=? AND aux_t IS NULL",
                     (aux_t, ac, ret, _hit(ret, d), now, sym, t, ver))
        n += 1
    conn.commit()
    return n


def summary(conn, version: str | None = None) -> list[dict]:
    """종목별: 에피소드 수, (가)·(나) 채점 수와 적중. 보드(board.py _strong15_summary)와 같은 SQL."""
    q_kinds = ",".join("?" * len(KINDS_SCORED))
    sql = (f"SELECT symbol, COUNT(*) n, SUM(hit IS NOT NULL) called, SUM(hit=1) hit, SUM(end_t IS NOT NULL) ended, "
           f"SUM(aux_hit IS NOT NULL) aux_called, SUM(aux_hit=1) aux_hit FROM strong15 WHERE kind IN ({q_kinds})")
    params: list = list(KINDS_SCORED)
    if version is not None:
        sql += " AND rules_version=?"
        params.append(version)
    sql += " GROUP BY symbol ORDER BY symbol"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(zip(["symbol", "n", "called", "hit", "ended", "aux_called", "aux_hit"], [x or 0 for x in r]))
        d["hit_pct"] = round(100 * d["hit"] / d["called"], 1) if d["called"] else None
        d["aux_pct"] = round(100 * d["aux_hit"] / d["aux_called"], 1) if d["aux_called"] else None
        out.append(d)
    return out


def current(conn, symbol: str, version: str) -> dict | None:
    """지금 상태 = 이 종목·규칙 버전의 마지막 행. 없으면 None."""
    r = conn.execute("SELECT t_close, dir, kind, close FROM strong15 WHERE symbol=? AND rules_version=? "
                     "ORDER BY t_close DESC LIMIT 1", (symbol, version)).fetchone()
    return None if r is None else {"t_close": int(r[0]), "dir": int(r[1]), "kind": r[2], "close": r[3]}


def run(conn, rules: dict, version: str, now: int | None = None, conf: dict | None = None) -> dict:
    """15분 사이클 한 번: 종목별 상태 재계산 → 바뀐 봉 기록 → 채점. 반환 {"new": [새 행], "scored": n}."""
    conf = conf if conf is not None else load_conf()
    if not conf.get("enabled", False):
        return {"new": [], "scored": 0, "enabled": False}
    now = now if now is not None else db.now_ms()
    days = int(conf.get("lookback_days", 7))
    new = []
    core_all = {}
    for sym in rules["symbols"]:
        core = {}
        states, closes = state_series(conn, sym, rules, now, days, core)
        new += record(conn, sym, version, states, closes, now)
        if core:
            core_all[sym] = core
    scored = score_pending(conn, conf, now)
    db.kv_set(conn, "strong15_last_run", now)
    db.kv_set(conn, "core_now", json.dumps({"version": version, "at": now, "symbols": core_all}))
    return {"new": new, "scored": scored, "enabled": True}


def main() -> int:
    rules = db.load_json("rules_v3.json")
    version = db.rules_version(rules)
    conn = db.connect()
    r = run(conn, rules, version)
    for row in r["new"]:
        print(f"{row['symbol']} {db.kst_text(row['t_close'])} {row['kind']} {LABEL[row['dir']]}")
    print(f"15분 확실한 신호: 새 기록 {len(r['new'])}건 · 채점 {r['scored']}건")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
