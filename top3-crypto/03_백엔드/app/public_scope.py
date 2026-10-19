"""공개 범위(2026-10-13 결정 84-A): 공개 화면에 내보내는 것과 맥에서만 보는 것을 이 파일 한곳에서 정한다.

- 공개: 확신도 KPI(v4.confidence, 계산식·신호 행 포함), 지표 그래프 선, 7일 가격선(spark), AI 분석(v4.ai, 기사 표지·항목별 비중
  포함), 뉴스, 공포탐욕지수(크게 움직인 날 포함), 코인별 Core Condition 충족 여부(상태만), 매매 트리거 기록(시각·코인·방향·진입가
  = 디스코드 메시지와 같은 내용), AI 분석 마지막 시도의 짧은 사유(사용 한도·다시 시도할 시각·대신 분석한 모델).
- 맥에서만(검증 화면): 매매 조건(지표 조합·순서·설정값·가중치)과 채점(성공·실패, 성공률, MFE/MAE,
  과거 재현, AI 게이트 확인 기록, 4시간 분석 점수).
- 공개 응답은 아래 목록에 적은 키만 골라 담는다(화이트리스트). 엔진·보드에 새 필드가 생겨도 여기에 적기 전에는 공개되지 않는다.
  V5(10-14): 안쪽 객체(AI 분석·마지막 시도·확신도·공포탐욕)도 키 목록으로 새 객체를 만들어 담는다. 원문 실패 사유(note)는 로컬만.
- 팀 논의 뒤 범위를 바꾸려면 이 파일의 목록만 고친다. 시험: 03_백엔드/tests/test_public_scope.py
"""
from __future__ import annotations

import ipaddress
import unicodedata
from typing import Optional

# ---------------------------------------------------------------- 1. 요청이 공개인지
# 맥에서 직접 연 요청(프록시 머리글 없음 + Host 가 루프백 이름 + 접속 IP 가 루프백)만 로컬. 하나라도 어긋나면 공개.
# Funnel(https://<맥>.ts.net/api)은 맥 안의 프록시가 127.0.0.1 로 넘기므로 접속 IP 만으로는 알 수 없다 → 머리글·Host 로 가린다.
PUBLIC_HEADER = "x-top3-public"   # 저장본 만들기(scripts/export_snapshot.py)가 붙임. 값과 상관없이 있으면 공개
PROXY_HEADERS = frozenset({"x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded",
                           "tailscale-funnel-request"})
PROXY_PREFIX = "tailscale-"       # Tailscale 프록시가 붙이는 머리글(Tailscale-User-Login 등)
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _hostname(host: str) -> str:
    """Host 머리글에서 포트를 뗀 이름. '[::1]:8765' → '::1', '127.0.0.1:8765' → '127.0.0.1'."""
    h = (host or "").strip().lower()
    if h.startswith("["):
        return h[1:h.index("]")] if "]" in h else h
    return h.split(":", 1)[0] if h.count(":") == 1 else h


def _loopback(ip: Optional[str]) -> bool:
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:            # 'testclient' 같은 이름, 빈 값
        return False
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_loopback


def is_public(request) -> bool:
    """공개 요청이면 True. request 가 None 이면 HTTP 가 아닌 같은 프로세스 안의 호출(시험·스크립트)이라 로컬로 본다.
    (FastAPI 는 경로 함수에 Request 를 늘 넣어 주므로 바깥 요청이 None 으로 들어오는 일은 없다.)"""
    if request is None:
        return False
    try:
        headers = request.headers
        names = {k.lower() for k in headers.keys()}
        if PUBLIC_HEADER in names or names & PROXY_HEADERS or any(n.startswith(PROXY_PREFIX) for n in names):
            return True
        if _hostname(headers.get("host", "")) not in LOCAL_HOSTS:
            return True
        client = request.client
        return not (client is not None and _loopback(client.host))
    except Exception:             # 판단이 애매하면 공개
        return True


def scope_name(request) -> str:
    return "public" if is_public(request) else "local"


# ---------------------------------------------------------------- 2. 공개 응답에 담는 것(화이트리스트)
# /api/board
BOARD_KEYS = ("generated_at", "t_close", "t_close_kst", "briefing")
ALERT_KEYS = ("kind", "text")                            # 데이터 · 분석 지연 안내
NEWS_KEYS = ("source", "source_label", "publisher", "title", "url", "published", "published_kst", "symbols")
RULES_KEYS = ("version", "status")                       # 가중치(weights)는 뺌
SYMBOL_KEYS = ("symbol", "short", "name", "market", "spark")   # 4시간 분석 점수·지표별 방향·계산식·확실한 신호·15분 신호는 뺌
SPARK_KEYS = ("t", "close")                              # V5 7일 가격선(4시간봉 종가). strong_marks 는 계속 비공개
V4_KEYS = ("generated_at", "rules_version", "live_start")
# AI 분석(공개 결정): 본문은 스키마로 정해진 칸 + 코드가 더한 뉴스 방향·기사 목록·뺀 기사 수
AI_LATEST_KEYS = ("created_at", "created_kst", "ref_kst", "kind", "ref_t", "trend_dir", "confidence_pct", "model", "source", "body")
AI_BODY_KEYS = ("trend_direction", "expected_change_pct", "expected_price_range", "summary_reasoning", "confidence_level",
                "confidence_pct", "key_signals", "risks", "news_analysis", "fear_greed_analysis", "coinbase_premium",
                "open_interest", "technical", "current_price", "news_items", "factor_weights", "news_bias", "news_ref",
                "news_filtered")
LAST_TRY_KEYS = ("created_kst", "ok", "code", "retry_at_kst", "retry_est", "model", "fallback_from")   # 원문 note 는 뺌
# 확신도(conf_v2, 기획안 v5 1절 4 출력 계약). 계산식·가중치는 공개 정보
CONF_KEYS = ("version", "p_long", "side", "side_pct", "level", "label", "score", "coverage_pct", "support_pct", "groups",
             "missing", "note", "formula", "signals", "ref_t", "ref_kst", "price")
CONF_GROUP_KEYS = ("score", "coverage_pct", "used", "missing")
CONF_SIGNAL_KEYS = ("key", "name", "group", "w", "x", "used", "value", "note")
CONF_META = ("_errors", "_at")
# 공포탐욕지수(크게 움직인 날의 뉴스 제목은 공개 뉴스 띠와 같은 자료)
FNG_KEYS = ("value", "date", "classification", "source", "series", "events")
FNG_SERIES_KEYS = ("date", "value")
FNG_EVENT_KEYS = ("date", "value", "delta", "btc_date", "btc_chg_pct", "news", "news_note")
FNG_NEWS_KEYS = ("title", "url", "publisher")
CORE_KEYS = ("t", "state", "ok")                         # Core Condition 은 충족 여부만(단계별 h4·h1·m15 는 뺌)
CORE_META = ("_at",)
TRIGGER_KEYS = ("symbol", "short", "t_bar", "issued_at", "dir", "entry")   # 디스코드 메시지와 같은 내용(결과·수익률은 뺌)
# 뺀 것(참고): rules.weights, explain, track, ai_report, strong15, replay, next_t_close_kst,
#             v4.conf, v4.stats, v4.recent.tech, v4.recent.checks, 트리거 결과(result·mfe·mae·ret)

# /api/chart/{symbol}: 가격·지표 선은 그대로, 4시간 분석 점수 표시·판정 교차 사건·판정 기준선은 비움
CHART_KEYS = ("symbol", "rules_version", "generated_at", "generated_ms", "last_close", "price", "macd", "sto", "srsi",
              "vpci", "gaps", "days", "range", "generated_kst", "last_close_kst", "stale")
CHART_BLANK = {"events": [], "analyses": [], "zone": None}

# /api/engine(데이터 상태): 수집·자료 신선도만. 디스코드·배포·채점 보류·15분 확실한 신호·규칙 시작 시각은 뺌
ENGINE_COLLECTOR_KEYS = ("last_run_kst", "ok_calls", "failed_calls", "schedule", "enabled")
ENGINE_ENGINE_KEYS = ("cycle_enabled", "last_run_kst", "live_start", "live_start_kst", "rules_version", "rules_status")
ENGINE_CANDLE_KEYS = ("symbol", "period", "n", "min_ts", "max_ts", "from_kst", "to_kst")
ENGINE_FNG_KEYS = ("n", "from", "to", "source")
ENGINE_NEWS_KEYS = ("name", "label", "last_try_kst", "last_ok_kst", "last_error", "n_48h")

# 공부 탭: 공개 화면에서 목록에서 빼고 직접 열어도 404. 7장은 매매 조건·12시간 규칙·채점·과거 재현 결과를 설명한다
STUDY_LOCAL_ONLY = frozenset({"07_우리_프로젝트는_어떻게_돌아가나.md"})


# 검증 화면(맥에서만)의 설명 문장: 매매 조건 논리·채점 정의가 들어 있어 화면 파일(index.html·app.js)에 두지 않고
# 로컬 /api/board 응답의 verify_text 로만 보낸다. 공개 응답은 화이트리스트(BOARD_KEYS)에 없으므로 빠진다.
LOCAL_VERIFY_TEXT = {
    "tip_scoring": "공식 트리거(Core Condition + AI 추세 일치)와 기술 조건만 따른 트리거를 같은 기준으로 셉니다. 성공 = 다음 트리거까지 최대수익률이 수수료를 빼고 기준 이상(기준값은 아래 설명 줄). 성공률은 다음 트리거가 나서 끝난 것만 셉니다. '같은 구간 항상 Long'·'반대 방향'은 같은 시각·구간에 늘 Long이었다면·반대로 들어갔다면의 성공률이고, '양쪽 다'는 두 방향 모두 기준을 넘은 비율입니다. 끝난 것이 30건 미만이면 표본 부족입니다.",
    "tip_ind": "Core Condition을 이루는 세 단계(4시간·1시간·15분)의 지금 방향과, 마지막 4시간봉 기준 기술 점수(2차 회의 정의: 기술 지표 4개 가중 점수, −100–+100)입니다.",
    "tip_old": "10-12 리팩토링 전의 방식입니다. 4시간마다 기술 점수와 확실한 신호를 내고, 다음 4시간봉 종가 방향으로 채점했습니다. 지난 기록과 이어 보도록 참고로만 남깁니다.",
    "held_note": "1시간 조건 보류 · Stochastic이나 StochRSI가 80 이상에서 꺾여 내려오는 중(조건서 '가짜 신호 거르기')",
    "seq_hint": "세 단계가 같은 방향이지만 VPCI(15분)가 4시간·1시간이 맞춰지기 전에 돌아서 확실한 신호가 아닙니다. 조건서대로 정렬된 뒤 VPCI가 다시 돌면 확실한 신호가 됩니다.",
    "replay_note": "같은 규칙을 과거 15분봉마다 적용한 결과입니다(규칙을 고르는 데 쓰지 않음). AI 추세는 과거 시점의 판단이 없어 재현하지 않고 운영 기록에서만 셉니다. Long 트리거는 '항상 Long'이 트리거 자신과 같은 값이라, 방향을 맞힌 효과는 '같은 구간 반대 방향'과 비교해야 보입니다. 다음 트리거까지 창이 최소 12시간이라 이 성공 기준은 변동성만으로도 어느 방향이든 넘기 쉽습니다('양쪽 다' 열).",
    "conf_replay_note": "최근 1년 4시간봉 마감마다 지금 식(확신도 v2)으로 계산하고, 다음 4시간·24시간 종가 방향이 확신도의 우세 쪽과 같았던 비율입니다. 과거 AI 분석이 없어 뉴스 방향은 빠졌습니다. '오른 비율'은 같은 시점들에서 늘 Long이었다면의 적중입니다. 확률을 맞추는 데(보정) 쓰지 않았고, 4시간마다의 판정은 서로 겹쳐 독립 시행이 아닙니다.",
    "score_note": "최대수익률·손익은 수수료(왕복)를 뺀 값입니다. 두 방식은 각자 12시간 금지와 '다음 트리거'를 따로 셉니다. 트리거가 드물수록 다음 트리거까지 구간이 길어져 최대수익률이 커지기 쉬우므로, 방식끼리 성공률을 바로 비교하기보다 각 방식의 '같은 구간 항상 Long'과의 차이를 보세요.",
}


def _pick(d, keys) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k) for k in keys}


def _rows(v, keys) -> list:
    return [_pick(x, keys) for x in (v or []) if isinstance(x, dict)] if isinstance(v, list) else []


def _symbol_view(s: dict) -> dict:
    out = _pick(s, SYMBOL_KEYS)
    out["spark"] = _rows(s.get("spark"), SPARK_KEYS)
    return out


def fng_view(f) -> Optional[dict]:
    if not isinstance(f, dict):
        return None
    out = _pick(f, FNG_KEYS)
    out["series"] = _rows(f.get("series"), FNG_SERIES_KEYS)
    out["events"] = [dict(_pick(e, FNG_EVENT_KEYS), news=_rows(e.get("news"), FNG_NEWS_KEYS))
                     for e in (f.get("events") or []) if isinstance(e, dict)]
    return out


def ai_view(node) -> Optional[dict]:
    """v4.ai[코인] = {latest, last_try}."""
    if not isinstance(node, dict):
        return None
    latest = node.get("latest")
    if isinstance(latest, dict):
        latest = _pick(latest, AI_LATEST_KEYS)
        latest["body"] = _pick(latest["body"], AI_BODY_KEYS) if isinstance(latest["body"], dict) else None
    else:
        latest = None
    last = node.get("last_try")
    return {"latest": latest, "last_try": _pick(last, LAST_TRY_KEYS) if isinstance(last, dict) else None}


def conf_view(c) -> Optional[dict]:
    """v4.confidence[코인]."""
    if not isinstance(c, dict):
        return None
    out = _pick(c, CONF_KEYS)
    g = c.get("groups")
    out["groups"] = {k: _pick(v, CONF_GROUP_KEYS) for k, v in g.items() if isinstance(v, dict)} if isinstance(g, dict) else None
    out["signals"] = _rows(c.get("signals"), CONF_SIGNAL_KEYS)
    return out


def board_view(full: dict) -> dict:
    """/api/board 공개 응답."""
    out = _pick(full, BOARD_KEYS)
    out["alerts"] = _rows(full.get("alerts"), ALERT_KEYS)
    out["news"] = _rows(full.get("news"), NEWS_KEYS) if isinstance(full.get("news"), list) else None
    out["fng"] = fng_view(full.get("fng"))
    out["rules"] = _pick(full.get("rules"), RULES_KEYS)
    out["symbols"] = [_symbol_view(s) for s in (full.get("symbols") or []) if isinstance(s, dict)]
    out["v4"] = v4_view(full.get("v4"))
    out["scope"] = "public"
    return out


def v4_view(v4) -> Optional[dict]:
    if not isinstance(v4, dict):
        return None
    out = _pick(v4, V4_KEYS)
    ai = v4.get("ai")
    out["ai"] = {k: ai_view(v) for k, v in ai.items() if not str(k).startswith("_")} if isinstance(ai, dict) else None
    cf = v4.get("confidence")
    if isinstance(cf, dict):
        out["confidence"] = {k: conf_view(v) for k, v in cf.items() if not str(k).startswith("_")}
        out["confidence"].update({k: cf[k] for k in CONF_META if k in cf})
    else:
        out["confidence"] = None
    core = v4.get("core")
    if isinstance(core, dict):
        out["core"] = {k: (_pick(v, CORE_KEYS) if isinstance(v, dict) else None)
                       for k, v in core.items() if not k.startswith("_")}
        out["core"].update({k: core[k] for k in CORE_META if k in core})
    else:
        out["core"] = None
    official = (v4.get("recent") or {}).get("official") if isinstance(v4.get("recent"), dict) else None
    out["recent"] = {"official": [_pick(r, TRIGGER_KEYS) for r in (official or []) if isinstance(r, dict)]}
    return out


def chart_view(full: dict) -> dict:
    """/api/chart/{symbol} 공개 응답."""
    out = _pick(full, CHART_KEYS)
    out.update({k: (list(v) if isinstance(v, list) else v) for k, v in CHART_BLANK.items()})
    out["scope"] = "public"
    return out


def engine_view(full: dict) -> dict:
    """/api/engine(데이터 상태) 공개 응답."""
    return {
        "collector": _pick(full.get("collector"), ENGINE_COLLECTOR_KEYS),
        "engine": _pick(full.get("engine"), ENGINE_ENGINE_KEYS),
        "candles": [_pick(c, ENGINE_CANDLE_KEYS) for c in (full.get("candles") or []) if isinstance(c, dict)],
        "fear_greed": _pick(full.get("fear_greed"), ENGINE_FNG_KEYS),
        "news": [_pick(n, ENGINE_NEWS_KEYS) for n in (full.get("news") or []) if isinstance(n, dict)],
        "scope": "public",
    }


def analyses_blank(all_versions: bool) -> dict:
    """/api/analyses 공개 응답: 지난 4시간 분석(점수·적중)은 검증 화면 자료라 비운다. 모양은 로컬 응답과 같다."""
    return {"count": 0, "data": [], "other_versions_n": 0, "all_versions": bool(all_versions), "scope": "public"}


def replay_blank() -> dict:
    """/api/replay 공개 응답: 과거 재현 요약(replay_summary.json)과 같은 모양, 값은 비움."""
    return {"rules_version": None, "rules_status": None, "generated_at": None, "live_start": None,
            "end_exclusive": None, "replaced_rows": None, "tries_log_len": None, "check_reused": None,
            "periods": {"reference": None, "check": None}, "score_hint_reference": {}, "chase": None, "notes": [],
            "scope": "public"}


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def study_visible(name: str, public: bool) -> bool:
    """공개 요청에서 이 장을 보여 줘도 되는지. 맥 파일 시스템은 한글 이름의 NFC·NFD 를 같은 파일로 찾으므로 NFC 로 맞춰 비교
    (board.study_doc 은 파일이 같은지도 한 번 더 본다)."""
    return not (public and _nfc(name) in {_nfc(x) for x in STUDY_LOCAL_ONLY})
