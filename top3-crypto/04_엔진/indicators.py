"""기술 지표 계산 (pandas만 사용). 기획서 ver3 AI학습용 §1-3.

모든 함수는 인과적이다: t 시점 값은 t 이하의 데이터만 쓴다(미래 정보 없음).
분모가 0이면 NaN 을 돌려주고, 판정 단계에서 방향 0(없음)으로 처리한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD선 = EMA(fast) − EMA(slow), 시그널 = MACD선의 EMA(signal)."""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k: int = 14, smooth_k: int = 3, d: int = 3) -> pd.DataFrame:
    """Full Stochastic. raw = 100·(C − 최저저가k)/(최고고가k − 최저저가k), %K = SMA(raw, smooth_k), %D = SMA(%K, d)."""
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    rng = (hh - ll).replace(0, np.nan)
    raw = 100 * (close - ll) / rng
    kk = sma(raw, smooth_k)
    return pd.DataFrame({"k": kk, "d": sma(kk, d)})


def _wilder_avg(x: pd.Series, n: int) -> pd.Series:
    """Wilder 평균: 첫 값 = 처음 n개 변화의 단순 평균, 그 뒤 avg = (이전·(n−1) + 이번)/n (= alpha 1/n 지수평활).
    10-04 GPT-6.1 Sol 지적: 예전에는 첫 변화 하나로 시작해 시작 구간 RSI가 표준(StockCharts)과 최대 22포인트 달랐다."""
    valid = x.notna()
    if valid.sum() < n:
        return pd.Series(np.nan, index=x.index)
    seed_pos = int(np.flatnonzero(valid.to_numpy())[n - 1])
    first = int(np.flatnonzero(valid.to_numpy())[0])
    y = x.copy().astype(float)
    y.iloc[:seed_pos] = np.nan
    y.iloc[seed_pos] = x.iloc[first:seed_pos + 1].mean()
    return y.ewm(alpha=1 / n, adjust=False).mean()


def rsi_wilder(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder RSI. 상승·하락 평균은 처음 n개 단순 평균으로 시작해 alpha=1/n 지수평활(_wilder_avg)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = _wilder_avg(gain, n)
    al = _wilder_avg(loss, n)
    rs = ag / al.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    out = out.where(~((al == 0) & (ag > 0)), 100.0)  # 하락 없이 상승만 → 100
    return out


def stoch_rsi(close: pd.Series, rsi_n: int = 14, stoch_n: int = 14, k: int = 3, d: int = 3) -> pd.DataFrame:
    """StochRSI(0~100 으로 저장). raw = 100·(RSI − 최저RSI)/(최고RSI − 최저RSI), K = SMA(raw,k), D = SMA(K,d)."""
    r = rsi_wilder(close, rsi_n)
    lo = r.rolling(stoch_n, min_periods=stoch_n).min()
    hi = r.rolling(stoch_n, min_periods=stoch_n).max()
    raw = 100 * (r - lo) / (hi - lo).replace(0, np.nan)
    kk = sma(raw, k)
    return pd.DataFrame({"k": kk, "d": sma(kk, d)})


def vwma(close: pd.Series, volume: pd.Series, n: int) -> pd.Series:
    num = (close * volume).rolling(n, min_periods=n).sum()
    den = volume.rolling(n, min_periods=n).sum()
    return num / den.replace(0, np.nan)


def vpci(close: pd.Series, volume: pd.Series, short: int = 5, long: int = 20, signal: int = 20,
         signal_ma: str = "vwma") -> pd.DataFrame:
    """VPCI (Buff Dormeier, 2007 다우상 논문 "Price And Volume: Digging Deeper"의 식):
    VPC = VWMA(long) − SMA(long), VPR = VWMA(short)/SMA(short), VM = SMA(V, short)/SMA(V, long),
    VPCI = VPC × VPR × VM. 신호선 VPCIS:
    - signal_ma="vwma": Σ_signal(VPCI·V)/Σ_signal V (거래량 가중 평균, 원저)
    - signal_ma="sma": VPCI 의 단순 이동평균(정미님 조건서 10-03 "자체 시그널 선(SMA)")
    """
    vpc = vwma(close, volume, long) - sma(close, long)
    vpr = vwma(close, volume, short) / sma(close, short).replace(0, np.nan)
    vm = sma(volume, short) / sma(volume, long).replace(0, np.nan)
    v = vpc * vpr * vm
    if signal_ma == "sma":
        vs = sma(v, signal)
    elif signal_ma == "vwma":
        vs = (v * volume).rolling(signal, min_periods=signal).sum() / volume.rolling(signal, min_periods=signal).sum().replace(0, np.nan)
    else:
        raise ValueError(f"signal_ma 값 오류: {signal_ma}")
    return pd.DataFrame({"vpci": v, "vpcis": vs})
