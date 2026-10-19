"""SQLite 저장소. 멱등 upsert 전용.

설계 원칙
- 같은 (source, symbol, metric, period, ts)는 절대 중복 저장되지 않는다.
- 수집 시각(collected_at)을 함께 남긴다. point-in-time 감사를 위해 필요하다.
- 값은 원본 문자열을 그대로 REAL로 변환해 넣고, 원본 JSON은 남기지 않는다
  (30일 창 시계열은 스키마가 안정적이라 원본 보관의 실익이 없다).
"""
from __future__ import annotations

import sqlite3
import datetime as dt
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    source       TEXT NOT NULL,   -- binance | bybit
    symbol       TEXT NOT NULL,   -- BTCUSDT ...
    metric       TEXT NOT NULL,   -- oi_base | long_short_ratio | funding_rate ...
    period       TEXT NOT NULL,   -- 4h | 1h | event(펀딩비처럼 고정 주기 아닌 것)
    ts           INTEGER NOT NULL,-- 관측 시각 (epoch ms, UTC)
    value        REAL,
    collected_at INTEGER NOT NULL,-- 우리가 실제로 받아온 시각 (epoch ms, UTC)
    PRIMARY KEY (source, symbol, metric, period, ts)
);

CREATE INDEX IF NOT EXISTS idx_series_lookup
    ON series (symbol, metric, period, ts);

-- 캔들(OHLCV). 봉 시작 시각 기준. 미완성(진행 중) 봉은 저장하지 않는다 → INSERT OR IGNORE 로 충분.
CREATE TABLE IF NOT EXISTS candles (
    source       TEXT NOT NULL,   -- binance | upbit | coinbase
    symbol       TEXT NOT NULL,   -- BTCUSDT | KRW-BTC | BTC-USD
    period       TEXT NOT NULL,   -- 4h | 1d
    ts           INTEGER NOT NULL,-- 봉 시작 시각 (epoch ms, UTC)
    open         REAL, high REAL, low REAL, close REAL,
    volume       REAL,            -- 기초자산 수량
    quote_volume REAL,            -- 거래대금 (USDT / KRW / USD). 없으면 NULL
    collected_at INTEGER NOT NULL,
    PRIMARY KEY (source, symbol, period, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles (symbol, period, ts);

-- ---- 2~3주차용 테이블. 지금은 비어 있고 스키마만 먼저 고정한다 ----
-- AI 리포트: created_at 을 남겨 "사전 공개" 근거로 쓴다.
CREATE TABLE IF NOT EXISTS reports (
    report_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT NOT NULL,
    as_of_ts       INTEGER NOT NULL,  -- 리포트가 본 마지막 봉 마감 시각
    created_at     INTEGER NOT NULL,  -- 실제 생성 시각
    model          TEXT,              -- LLM 모델 id
    prompt_version TEXT,
    direction      TEXT,              -- long | short | neutral
    confidence     REAL,              -- 0~1
    horizon_h      INTEGER,           -- 예측 지평(시간)
    body_json      TEXT               -- A~F 6항목 구조화 출력(JSON)
);
-- 퀀트 시그널: 규칙 파일 해시를 남겨 어떤 규칙으로 났는지 재현 가능하게.
CREATE TABLE IF NOT EXISTS signals (
    signal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    ts              INTEGER NOT NULL,  -- 신호가 난 봉 마감 시각
    created_at      INTEGER NOT NULL,
    rules_version   TEXT,              -- signal_rules.json 해시
    score           REAL,              -- 지표 합산 점수
    direction       TEXT,              -- buy | sell | hold
    indicators_json TEXT,              -- 지표별 값과 판정
    report_id       INTEGER,           -- 함께 본 리포트 (없으면 NULL)
    sent_discord    INTEGER DEFAULT 0
);
-- 포워드(전향) 기록: 리포트·시그널을 낸 뒤 실제로 어떻게 됐는지 자동 채점.
CREATE TABLE IF NOT EXISTS forward_track (
    track_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,     -- report | signal
    ref_id        INTEGER NOT NULL,  -- reports.report_id 또는 signals.signal_id
    symbol        TEXT NOT NULL,
    entry_ts      INTEGER NOT NULL,
    entry_price   REAL NOT NULL,
    horizon_h     INTEGER NOT NULL,
    exit_ts       INTEGER,
    exit_price    REAL,
    realized_ret  REAL,              -- 방향 반영, 비용 차감 전
    fee_adj_ret   REAL,              -- 수수료·슬리피지 차감 후
    benchmark_ret REAL,              -- 같은 구간 BTC 존버 수익률
    scored_at     INTEGER
);

-- 뉴스 헤드라인(2026-10-03 추가). 제목·링크·시각만 저장하고 본문은 받지 않는다.
-- 종목 표시는 제목 키워드로만 붙인다(LLM 라벨은 엔진 단계에서 별도 열로 추가).
CREATE TABLE IF NOT EXISTS news (
    news_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,   -- conf news.feeds[].name
    lang         TEXT,            -- ko | en
    title        TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    published_at INTEGER,         -- 피드의 발행 시각 (epoch ms, UTC). 없으면 NULL
    symbols      TEXT,            -- 제목 키워드로 찾은 종목 "BTC,ETH" / 일반 코인 단어만 있으면 "CRYPTO" / 없으면 ''
    fetched_at   INTEGER NOT NULL,-- 우리가 처음 받은 시각 (epoch ms, UTC)
    publisher    TEXT             -- 실제 언론사(도메인). 모음 API(네이버·GDELT)일 때 원 기사 출처
);
CREATE INDEX IF NOT EXISTS idx_news_pub ON news (published_at);

-- 수집기 상태값(예: 뉴스 피드별 마지막 요청 시각). 새 행이 없어도 요청 간격을 지키기 위해 따로 둔다.
CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   INTEGER NOT NULL,
    finished_at  INTEGER,
    ok_calls     INTEGER DEFAULT 0,
    failed_calls INTEGER DEFAULT 0,
    rows_new     INTEGER DEFAULT 0,
    note         TEXT
);
"""


def now_ms() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)


def ms_to_utc(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)   # 잠금 대기 30초(엔진과 같게, 10-06)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(news)")}
        if "publisher" not in cols:   # 10-03 추가 열(기존 DB 보강)
            self.conn.execute("ALTER TABLE news ADD COLUMN publisher TEXT")
        self.conn.commit()

    def upsert(self, rows) -> int:
        """rows: iterable of (source, symbol, metric, period, ts, value).

        이미 있는 행은 조용히 무시한다. 반환값은 '새로 들어간 행 수'.
        """
        collected = now_ms()
        payload = [(s, sy, m, p, int(t), (None if v is None else float(v)), collected)
                   for (s, sy, m, p, t, v) in rows]
        if not payload:
            return 0
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO series "
            "(source, symbol, metric, period, ts, value, collected_at) "
            "VALUES (?,?,?,?,?,?,?)",
            payload,
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO run_log (started_at) VALUES (?)", (now_ms(),))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, ok: int, failed: int, rows_new: int, note: str = "") -> None:
        self.conn.execute(
            "UPDATE run_log SET finished_at=?, ok_calls=?, failed_calls=?, rows_new=?, note=? "
            "WHERE run_id=?",
            (now_ms(), ok, failed, rows_new, note, run_id),
        )
        self.conn.commit()

    def max_ts(self, source: str, symbol: str, metric: str, period: str):
        row = self.conn.execute(
            "SELECT MAX(ts) FROM series WHERE source=? AND symbol=? AND metric=? AND period=?",
            (source, symbol, metric, period),
        ).fetchone()
        return row[0]

    def upsert_candles(self, rows) -> int:
        """rows: iterable of (source, symbol, period, ts, open, high, low, close, volume, quote_volume)."""
        collected = now_ms()

        def f(x):
            return None if x in (None, "") else float(x)

        payload = [(s, sy, p, int(t), f(o), f(h), f(l), f(c), f(v), f(q), collected)
                   for (s, sy, p, t, o, h, l, c, v, q) in rows]
        if not payload:
            return 0
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO candles "
            "(source, symbol, period, ts, open, high, low, close, volume, quote_volume, collected_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def max_ts_candle(self, source: str, symbol: str, period: str):
        row = self.conn.execute(
            "SELECT MAX(ts) FROM candles WHERE source=? AND symbol=? AND period=?",
            (source, symbol, period),
        ).fetchone()
        return row[0]

    def coverage_candles(self):
        return self.conn.execute(
            "SELECT source, symbol, period, COUNT(*), MIN(ts), MAX(ts) "
            "FROM candles GROUP BY source, symbol, period ORDER BY source, symbol, period"
        ).fetchall()

    def coverage(self):
        return self.conn.execute(
            "SELECT source, symbol, metric, period, COUNT(*), MIN(ts), MAX(ts) "
            "FROM series GROUP BY source, symbol, metric, period "
            "ORDER BY source, metric, symbol, period"
        ).fetchall()

    def upsert_news(self, rows) -> int:
        """rows: iterable of (source, lang, title, url, published_at_ms|None, symbols[, publisher]). 반환: 새로 들어간 행 수.
        url 이 이미 있으면 새 행을 만들지 않고 출처만 이번 수집 경로로 바꾼다(10-04 GPT-6.1 Sol 재현: 예전에 RSS 로 받은 기사를
        지금 공식 API 가 다시 받아도 RSS 출처로 남아 화면에서 숨겨졌음. 꺼진 출처는 수집하지 않으므로 마지막 수집 경로 = 켜진 출처)."""
        fetched = now_ms()
        payload = []
        for r in rows:
            s, lg, t, u, p, sy = r[:6]
            pub = r[6] if len(r) > 6 else None
            payload.append((s, lg, t, u, (None if p is None else int(p)), sy, fetched, pub))
        if not payload:
            return 0
        before = self.conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        self.conn.executemany(
            "INSERT INTO news (source, lang, title, url, published_at, symbols, fetched_at, publisher) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET source=excluded.source, "
            "publisher=COALESCE(excluded.publisher, news.publisher) WHERE news.source != excluded.source",
            payload,
        )
        self.conn.commit()
        return self.conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] - before

    def prune_news(self, source: str, before_ms: int) -> int:
        """source 출처의 뉴스 중 우리가 처음 받은 시각(fetched_at)이 before_ms 보다 이른 행을 지운다. 반환: 지운 행 수.
        네이버 검색 API 약관 특약 2.4(2026-09-07): 서버 보관은 이력 조회 목적으로 최대 21일."""
        cur = self.conn.execute("DELETE FROM news WHERE source=? AND fetched_at < ?", (source, int(before_ms)))
        self.conn.commit()
        return cur.rowcount or 0

    def kv_get(self, key: str):
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return None if row is None else row[0]

    def kv_set(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO kv (key, value, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, str(value), now_ms()),
        )
        self.conn.commit()

    def coverage_news(self):
        return self.conn.execute(
            "SELECT source, COUNT(*), SUM(symbols != ''), MIN(published_at), MAX(published_at) "
            "FROM news GROUP BY source ORDER BY source"
        ).fetchall()

    def close(self) -> None:
        self.conn.close()
