"""채점: 분석(T)의 기준가와 다음 4시간봉(마감 T+4h) 종가를 비교. 기획서 ver3 AI학습용 §1-6.

- call_dir = sign(score). 0 이면 방향 없음(채점 제외, hit NULL).
- ret = 0(보합)이면 hit NULL.
- 기준 예측 '항상 Long': ret > 0 이면 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import db

FOUR_H = db.PERIOD_MS["4h"]
# 운영 성적에 넣는 분석: 분석 시각 T부터 이 시간 안에 만든 것만(10-04 호연 승인, 1시간).
# 예전에는 "다음 4h 봉이 닫히기 전"이라 T+3시간에 만든 분석도 '미리 낸 분석'으로 셌다(GPT-6.1 Sol 지적).
# 03_백엔드/app/board.py 의 ON_TIME 과 같아야 한다(시험으로 확인).
ON_TIME_MS = db.PERIOD_MS["1h"]


def outcome_fields(close, next_close, score, strong, strong_dir):
    """배열 입력 → (ret, call_dir, hit, strong_hit, base_hit). 정수 열의 NULL 은 NaN 으로."""
    close = np.asarray(close, dtype=float)
    nxt = np.asarray(next_close, dtype=float)
    sc = np.asarray(score, dtype=float)
    ret = nxt / close - 1
    sgn_ret = np.sign(ret)
    call = np.sign(np.nan_to_num(sc, nan=0.0))
    hit = np.where((call != 0) & (sgn_ret != 0), (sgn_ret == call).astype(float), np.nan)
    st = np.asarray(strong, dtype=float)
    sd = np.asarray(strong_dir, dtype=float)
    strong_hit = np.where((st == 1) & (sgn_ret != 0), (sgn_ret == sd).astype(float), np.nan)
    base_hit = np.where(sgn_ret != 0, (sgn_ret > 0).astype(float), np.nan)
    bad = np.isnan(ret)
    for a in (hit, strong_hit, base_hit):
        a[bad] = np.nan
    return ret, call, hit, strong_hit, base_hit


def _n(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else (int(v) if float(v).is_integer() else float(v))


def score_pending(conn, mode: str = "live") -> int:
    """채점 안 된 분석 중 다음 4h 봉이 닫힌 것을 채점해 outcomes 에 넣는다. 반환: 새로 채점한 수."""
    pend = pd.read_sql_query(
        "SELECT a.symbol, a.t_close, a.rules_version, a.close, a.score, a.strong, a.strong_dir "
        "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close "
        "AND o.rules_version=a.rules_version AND o.mode=a.mode "
        "WHERE a.mode=? AND a.status='ok' AND o.t_close IS NULL", conn, params=[mode])
    if pend.empty:
        return 0
    added = 0
    now = db.now_ms()
    for sym, g in pend.groupby("symbol"):
        ts_list = [int(t) for t in g["t_close"]]
        q = ",".join("?" * len(ts_list))
        nb = pd.read_sql_query(
            f"SELECT ts, open, high, low, close, volume FROM candles "
            f"WHERE source='binance' AND symbol=? AND period='4h' AND ts IN ({q})",
            conn, params=[sym, *ts_list])  # 시작이 T 인 봉 = 마감 T+4h
        nb = nb[db.good_ohlcv(nb)] if not nb.empty else nb   # 깨진 다음 봉으로는 채점하지 않고 보류
        nxt = {int(t): float(c) for t, c in zip(nb["ts"], nb["close"])}
        g = g[g["t_close"].map(lambda t: int(t) in nxt and int(t) + FOUR_H <= now)]
        if g.empty:
            continue
        next_close = g["t_close"].map(lambda t: nxt[int(t)]).values
        ret, call, hit, sh, bh = outcome_fields(g["close"], next_close, g["score"], g["strong"], g["strong_dir"])
        rows = [(sym, int(t), v, mode, float(nc), float(r), int(c), _n(h), _n(s), _n(b), now)
                for t, v, nc, r, c, h, s, b in zip(g["t_close"], g["rules_version"], next_close, ret, call, hit, sh, bh)]
        cur = conn.executemany(
            "INSERT OR IGNORE INTO outcomes (symbol, t_close, rules_version, mode, next_close, ret, call_dir, hit, "
            "strong_hit, base_hit, scored_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        added += cur.rowcount
    conn.commit()
    return added


def summary(conn, mode: str = "live", since_ms: int | None = None, until_ms: int | None = None,
            version: str | None = None, on_time_only: bool = False) -> list[dict]:
    """종목별 집계. n=생성, scored=채점 완료, hit/called, strong_hit/strong_scored, base_hit/base_scored.
    on_time_only: 분석 시각 T부터 ON_TIME_MS(1시간) 안에 만든 분석만(운영 성적용). 늦게 복구한 분석은 이미 가격이
    움직인 뒤에 만들어졌으므로 성적에서 뺀다(계산은 T 까지의 봉만 쓰지만, '미리 낸 분석'이라는 운영 성적의 뜻을 지키기 위함)."""
    sql = ("SELECT a.symbol, COUNT(*) n, SUM(o.t_close IS NOT NULL) scored, "
           "SUM(o.hit=1) hit, SUM(o.hit IS NOT NULL) called, "
           "SUM(a.strong=1) strong_n, SUM(o.strong_hit=1) strong_hit, SUM(o.strong_hit IS NOT NULL) strong_scored, "
           "SUM(o.base_hit=1) base_hit, SUM(o.base_hit IS NOT NULL) base_scored, "
           "SUM(a.strong=1 AND o.base_hit=1) strong_base_hit, SUM(a.strong=1 AND o.base_hit IS NOT NULL) strong_base_scored "
           "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close "
           "AND o.rules_version=a.rules_version AND o.mode=a.mode "
           "WHERE a.mode=? AND a.status='ok'")
    params: list = [mode]
    if since_ms is not None:
        sql += " AND a.t_close >= ?"
        params.append(since_ms)
    if until_ms is not None:
        sql += " AND a.t_close < ?"
        params.append(until_ms)
    if version is not None:
        sql += " AND a.rules_version = ?"
        params.append(version)
    if on_time_only:
        sql += f" AND a.created_at < a.t_close + {ON_TIME_MS}"
    sql += " GROUP BY a.symbol ORDER BY a.symbol"
    out = []
    for r in conn.execute(sql, params).fetchall():
        d = dict(zip(["symbol", "n", "scored", "hit", "called", "strong_n", "strong_hit", "strong_scored",
                      "base_hit", "base_scored", "strong_base_hit", "strong_base_scored"],
                     [x if x is not None else 0 for x in r]))
        d["hit_pct"] = round(100 * d["hit"] / d["called"], 1) if d["called"] else None
        d["strong_pct"] = round(100 * d["strong_hit"] / d["strong_scored"], 1) if d["strong_scored"] else None
        d["base_pct"] = round(100 * d["base_hit"] / d["base_scored"], 1) if d["base_scored"] else None
        # 확실한 신호와 비교할 기준은 같은 시점들의 '항상 Long'(전체 기간 기준과 섞지 않음, 10-03 GPT-6 Astra 지적)
        d["strong_base_pct"] = (round(100 * d["strong_base_hit"] / d["strong_base_scored"], 1)
                                if d["strong_base_scored"] else None)
        d["small_sample"] = d["called"] < 30
        out.append(d)
    return out


def late_count(conn, version: str | None = None) -> int:
    """늦게 만든 운영 분석(분석 시각 T부터 ON_TIME_MS 뒤에 만든 ok 행) 수."""
    sql = f"SELECT COUNT(*) FROM analyses WHERE mode='live' AND status='ok' AND created_at >= t_close + {ON_TIME_MS}"
    params: list = []
    if version is not None:
        sql += " AND rules_version = ?"
        params.append(version)
    return conn.execute(sql, params).fetchone()[0]
