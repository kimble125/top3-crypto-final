"""엔진 공용: DB 경로, 엔진 표 스키마, 캔들·공포탐욕 읽기, 설정 읽기.

시각 규약
- candles.ts 는 봉 **시작** 시각(UTC epoch ms). 엔진은 봉 **마감** 시각(시작 + 길이)으로 다룬다.
- 분석 시각 T = 4시간봉 마감 시각. T 에는 마감이 T 이하인 봉만 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE = Path(__file__).resolve().parent
REPO = ENGINE.parent
DB_PATH = REPO / "02_데이터수집" / "data" / "raw" / "market.db"
CONF = ENGINE / "conf"

PERIOD_MS = {"15m": 15 * 60_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

# 계산 로직 버전. 판정·점수·상태 판단의 의미가 바뀌는 코드 수정이면 올린다(규칙 버전 이름에 들어가 기록이 구분됨).
# e1: 10-03 첫 구현. e2: 10-03 검토 반영(워밍업·봉 누락 제외, 결측 시 방향 0, 교차 시각 정의).
# e3: 10-03 검토 2회차(봉 누락 뒤 Stochastic·StochRSI 기억 지움, '없음'을 사이에 둔 방향 바뀜도 교차 시각으로, 깨진 가격 봉은 누락으로).
# e4: 10-04 진단 반영(Wilder RSI 첫 값 = 처음 14개 평균, %K·%D 비교 허용오차 1e-8, StochRSI 교차 예외는 규칙 값으로).
ENGINE_LOGIC = "e4"

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    symbol        TEXT NOT NULL,
    t_close       INTEGER NOT NULL,   -- 4시간봉 마감 시각 (UTC ms) = 분석 기준 시각
    rules_version TEXT NOT NULL,
    mode          TEXT NOT NULL,      -- live | replay
    status        TEXT NOT NULL,      -- ok | data_short
    close         REAL,               -- 기준가: 마감 T 인 4h 봉 종가
    macd REAL, macd_signal REAL, macd_dir INTEGER, macd_last_cross INTEGER,
    sto_k REAL, sto_d REAL, sto_state INTEGER, sto_last_event INTEGER,
    srsi_k REAL, srsi_d REAL, srsi_state INTEGER, srsi_last_event INTEGER,
    pair_dir INTEGER,
    vpci REAL, vpcis REAL, vpci_dir INTEGER, vpci_last_cross INTEGER,
    score INTEGER, strong INTEGER, strong_dir INTEGER,
    fng INTEGER,
    bar_1h_close INTEGER, bar_15m_close INTEGER,
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (symbol, t_close, rules_version, mode)
);
CREATE INDEX IF NOT EXISTS idx_analyses_mode_t ON analyses (mode, t_close);

CREATE TABLE IF NOT EXISTS outcomes (
    symbol        TEXT NOT NULL,
    t_close       INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    mode          TEXT NOT NULL,
    next_close    REAL,
    ret           REAL,               -- next_close / close - 1
    call_dir      INTEGER,            -- sign(score)
    hit           INTEGER,            -- 1/0, 방향 없음·보합이면 NULL
    strong_hit    INTEGER,            -- 확실한 신호일 때만 1/0
    base_hit      INTEGER,            -- 기준 '항상 Long': ret>0 이면 1, 보합 NULL
    scored_at     INTEGER NOT NULL,
    PRIMARY KEY (symbol, t_close, rules_version, mode)
);

CREATE TABLE IF NOT EXISTS explanations (
    t_close        INTEGER NOT NULL,
    rules_version  TEXT NOT NULL,
    source         TEXT NOT NULL,     -- gpt | template
    model          TEXT,
    prompt_version TEXT,
    body_json      TEXT NOT NULL,     -- {"items":[{"symbol","text"}], "overall"}
    input_json     TEXT,
    note           TEXT,              -- 템플릿으로 바꾼 이유 등
    shadow_json    TEXT,              -- 리허설(shadow) 모드의 GPT 결과. 화면·디스코드에는 쓰지 않음
    created_at     INTEGER NOT NULL,
    PRIMARY KEY (t_close, rules_version)
);

CREATE TABLE IF NOT EXISTS ai_reports (     -- 10-06 AI 심층 리포트(정량·정성·성적 세 단락)
    t_close        INTEGER NOT NULL,
    rules_version  TEXT NOT NULL,
    source         TEXT NOT NULL,     -- gpt | none(실패)
    model          TEXT,
    prompt_version TEXT,
    body_json      TEXT,              -- {"technical","qualitative","record"}
    input_json     TEXT,
    note           TEXT,
    created_at     INTEGER NOT NULL,
    PRIMARY KEY (t_close, rules_version)
);

CREATE TABLE IF NOT EXISTS discord_alerts (  -- 10-06 확신도 ±100·확실한 신호 알림(종목·종류별 한 번)
    t_close        INTEGER NOT NULL,
    symbol         TEXT NOT NULL,
    rules_version  TEXT NOT NULL,
    kind           TEXT NOT NULL,     -- strong | score100 | strong15(10-07 15분 확실한 신호)
    status         TEXT NOT NULL,     -- sending | sent | dry_run | failed
    body           TEXT,
    note           TEXT,
    created_at     INTEGER NOT NULL,
    PRIMARY KEY (t_close, symbol, kind)   -- 10-07: kind 포함. 4시간봉 마감 T 에 15분 알림(strong15)과 4시간 알림(strong)이 같이 나갈 수 있게
);

CREATE TABLE IF NOT EXISTS discord_log (
    t_close       INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    status        TEXT NOT NULL,      -- dry_run | sent | failed
    body          TEXT,
    note          TEXT,
    created_at    INTEGER NOT NULL,
    PRIMARY KEY (t_close, rules_version)
);

CREATE TABLE IF NOT EXISTS strong15 (        -- 10-07 15분 확실한 신호: 상태가 바뀐 15분봉마다 한 행(strong15.py)
    symbol        TEXT NOT NULL,
    t_close       INTEGER NOT NULL,   -- 상태가 바뀐 15분봉 마감 시각 (UTC ms)
    rules_version TEXT NOT NULL,      -- 판정에 쓴 4시간 규칙 버전(rules_v3.json 해시)
    dir           INTEGER NOT NULL,   -- 바뀐 뒤 상태: +1 Long / −1 Short / 0 없음
    prev_dir      INTEGER NOT NULL,
    kind          TEXT NOT NULL,      -- on(켜짐) | off(꺼짐) | flip(방향 바뀜) | init(첫 기록 때 이미 켜져 있던 상태, 채점 안 함)
    close         REAL,               -- 그 15분봉 종가
    created_at    INTEGER NOT NULL,
    end_t         INTEGER,            -- (가) 에피소드 끝: 설정 episode_end 에 따라 off/flip 또는 반대 신호의 15분봉 마감
    end_close     REAL,
    end_reason    TEXT,               -- off | flip | opposite
    ret           REAL,               -- end_close / close − 1
    hit           INTEGER,            -- 1/0, 보합이면 NULL
    aux_t         INTEGER,            -- (나) 보조: 켜진 뒤 aux_horizon_ms(기본 4시간) 뒤 15분봉 마감
    aux_close     REAL,
    aux_ret       REAL,
    aux_hit       INTEGER,
    scored_at     INTEGER,
    PRIMARY KEY (symbol, t_close, rules_version)
);

CREATE TABLE IF NOT EXISTS triggers (         -- 10-12 트리거(trigger.py): 기술 조건 사건 중 12시간 금지·AI 게이트를 통과한 것
    symbol        TEXT NOT NULL,
    track         TEXT NOT NULL,      -- ai(공식: 기술 조건 + AI 추세 일치) | tech(기술 조건만, 비교용)
    mode          TEXT NOT NULL,      -- live | replay(tech 만)
    rules_version TEXT NOT NULL,
    t_bar         INTEGER NOT NULL,   -- 사건이 난 15분봉 마감 시각(UTC ms)
    dir           INTEGER NOT NULL,   -- +1 Long / −1 Short
    kind          TEXT NOT NULL,      -- on | flip
    entry         REAL NOT NULL,      -- 진입가 = 그 15분봉 종가(바이낸스 현물)
    issued_at     INTEGER NOT NULL,   -- 트리거를 확정한 시각(운영: 실제 시각, 재현: t_bar)
    ai_created_at INTEGER,            -- 공식 트리거가 쓴 AI 분석(ai_analyses.created_at)
    end_t         INTEGER,            -- 같은 트랙 다음 트리거의 15분봉 마감(없으면 진행 중)
    end_close     REAL,
    last_bar_t    INTEGER,            -- 채점에 넣은 마지막 15분봉 마감
    mfe           REAL,               -- 최대수익률(진입 방향, 비율). 수수료 빼기 전
    mae           REAL,               -- 최대 손실폭(비율, 양수 = 불리하게 간 폭)
    ret_end       REAL,               -- 다음 트리거 때 실제 손익(비율, 수수료 빼기 전)
    base_mfe      REAL,               -- 같은 구간 '항상 Long'의 최대수익률
    status        TEXT NOT NULL DEFAULT 'open',   -- open | closed
    scored_at     INTEGER,
    discord_status TEXT,              -- 공식 트리거만: sending | sent | failed | dry_run
    discord_body  TEXT,
    discord_at    INTEGER,
    fix24_mfe     REAL,               -- V5 참고 열: 진입 뒤 24시간 고정 창의 최대수익률(비율, 수수료 빼기 전). 창이 덜 찼거나 봉 결측이면 NULL
    fix24_mae     REAL,               -- 같은 창의 최대 손실폭
    PRIMARY KEY (symbol, track, mode, rules_version, t_bar)
);
CREATE INDEX IF NOT EXISTS idx_triggers_mode ON triggers (mode, track, rules_version, t_bar);

CREATE TABLE IF NOT EXISTS trigger_checks (   -- 10-12 공식 트랙의 AI 게이트 기록(사건마다 한 번)
    symbol        TEXT NOT NULL,
    t_bar         INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    dir           INTEGER NOT NULL,
    checked_at    INTEGER NOT NULL,
    ai_created_at INTEGER,
    ai_dir        INTEGER,
    result        TEXT NOT NULL,      -- pass | mismatch | neutral | ai_error | banned | late | off | repeat(V5: 직전 트리거와 같은 방향)
    PRIMARY KEY (symbol, t_bar, rules_version)
);

CREATE TABLE IF NOT EXISTS ai_analyses (      -- 10-12 정미님 6절 AI 분석(ai_analysis.py), 코인별
    symbol         TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    kind           TEXT NOT NULL,     -- scheduled(09·21시) | on_demand(기술 조건이 켜질 때)
    ref_t          INTEGER NOT NULL,  -- 입력 데이터 기준 시각(마지막 15분봉 마감)
    source         TEXT NOT NULL,     -- gpt | claude(V5: Codex 대신 Claude CLI 구독 로그인) | none(실패)
    model          TEXT,
    prompt_version TEXT,
    trend_dir      INTEGER,           -- +1 Long / −1 Short / 0 Neutral(실패면 NULL)
    confidence_pct INTEGER,
    body_json      TEXT,
    input_json     TEXT,
    note           TEXT,              -- 실패 원문 사유(로컬 전용, 공개 응답에서 뺌)
    code           TEXT,              -- V5 실패 코드: limit | timeout | invalid | error (성공이면 NULL)
    fallback_from  TEXT,              -- V5: Claude 가 대신 성공한 행의 원래 Codex 실패 코드
    retry_at       INTEGER,           -- V5: Codex 사용 한도가 풀리는 시각(UTC ms)
    retry_est      INTEGER,           -- V5: 그 시각이 6시간 넘게 뒤라 추정으로 볼 때 1
    PRIMARY KEY (symbol, created_at)
);

-- 규칙 버전별 설정 스냅샷. 화면·보고서가 '그 분석을 만든 규칙'으로 설명하게 한다.
CREATE TABLE IF NOT EXISTS rules_versions (
    rules_version TEXT PRIMARY KEY,
    rules_json    TEXT NOT NULL,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at INTEGER NOT NULL
);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    return conn


def _migrate(conn) -> None:
    """이전 스키마에 빠진 열을 더한다(멱등)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(discord_log)")}
    if "attempts" not in cols:
        conn.execute("ALTER TABLE discord_log ADD COLUMN attempts INTEGER NOT NULL DEFAULT 1")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(explanations)")}
    if "shadow_json" not in cols:
        conn.execute("ALTER TABLE explanations ADD COLUMN shadow_json TEXT")
    # 10-07: discord_alerts PK (t_close, symbol) → (t_close, symbol, kind). SQLite 는 PK 를 ALTER 못 하므로 새 표로 옮긴다
    pk = {r[1] for r in conn.execute("PRAGMA table_info(discord_alerts)") if r[5]}
    if pk and "kind" not in pk:
        conn.execute("ALTER TABLE discord_alerts RENAME TO discord_alerts_pk2")
        conn.executescript(SCHEMA)         # 새 PK 로 discord_alerts 를 다시 만든다
        conn.execute("INSERT OR IGNORE INTO discord_alerts (t_close, symbol, rules_version, kind, status, body, note, created_at) "
                     "SELECT t_close, symbol, rules_version, kind, status, body, note, created_at FROM discord_alerts_pk2")
        conn.execute("DROP TABLE discord_alerts_pk2")
    # V5(10-14): 24시간 고정 창 참고 열, AI 분석 실패 코드 · Claude 대체 기록
    for table, col, typ in (("triggers", "fix24_mfe", "REAL"), ("triggers", "fix24_mae", "REAL"),
                            ("ai_analyses", "code", "TEXT"), ("ai_analyses", "fallback_from", "TEXT"),
                            ("ai_analyses", "retry_at", "INTEGER"), ("ai_analyses", "retry_est", "INTEGER")):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")


def save_rules_snapshot(conn, version: str, rules: dict) -> None:
    conn.execute("INSERT OR IGNORE INTO rules_versions (rules_version, rules_json, created_at) VALUES (?,?,?)",
                 (version, json.dumps(rules, ensure_ascii=False), now_ms()))
    conn.commit()


def load_json(name: str) -> dict:
    return json.loads((CONF / name).read_text(encoding="utf-8"))


def save_json(name: str, data: dict) -> None:
    (CONF / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rules_version(rules: dict) -> str:
    """설명 키(_로 시작)와 tries_log 를 뺀 규칙 내용의 해시 + temp/final."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if not k.startswith("_") and k != "tries_log"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    core = json.dumps(strip(rules), sort_keys=True, ensure_ascii=False) + "|" + ENGINE_LOGIC
    return hashlib.sha256(core.encode("utf-8")).hexdigest()[:12] + "-" + rules.get("status", "temp")


def load_env() -> None:
    """저장소 루트 .env 를 읽어 os.environ 에 없는 키만 채운다. 값은 출력하지 않는다."""
    path = REPO / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def load_candles(conn: sqlite3.Connection, symbol: str, period: str, end_close_ms: int | None = None,
                 start_close_ms: int | None = None) -> pd.DataFrame:
    """바이낸스 현물 캔들. index = 봉 마감 시각(UTC ms). end_close_ms 를 주면 마감이 그 이하인 봉만,
    start_close_ms 를 주면 마감이 그 이상인 봉만(그래프처럼 최근 구간만 필요할 때)."""
    plen = PERIOD_MS[period]
    sql = ("SELECT ts, open, high, low, close, volume FROM candles "
           "WHERE source='binance' AND symbol=? AND period=?")
    params: list = [symbol, period]
    if end_close_ms is not None:
        sql += " AND ts + ? <= ?"
        params += [plen, end_close_ms]
    if start_close_ms is not None:
        sql += " AND ts + ? >= ?"
        params += [plen, start_close_ms]
    sql += " ORDER BY ts"
    df = pd.read_sql_query(sql, conn, params=params)
    df = df[good_ohlcv(df)].copy()
    df["close_ms"] = df["ts"] + plen
    return df.set_index("close_ms")


def good_ohlcv(df: pd.DataFrame) -> pd.Series:
    """정상 봉이면 True. 값이 깨진 봉(무한대·결측·0 이하 가격, 음수 거래량, 고가<저가, 시가·종가가 고가~저가 밖)은
    없는 봉으로 본다 → 계산에서는 누락 규칙(data_short), 채점에서는 보류(track.score_pending).
    10-03 GPT-6 Astra 재현: 종가가 범위 밖이면 Stochastic 이 수만으로 튐. 실제 데이터 위반 0건이라 결과는 같아 로직 버전은 e3 유지.
    10-04 GPT-6.1 Sol 재현: 채점이 이 검사를 거치지 않아 깨진 다음 봉으로 적중 처리됨 → 같은 검사를 씀."""
    px = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").astype(float)
    vol = pd.to_numeric(df["volume"], errors="coerce").astype(float)
    return (np.isfinite(px).all(axis=1) & (px > 0).all(axis=1) & np.isfinite(vol) & (vol >= 0)
            & (px["high"] >= px["low"]) & (px["low"] <= px[["open", "close"]].min(axis=1))
            & (px["high"] >= px[["open", "close"]].max(axis=1)))


def load_fng(conn: sqlite3.Connection) -> pd.Series:
    """공포탐욕지수. index = 값의 기준일 00:00 UTC ms."""
    df = pd.read_sql_query(
        "SELECT ts, value FROM series WHERE source='alternative.me' AND metric='fear_greed' ORDER BY ts", conn)
    return pd.Series(df["value"].values, index=df["ts"].values, dtype="float64")


def kv_get(conn, key):
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


def kv_set(conn, key, value) -> None:
    conn.execute(
        "INSERT INTO kv (key, value, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value), now_ms()))
    conn.commit()


def utc_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def kst_text(ms: int | None, fmt: str = "%m-%d %H:%M") -> str | None:
    if ms is None:
        return None
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").tz_convert("Asia/Seoul").strftime(fmt)
