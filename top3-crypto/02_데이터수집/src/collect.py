"""Top3 데이터 수집기 — 30일 창 시계열 적립 + 펀딩비 증분 수집.

왜 필요한가
-----------
Binance `futures/data/*` 계열은 **과거 약 30일치만** 반환한다
(2026-09-22 실측: 4h 186건 ≈ 31일. startTime을 30일보다 과거로 주면 -1130 invalid).
따라서 오늘부터 적립하지 않으면 3개월 뒤에도 30일치밖에 못 쓴다.
백테스트 구간은 첫 실행일부터 자라기 시작한다.

Bybit open-interest는 다르다 (2026-09-22 저녁 재실측): '요청당 200건'이 제한일 뿐이고
endTime을 뒤로 밀면 과거 전체를 페이지 단위로 받을 수 있다. 그래서 1회 백필 + 이후 증분이면 된다.

반대로 펀딩비(`fapi/v1/fundingRate`)는 전체 이력이 열려 있다
(BTCUSDT 2019-09-10, ETHUSDT 2019-11-27, XRPUSDT 2020-01-06부터).
이쪽은 한 번 백필하고 이후 증분만 받으면 된다.

설계
----
- 매 실행마다 **가용한 전체 창**을 받아 멱등 upsert 한다.
  → 몇 번 걸러도 공백이 30일 미만이면 자동 복구된다. 스케줄 정확도가 중요하지 않다.
- API 키 불필요. 전부 공개 엔드포인트.
- 표준 라이브러리만 사용. 의존성 설치 없음.

2026-10-03 변경 (2차 회의 D1·D2)
--------------------------------
- 확신도 재료는 바이낸스 현물 캔들(15m·1h·4h)뿐. 15분마다 실행(launchd, 봉 마감 1분 뒤).
- 선물 30일 창·바이비트 OI·펀딩비·업비트·코인베이스 수집은 conf `enabled`에서 끔. 코드와 쌓인 데이터는 남김.
- 공포탐욕지수는 그날(UTC) 값이 이미 있으면 건너뜀(하루 1회 UTC 00:00 갱신).
- 뉴스 헤드라인(news.py): 10-03부터 공식 API(네이버 뉴스 검색·GDELT)만 15분마다. 매체 RSS는 꺼 둠, `--news-once`로 비교용 1회 수집.

사용
----
    python3 src/collect.py              # 정기 수집 (conf enabled 에 켜진 것만)
    python3 src/collect.py --funding-backfill   # 펀딩비 전체 이력 1회 백필
    python3 src/collect.py --bybit-oi-backfill  # Bybit OI 전체 이력 1회 백필
    python3 src/collect.py --candles-backfill   # 캔들(바이낸스·업비트·코인베이스) 전체 이력 1회 백필
    python3 src/collect.py --news-once  # 꺼 둔 매체 RSS까지 모든 뉴스 출처를 1회 수집 (소스 비교용)
    python3 src/collect.py --status     # 현재 적재 현황만 출력
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from store import Store, ms_to_utc, now_ms  # noqa: E402
from news import collect_news  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONF_PATH = ROOT / "conf" / "collectors.json"
DB_PATH = ROOT / "data" / "raw" / "market.db"

BINANCE_DATA = "https://fapi.binance.com/futures/data"
BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
BYBIT = "https://api.bybit.com/v5/market"
BINANCE_SPOT = "https://api.binance.com/api/v3"
UPBIT = "https://api.upbit.com/v1"
COINBASE_V3 = "https://api.coinbase.com/api/v3/brokerage/market"
PERIOD_MS = {"15m": 15 * 60 * 1000, "1h": 3600 * 1000, "4h": 4 * 3600 * 1000, "1d": 24 * 3600 * 1000}

UA = {"User-Agent": "topo3-collector/1.0 (research)"}


# --------------------------------------------------------------------------- http

def http_json(url: str, timeout: int, retries: int):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            last = exc
            # 429/418은 좀 더 길게 쉰다
            code = getattr(exc, "code", None)
            time.sleep(5.0 if code in (429, 418) else 1.5 * (attempt + 1))
    raise RuntimeError(f"GET 실패 ({retries}회): {url} :: {last}")


# ------------------------------------------------------------------- collectors

def collect_binance_window(conf, store, log):
    """Binance futures/data 계열 5종 × 심볼 × 주기. 약 30일 창 전체를 매번 upsert."""
    ok = failed = new = 0
    for metric_group, spec in conf["binance_window_endpoints"].items():
        if metric_group.startswith("_"):
            continue
        for symbol in conf["symbols"]:
            for period in conf["periods"]:
                url = (f"{BINANCE_DATA}/{spec['path']}"
                       f"?symbol={symbol}&period={period}&limit=500")
                try:
                    data = http_json(url, conf["timeout_sec"], conf["retries"])
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log(f"  [FAIL] {metric_group} {symbol} {period}: {exc}")
                    continue

                rows = []
                for item in data:
                    ts = int(item["timestamp"])
                    for metric_name, src_field in spec["fields"].items():
                        raw = item.get(src_field)
                        if raw in (None, ""):
                            continue
                        rows.append(("binance", symbol, metric_name, period, ts, raw))
                added = store.upsert(rows)
                new += added
                log(f"  binance {metric_group:<28} {symbol:<8} {period:<3} "
                    f"수신 {len(data):>4}건 신규 {added:>5}행")
                time.sleep(conf["request_sleep_sec"])
    return ok, failed, new


def collect_bybit_oi(conf, store, log, full_backfill: bool = False):
    """Bybit open-interest. endTime을 뒤로 밀며 200건씩 페이지를 넘긴다.

    2026-09-22 실측: Bybit는 '요청당 200건'이 제한일 뿐 30일 상한이 없다
    (endTime=90일 전 → 그 이전 33일치가 정상 반환, BTCUSDT 4h).
    - 정기 실행: 이미 저장된 구간에 닿을 때까지만(페이지 신규 0행) 뒤로 간다.
      → 공백이 8일(1h 창)보다 커도 자동 복구된다. 안전상 최대 30페이지.
    - --bybit-oi-backfill: 빈 페이지가 나올 때까지 끝까지 뒤로 간다 (1회면 충분).
    """
    ok = failed = new = 0
    cat = conf["bybit"]["category"]
    max_pages = int(conf["bybit"].get("backfill_max_pages", 1000)) if full_backfill else 30
    for symbol in conf["symbols"]:
        for period in conf["periods"]:
            interval = conf["bybit"]["interval_map"].get(period)
            if not interval:
                continue
            end_ms = None
            oldest = None
            pages = total = series_new = 0
            while pages < max_pages:
                url = (f"{BYBIT}/open-interest?category={cat}"
                       f"&symbol={symbol}&intervalTime={interval}&limit=200")
                if end_ms is not None:
                    url += f"&endTime={end_ms}"
                try:
                    payload = http_json(url, conf["timeout_sec"], conf["retries"])
                    if payload.get("retCode") != 0:
                        raise RuntimeError(payload.get("retMsg"))
                    items = payload["result"]["list"]
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log(f"  [FAIL] bybit oi {symbol} {period} page {pages + 1}: {exc}")
                    break
                if not items:
                    break
                rows = [("bybit", symbol, "oi_base", period, int(it["timestamp"]), it["openInterest"])
                        for it in items if it.get("openInterest") not in (None, "")]
                added = store.upsert(rows)
                series_new += added
                total += len(items)
                pages += 1
                page_oldest = min(int(it["timestamp"]) for it in items)
                if oldest is not None and page_oldest >= oldest:
                    break  # 더 과거로 진행되지 않음
                oldest = page_oldest
                if not full_backfill and added == 0:
                    break  # 이미 저장된 구간에 닿음
                end_ms = oldest - 1
                time.sleep(conf["request_sleep_sec"])
            new += series_new
            log(f"  bybit   {'open_interest':<28} {symbol:<8} {period:<3} "
                f"수신 {total:>5}건 신규 {series_new:>5}행 ({pages}페이지, 최고 "
                f"{ms_to_utc(oldest) if oldest else '-'})")
    return ok, failed, new


def collect_funding(conf, store, log, full_backfill: bool = False):
    """펀딩비. period는 'event'로 저장(8시간 주기지만 거래소가 바꿀 수 있어 고정하지 않음)."""
    ok = failed = new = 0
    page_limit = conf["funding"]["page_limit"]
    for symbol in conf["symbols"]:
        if full_backfill:
            cursor = conf["funding"]["binance_first_ms"]
        else:
            last = store.max_ts("binance", symbol, "funding_rate", "event")
            # 증분: 마지막 관측 직후부터. 없으면 최근 page_limit건만.
            cursor = (last + 1) if last else None

        total_sym = 0
        pages = 0
        while True:
            if cursor is None:
                url = f"{BINANCE_FAPI}/fundingRate?symbol={symbol}&limit={page_limit}"
            else:
                url = (f"{BINANCE_FAPI}/fundingRate?symbol={symbol}"
                       f"&startTime={cursor}&limit={page_limit}")
            try:
                data = http_json(url, conf["timeout_sec"], conf["retries"])
                ok += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log(f"  [FAIL] funding {symbol}: {exc}")
                break

            if not data:
                break

            rows = [("binance", symbol, "funding_rate", "event",
                     int(d["fundingTime"]), d["fundingRate"])
                    for d in data if d.get("fundingRate") not in (None, "")]
            new += store.upsert(rows)
            total_sym += len(data)
            pages += 1

            if cursor is None or len(data) < page_limit:
                break
            cursor = int(data[-1]["fundingTime"]) + 1
            time.sleep(conf["request_sleep_sec"])
            if pages > 400:  # 안전장치
                log(f"  [WARN] funding {symbol}: 페이지 상한 도달")
                break

        log(f"  binance {'funding_rate':<28} {symbol:<8} {'evt':<3} "
            f"수신 {total_sym:>4}건 ({pages}페이지)")
    return ok, failed, new


# --------------------------------------------------------------- candles / F&G
# 공통 원칙: 아직 끝나지 않은(진행 중) 봉은 저장하지 않는다. 그래야 INSERT OR IGNORE 만으로
# 멱등이 되고, 나중에 값이 바뀌는 행이 없다.

def collect_binance_klines(conf, store, log, full_backfill: bool = False):
    """Binance 현물 캔들. startTime 을 앞으로 밀며 1000건씩. 2017-08-17 부터 전체 무료."""
    c = conf["candles"]["binance"]
    ok = failed = new = 0
    now = now_ms()
    for symbol in c["symbols"]:
        for period in c["periods"]:
            last = None if full_backfill else store.max_ts_candle("binance", symbol, period)
            cursor = (last + 1) if last else int(c["first_ms"])
            total = pages = series_new = 0
            while pages < 400:
                url = (f"{BINANCE_SPOT}/klines?symbol={symbol}&interval={period}"
                       f"&limit={c['page_limit']}&startTime={cursor}")
                try:
                    data = http_json(url, conf["timeout_sec"], conf["retries"])
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log(f"  [FAIL] binance klines {symbol} {period}: {exc}")
                    break
                if not data:
                    break
                rows = [("binance", symbol, period, int(k[0]), k[1], k[2], k[3], k[4], k[5], k[7])
                        for k in data if int(k[6]) < now]  # closeTime < now → 완성 봉만
                series_new += store.upsert_candles(rows)
                total += len(data)
                pages += 1
                if len(data) < c["page_limit"]:
                    break
                cursor = int(data[-1][0]) + 1
                time.sleep(conf["request_sleep_sec"])
            new += series_new
            log(f"  binance {'klines':<28} {symbol:<8} {period:<3} "
                f"수신 {total:>5}건 신규 {series_new:>5}행 ({pages}페이지)")
    return ok, failed, new


def _upbit_ts(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
               .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def collect_upbit_candles(conf, store, log, full_backfill: bool = False):
    """Upbit 원화 캔들. `to`(exclusive) 를 뒤로 밀며 200건씩. 2017-09-25 부터 전체 무료.
    정기 실행은 저장된 구간에 닿으면(페이지 신규 0행) 멈춘다."""
    c = conf["candles"]["upbit"]
    ok = failed = new = 0
    now = now_ms()
    sleep = c.get("request_sleep_sec", 0.15)
    for market in c["markets"]:
        for period, path in c["periods"].items():
            to = None
            oldest = None
            pages = total = series_new = 0
            while pages < c.get("max_pages", 400):
                url = f"{UPBIT}/candles/{path}?market={market}&count={c['count']}"
                if to:
                    url += f"&to={to}"
                try:
                    data = http_json(url, conf["timeout_sec"], conf["retries"])
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    log(f"  [FAIL] upbit {market} {period} page {pages + 1}: {exc}")
                    break
                if not data:
                    break
                rows = []
                for x in data:
                    ts = _upbit_ts(x["candle_date_time_utc"])
                    if ts + PERIOD_MS[period] > now:
                        continue  # 미완성 봉
                    rows.append(("upbit", market, period, ts, x["opening_price"], x["high_price"],
                                 x["low_price"], x["trade_price"], x["candle_acc_trade_volume"],
                                 x["candle_acc_trade_price"]))
                added = store.upsert_candles(rows)
                series_new += added
                total += len(data)
                pages += 1
                page_oldest = min(_upbit_ts(x["candle_date_time_utc"]) for x in data)
                if oldest is not None and page_oldest >= oldest:
                    break
                oldest = page_oldest
                if not full_backfill and added == 0:
                    break  # 이미 저장된 구간
                to = data[-1]["candle_date_time_utc"] + "Z"
                time.sleep(sleep)
            new += series_new
            log(f"  upbit   {'candles':<28} {market:<8} {period:<3} "
                f"수신 {total:>5}건 신규 {series_new:>5}행 ({pages}페이지, 최고 "
                f"{ms_to_utc(oldest) if oldest else '-'})")
    return ok, failed, new


def collect_coinbase_candles(conf, store, log, full_backfill: bool = False):
    """Coinbase 공개 v3 캔들(코인베이스 프리미엄 계산용). start/end(초) 창을 앞으로 밀며 최대 300건씩.
    구 exchange API 는 4h 를 지원하지 않아(Unsupported granularity) v3 를 쓴다. 거래대금 필드는 없음(NULL)."""
    c = conf["candles"]["coinbase"]
    ok = failed = new = 0
    now_s = now_ms() // 1000
    gran = {"4h": ("FOUR_HOUR", 14400), "1d": ("ONE_DAY", 86400)}
    sleep = c.get("request_sleep_sec", 0.15)
    for product, first_iso in c["products"].items():
        for period in c["periods"]:
            gname, gsec = gran[period]
            last = None if full_backfill else store.max_ts_candle("coinbase", product, period)
            if last:
                start = last // 1000 + gsec
            else:
                start = int(dt.datetime.fromisoformat(first_iso.replace("Z", "+00:00")).timestamp())
            window = gsec * int(c.get("max_candles", 300))
            pages = total = series_new = fails = 0
            while start < now_s and pages < 2000:
                end = min(start + window, now_s)
                url = f"{COINBASE_V3}/products/{product}/candles?start={start}&end={end}&granularity={gname}"
                try:
                    payload = http_json(url, conf["timeout_sec"], 1)
                    ok += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    fails += 1
                    if fails <= 3:
                        log(f"  [WARN] coinbase {product} {period} {ms_to_utc(start * 1000)}: {exc}")
                    start = end  # 상장 전·거래 중단 구간은 건너뛰고 계속
                    continue
                items = payload.get("candles", []) if isinstance(payload, dict) else []
                rows = [("coinbase", product, period, int(x["start"]) * 1000, x["open"], x["high"],
                         x["low"], x["close"], x["volume"], None)
                        for x in items if int(x["start"]) + gsec <= now_s]
                series_new += store.upsert_candles(rows)
                total += len(items)
                pages += 1
                start = end
                time.sleep(sleep)
            new += series_new
            log(f"  coinbase{'candles':<28} {product:<8} {period:<3} "
                f"수신 {total:>5}건 신규 {series_new:>5}행 ({pages}페이지, 건너뜀 {fails})")
    return ok, failed, new


def collect_candles_all(conf, store, log, full_backfill: bool = False):
    ok = failed = new = 0
    on = conf.get("enabled", {})
    for key, fn in (("candles_binance", collect_binance_klines),
                    ("candles_upbit", collect_upbit_candles),
                    ("candles_coinbase", collect_coinbase_candles)):
        if not (on.get(key, True) or full_backfill):
            continue
        try:
            a, b, c_ = fn(conf, store, log, full_backfill=full_backfill)
        except Exception as exc:  # noqa: BLE001
            log(f"  [ERROR] {fn.__name__}: {exc}")
            a, b, c_ = 0, 1, 0
        ok += a
        failed += b
        new += c_
    return ok, failed, new


def collect_fng(conf, store, log, full_backfill: bool = False):
    """공포탐욕지수(alternative.me). 하루 1회(UTC 00:00) 갱신된다.

    - DB가 비었거나 full_backfill 이면 limit=0(2018-02-01 부터 전량).
    - 오늘(UTC) 값이 이미 있으면 호출하지 않는다. 아니면 최근 10건만 받아 빈 날을 메운다.
    """
    fconf = conf["fear_greed"]
    last = store.max_ts("alternative.me", "CRYPTO", "fear_greed", "1d")
    today0 = int(dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                 .timestamp() * 1000)
    if last and last >= today0 and not full_backfill and store.kv_get("fng_latest"):
        return 0, 0, 0
    url = fconf["url"] if (full_backfill or not last) else fconf.get("url_incremental", fconf["url"])
    try:
        payload = http_json(url, conf["timeout_sec"], conf["retries"])
    except Exception as exc:  # noqa: BLE001
        log(f"  [FAIL] fear_greed: {exc}")
        return 0, 1, 0
    rows = [("alternative.me", "CRYPTO", "fear_greed", "1d", int(d["timestamp"]) * 1000, d["value"])
            for d in payload.get("data", []) if d.get("value") not in (None, "")]
    added = store.upsert(rows)
    data = payload.get("data") or []
    if data:  # 최신 값의 공식 분류(예: Greed)를 화면 표시용으로 보관
        latest = max(data, key=lambda d: int(d["timestamp"]))
        store.kv_set("fng_latest", json.dumps({"value": int(latest["value"]),
                                               "classification": latest.get("value_classification"),
                                               "timestamp": int(latest["timestamp"]) * 1000}))
        # 날짜별 공식 분류(최근 14일). 4시간 분석은 '전날 값'을 쓰므로 그날의 분류를 찾을 수 있게 한다
        try:
            recent = json.loads(store.kv_get("fng_class_recent") or "{}")
        except ValueError:
            recent = {}
        for d in data:
            if d.get("value_classification"):
                recent[str(int(d["timestamp"]) * 1000)] = d["value_classification"]
        recent = dict(sorted(recent.items(), key=lambda kv: int(kv[0]))[-14:])
        store.kv_set("fng_class_recent", json.dumps(recent))
    log(f"  alt.me  {'fear_greed':<28} {'CRYPTO':<8} {'1d':<3} 수신 {len(rows):>5}건 신규 {added:>5}행")
    return 1, 0, added


# ------------------------------------------------------------------------ status

def print_status(store):
    nrows = store.coverage_news()
    rows = store.coverage()
    if not rows:
        print("적재된 데이터가 없습니다.")
    else:
        print(f"{'source':<8} {'symbol':<9} {'metric':<20} {'per':<5} {'건수':>7}  범위")
        print("-" * 96)
        for source, symbol, metric, period, cnt, mn, mx in rows:
            span_days = (mx - mn) / 86400000 if mn and mx else 0
            print(f"{source:<8} {symbol:<9} {metric:<20} {period:<5} {cnt:>7}  "
                  f"{ms_to_utc(mn)} ~ {ms_to_utc(mx)}  ({span_days:.1f}일)")
    crows = store.coverage_candles()
    if crows:
        print()
        print(f"{'source':<8} {'symbol':<9} {'candles':<20} {'per':<5} {'건수':>7}  범위")
        print("-" * 96)
        for source, symbol, period, cnt, mn, mx in crows:
            span_days = (mx - mn) / 86400000 if mn and mx else 0
            print(f"{source:<8} {symbol:<9} {'ohlcv':<20} {period:<5} {cnt:>7}  "
                  f"{ms_to_utc(mn)} ~ {ms_to_utc(mx)}  ({span_days:.1f}일)")
    if nrows:
        print()
        print(f"{'news':<37} {'건수':>7}  {'코인 관련':>9}  발행 범위")
        print("-" * 96)
        for source, cnt, matched, mn, mx in nrows:
            rng = f"{ms_to_utc(mn)} ~ {ms_to_utc(mx)}" if mn and mx else "-"
            print(f"{source:<37} {cnt:>7}  {int(matched or 0):>9}  {rng}")


# -------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Top3 시장 데이터 수집기")
    ap.add_argument("--funding-backfill", action="store_true",
                    help="펀딩비 전체 이력을 처음부터 다시 받습니다 (1회면 충분)")
    ap.add_argument("--bybit-oi-backfill", action="store_true",
                    help="Bybit open-interest 전체 이력을 끝까지 페이지 넘겨 받습니다 (1회면 충분)")
    ap.add_argument("--candles-backfill", action="store_true",
                    help="캔들(바이낸스·업비트·코인베이스) 전체 이력을 받습니다 (1회면 충분, 약 5분)")
    ap.add_argument("--news-once", action="store_true",
                    help="뉴스 피드를 설정에서 꺼져 있어도 1회 수집합니다 (소스 비교용)")
    ap.add_argument("--status", action="store_true", help="적재 현황만 출력하고 종료")
    args = ap.parse_args()

    conf = json.loads(CONF_PATH.read_text(encoding="utf-8"))
    store = Store(DB_PATH)

    if args.status:
        print_status(store)
        store.close()
        return 0

    started = now_ms()
    lines = []

    def log(msg: str):
        print(msg, flush=True)
        lines.append(msg)

    run_id = store.start_run()
    log(f"=== 수집 시작 {ms_to_utc(started)} (run_id={run_id}) ===")

    ok = failed = new = 0
    on = conf.get("enabled", {})
    # (설정 키, 함수, 인자). 설정에서 꺼져 있어도 해당 백필 옵션을 주면 실행한다.
    jobs = (
        ("binance_window", collect_binance_window, {}),
        ("bybit_oi", collect_bybit_oi, {"full_backfill": args.bybit_oi_backfill}),
        ("funding", collect_funding, {"full_backfill": args.funding_backfill}),
        ("candles", collect_candles_all, {"full_backfill": args.candles_backfill}),
        ("fear_greed", collect_fng, {"full_backfill": args.candles_backfill}),
        ("news", collect_news, {"force": args.news_once}),
    )
    for key, fn, kwargs in jobs:
        forced = any(kwargs.values())
        if key != "candles" and not (on.get(key, True) or forced):
            continue
        try:
            a, b, c = fn(conf, store, log, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log(f"  [ERROR] {fn.__name__}: {exc}")
            a, b, c = 0, 1, 0
        ok += a
        failed += b
        new += c

    note = f"ok={ok} failed={failed} new_rows={new}"
    store.finish_run(run_id, ok, failed, new, note)
    log(f"=== 완료: 호출 성공 {ok} / 실패 {failed} / 신규 {new}행 ===")

    print()
    print_status(store)
    store.close()

    # 전부 실패했을 때만 비정상 종료 (스케줄러 알림용)
    return 1 if ok == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
