"""가격 소스 어댑터. 모두 읽기 전용이며 주문 기능은 없다.

- FixedPriceSource: 시험용 고정값
- UpbitPriceSource: 업비트 공개 시세(키 없음, urllib). 실패 시 PriceSourceError
- Top3DbPriceSource: Top3 Crypto 수집 DB(market.db)의 candles 표를 읽기 전용으로 연다.
  경로는 환경변수 ALFREDO_TOP3_DB. 없으면 비활성(available()=False).
"""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request

TOP3_DB_ENV = "ALFREDO_TOP3_DB"


class PriceSourceError(Exception):
    pass


class PriceSource:
    name = "base"

    def available(self) -> bool:
        return True

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        """symbol -> 가격. 못 구한 심볼은 빠진다. 소스 자체 장애는 PriceSourceError."""
        raise NotImplementedError

    def get_price(self, symbol: str) -> float | None:
        return self.get_prices([symbol]).get(symbol)


class FixedPriceSource(PriceSource):
    name = "fixed"

    def __init__(self, prices: dict[str, float]):
        self.prices = {k: float(v) for k, v in prices.items()}

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        return {s: self.prices[s] for s in symbols if s in self.prices}


class UpbitPriceSource(PriceSource):
    """KRW 마켓 현재가. 심볼 'BTC' -> 마켓 'KRW-BTC'."""
    name = "upbit"
    URL = "https://api.upbit.com/v1/ticker"

    def __init__(self, quote: str = "KRW", timeout: float = 5.0):
        self.quote = quote
        self.timeout = timeout

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        markets = ",".join(f"{self.quote}-{s}" for s in symbols)
        url = f"{self.URL}?{urllib.parse.urlencode({'markets': markets})}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "alfredo-sim/0"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise PriceSourceError(f"업비트 시세 조회 실패: {e}") from e
        out = {}
        for row in data:
            market = row.get("market", "")
            if market.startswith(self.quote + "-") and "trade_price" in row:
                out[market.split("-", 1)[1]] = float(row["trade_price"])
        return out


class Top3DbPriceSource(PriceSource):
    """Top3 수집 DB의 바이낸스 캔들 종가(USDT). 환경변수가 없으면 비활성.

    읽기 전용(mode=ro)으로만 연다. 심볼 'BTC' -> 'BTCUSDT'.
    주의: 통화가 USDT라 KRW 장부와 섞어 쓰면 안 된다(환산은 호출자 몫).
    """
    name = "top3"

    def __init__(self, path: str | None = None, period: str = "4h", quote: str = "USDT"):
        self.path = path if path is not None else os.environ.get(TOP3_DB_ENV)
        self.period = period
        self.quote = quote

    def available(self) -> bool:
        return bool(self.path) and os.path.exists(self.path)

    def get_prices(self, symbols: list[str]) -> dict[str, float]:
        if not self.available():
            raise PriceSourceError(f"Top3 DB 비활성: 환경변수 {TOP3_DB_ENV}가 없거나 파일이 없다")
        uri = "file:" + urllib.parse.quote(os.path.abspath(self.path)) + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as e:
            raise PriceSourceError(f"Top3 DB 열기 실패: {e}") from e
        out = {}
        try:
            for s in symbols:
                row = conn.execute(
                    "SELECT close FROM candles WHERE source='binance' AND symbol=? AND period=? "
                    "AND close>0 ORDER BY ts DESC LIMIT 1", (f"{s}{self.quote}", self.period)).fetchone()
                if row:
                    out[s] = float(row[0])
        except sqlite3.Error as e:
            raise PriceSourceError(f"Top3 DB 조회 실패: {e}") from e
        finally:
            conn.close()
        return out


def make_source(name: str, fixed: dict[str, float] | None = None) -> PriceSource:
    if name == "fixed":
        return FixedPriceSource(fixed or {})
    if name == "upbit":
        return UpbitPriceSource()
    if name == "top3":
        return Top3DbPriceSource()
    raise PriceSourceError(f"모르는 가격 소스: {name}")
