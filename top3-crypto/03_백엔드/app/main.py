"""Top 3 Crypto 백엔드 — 읽기 전용 API (FastAPI) + 보드 화면(정적 파일).

2026-10-03 (기획서 ver3): /api/board·/api/analyses·/api/replay·/api/engine 은 app/board.py.
보드 화면은 05_프론트/app 을 / 에서 내려준다 → http://127.0.0.1:8765/
아래 1주차 엔드포인트(series·snapshot 등)는 그대로 두되, 선물·업비트·코인베이스 값은 10-03부터 갱신되지 않는다.

역할
----
- 수집기가 채우는 SQLite(`02_데이터수집/data/raw/market.db`)를 대시보드·챗봇·디스코드 봇이 읽을 수 있게 HTTP로 연다.
- 이 서버는 DB를 **읽기만** 한다(`mode=ro`). 쓰기는 수집기·엔진이 담당한다.
- 1주차 범위: 상태·시계열·캔들·스냅샷. 리포트/시그널/포워드 기록 엔드포인트는 테이블만 있고 비어 있다.

실행
----
    cd 03_백엔드
    ./.venv/bin/uvicorn app.main:app --reload --port 8765
    TOP3_API_DOCS=1 ./.venv/bin/uvicorn app.main:app --port 8765   # 자동 생성 API 문서(/docs)를 켜서 볼 때

환경변수
--------
    TOPO3_DB   SQLite 경로 (기본: ../02_데이터수집/data/raw/market.db)
"""
from __future__ import annotations

import os
import sqlite3
import datetime as dt
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import board
from app.request_guard import RequestGuardMiddleware

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("TOPO3_DB", ROOT.parent / "02_데이터수집" / "data" / "raw" / "market.db"))

FRONT = ROOT.parent / "05_프론트" / "app"

# 자동 생성 API 문서(/docs·/redoc·/openapi.json)는 기본으로 끈다. 보드가 Funnel로 바깥에 열려 있어 쓰지 않는 문은 닫아 둠(10-03).
# 개발 중에 보려면: TOP3_API_DOCS=1 ./.venv/bin/uvicorn app.main:app --port 8765
_DOCS = os.environ.get("TOP3_API_DOCS") == "1"
app = FastAPI(
    title="Top 3 Crypto API",
    version="0.3.0",
    description="Top 3 Crypto — 데이터·분석 읽기 전용 API (기획서 ver3)",
    docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])
# 공개 /api 요청 횟수 제한·AI 수집기 차단(2026-10-20, app/request_guard.py). 맥에서 직접 연 화면은 제외
app.add_middleware(RequestGuardMiddleware)


# --------------------------------------------------------------------------- db

def db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        print(f"DB 없음: {DB_PATH}")   # 경로는 서버 기록에만(공개 응답에 맥의 파일 경로를 내보내지 않음, 10-13)
        raise HTTPException(503, "DB 없음")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False, timeout=30)   # 잠금 대기 30초(엔진과 같게, 10-06)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------- routes
# 1주차 데이터 API(series·candles 등). 보드 화면은 쓰지 않고, Funnel·Vercel 로 공개되면 누구나 대량 조회를 할 수 있어
# 기본은 끈다(10-04 Claude Fable 검토). 로컬에서 쓰려면 TOP3_LEGACY_API=1 로 서버를 띄운다.
from fastapi import APIRouter  # noqa: E402
legacy = APIRouter()

@app.get("/health", tags=["meta"])
def health():
    exists = DB_PATH.exists()
    n = None
    if exists:
        conn = db()
        n = conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]
        conn.close()
    return {"ok": exists, "series_rows": n}   # DB 경로는 공개 주소에서 보이지 않게 뺌(10-04 GPT-6.1 Sol)


@legacy.get("/api/status", tags=["meta"])
def status():
    """지표·캔들별 적재 범위. 대시보드 '데이터 상태' 패널용."""
    conn = db()
    series = rows(conn, "SELECT source, symbol, metric, period, COUNT(*) AS n, MIN(ts) AS min_ts, MAX(ts) AS max_ts "
                        "FROM series GROUP BY source, symbol, metric, period ORDER BY source, metric, symbol, period")
    candles = rows(conn, "SELECT source, symbol, period, COUNT(*) AS n, MIN(ts) AS min_ts, MAX(ts) AS max_ts "
                         "FROM candles GROUP BY source, symbol, period ORDER BY source, symbol, period")
    last_run = rows(conn, "SELECT run_id, started_at, finished_at, ok_calls, failed_calls, rows_new FROM run_log "
                          "ORDER BY run_id DESC LIMIT 1")
    conn.close()
    for r in series + candles:
        r["min_at"], r["max_at"] = iso(r["min_ts"]), iso(r["max_ts"])
    return {"series": series, "candles": candles, "last_run": last_run[0] if last_run else None}


@legacy.get("/api/series", tags=["data"])
def series(
    metric: str = Query(..., description="예: oi_base, funding_rate, global_acc_long_short_ratio, fear_greed"),
    symbol: str = Query("BTCUSDT"),
    source: Optional[str] = Query(None, description="binance | bybit | alternative.me"),
    period: Optional[str] = Query(None, description="4h | 1h | 1d | event"),
    since: Optional[int] = Query(None, description="epoch ms 이후만"),
    limit: int = Query(500, ge=1, le=5000),
):
    conn = db()
    sql = "SELECT source, symbol, metric, period, ts, value FROM series WHERE metric=? AND symbol=?"
    params: list = [metric, symbol]
    if source:
        sql += " AND source=?"; params.append(source)
    if period:
        sql += " AND period=?"; params.append(period)
    if since:
        sql += " AND ts>=?"; params.append(since)
    sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
    out = rows(conn, sql, params)
    conn.close()
    out.reverse()  # 오래된 → 최신
    return {"count": len(out), "data": out}


@legacy.get("/api/candles", tags=["data"])
def candles(
    symbol: str = Query("BTCUSDT", description="binance: BTCUSDT / upbit: KRW-BTC / coinbase: BTC-USD"),
    source: str = Query("binance"),
    period: str = Query("4h"),
    since: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    conn = db()
    sql = "SELECT ts, open, high, low, close, volume, quote_volume FROM candles WHERE source=? AND symbol=? AND period=?"
    params: list = [source, symbol, period]
    if since:
        sql += " AND ts>=?"; params.append(since)
    sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
    out = rows(conn, sql, params)
    conn.close()
    out.reverse()
    return {"source": source, "symbol": symbol, "period": period, "count": len(out), "data": out}


@legacy.get("/api/snapshot", tags=["data"])
def snapshot(symbol: str = Query("BTCUSDT")):
    """대시보드 홈 상단용 '지금' 한 장. 각 값의 관측 시각(ts)을 함께 준다."""
    conn = db()

    def latest(metric, source=None, period=None, sym=symbol):
        sql = "SELECT ts, value FROM series WHERE metric=? AND symbol=?"
        params = [metric, sym]
        if source:
            sql += " AND source=?"; params.append(source)
        if period:
            sql += " AND period=?"; params.append(period)
        r = conn.execute(sql + " ORDER BY ts DESC LIMIT 1", params).fetchone()
        return {"ts": r["ts"], "at": iso(r["ts"]), "value": r["value"]} if r else None

    def latest_close(source, sym, period="4h"):
        r = conn.execute("SELECT ts, close FROM candles WHERE source=? AND symbol=? AND period=? ORDER BY ts DESC LIMIT 1",
                         (source, sym, period)).fetchone()
        return {"ts": r["ts"], "at": iso(r["ts"]), "close": r["close"]} if r else None

    base = symbol.replace("USDT", "")
    out = {
        "symbol": symbol,
        "price": {
            "binance_4h": latest_close("binance", symbol),
            "upbit_4h": latest_close("upbit", f"KRW-{base}"),
            "coinbase_4h": latest_close("coinbase", f"{base}-USD"),
        },
        "funding_rate": latest("funding_rate", "binance", "event"),
        "open_interest": {
            "binance_4h": latest("oi_base", "binance", "4h"),
            "bybit_4h": latest("oi_base", "bybit", "4h"),
        },
        "long_short_4h": {
            "global_accounts": latest("global_acc_long_short_ratio", "binance", "4h"),
            "top_accounts": latest("top_acc_long_short_ratio", "binance", "4h"),
            "top_positions": latest("top_pos_long_short_ratio", "binance", "4h"),
        },
        "taker_buy_sell_4h": latest("buy_sell_ratio", "binance", "4h"),
        "fear_greed": latest("fear_greed", "alternative.me", "1d", sym="CRYPTO"),
    }
    conn.close()
    return out


@legacy.get("/api/fng", tags=["data"])
def fng(limit: int = Query(365, ge=1, le=5000)):
    conn = db()
    out = rows(conn, "SELECT ts, value FROM series WHERE metric='fear_greed' ORDER BY ts DESC LIMIT ?", (limit,))
    conn.close()
    out.reverse()
    return {"count": len(out), "data": out}


# ---- 2~3주차에 채워질 것들. 지금은 테이블만 있고 비어 있다. ----

@legacy.get("/api/reports", tags=["week2+"])
def reports(symbol: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    conn = db()
    sql = "SELECT report_id, symbol, as_of_ts, created_at, model, prompt_version, direction, confidence, horizon_h FROM reports"
    params: list = []
    if symbol:
        sql += " WHERE symbol=?"; params.append(symbol)
    sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
    out = rows(conn, sql, params)
    conn.close()
    return {"count": len(out), "data": out}


@legacy.get("/api/signals", tags=["week2+"])
def signals(symbol: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    conn = db()
    sql = "SELECT signal_id, symbol, ts, created_at, rules_version, score, direction, report_id, sent_discord FROM signals"
    params: list = []
    if symbol:
        sql += " WHERE symbol=?"; params.append(symbol)
    sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
    out = rows(conn, sql, params)
    conn.close()
    return {"count": len(out), "data": out}


@legacy.get("/api/track", tags=["week2+"])
def track(kind: Optional[str] = Query(None, description="report | signal"), limit: int = Query(100, ge=1, le=1000)):
    """포워드 기록. 대시보드의 '존버 대비 성과' 패널이 읽는 곳."""
    conn = db()
    sql = "SELECT * FROM forward_track"
    params: list = []
    if kind:
        sql += " WHERE kind=?"; params.append(kind)
    sql += " ORDER BY entry_ts DESC LIMIT ?"; params.append(limit)
    out = rows(conn, sql, params)
    n_scored = sum(1 for r in out if r.get("scored_at"))
    conn.close()
    return {"count": len(out), "scored": n_scored, "data": out}


# ---- 기획서 ver3: 보드 API + 화면 ----
board.set_db(db)
app.include_router(board.router)
if os.environ.get("TOP3_LEGACY_API") == "1":
    app.include_router(legacy)
if FRONT.exists():
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="board")  # 라우트들 뒤에 둔다
