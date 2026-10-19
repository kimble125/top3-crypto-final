"""기획서 ver3 보드용 읽기 API. 엔진(04_엔진)이 쓴 analyses·outcomes·explanations·rules_versions 표를 읽기만 한다.

엔드포인트: /api/board, /api/analyses, /api/replay, /api/engine, /api/study, /api/study/{name}, /api/chart/{symbol}
계산은 엔진이 끝낸 값을 그대로 쓰고, 여기서는 화면에 맞게 묶기만 한다.
화면 설명(가중치·임시 여부·판정 문장)은 '그 분석을 만든 규칙 버전'의 스냅샷으로 만든다.
공개 범위(10-13 결정 84-A): 맥에서 직접 연 요청만 전체(scope=local), 그 밖(Funnel·Vercel·저장본)은 app/public_scope.py 의
화이트리스트만(scope=public). 매매 조건과 채점은 맥의 검증 화면에서만 보인다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request

from app import public_scope as pub

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "04_엔진"
STUDY = REPO / "01_운영" / "공부노트"
COLLECT_CONF = REPO / "02_데이터수집" / "conf" / "collectors.json"
KST = ZoneInfo("Asia/Seoul")
H4 = 4 * 3_600_000
ON_TIME = 3_600_000   # 운영 성적에 넣는 분석: T부터 1시간 안에 만든 것만. 04_엔진/track.py ON_TIME_MS 와 같아야 함
M15 = 15 * 60_000
NAMES = {"BTCUSDT": "비트코인", "ETHUSDT": "이더리움", "XRPUSDT": "리플"}
SHORT = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP"}
STATUS_LABEL = {"data_short": "데이터 부족", "not_ready": "계산 준비 중"}
LABEL15 = {1: "롱 확실", -1: "숏 확실", 0: "없음"}   # 15분 확실한 신호(10-07). 04_엔진/strong15.py LABEL 과 같아야 함(시험으로 확인)
KINDS15 = ("on", "flip")                            # 채점 대상 = 켜진 에피소드(04_엔진/strong15.py KINDS_SCORED)

router = APIRouter(tags=["board v3"])
_db = None  # main.py 가 주입하는 연결 함수


def set_db(fn):
    global _db
    _db = fn


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kst(ms: Optional[int], fmt: str = "%m-%d %H:%M") -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(KST).strftime(fmt)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def signed(n) -> str:
    return f"+{n}" if n > 0 else (f"−{abs(n)}" if n < 0 else "0")


def label(score, strong, strong_dir, d_macd=None, d_pair=None, d_vpci=None, weights=None, status="ok") -> str:
    """04_엔진/pipeline.label 과 같은 규칙(백엔드는 엔진을 import 하지 않으므로 같은 규칙을 둔다)."""
    if status != "ok" or score is None:
        return STATUS_LABEL.get(status, "데이터 부족")
    if strong:
        return "확실한 신호 Long" if strong_dir > 0 else "확실한 신호 Short"
    if d_macd and d_pair == -d_macd and d_vpci == -d_macd:
        w = weights or {"macd": 4, "pair": 2, "vpci": 1}
        if w["macd"] > w["pair"] + w["vpci"]:
            return "MACD만 Long" if d_macd > 0 else "MACD만 Short"
    return "Long 우세" if score > 0 else "Short 우세" if score < 0 else "방향 없음"


def _iso_ms(text: Optional[str]) -> Optional[int]:
    """'2026-10-02T20:00:00Z' → epoch ms."""
    if not text:
        return None
    try:
        return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _kv(conn, key):
    r = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return None if r is None else r[0]


def _has_table(conn, name) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _current_version(conn) -> Optional[str]:
    r = conn.execute("SELECT rules_version FROM analyses WHERE mode='live' ORDER BY t_close DESC, created_at DESC "
                     "LIMIT 1").fetchone()
    return r[0] if r else None


def _rules_of(conn, version: Optional[str]) -> dict:
    if version and _has_table(conn, "rules_versions"):
        r = conn.execute("SELECT rules_json FROM rules_versions WHERE rules_version=?", (version,)).fetchone()
        if r:
            return json.loads(r[0])
    return _json(ENGINE / "conf" / "rules_v3.json") or {}


def _alerts(conn, symbols, version) -> list[dict]:
    """종목별로: 15분봉 수집 지연, 분석 지연(최신 4h 마감 뒤 15분 넘게 분석 없음), 분석 전체 없음."""
    out = []
    now = now_ms()
    late_data = []
    for sym in symbols:
        mx = conn.execute("SELECT MAX(ts) FROM candles WHERE source='binance' AND period='15m' AND symbol=?",
                          (sym,)).fetchone()[0]
        if mx is None or now - (mx + M15) > 35 * 60_000:
            late_data.append(f"{SHORT.get(sym, sym)} {kst(mx + M15) + ' KST' if mx else '없음'}")
    if late_data:
        out.append({"kind": "data", "text": "데이터 지연 · 마지막 15분봉 마감: " + ", ".join(late_data)})
    expected = now // H4 * H4
    if now - expected > 15 * 60_000:
        late = []
        for sym in symbols:
            t = conn.execute("SELECT MAX(t_close) FROM analyses WHERE mode='live' AND symbol=? AND rules_version=?",
                             (sym, version)).fetchone()[0] if version else None
            if t is None or t < expected:
                late.append(f"{SHORT.get(sym, sym)} {kst(t) + ' KST' if t else '없음'}")
        if late:
            out.append({"kind": "analysis", "text": "분석 지연 · 마지막 분석: " + ", ".join(late)})
    return out


def _summary(conn, mode, version, since=None, until=None):
    """운영 성적. 분석 시각 T부터 ON_TIME(1시간) 안에 만든 분석만 센다(늦게 복구한 분석은 가격이 이미 움직인 뒤에 만들어짐)."""
    sql = ("SELECT a.symbol, COUNT(*), SUM(o.t_close IS NOT NULL), SUM(o.hit=1), SUM(o.hit IS NOT NULL), "
           "SUM(a.strong=1), SUM(o.strong_hit=1), SUM(o.strong_hit IS NOT NULL), SUM(o.base_hit=1), "
           "SUM(o.base_hit IS NOT NULL), SUM(a.strong=1 AND o.base_hit=1), SUM(a.strong=1 AND o.base_hit IS NOT NULL) "
           "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND "
           "o.t_close=a.t_close AND o.rules_version=a.rules_version AND o.mode=a.mode "
           f"WHERE a.mode=? AND a.rules_version=? AND a.status='ok' AND a.created_at < a.t_close + {ON_TIME}")
    p = [mode, version]
    if since is not None:
        sql += " AND a.t_close>=?"; p.append(since)
    if until is not None:
        sql += " AND a.t_close<?"; p.append(until)
    out = []
    for r in conn.execute(sql + " GROUP BY a.symbol ORDER BY a.symbol", p).fetchall():
        r = tuple(r)
        n, scored, hit, called, sn, sh, ss, bh, bs, sbh, sbs = [x or 0 for x in r[1:]]
        # 확실한 신호 옆에는 같은 시점들의 '항상 Long'을 둔다(10-04 GPT-6.1 Sol: 운영 표에 빠져 있었음)
        out.append({"symbol": r[0], "n": n, "scored": scored, "hit": hit, "called": called,
                    "strong_n": sn, "strong_hit": sh, "strong_scored": ss, "base_hit": bh, "base_scored": bs,
                    "strong_base_hit": sbh, "strong_base_scored": sbs, "small_sample": called < 30})
    return out


def _indicators(a, rules):
    vp, sp = rules.get("vpci", {}), rules.get("stoch_pair", {})
    vpci_rule = {"signal": "VPCI가 신호선 위 Long · 아래 Short",
                 "zero": "VPCI가 0 위 Long · 아래 Short",
                 "zero_or_signal": "VPCI가 0선이나 신호선(SMA)을 위로 넘으면 Long · 아래로 넘으면 Short, 다음 반대 교차까지 유지"
                 }.get(vp.get("cross_target", "signal"), "")
    if sp.get("mode", "zone_event") == "kd_state":   # 정미님 조건서(10-03)
        def kd_rule(cross):
            return ("%K가 %D 위에서 오르거나 위로 교차하면 Long · 아래에서 내리거나 아래로 교차하면 Short" if cross
                    else "%K가 %D 위에서 오르면 Long · 아래에서 내리면 Short") + "(80·20 근처면 더 믿을 만하다고 봄)"
        zone = kd_rule(sp.get("stoch", {}).get("cross_exception", True))
        zone_r = kd_rule(sp.get("stochrsi", {}).get("cross_exception", True))
        sto_word = "이 방향이 된 시각"
    else:
        zone = ("20 이하 상향 교차 Long · 80 이상 하향 교차 Short" if sp.get("zone_mapping", "standard") == "standard"
                else "80 이상 교차 Long · 20 이하 교차 Short")
        zone_r = zone
        sto_word = "마지막 기준 교차"
    return [
        {"key": "macd", "name": "MACD", "tf": "4시간", "dir": a["macd_dir"],
         "values": {"MACD": a["macd"], "시그널": a["macd_signal"]}, "last_kst": kst(a["macd_last_cross"]),
         "last_word": "마지막 교차", "rule": "MACD선이 시그널선 위 Long · 아래 Short"},
        {"key": "stoch", "name": "Stochastic", "tf": "1시간", "dir": a["sto_state"],
         "values": {"%K": a["sto_k"], "%D": a["sto_d"]}, "last_kst": kst(a["sto_last_event"]),
         "last_word": sto_word, "rule": zone},
        {"key": "stochrsi", "name": "StochRSI", "tf": "1시간", "dir": a["srsi_state"],
         "values": {"%K": a["srsi_k"], "%D": a["srsi_d"]}, "last_kst": kst(a["srsi_last_event"]),
         "last_word": sto_word, "rule": zone_r},
        {"key": "vpci", "name": "VPCI", "tf": "15분", "dir": a["vpci_dir"],
         "values": {"VPCI": a["vpci"], "신호선": a["vpcis"]}, "last_kst": kst(a["vpci_last_cross"]),
         "last_word": "마지막 교차", "rule": vpci_rule},
    ]


CHASE_WARN_PCT = 5.0   # 04_엔진/replay.py CHASE_WARN_PCT 와 같음(재현 JSON 이 있으면 그 값을 씀)


def _chase_info(conn, version, sym, t, sdir, chg24, cfg, ref_span):
    """확실한 신호의 '추격 주의' 표시(10-04 E2). move = 직전 24시간 동안 신호 방향으로 움직인 정도(%).
    근거 숫자는 과거 재현(참고 기간)의 같은 구간 성적. 수익 규칙이 아니라 읽는 사람에게 주는 정보."""
    move = round(chg24 * sdir, 2)
    # 연속: 지금 규칙 버전에서 4시간 간격으로 빠짐없이 같은 방향 확실한 신호였던 분석 수.
    # 빠진 시각·데이터 부족(status≠ok)·규칙 버전 경계에서 끊는다(10-04 Fable 검토). 화면에 "현 규칙 기준"이라고 씀.
    streak, expect = 0, t
    for tc, st, sd, status in conn.execute(
            "SELECT t_close, strong, strong_dir, status FROM analyses WHERE mode='live' AND rules_version=? AND symbol=? "
            "AND t_close<=? ORDER BY t_close DESC", (version, sym, t)):
        if tc != expect or status != "ok" or not st or sd != sdir:
            break
        streak += 1
        expect = tc - H4
    warn_pct = (cfg or {}).get("warn_pct", CHASE_WARN_PCT)
    out = {"move_pct": move, "warn": move >= warn_pct, "warn_pct": warn_pct, "streak": streak, "bucket": None}
    for bk in (cfg or {}).get("reference", []):
        if (bk["lo"] is None or move >= bk["lo"]) and (bk["hi"] is None or move < bk["hi"]):
            v = bk["by_symbol"].get(sym) or {}
            out["bucket"] = {"label": bk["label"], "n": v.get("n"), "hit4_pct": v.get("hit4_pct"), "n4": v.get("n4"),
                             "hit24_pct": v.get("hit24_pct"), "n24": v.get("n24"), "period": ref_span}
            break
    return out


def _formula(a, w):
    def term(wt, d):
        return f"{wt}×({'+1' if d > 0 else '−1' if d < 0 else '0'})"
    tot = w["macd"] * a["macd_dir"] + w["pair"] * a["pair_dir"] + w["vpci"] * a["vpci_dir"]
    den = w["macd"] + w["pair"] + w["vpci"]
    return (f"{term(w['macd'], a['macd_dir'])} + {term(w['pair'], a['pair_dir'])} + {term(w['vpci'], a['vpci_dir'])}"
            f" = {signed(tot)} → ÷{den} ×100 = {signed(a['score'])}")


def _market(conn, sym):
    """카드의 시세 줄: 마지막으로 닫힌 15분봉 종가, 최근 24시간(15분봉 96개) 고가·저가, 24시간 전 종가 대비 변동.
    판정(4시간봉 종가 기준)과 따로 보여 주는 참고 시세. 봉이 빠져 24시간을 정확히 못 맞추면 None."""
    rows = conn.execute("SELECT ts, high, low, close FROM candles WHERE source='binance' AND symbol=? AND period='15m' "
                        "ORDER BY ts DESC LIMIT 97", (sym,)).fetchall()
    if len(rows) < 97 or rows[0][0] - rows[96][0] != 86_400_000:
        return None
    last, base, win = rows[0], rows[96], rows[:96]
    return {"price": last[3], "at_kst": kst(last[0] + M15, "%H:%M"),
            "high_24h": max(r[1] for r in win), "low_24h": min(r[2] for r in win),
            "chg_24h": last[3] - base[3], "chg_24h_pct": round(100 * (last[3] / base[3] - 1), 2)}


def _recent_strong(conn, version, limit: int = 5) -> list[dict]:
    """운영 기록에서 확실한 신호가 '새로 켜지거나 방향이 바뀐' 분석(종목 합쳐 최근 순)과 채점 결과(다음 4시간봉 종가).
    10-06 P4: 규칙이 바뀌면 지금 규칙 기록이 비어 보여서, 모든 규칙 버전을 보고 이전 규칙 것은 prev_rules=True 로 표시.
    같은 시각을 두 버전이 계산했으면 지금 규칙(없으면 나중에 만든 것)을 쓴다."""
    rows = conn.execute(
        "SELECT a.symbol, a.t_close, a.rules_version, a.strong, a.strong_dir, a.close, o.next_close, o.strong_hit, a.created_at "
        "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close AND o.rules_version=a.rules_version "
        "AND o.mode=a.mode WHERE a.mode='live' AND a.status='ok' ORDER BY a.symbol, a.t_close, "
        "a.rules_version=? DESC, a.created_at DESC", (version or "",)).fetchall()
    out, prev, seen = [], {}, set()
    for sym, t, ver, st, sd, close, nxt, hit, _ in rows:
        if (sym, t) in seen:
            continue
        seen.add((sym, t))
        if st and (st, sd) != prev.get(sym):
            out.append({"symbol": sym, "short": SHORT.get(sym, sym), "t": iso(t), "t_kst": kst(t), "dir": sd, "close": close,
                        "next_close": nxt, "ret_pct": round(100 * (nxt / close - 1), 2) if nxt and close else None,
                        "hit": None if hit is None else bool(hit), "prev_rules": ver != version})
        prev[sym] = (st, sd)
    out.sort(key=lambda r: r["t"], reverse=True)
    return out[:limit]


def _summary_all(conn) -> dict:
    """운영 기록 전체(규칙 버전 합침, 1시간 안에 만든 분석만): 확실한 신호·방향 적중과 같은 시점 '항상 Long'."""
    r = conn.execute(
        "SELECT SUM(a.strong=1 AND o.strong_hit IS NOT NULL), SUM(o.strong_hit=1), SUM(o.hit IS NOT NULL), SUM(o.hit=1), "
        "SUM(a.strong=1 AND o.base_hit IS NOT NULL), SUM(a.strong=1 AND o.base_hit=1), MIN(a.t_close), COUNT(DISTINCT a.rules_version) "
        "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close AND o.rules_version=a.rules_version "
        f"AND o.mode=a.mode WHERE a.mode='live' AND a.status='ok' AND a.created_at < a.t_close + {ON_TIME}").fetchone()
    ss, sh, dc, dh, bs, bh, first, nv = [x or 0 for x in tuple(r)]
    return {"strong_scored": ss, "strong_hit": sh, "direction_scored": dc, "direction_hit": dh,
            "strong_base_scored": bs, "strong_base_hit": bh, "since_kst": kst(first) if first else None, "versions": nv}


def _now15(conn, sym, version, now=None):
    """카드의 '지금(15분 기준)' 줄(10-07): strong15 표의 마지막 행 = 지금 상태. 표가 없으면 None(옛 DB·저장본),
    행이 없으면 '없음'(since 없음). since_hm 은 바뀐 시각 HH:MM, since_today 는 그 시각이 KST 오늘이면 True."""
    if not _has_table(conn, "strong15") or not version:
        return None
    r = conn.execute("SELECT t_close, dir, kind, close FROM strong15 WHERE symbol=? AND rules_version=? "
                     "ORDER BY t_close DESC LIMIT 1", (sym, version)).fetchone()
    if r is None:
        return {"dir": 0, "label": LABEL15[0], "kind": None, "t_close": None, "since_kst": None, "since_hm": None,
                "since_today": None}
    t, d = int(r[0]), int(r[1])
    today = kst(now if now is not None else now_ms(), "%Y-%m-%d")
    return {"dir": d, "label": LABEL15.get(d, LABEL15[0]), "kind": r[2], "t_close": iso(t), "since_kst": kst(t),
            "since_hm": kst(t, "%H:%M"), "since_today": kst(t, "%Y-%m-%d") == today, "close": r[3]}


def _strong15_summary(conn, version):
    """종목별 15분 에피소드 성적(04_엔진/strong15.summary 와 같은 SQL). (가) 끝 종가 적중, (나) 4시간 뒤 적중."""
    q = ",".join("?" * len(KINDS15))
    out = []
    for r in conn.execute(
            f"SELECT symbol, COUNT(*) n, SUM(hit IS NOT NULL) called, SUM(hit=1) hit, SUM(end_t IS NOT NULL) ended, "
            f"SUM(aux_hit IS NOT NULL) aux_called, SUM(aux_hit=1) aux_hit FROM strong15 WHERE kind IN ({q}) "
            f"AND rules_version=? GROUP BY symbol ORDER BY symbol", (*KINDS15, version)).fetchall():
        d = dict(zip(["symbol", "n", "called", "hit", "ended", "aux_called", "aux_hit"], [x or 0 for x in r]))
        d["short"] = SHORT.get(d["symbol"], d["symbol"])
        d["hit_pct"] = round(100 * d["hit"] / d["called"], 1) if d["called"] else None
        d["aux_pct"] = round(100 * d["aux_hit"] / d["aux_called"], 1) if d["aux_called"] else None
        out.append(d)
    return out


def _strong15_block(conn, version, limit: int = 8):
    """보드 맨 위 `strong15`: 마지막 계산 시각, 종목별 성적, 최근 바뀜(켜짐·꺼짐·방향 바뀜) 목록. 표가 없으면 None."""
    if not _has_table(conn, "strong15") or not version:
        return None
    last = _kv(conn, "strong15_last_run")
    recent = [{"symbol": s, "short": SHORT.get(s, s), "t_kst": kst(t), "kind": k, "dir": d, "label": LABEL15.get(d, LABEL15[0]),
               "close": c, "end_reason": er, "ret_pct": None if ret is None else round(100 * ret, 2),
               "hit": None if h is None else bool(h), "aux_hit": None if ah is None else bool(ah)}
              for s, t, k, d, c, er, ret, h, ah in conn.execute(
                  "SELECT symbol, t_close, kind, dir, close, end_reason, ret, hit, aux_hit FROM strong15 WHERE rules_version=? "
                  "AND kind<>'init' ORDER BY t_close DESC LIMIT ?", (version, limit)).fetchall()]
    return {"last_run_kst": kst(int(last), "%m-%d %H:%M") if last else None, "rows": _strong15_summary(conn, version),
            "recent": recent}


def _ai_report(conn, version):
    """가장 최근 AI 심층 리포트(10-06 P4). 지금 규칙 것을 먼저, 없으면 None."""
    if not _has_table(conn, "ai_reports"):
        return None
    r = conn.execute("SELECT t_close, model, body_json, created_at FROM ai_reports WHERE rules_version=? AND body_json IS NOT NULL "
                     "ORDER BY t_close DESC LIMIT 1", (version,)).fetchone()
    if not r:
        return None
    return {"t_close_kst": kst(r[0]), "model": r[1], "created_kst": kst(r[3]), **json.loads(r[2])}


def _trigger_board(version):
    """10-12 리팩토링: 엔진이 15분마다 쓰는 reports/trigger_board.json(트리거 성적·최근 목록·AI 분석·Core Condition).
    계산은 엔진(04_엔진/trigger.export_board)에서만 한다. 지금 규칙 버전 것이 아니면 None."""
    d = _json(ENGINE / "reports" / "trigger_board.json")
    if not d or (version and d.get("rules_version") != version):
        return None
    return d


@router.get("/api/board")
def board(request: Request = None):
    """홈 화면 한 장. 기획서 ver3 AI학습용 부록 A. 공개 요청이면 public_scope.board_view 의 화이트리스트만."""
    full = _board_full()
    return pub.board_view(full) if pub.is_public(request) else {**full, "scope": "local", "verify_text": pub.LOCAL_VERIFY_TEXT}


def _board_full() -> dict:
    """맥에서 보는 전체 보드(검증 화면 자료 포함)."""
    conn = _db()
    if not _has_table(conn, "analyses"):
        conn.close()
        raise HTTPException(503, "엔진 표가 아직 없습니다. 04_엔진/run_cycle.py 를 먼저 실행하세요.")
    version = _current_version(conn)
    rules = _rules_of(conn, version)
    w = rules.get("weights", {"macd": 4, "pair": 2, "vpci": 1})
    symbols_cfg = rules.get("symbols", list(NAMES))
    latest_t = None
    if version:
        latest_t = conn.execute("SELECT MAX(t_close) FROM analyses WHERE mode='live' AND rules_version=?",
                                (version,)).fetchone()[0]
    replay = _json(ENGINE / "reports" / "replay_summary.json") or {}
    same_replay = replay.get("rules_version") == version
    hints = replay.get("score_hint_reference", {}) if same_replay else {}
    ref = replay.get("periods", {}).get("reference", {})
    expl = None
    if latest_t is not None:
        r = conn.execute("SELECT source, model, body_json FROM explanations WHERE t_close=? AND rules_version=?",
                         (latest_t, version)).fetchone()
        if r:
            expl = {"source": r[0], "model": r[1], "body": json.loads(r[2])}
    expl_by = {it["symbol"]: it["text"] for it in (expl or {}).get("body", {}).get("items", [])}

    symbols = []
    for sym in symbols_cfg:
        a = None
        if latest_t is not None:
            a = conn.execute("SELECT * FROM analyses WHERE mode='live' AND rules_version=? AND symbol=? AND t_close=?",
                             (version, sym, latest_t)).fetchone()
        a = dict(a) if a else None
        ref_t = latest_t or now_ms() // H4 * H4
        spark = conn.execute("SELECT ts, close FROM candles WHERE source='binance' AND symbol=? AND period='4h' "
                             "AND ts>=? AND ts<? ORDER BY ts", (sym, ref_t - 7 * 86_400_000, ref_t)).fetchall()
        # 운영 기록에서 확실한 신호가 '새로 켜지거나 방향이 바뀐' 시점만 점으로(과거 재현은 섞지 않음)
        marks = []
        if version and spark:
            lo = spark[0][0] + H4
            rows = conn.execute(
                "SELECT t_close, strong, strong_dir FROM analyses WHERE mode='live' AND rules_version=? AND symbol=? "
                "AND status='ok' AND t_close<=? ORDER BY t_close", (version, sym, ref_t)).fetchall()
            prev = None
            for t, st, sd in rows:
                if st and (st, sd) != prev and t >= lo:
                    marks.append({"t": iso(t), "dir": sd})
                prev = (st, sd)
        item = {"symbol": sym, "short": SHORT.get(sym, sym), "name": NAMES.get(sym, sym),
                "spark": [{"t": iso(t + H4), "close": c} for t, c in spark], "strong_marks": marks,
                "market": _market(conn, sym), "now15": _now15(conn, sym, version)}
        if a and a["status"] == "ok" and a["score"] is not None:
            prev = conn.execute("SELECT close FROM candles WHERE source='binance' AND symbol=? AND period='4h' AND ts=?",
                                (sym, latest_t - 7 * H4)).fetchone()
            close = a["close"]
            hint = None
            hs = hints.get(sym, {}).get(str(a["score"]))
            if hs and a["score"] != 0:
                up = hs["up_pct"]
                hint = {"score": a["score"], "n": hs["n"], "period": f"{ref.get('from', '')}–{ref.get('to', '')}",
                        "dir_word": "오른" if a["score"] > 0 else "내린",
                        "match_pct": up if a["score"] > 0 else round(100 - up, 1)}
            item.update({
                "status": "ok", "close": close, "close_kst": kst(latest_t, "%H:%M"),
                "chg_24h_pct": round(100 * (close / prev[0] - 1), 2) if prev and prev[0] else None,
                "score": a["score"], "strong": bool(a["strong"]), "strong_dir": a["strong_dir"],
                "label": label(a["score"], a["strong"], a["strong_dir"], a["macd_dir"], a["pair_dir"], a["vpci_dir"], w),
                "indicators": _indicators(a, rules), "pair_dir": a["pair_dir"],
                "formula": _formula(a, w), "history_hint": hint, "explanation": expl_by.get(sym),
            })
            if a["strong"] and item.get("chg_24h_pct") is not None:
                item["chase"] = _chase_info(conn, version, sym, latest_t, a["strong_dir"], item["chg_24h_pct"],
                                            replay.get("chase") if same_replay else None,
                                            f"{ref.get('from', '')}–{ref.get('to', '')}")
        else:
            st = a["status"] if a else "none"
            item.update({"status": st, "label": STATUS_LABEL.get(st, "데이터 부족") if a else "분석 없음",
                         "explanation": expl_by.get(sym)})
        symbols.append(item)

    fng_series = [{"date": datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d"), "value": v}
                  for t, v in reversed(conn.execute(
                      "SELECT ts, value FROM series WHERE source='alternative.me' AND metric='fear_greed' "
                      "ORDER BY ts DESC LIMIT 30").fetchall())]
    fl = _kv(conn, "fng_latest")
    fl = json.loads(fl) if fl else {}
    latest_day_ms = conn.execute("SELECT MAX(ts) FROM series WHERE source='alternative.me' AND metric='fear_greed'"
                                 ).fetchone()[0]
    fng_class = fl.get("classification") if fl.get("timestamp") == latest_day_ms else None
    since_ms = conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live' AND rules_version=?",
                            (version,)).fetchone()[0] if version else None
    late_n = conn.execute(f"SELECT COUNT(*) FROM analyses WHERE mode='live' AND rules_version=? AND status='ok' "
                          f"AND created_at >= t_close + {ON_TIME}", (version,)).fetchone()[0] if version else 0
    prev = conn.execute("SELECT COUNT(*), MIN(t_close), MAX(t_close) FROM analyses WHERE mode='live' AND status='ok' "
                        "AND rules_version<>?", (version,)).fetchone() if version else (0, None, None)
    prev_versions = ({"n": prev[0], "from_kst": kst(prev[1]), "to_kst": kst(prev[2])} if prev and prev[0] else None)
    check = replay.get("periods", {}).get("check") if same_replay else None
    collectors = _json(COLLECT_CONF) or {}
    news_sources = [f["name"] for f in collectors.get("news", {}).get("feeds", []) if f.get("enabled", True)] \
        if collectors.get("enabled", {}).get("news") else []
    tb = _trigger_board(version)
    fng_events = [dict(e, **_fng_news(conn, e.get("btc_date") or e.get("date"), news_sources))
                  for e in ((tb or {}).get("fng_events") or []) if isinstance(e, dict)]
    out = {
        "generated_at": iso(now_ms()),
        "t_close": iso(latest_t), "t_close_kst": kst(latest_t),
        "next_t_close_kst": kst(latest_t + H4) if latest_t else None,
        "rules": {"version": version, "status": rules.get("status"), "weights": w},
        "explain": ({"source": expl["source"], "model": expl["model"], "overall": expl["body"].get("overall")}
                    if expl else None),
        "alerts": _alerts(conn, symbols_cfg, version),
        "symbols": symbols,
        "fng": {"value": fng_series[-1]["value"] if fng_series else None, "date": fng_series[-1]["date"] if fng_series else None,
                "classification": fng_class, "source": "alternative.me", "series": fng_series,
                # V5: 크게 움직인 날(엔진이 고름, 04_엔진/ai_analysis.fng_events) + 그 지수가 반영한 하루(btc_date)의 뉴스 제목
                "events": fng_events},
        "track": {"since_kst": kst(since_ms, "%m-%d %H:%M"), "rows": _summary(conn, "live", version) if version else [],
                  "late_n": late_n, "prev_versions": prev_versions,
                  "recent_strong": _recent_strong(conn, version), "all": _summary_all(conn)},
        "ai_report": _ai_report(conn, version),
        # 15분 확실한 신호(10-07): 마지막 계산 시각·종목별 성적·최근 바뀜. 표가 없으면 None(화면은 칸을 숨김)
        "strong15": _strong15_block(conn, version),
        "replay": ({"from": check["from"], "to_exclusive_kst": check.get("to_exclusive_kst"),
                    "reused": check.get("reused", False), "rows": check["rows"]} if check else None),
        "news": None if not collectors.get("enabled", {}).get("news") else _news(conn, news_sources),
        # 정미님 포맷 뉴스 브리핑 자리(10-05 포맷 수령 후 엔진이 채움). 없으면 화면에서 칸을 숨긴다
        "briefing": None,
        # 10-12 리팩토링: 트리거(공식 = 기술 조건 + AI 추세 일치)·채점·AI 분석(6대 분류)·Core Condition
        "v4": tb,
        # V5 8절: 가까운 과거 확신도 점검(04_엔진/confidence_replay.py, 참고 · 보정 전). 검증 화면 자료라 로컬 응답에만
        "conf_replay": _json(ENGINE / "reports" / "confidence_replay.json"),
    }
    conn.close()
    return out


NEWS_SOURCE_LABEL = {"naver_news": "네이버 뉴스 검색", "gdelt": "GDELT"}
NEWS_SINCE = "2026-10-03"   # 지금 켜진 뉴스 출처(네이버 뉴스 검색)의 기록 시작(UTC 날짜). 그 전 하루는 '뉴스 수집 전'


def _fng_news(conn, day: Optional[str], sources: list[str], n: int = 2) -> dict:
    """공포탐욕 사건 하루(UTC, KST 09:00–다음 날 09:00)에 게시된 BTC · CRYPTO 관련 제목 최대 n개와 없을 때 안내."""
    try:
        start = int(datetime.strptime(day or "", "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return {"news": [], "news_note": None}
    if (day or "") < NEWS_SINCE:
        return {"news": [], "news_note": "뉴스 수집 전"}
    if not sources or not _has_table(conn, "news"):
        return {"news": [], "news_note": "관련 뉴스 없음"}
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news)")}
    pub = "publisher" if "publisher" in cols else "NULL"
    q = ",".join("?" * len(sources))
    rows = conn.execute(f"SELECT title, url, {pub}, symbols FROM news WHERE source IN ({q}) AND published_at >= ? "
                        f"AND published_at < ? AND ((',' || symbols || ',') LIKE '%,BTC,%' OR (',' || symbols || ',') LIKE '%,CRYPTO,%') "
                        f"ORDER BY (',' || symbols || ',') LIKE '%,BTC,%' DESC, published_at DESC LIMIT 40",
                        (*sources, start, start + 86_400_000)).fetchall()
    out, seen = [], set()
    for t, u, pb, _ in rows:
        key = (t or "").strip().lower()[:40]
        if not t or key in seen or not str(u).startswith(("https://", "http://")):
            continue
        seen.add(key)
        out.append({"title": t, "url": u, "publisher": pb or ""})
        if len(out) >= n:
            break
    return {"news": out, "news_note": None if out else "관련 뉴스 없음"}


def _news(conn, sources: list[str], per_symbol: int = 2, hours: int = 48):
    """켜진 출처(conf news.feeds[].enabled)의 코인 관련 제목, 최근 hours 시간. 약관 때문에 꺼 둔 RSS 는 보여주지 않는다.
    한 종목 기사가 목록을 다 차지하지 않게 종목별(BTC·ETH·XRP·일반) 최신 per_symbol 건씩 모아 시각순으로."""
    if not sources or not _has_table(conn, "news"):
        return []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(news)")}
    pub = "publisher" if "publisher" in cols else "NULL"
    q = ",".join("?" * len(sources))
    now = now_ms()
    # 종목마다 따로 후보를 뽑는다(10-04 GPT-6.1 Sol 재현: 전체 최신 400건 제한 때문에 한 종목 기사가 많으면 다른 종목이 빠짐).
    # 여러 종목 기사는 먼저 뽑힌 종목 몫으로 한 번만. 발행 시각이 지금보다 10분 넘게 미래면 시계 오류로 보고 뺀다.
    picked, seen_urls, seen_titles = [], set(), set()
    for key in ("BTC", "ETH", "XRP", "CRYPTO"):
        cand = conn.execute(f"SELECT source, title, url, published_at, symbols, {pub} FROM news "
                            f"WHERE (',' || symbols || ',') LIKE ? AND source IN ({q}) AND published_at >= ? "
                            f"AND published_at <= ? ORDER BY published_at DESC LIMIT 40",
                            (f"%,{key},%", *sources, now - hours * 3_600_000, now + 10 * 60_000)).fetchall()
        n = 0
        for r in cand:
            title_key = r[1].strip().lower()[:40]
            if n >= per_symbol:
                break
            if r[2] in seen_urls or title_key in seen_titles:
                continue
            seen_urls.add(r[2]); seen_titles.add(title_key)
            picked.append(r); n += 1
    rows = sorted(picked, key=lambda r: r[3] or 0, reverse=True)
    return [{"source": s, "source_label": NEWS_SOURCE_LABEL.get(s, s), "publisher": pb or s, "title": t, "url": u,
             "published": iso(p), "published_kst": kst(p), "symbols": sy}
            for s, t, u, p, sy, pb in rows if str(u).startswith(("https://", "http://"))]


@router.get("/api/analyses")
def analyses(symbol: Optional[str] = None, limit: int = Query(60, ge=1, le=500), all_versions: bool = False,
             request: Request = None):
    """지난 분석 목록(운영 기록만). 4시간 뒤 결과 포함. 기본은 현재 규칙만, all_versions=true 면 이전 규칙 기록도.
    검증 화면 자료라 공개 요청에는 같은 모양의 빈 목록(DB 를 읽지 않음)."""
    if pub.is_public(request):
        return pub.analyses_blank(all_versions)
    conn = _db()
    if not _has_table(conn, "analyses"):
        conn.close()
        return {"count": 0, "data": [], "scope": "local"}
    version = _current_version(conn)
    sql = ("SELECT a.symbol, a.t_close, a.rules_version, a.status, a.close, a.score, a.strong, a.strong_dir, "
           "a.macd_dir, a.sto_state, a.srsi_state, a.pair_dir, a.vpci_dir, a.created_at, o.next_close, o.ret, o.hit "
           "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close "
           "AND o.rules_version=a.rules_version AND o.mode=a.mode WHERE a.mode='live'")
    p: list = []
    if symbol:
        sql += " AND a.symbol=?"; p.append(symbol)
    if not all_versions and version:
        sql += " AND a.rules_version=?"; p.append(version)
    sql += f" ORDER BY a.t_close DESC, a.symbol, a.rules_version={'?' if version else '0'} DESC, a.created_at DESC LIMIT ?"
    if version:
        p.append(version)
    p.append(limit)
    other_n = conn.execute("SELECT COUNT(*) FROM analyses WHERE mode='live' AND rules_version<>?",
                           (version,)).fetchone()[0] if version else 0
    weights_cache = {}
    out = []
    for r in conn.execute(sql, p).fetchall():
        d = dict(r)
        v = d["rules_version"]
        if v not in weights_cache:
            weights_cache[v] = _rules_of(conn, v).get("weights")
        d["t_kst"] = kst(d["t_close"], "%Y-%m-%d %H:%M")
        d["label"] = label(d["score"], d["strong"], d["strong_dir"], d["macd_dir"], d["pair_dir"], d["vpci_dir"],
                           weights_cache[v], d["status"])
        d["current_rules"] = v == version
        ca = d.pop("created_at", None)
        d["late"] = bool(ca and ca >= d["t_close"] + ON_TIME)  # T부터 1시간 넘게 지나 만든 분석(성적에서 뺌)
        out.append(d)
    conn.close()
    return {"count": len(out), "data": out, "other_versions_n": other_n, "all_versions": all_versions, "scope": "local"}


@router.get("/api/replay")
def replay(request: Request = None):
    """과거 재현 요약. 채점 자료라 공개 요청에는 같은 모양의 빈 값(파일을 읽지 않음)."""
    if pub.is_public(request):
        return pub.replay_blank()
    data = _json(ENGINE / "reports" / "replay_summary.json")
    if data is None:
        raise HTTPException(404, "재현 요약이 없습니다. 04_엔진/replay.py 를 실행하세요.")
    return {**data, "scope": "local"}


@router.get("/api/engine")
def engine_status(request: Request = None):
    """데이터 상태 탭: 수집·엔진 상태. 공개 요청이면 수집·자료 신선도만(public_scope.engine_view)."""
    full = _engine_full()
    return pub.engine_view(full) if pub.is_public(request) else {**full, "scope": "local"}


def _engine_full() -> dict:
    """맥에서 보는 데이터 상태 전체(디스코드·배포·채점 보류 포함)."""
    conn = _db()
    eng = _json(ENGINE / "conf" / "engine.json") or {}
    collectors = _json(COLLECT_CONF) or {}
    last_run = conn.execute("SELECT run_id, started_at, finished_at, ok_calls, failed_calls, rows_new FROM run_log "
                            "ORDER BY run_id DESC LIMIT 1").fetchone()
    candles = [dict(zip(["symbol", "period", "n", "min_ts", "max_ts"], tuple(r))) for r in conn.execute(
        "SELECT symbol, period, COUNT(*), MIN(ts), MAX(ts) FROM candles WHERE source='binance' AND period IN "
        "('15m','1h','4h') GROUP BY symbol, period ORDER BY symbol, period").fetchall()]
    per_ms = {"15m": 900_000, "1h": 3_600_000, "4h": H4}
    for c in candles:   # 끝은 마지막 봉의 '마감' 시각(시작 시각이면 4시간봉이 17:00에 멈춘 것처럼 보임, 10-04 Fable)
        c["from_kst"], c["to_kst"] = kst(c["min_ts"], "%Y-%m-%d"), kst(c["max_ts"] + per_ms[c["period"]], "%Y-%m-%d %H:%M")
    fng = conn.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM series WHERE metric='fear_greed'").fetchone()
    engine_last = _kv(conn, "engine_last_run")
    cur_v = _current_version(conn)
    disc = None
    if _has_table(conn, "discord_log"):
        r = conn.execute("SELECT t_close, status FROM discord_log ORDER BY t_close DESC LIMIT 1").fetchone()
        disc = {"t_kst": kst(r[0]), "status": r[1]} if r else None
    out = {
        "collector": {"last_run_kst": kst(last_run[1], "%m-%d %H:%M:%S") if last_run else None,
                      "ok_calls": last_run[3] if last_run else None, "failed_calls": last_run[4] if last_run else None,
                      "schedule": "매시 01·16·31·46분 (15분봉 마감 1분 뒤)",
                      "enabled": {k: v for k, v in collectors.get("enabled", {}).items() if not k.startswith("_")}},
        "engine": {"cycle_enabled": eng.get("cycle_enabled"), "last_run_kst": kst(int(engine_last), "%m-%d %H:%M:%S")
                   if engine_last else None, "live_start": _kv(conn, "live_start"),
                   "live_start_kst": kst(_iso_ms(_kv(conn, "live_start")), "%Y-%m-%d %H:%M"),
                   "rules_version": cur_v, "rules_status": _rules_of(conn, cur_v).get("status") if cur_v else None,
                   "rules_since_kst": kst(conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live' AND "
                                                       "rules_version=?", (cur_v,)).fetchone()[0]) if cur_v else None},
        "candles": candles,
        "fear_greed": {"n": fng[0], "from": kst(fng[1], "%Y-%m-%d"), "to": kst(fng[2], "%Y-%m-%d"),
                       "source": "alternative.me"},
        "discord": disc,
        # 15분 확실한 신호(10-07): 마지막 계산 시각과 기록 수. 표가 없으면 None
        "strong15": ({"last_run_kst": kst(int(_kv(conn, "strong15_last_run")), "%m-%d %H:%M:%S")
                      if _kv(conn, "strong15_last_run") else None,
                      "rows": conn.execute("SELECT COUNT(*) FROM strong15 WHERE rules_version=?", (cur_v,)).fetchone()[0]
                      if cur_v else 0} if _has_table(conn, "strong15") else None),
        "news": _news_status(conn, collectors),
        "snapshot_deploy": _snapshot_deploy_status(),
        # 다음 봉이 깨져 채점을 미룬 분석(8시간 넘게 결과 없음). 0이면 화면에 안 보임
        "scoring_held": conn.execute(
            "SELECT COUNT(*) FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close "
            "AND o.rules_version=a.rules_version AND o.mode=a.mode WHERE a.mode='live' AND a.status='ok' "
            "AND a.rules_version=? AND o.t_close IS NULL AND a.t_close + ? < ?",
            (cur_v, 2 * H4, now_ms())).fetchone()[0] if cur_v else 0,
    }
    conn.close()
    return out


def _snapshot_deploy_status():
    """Vercel 저장본 배포(deploy_vercel.sh)가 남긴 마지막 성공·실패. 실패가 더 최근이면 failing."""
    d = _json(REPO / "03_백엔드" / "logs" / "snapshot-deploy.status.json")
    if not d:
        return None
    ok, fail = d.get("last_ok_ms"), d.get("last_fail_ms")
    return {"last_ok_kst": kst(ok, "%m-%d %H:%M") if ok else None,
            "last_fail_kst": kst(fail, "%m-%d %H:%M") if fail else None,
            "failing": bool(fail and (not ok or fail > ok)), "last_error": d.get("last_error")}


def _news_status(conn, collectors) -> list[dict]:
    """데이터 상태 탭용: 켜진 뉴스 출처별 마지막 요청 시각과 최근 48시간 건수(키 대기·거절을 알 수 있게)."""
    out = []
    if not collectors.get("enabled", {}).get("news"):
        return out
    since = now_ms() - 48 * 3_600_000
    for f in collectors.get("news", {}).get("feeds", []):
        if not f.get("enabled", True):
            continue
        last = _kv(conn, f"news_last_fetch:{f['name']}")
        ok = _kv(conn, f"news_last_ok:{f['name']}")
        n = conn.execute("SELECT COUNT(*) FROM news WHERE source=? AND published_at>=?", (f["name"], since)).fetchone()[0] \
            if _has_table(conn, "news") else 0
        out.append({"name": f["name"], "label": NEWS_SOURCE_LABEL.get(f["name"], f["name"]),
                    "last_try_kst": kst(int(last), "%m-%d %H:%M") if last else None,
                    "last_ok_kst": kst(int(ok), "%m-%d %H:%M") if ok else None,
                    "last_error": _kv(conn, f"news_last_error:{f['name']}") or None, "n_48h": n})
    return out


# ---- 공부 탭: 01_운영/공부노트 의 마크다운을 그대로 내려준다(화면에서 이스케이프 후 렌더링) ----
_STUDY_NAME = re.compile(r"^[0-9]{2}_[^/\\]+\.md$")


_STUDY_SHORT = {"00": "목차", "05": "5장 왜 화제인가·전망", "06": "6장 지표와 연구", "07": "7장 우리 프로젝트"}   # 10-13 v4: 안내 → 목차


def _short_title(name: str) -> str:
    """목차 버튼용 짧은 제목. 파일 이름에서 만든다(예: 02_비트코인.md → 2장 비트코인)."""
    num, rest = name[:2], name[3:-3].replace("_", " ")
    return _STUDY_SHORT.get(num, f"{int(num)}장 {rest}")


@router.get("/api/study")
def study_index(request: Request = None):
    """공부 노트 목록. 공개 요청이면 팀 내부 장(public_scope.STUDY_LOCAL_ONLY)을 뺀다."""
    public = pub.is_public(request)
    out = []
    for p in sorted(STUDY.glob("*.md")):
        if not _STUDY_NAME.match(p.name) or not pub.study_visible(p.name, public):
            continue
        first = p.read_text(encoding="utf-8").splitlines()[:1]
        out.append({"name": p.name, "title": first[0].lstrip("# ").strip() if first else p.name,
                    "short": _short_title(p.name)})
    return {"count": len(out), "data": out}


@router.get("/api/study/{name}")
def study_doc(name: str, request: Request = None):
    if not _STUDY_NAME.match(name):
        raise HTTPException(400, "잘못된 이름")
    path = (STUDY / name).resolve()
    if path.parent != STUDY.resolve() or not path.exists():
        raise HTTPException(404, "없음")
    if pub.is_public(request) and (not pub.study_visible(name, True) or _same_file_as_hidden(path)):
        raise HTTPException(404, "없음")   # 공개 요청의 팀 내부 장도 '없는 장'과 똑같이 404
    return {"name": name, "markdown": path.read_text(encoding="utf-8")}


def _same_file_as_hidden(path: Path) -> bool:
    """이름 표기(유니코드 정규화 등)가 달라도 같은 파일이면 숨긴 장으로 본다."""
    for h in pub.STUDY_LOCAL_ONLY:
        try:
            if path.samefile(STUDY / h):
                return True
        except OSError:
            continue
    return False


# ---- 지표 그래프: 엔진이 15분마다 쓰는 reports/charts/<SYMBOL>.json 을 기간만 잘라 내려준다(계산하지 않음) ----
_CHART_SYMBOL = re.compile(r"^[A-Z0-9]{2,15}USDT$")
CHART_DIR = ENGINE / "reports" / "charts"
STALE_MS = 30 * 60_000


@router.get("/api/chart/{symbol}")
def chart(symbol: str, days: int = Query(3, ge=1, le=7), request: Request = None):
    """기획안_지표그래프 §6. days = 1·3·7(그 사이 값도 허용). 시각은 봉 마감 시각(UTC ms).
    공개 요청이면 가격·지표 선만(4시간 분석 점수 표시·판정 교차 사건·판정 기준선은 비움, public_scope.chart_view)."""
    out = _chart_full(symbol, days)
    return pub.chart_view(out) if pub.is_public(request) else {**out, "scope": "local"}


def _chart_full(symbol: str, days: int) -> dict:
    if not _CHART_SYMBOL.match(symbol):
        raise HTTPException(400, "잘못된 종목")
    data = _json(CHART_DIR / f"{symbol}.json")
    if data is None:
        raise HTTPException(404, "그래프 데이터가 아직 없습니다. 엔진 사이클이 한 번 돌아야 합니다.")
    end = max([data["price"]["t"][-1]] if data["price"]["t"] else [0])
    since = end - days * 86_400_000

    def cut(block):
        t = block.get("t", [])
        i = next((k for k, x in enumerate(t) if x >= since), len(t))
        i = max(0, i - 1)   # 경계 직전 봉 1개를 넣어 선이 칸 왼쪽 밖에서 들어오게(4시간봉의 왼쪽 공백 방지, 칸 밖은 잘림)
        return {k: v[i:] for k, v in block.items()}

    out = {k: data[k] for k in ("symbol", "rules_version", "generated_at", "generated_ms", "last_close", "zone")}
    out.update({k: cut(data[k]) for k in ("price", "macd", "sto", "srsi", "vpci")})
    out["events"] = [e for e in data["events"] if e["t"] >= since]
    out["analyses"] = [a for a in data["analyses"] if a["t"] >= since]
    out["gaps"] = [g for g in data["gaps"] if g["to"] >= since]
    out["days"] = days
    out["range"] = {"from": since, "to": end}
    out["generated_kst"] = kst(data["generated_ms"], "%H:%M")
    out["last_close_kst"] = {k: kst(v, "%m-%d %H:%M") for k, v in data["last_close"].items()}
    # 지연 판단은 파일 생성 시각이 아니라 마지막으로 닫힌 15분봉 기준(수집이 멈췄는데 엔진만 돌아도 잡히게)
    last15 = (data.get("last_close") or {}).get("15m") or 0
    out["stale"] = now_ms() - int(last15) > STALE_MS + 15 * 60_000
    return out
