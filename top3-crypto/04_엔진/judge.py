"""판정: 지표 값 → 방향(+1 Long / −1 Short / 0 없음). 기획서 ver3 AI학습용 §1-4.

모든 계산은 인과적이며, 결과 프레임의 index 는 봉 마감 시각(UTC ms)이다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import indicators as ind


def _sign(x: pd.Series) -> pd.Series:
    return np.sign(x).fillna(0).astype(int)


def change_points(dir_s: pd.Series) -> pd.Series:
    """방향이 실제로 바뀐 봉이면 새 방향(+1/−1), 아니면 0. _last_change_time 과 같은 정의."""
    prev = dir_s.replace(0, np.nan).ffill().shift(1)
    flipped = dir_s.ne(0) & prev.notna() & dir_s.ne(prev)
    return pd.Series(np.where(flipped, dir_s, 0), index=dir_s.index).astype(int)


def _last_change_time(dir_s: pd.Series) -> pd.Series:
    """방향이 실제로 바뀐 마지막 봉의 마감 시각. 비교 대상은 '직전 봉'이 아니라 '직전의 마지막 유효 방향'이다.
    그래서 Long → 방향 없음 → Short 도 Short 가 된 봉에서 바뀐 것으로 센다.
    워밍업이 끝나며 처음 방향이 생긴 것, 결측 뒤 같은 방향으로 돌아온 것은 세지 않는다."""
    t = pd.Series(np.where(change_points(dir_s) != 0, dir_s.index.values, np.nan), index=dir_s.index)
    return t.ffill()


def macd_frame(c4: pd.DataFrame, p: dict) -> pd.DataFrame:
    m = ind.macd(c4["close"], p["fast"], p["slow"], p["signal"])
    d = _sign(m["macd"] - m["signal"])
    d[m["macd"].isna() | m["signal"].isna()] = 0
    return pd.DataFrame({"macd": m["macd"], "macd_signal": m["signal"], "macd_dir": d,
                         "macd_last_cross": _last_change_time(d)})


def zone_cross_state(k: pd.Series, d: pd.Series, upper: float, lower: float,
                     mapping: str = "standard", max_age_bars=None, breaks: pd.Series | None = None) -> pd.DataFrame:
    """%K·%D 교차 중 '80 이상'·'20 이하'에서 난 것만 사건으로 보고, 마지막 사건 방향을 상태로 유지.

    교차 높이 z = (K + D) / 2 (교차한 봉 기준).
    standard: z ≥ upper 에서 하향 교차 → −1, z ≤ lower 에서 상향 교차 → +1.
    momentum: z ≥ upper 에서 교차(방향 무관) → +1, z ≤ lower 에서 교차 → −1.
    breaks: 바로 앞 봉이 빠진 봉이면 True. 빠진 구간에서 사건이 있었는지 알 수 없으므로
    그 봉에서 기억을 지우고(상태 0), 빠진 봉을 건너뛴 교차도 사건으로 세지 않는다.
    """
    up = (k.shift(1) <= d.shift(1)) & (k > d)
    down = (k.shift(1) >= d.shift(1)) & (k < d)
    z = (k + d) / 2
    hi, lo = z >= upper, z <= lower
    ev = pd.Series(0, index=k.index, dtype=int)
    if mapping == "standard":
        ev[hi & down] = -1
        ev[lo & up] = 1
    elif mapping == "momentum":
        ev[hi & (up | down)] = 1
        ev[lo & (up | down)] = -1
    else:
        raise ValueError(f"zone_mapping 값 오류: {mapping}")
    invalid = k.isna() | d.isna()
    brk = (breaks.reindex(k.index).fillna(False).astype(bool) if breaks is not None
           else pd.Series(False, index=k.index))
    ev[invalid | k.shift(1).isna() | d.shift(1).isna() | brk] = 0
    seg = brk.cumsum()  # 빠진 봉마다 새 구간. 기억은 구간 안에서만 이어진다
    evf = ev.astype(float).replace(0, np.nan)
    state = evf.groupby(seg).ffill().fillna(0).astype(int)  # 마지막 사건의 방향을 기억
    ev_time = pd.Series(np.where(ev != 0, k.index.values, np.nan), index=k.index).groupby(seg).ffill()
    if max_age_bars:
        pos = pd.Series(np.arange(len(k)), index=k.index)
        ev_pos = pd.Series(np.where(ev != 0, pos, np.nan), index=k.index).groupby(seg).ffill()
        state[(pos - ev_pos) > int(max_age_bars)] = 0
    state[invalid] = 0  # 지금 값이 계산되지 않으면(분모 0 등) 출력 방향은 없음. 기억은 다음 봉에서 이어짐
    return pd.DataFrame({"event": ev, "state": state, "last_event": ev_time})


def _hold_events(ev: pd.Series, invalid: pd.Series, brk: pd.Series) -> tuple[pd.Series, pd.Series]:
    """사건(+1/−1/0)의 방향을 다음 사건 전까지 유지. 빠진 봉에서는 기억을 지운다(zone_cross_state 와 같은 규칙)."""
    seg = brk.cumsum()
    state = ev.astype(float).replace(0, np.nan).groupby(seg).ffill().fillna(0).astype(int)
    ev_time = pd.Series(np.where(ev != 0, ev.index.values, np.nan), index=ev.index).groupby(seg).ffill()
    state[invalid] = 0
    return state, ev_time


KD_EPS = 1e-8   # %K·%D(0–100) 비교 허용오차. 10-04 GPT-6.1 Sol: 100.00000000000001 대 100.0000000000001 같은 소수점 오차가 방향을 만듦


def kd_state(k: pd.Series, d: pd.Series, breaks: pd.Series | None = None,
             cross_exception: bool = True) -> pd.DataFrame:
    """정미님 조건서(10-03) 방식: 그 봉의 상태로 본다.
    Long(+1) = %K가 %D 위에 있고 오르는 중(직전 봉보다 큼). cross_exception 이면 이번 봉에서 %D를 상향 돌파한 것도 Long.
    Short(−1) = 거울상. 그 밖(위에 있지만 내림 등)은 0.
    조건서: Stochastic 은 "상향 돌파했거나 위에서 우상향"(교차 예외 있음), StochRSI 는 "위에서 위를 향함"(교차 예외 없음).
    "오르는 중 = 직전 1시간봉보다 %K가 큼"은 해석(정미님 확인 대기). 80·20은 판정에 쓰지 않는다(조건서: 신뢰도 설명).
    비교는 KD_EPS 만큼의 차이는 같다고 본다. 바로 앞 봉이 빠졌으면 기울기·교차를 알 수 없어 0.
    event 는 그래프용 %K·%D 교차(+1 상향, −1 하향)."""
    k1, d1 = k.shift(1), d.shift(1)
    above, below = k > d + KD_EPS, k < d - KD_EPS
    up_x = (k1 <= d1 + KD_EPS) & above
    dn_x = (k1 >= d1 - KD_EPS) & below
    rise, fall = k > k1 + KD_EPS, k < k1 - KD_EPS
    if cross_exception:
        rise, fall = rise | up_x, fall | dn_x
    st = np.where(above & rise, 1, np.where(below & fall, -1, 0))
    state = pd.Series(st, index=k.index).astype(int)
    brk = (breaks.reindex(k.index).fillna(False).astype(bool) if breaks is not None
           else pd.Series(False, index=k.index))
    invalid = k.isna() | d.isna() | k1.isna() | d1.isna() | brk
    state[invalid] = 0
    ev = pd.Series(np.where(up_x, 1, np.where(dn_x, -1, 0)), index=k.index).astype(int)
    ev[invalid] = 0
    return pd.DataFrame({"event": ev, "state": state, "last_event": _last_change_time(state)})


def bar_breaks(index: pd.Index, period_ms: int) -> pd.Series:
    """바로 앞 봉과의 간격이 한 봉 길이가 아니면(사이에 빠진 봉이 있으면) True."""
    return pd.Series(np.r_[False, np.diff(np.asarray(index, dtype="int64")) != period_ms], index=index)


def pair_frame(c1: pd.DataFrame, p: dict, period_ms: int | None = None) -> pd.DataFrame:
    s = ind.stochastic(c1["high"], c1["low"], c1["close"], p["stoch"]["k"], p["stoch"]["smooth_k"], p["stoch"]["d"])
    r = ind.stoch_rsi(c1["close"], p["stochrsi"]["rsi"], p["stochrsi"]["stoch"], p["stochrsi"]["k"], p["stochrsi"]["d"])
    brk = bar_breaks(c1.index, period_ms) if period_ms else None
    mode = p.get("mode", "zone_event")
    if mode == "kd_state":       # 정미님 조건서(10-03): %K·%D 위치와 기울기
        zs = kd_state(s["k"], s["d"], brk, p["stoch"].get("cross_exception", True))
        zr = kd_state(r["k"], r["d"], brk, p["stochrsi"].get("cross_exception", True))
    elif mode == "zone_event":   # 2차 회의 필기: 80 이상·20 이하에서 난 교차만 사건, 다음 사건까지 유지
        zs = zone_cross_state(s["k"], s["d"], p["upper"], p["lower"], p["zone_mapping"], p.get("max_age_bars"), brk)
        zr = zone_cross_state(r["k"], r["d"], p["upper"], p["lower"], p["zone_mapping"], p.get("max_age_bars"), brk)
    else:
        raise ValueError(f"stoch_pair.mode 값 오류: {mode}")
    agree = (zs["state"] == zr["state"]) & (zs["state"] != 0)
    pair = pd.Series(np.where(agree, zs["state"], 0), index=c1.index).astype(int)
    # 조건서 '가짜 신호 거르기'(10-06 호연 P3, 막힌 작업 31): Stochastic 이나 StochRSI 가 80 이상에서 꺾여 내려오는 중이면
    # 1시간 조건을 Long 으로 보지 않는다(보류). 지금 규칙은 대부분 이미 거르지만, Stochastic 의 '이번 봉 상향 교차' 예외로
    # %K 가 80 이상에서 내려오는데도 Long 이 되는 경우가 남아 따로 막는다. 조건서는 Long 쪽만 말해 Short 쪽은 두지 않는다.
    ff = p.get("fake_filter")
    blocked = pd.Series(False, index=c1.index)
    if ff:
        up = ff.get("upper", 80)
        falling = lambda k: (k.shift(1) >= up) & (k < k.shift(1) - KD_EPS)
        blocked = (pair == 1) & (falling(s["k"]) | falling(r["k"]))
        pair[blocked] = 0
    return pd.DataFrame({
        "sto_k": s["k"], "sto_d": s["d"], "sto_state": zs["state"], "sto_last_event": zs["last_event"],
        "srsi_k": r["k"], "srsi_d": r["d"], "srsi_state": zr["state"], "srsi_last_event": zr["last_event"],
        "sto_event": zs["event"], "srsi_event": zr["event"],  # 그래프의 교차 표시용(판정과 같은 사건)
        "pair_dir": pair, "pair_blocked": blocked.astype(int),
    })


def vpci_frame(c15: pd.DataFrame, p: dict, period_ms: int | None = None) -> pd.DataFrame:
    v = ind.vpci(c15["close"], c15["volume"], p["short"], p["long"], p["signal"], p.get("signal_ma", "vwma"))
    vp, vs = v["vpci"], v["vpcis"]
    if p["cross_target"] == "signal":
        d = _sign(vp - vs)
        d[vp.isna() | vs.isna()] = 0
        last = _last_change_time(d)
    elif p["cross_target"] == "zero":
        d = _sign(vp)
        d[vp.isna()] = 0
        last = _last_change_time(d)
    elif p["cross_target"] == "zero_or_signal":
        # 정미님 조건서(10-03): 0선 돌파 또는 시그널선 교차가 나면 그 방향. 다음 반대 사건까지 유지(유효 기간은 확인 대기).
        # 같은 봉에 반대 방향 사건이 함께 나면(예: 시그널선 위로, 0선 아래로) 사건으로 보지 않는다.
        v1, s1 = vp.shift(1), vs.shift(1)
        up = ((v1 <= 0) & (vp > 0)) | ((v1 <= s1) & (vp > vs))
        dn = ((v1 >= 0) & (vp < 0)) | ((v1 >= s1) & (vp < vs))
        ev = pd.Series(up.astype(int) - dn.astype(int), index=vp.index)
        brk = (bar_breaks(vp.index, period_ms) if period_ms else pd.Series(False, index=vp.index))
        invalid = vp.isna() | vs.isna() | v1.isna() | s1.isna() | brk
        ev[invalid] = 0
        d, last = _hold_events(ev, vp.isna() | vs.isna(), brk)
    else:
        raise ValueError(f"cross_target 값 오류: {p['cross_target']}")
    return pd.DataFrame({"vpci": vp, "vpcis": vs, "vpci_dir": d, "vpci_last_cross": last})


def strong_sequence(macd_dir: pd.Series, pair_dir: pd.Series, vpci_dir: pd.Series, vpci_last: pd.Series) -> pd.Series:
    """조건서 운영 팁(10-06 호연 P3, 막힌 작업 32): 4시간·1시간이 같은 방향으로 정렬된 '뒤에' 15분 VPCI 가 그 방향으로 돈 때만
    확실한 신호. 15분봉 마감 시각 기준. 반환: +1/−1/0 (그 15분 시점의 확실한 신호 방향).
    - 4시간·1시간 방향은 그 시각까지 닫힌 마지막 봉의 값(앞 값 유지).
    - 정렬(두 단계가 같은 방향)이 시작된 시각 S 보다 VPCI 의 마지막 사건(0선·시그널선 교차)이 같거나 늦어야 한다.
    - 정렬이 깨졌다가 다시 맞춰지면 S 가 새로 정해지므로 VPCI 가 다시 돌아야 한다."""
    idx = vpci_dir.index
    md = macd_dir.reindex(idx, method="ffill").fillna(0)
    pdr = pair_dir.reindex(idx, method="ffill").fillna(0)
    aligned = pd.Series(np.where((md == pdr) & (md != 0), md, 0), index=idx)
    run = (aligned != aligned.shift()).cumsum()
    start = pd.Series(idx.values, index=idx).groupby(run).transform("first")
    ok = (aligned != 0) & (vpci_dir == aligned) & (vpci_last.reindex(idx) >= start)
    return pd.Series(np.where(ok, aligned, 0), index=idx).astype(int)
