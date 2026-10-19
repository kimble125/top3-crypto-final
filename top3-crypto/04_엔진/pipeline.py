"""분석 계산: 캔들 → 지표 → 방향 → 가중 점수·확실한 신호. live 와 replay 가 같은 함수를 쓴다.

기획서 ver3 AI학습용 §1-4, §1-5.
- 분석 시각 T = 4시간봉 마감. 1h·15m 은 마감이 정확히 T 인 봉의 값을 쓴다(그 봉까지가 T 에 닫힌 마지막 봉).
- status: ok / data_short(그 봉이 없거나, 지표 계산 구간 안에 봉 누락이 있음) / not_ready(워밍업 등으로 지표 값이 없음).
  ok 가 아니면 점수를 내지 않는다(채점·재현 집계에서도 빠짐).
- 지표는 전 구간으로 계산해도 인과적이므로, T 까지 자른 데이터로 계산한 것과 같다(tests 에서 확인).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import db
import judge

DIR_COLS = ["macd_dir", "pair_dir", "vpci_dir"]
PAIR_COLS = ["sto_k", "sto_d", "sto_state", "sto_last_event", "srsi_k", "srsi_d", "srsi_state",
             "srsi_last_event", "pair_dir"]
VPCI_COLS = ["vpci", "vpcis", "vpci_dir", "vpci_last_cross"]
VALUE_COLS = ["macd", "macd_signal", "sto_k", "sto_d", "srsi_k", "srsi_d", "vpci", "vpcis"]


def score_from_dirs(d_macd, d_pair, d_vpci, w: dict):
    """점수 = round(100 × Σ w·d / Σ w). 스칼라·배열 모두 받는다."""
    num = w["macd"] * np.asarray(d_macd) + w["pair"] * np.asarray(d_pair) + w["vpci"] * np.asarray(d_vpci)
    den = w["macd"] + w["pair"] + w["vpci"]
    return np.rint(100 * num / den).astype(int)


def strong_from_dirs(d_macd, d_pair, d_vpci):
    a, b, c = (np.asarray(x) for x in (d_macd, d_pair, d_vpci))
    strong = (a == b) & (b == c) & (a != 0)
    return strong.astype(int), np.where(strong, a, 0).astype(int)


def label(score, strong, strong_dir, d_macd=None, d_pair=None, d_vpci=None, weights=None) -> str:
    """화면·디스코드·해설 공용 라벨.
    MACD 가중치가 나머지 합보다 크고 나머지 둘이 모두 MACD 와 반대면 'MACD만 Long/Short'
    (화살표 셋이 반대인데 점수 부호가 MACD 를 따르는 경우를 초보자가 오해하지 않게)."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "데이터 부족"
    if strong:
        return "확실한 신호 Long" if strong_dir > 0 else "확실한 신호 Short"
    if d_macd is not None and d_macd != 0 and d_pair == -d_macd and d_vpci == -d_macd:
        w = weights or {"macd": 4, "pair": 2, "vpci": 1}
        if w["macd"] > w["pair"] + w["vpci"]:
            return "MACD만 Long" if d_macd > 0 else "MACD만 Short"
    if score > 0:
        return "Long 우세"
    if score < 0:
        return "Short 우세"
    return "방향 없음"


def lookback_bars(rules: dict) -> dict:
    """지표 계산에 필요한 봉 수(+교차 판정용 1봉). 이 구간 안에 봉 누락이 있으면 data_short."""
    m, sp, v = rules["macd"], rules["stoch_pair"], rules["vpci"]
    sto = sp["stoch"]["k"] + sp["stoch"]["smooth_k"] + sp["stoch"]["d"]
    srsi = sp["stochrsi"]["rsi"] + sp["stochrsi"]["stoch"] + sp["stochrsi"]["k"] + sp["stochrsi"]["d"]
    return {"4h": m["slow"] + m["signal"] + 1, "1h": max(sto, srsi) + 1, "15m": v["long"] + v["signal"] + 1}


def _recent_gap(c: pd.DataFrame, period: str, window: int) -> pd.Series:
    """각 봉에서 최근 window 봉 안에 시간 간격이 어긋난(빠진 봉이 있는) 곳이 있는지."""
    if c.empty:
        return pd.Series(dtype=bool)
    gap = judge.bar_breaks(c.index, db.PERIOD_MS[period])
    return gap.astype(int).rolling(window, min_periods=1).max().astype(bool)


def compute(conn, symbol: str, rules: dict, end_close_ms: int | None = None) -> pd.DataFrame:
    """종목 하나의 모든 4h 마감 T 에 대한 분석 표. index = T(UTC ms)."""
    p4, p1, p15 = rules["macd"]["period"], rules["stoch_pair"]["period"], rules["vpci"]["period"]
    c4 = db.load_candles(conn, symbol, p4, end_close_ms)
    c1 = db.load_candles(conn, symbol, p1, end_close_ms)
    c15 = db.load_candles(conn, symbol, p15, end_close_ms)
    if c4.empty:
        return pd.DataFrame()
    lb = lookback_bars(rules)
    m = judge.macd_frame(c4, rules["macd"])
    pr = judge.pair_frame(c1, rules["stoch_pair"], db.PERIOD_MS[p1]) if not c1.empty else pd.DataFrame(columns=PAIR_COLS, dtype=float)
    vp = judge.vpci_frame(c15, rules["vpci"], db.PERIOD_MS[p15]) if not c15.empty else pd.DataFrame(columns=VPCI_COLS, dtype=float)

    T = c4.index
    out = pd.DataFrame(index=T)
    out["close"] = c4["close"]
    out = out.join(m)
    out = out.join(pr.reindex(T))
    out = out.join(vp.reindex(T))
    has1 = T.isin(c1.index)
    has15 = T.isin(c15.index)
    out["bar_1h_close"] = np.where(has1, T, np.nan)
    out["bar_15m_close"] = np.where(has15, T, np.nan)

    gap4 = _recent_gap(c4, p4, lb["4h"]).reindex(T).fillna(False).astype(bool)
    gap1 = _recent_gap(c1, p1, lb["1h"]).reindex(T).fillna(False).astype(bool)
    gap15 = _recent_gap(c15, p15, lb["15m"]).reindex(T).fillna(False).astype(bool)
    short = (~has1) | (~has15) | gap4.values | gap1.values | gap15.values
    not_ready = out[VALUE_COLS].isna().any(axis=1).values
    out["status"] = np.where(short, "data_short", np.where(not_ready, "not_ready", "ok"))
    ok = out["status"].values == "ok"

    for c in DIR_COLS + ["sto_state", "srsi_state"]:
        out[c] = out[c].fillna(0).astype(int)
    w = rules["weights"]
    sc = score_from_dirs(out["macd_dir"], out["pair_dir"], out["vpci_dir"], w)
    st, sd = strong_from_dirs(out["macd_dir"], out["pair_dir"], out["vpci_dir"])
    if rules.get("strong", {}).get("sequence") == "vpci_after_alignment" and not c15.empty and not c1.empty:
        seq = judge.strong_sequence(m["macd_dir"], pr["pair_dir"], vp["vpci_dir"], vp["vpci_last_cross"]).reindex(T).fillna(0).astype(int)
        st = ((st == 1) & (seq.values != 0)).astype(int)
        sd = np.where(st == 1, sd, 0).astype(int)
    out["score"] = np.where(ok, sc, np.nan)
    out["strong"] = np.where(ok, st, 0)
    out["strong_dir"] = np.where(ok, sd, 0)

    fng = db.load_fng(conn)
    if len(fng):
        # T 에 이미 공개된 값만: 기준일 00:00 이 T 보다 이전인 마지막 값
        pos = np.searchsorted(fng.index.values, T.values - 1, side="right") - 1
        out["fng"] = np.where(pos >= 0, fng.values[np.clip(pos, 0, None)], np.nan)
        out["fng_day"] = np.where(pos >= 0, fng.index.values[np.clip(pos, 0, None)], np.nan)
    else:
        out["fng"] = np.nan
        out["fng_day"] = np.nan
    return out


ROW_COLS = ["status", "close", "macd", "macd_signal", "macd_dir", "macd_last_cross",
            "sto_k", "sto_d", "sto_state", "sto_last_event", "srsi_k", "srsi_d", "srsi_state", "srsi_last_event",
            "pair_dir", "vpci", "vpcis", "vpci_dir", "vpci_last_cross", "score", "strong", "strong_dir", "fng",
            "bar_1h_close", "bar_15m_close"]
INT_COLS = {"macd_dir", "sto_state", "srsi_state", "pair_dir", "vpci_dir", "strong", "strong_dir",
            "macd_last_cross", "sto_last_event", "srsi_last_event", "vpci_last_cross",
            "bar_1h_close", "bar_15m_close", "score", "fng"}


def _py(v):
    if v is None:
        return None
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def to_rows(frame: pd.DataFrame, symbol: str, version: str, mode: str, created_at: int):
    """analyses 표 INSERT 용 튜플 목록."""
    rows = []
    for t, r in frame[ROW_COLS].iterrows():
        vals = []
        for c in ROW_COLS:
            v = _py(r[c])
            if c in INT_COLS and v is not None and not isinstance(v, str):
                v = int(round(v))
            vals.append(v)
        rows.append((symbol, int(t), version, mode, *vals, created_at))
    return rows


INSERT_SQL = ("INSERT OR IGNORE INTO analyses (symbol, t_close, rules_version, mode, "
              + ", ".join(ROW_COLS) + ", created_at) VALUES ("
              + ",".join(["?"] * (4 + len(ROW_COLS) + 1)) + ")")
