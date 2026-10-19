"""지표 그래프 데이터 내보내기. 기획안 `01_운영/Plan/기획서/기획안_지표그래프_2026-10-03.md` §6.

- 4시간 사이클(run_cycle)이 15분마다 실행될 때 마지막에 부른다. 수집기가 넣은 닫힌 봉만 쓴다(진행 중 봉 없음).
- 판정과 같은 함수(indicators·judge)로 계산하므로 그래프 값과 판정 값이 어긋나지 않는다.
- 최근 DAYS일만 저장하되, 지표 준비 구간(워밍업)을 넉넉히 앞에서부터 계산한다.
  EMA·Wilder RSI 는 처음 값의 영향이 남지만 1,000봉 이상이면 (1−α)^n 이 무시할 만큼 작다.
- 결과: reports/charts/<SYMBOL>.json (파생 데이터, git 제외). 임시 파일에 쓴 뒤 이름을 바꿔 원자적으로 교체한다.

사용: python3 chart_export.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd

import db
import judge

DAYS = 7
DAY_MS = 86_400_000
WARMUP_BARS = {"4h": 1000, "1h": 3000, "15m": 1500}
OUT_DIR = db.ENGINE / "reports" / "charts"
EVENT_NAMES = ("macd", "sto", "srsi", "vpci")


def _r(v, digits: int = 6):
    """JSON 용 숫자: NaN·무한대는 null, 나머지는 유효숫자 digits 자리."""
    if v is None:
        return None
    f = float(v)
    if not math.isfinite(f):
        return None
    return float(f"{f:.{digits}g}")


def _series(frame: pd.DataFrame, cols: dict, since: int) -> dict:
    """{"t": [...], 열이름: [...]} (since 이후, 마감 시각 ms)."""
    f = frame[frame.index >= since]
    out = {"t": [int(t) for t in f.index]}
    for key, col in cols.items():
        out[key] = [_r(v) for v in f[col].values]
    return out


def _gaps(c: pd.DataFrame, period: str, since: int) -> list[dict]:
    """빠진 봉 구간: 앞 봉 마감 ~ 다음 봉 마감 사이가 한 봉보다 긴 곳."""
    if c.empty:
        return []
    idx = np.asarray(c.index, dtype="int64")
    step = db.PERIOD_MS[period]
    out = []
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a != step and b >= since:
            out.append({"tf": period, "from": int(a), "to": int(b)})
    return out


def build(conn, symbol: str, rules: dict, version: str, now_ms: int | None = None) -> dict | None:
    p4, p1, p15 = rules["macd"]["period"], rules["stoch_pair"]["period"], rules["vpci"]["period"]
    frames = {}
    for per in (p4, p1, p15):
        last = conn.execute("SELECT MAX(ts) FROM candles WHERE source='binance' AND symbol=? AND period=?",
                            (symbol, per)).fetchone()[0]
        if last is None:
            return None
        last_close = int(last) + db.PERIOD_MS[per]
        start = last_close - (WARMUP_BARS[per] + DAYS * DAY_MS // db.PERIOD_MS[per]) * db.PERIOD_MS[per]
        frames[per] = db.load_candles(conn, symbol, per, end_close_ms=now_ms, start_close_ms=start)
    c4, c1, c15 = frames[p4], frames[p1], frames[p15]
    if c15.empty:
        return None
    end = int(c15.index.max())                 # 가장 최근에 닫힌 15분봉 마감
    since = end - DAYS * DAY_MS

    m = judge.macd_frame(c4, rules["macd"]) if not c4.empty else pd.DataFrame()
    pr = judge.pair_frame(c1, rules["stoch_pair"], db.PERIOD_MS[p1]) if not c1.empty else pd.DataFrame()
    vp = judge.vpci_frame(c15, rules["vpci"], db.PERIOD_MS[p15])

    events = []
    def add_events(name, s: pd.Series):
        s = s[(s.index >= since) & (s != 0)]
        events.extend({"t": int(t), "ind": name, "dir": int(d)} for t, d in s.items())
    if not m.empty:
        add_events("macd", judge.change_points(m["macd_dir"]))
    if not pr.empty:
        add_events("sto", pr["sto_event"])
        add_events("srsi", pr["srsi_event"])
    add_events("vpci", judge.change_points(vp["vpci_dir"]))
    events.sort(key=lambda e: (e["t"], EVENT_NAMES.index(e["ind"])))

    now = now_ms if now_ms is not None else db.now_ms()
    rows = conn.execute(   # 그래프 끝(now) 뒤의 분석은 넣지 않는다(10-04 GPT-6.1 Sol 재현: 과거 시점 그래프에 미래 분석점)
        "SELECT t_close, status, score, strong, strong_dir FROM analyses WHERE mode='live' AND symbol=? "
        "AND rules_version=? AND t_close>=? AND t_close<=? ORDER BY t_close", (symbol, version, since, now)).fetchall()
    analyses = [{"t": int(t), "status": st, "score": None if sc is None else int(sc),
                 "strong": int(s or 0), "strong_dir": int(sd or 0)} for t, st, sc, s, sd in rows]

    return {
        "symbol": symbol, "rules_version": version, "days": DAYS,
        "generated_at": db.utc_iso(now), "generated_ms": now,
        "last_close": {per: (int(f.index.max()) if not f.empty else None) for per, f in frames.items()},
        "price": _series(c15, {"c": "close"}, since),
        "macd": _series(m, {"macd": "macd", "signal": "macd_signal"}, since) if not m.empty else {"t": []},
        "sto": _series(pr, {"k": "sto_k", "d": "sto_d"}, since) if not pr.empty else {"t": []},
        "srsi": _series(pr, {"k": "srsi_k", "d": "srsi_d"}, since) if not pr.empty else {"t": []},
        "vpci": _series(vp, {"v": "vpci", "s": "vpcis"}, since),
        "events": events,
        "analyses": analyses,
        "gaps": _gaps(c4, p4, since) + _gaps(c1, p1, since) + _gaps(c15, p15, since),
        "zone": {"upper": rules["stoch_pair"]["upper"], "lower": rules["stoch_pair"]["lower"]},
    }


def write_atomic(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)                  # 같은 폴더 안 이름 바꾸기 = 원자적 교체
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def export_all(conn, rules: dict, version: str, out_dir=None) -> list[str]:
    out = []
    for sym in rules["symbols"]:
        data = build(conn, sym, rules, version)
        if data is None:
            continue
        write_atomic((out_dir or OUT_DIR) / f"{sym}.json", data)
        out.append(sym)
    return out


def main() -> int:
    rules = db.load_json("rules_v3.json")
    version = db.rules_version(rules)
    conn = db.connect()
    done = export_all(conn, rules, version)
    conn.close()
    print(f"그래프 데이터 {len(done)}종목 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
