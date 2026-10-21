"""알프레도 MVP 데모 만들기 (V1, 2026-10-13. 처음 판 2026-10-08).

합성 시나리오를 알프레도 엔진 v0(장부·원칙 판정)으로 돌려 공개용 데모 데이터와 메일 첨부용 HTML 한 파일을 만든다.

- 가격: 시드를 고정한 **합성 가격**(실제 시세 아님, 10-13 호연 결정: 막힌작업 10-08 9번 B). 빌드 중 바깥 호출을 막는다.
- 배분: 보수·중립·적극 예시 템플릿(주식·채권·금·코인·현금, D-1013-9 a). 모두에게 같은 예시이며 추천이 아니다.
- 공개 범위: 내보내는 키는 PUBLIC_SCHEMA에 적은 것만 나간다. 목록 밖 키가 나오면 빌드를 멈춘다(Top3 public_scope와 같은 생각).
- 개인 자료: personal 경로·비공개 폴더를 여는 순간 빌드를 멈춘다(감사 훅). 이 스크립트는 개인 자료를 읽을 일이 없다.
- 체결: 결정은 그날 종가를 보고, 체결은 다음 날 시가(설계서 fill_rule). 비용은 설계서 기본(수수료 0.05%, 슬리피지 0.10%).

실행(저장소 루트에서): python3 -I mvp/build_demo.py
결과: mvp/data/demo_week.json·demo_week.js, mvp/dist/alfredo_mvp_demo.html(데이터·글꼴을 넣은 한 파일)
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MVP = os.path.join(ROOT, "mvp")
DATA = os.path.join(MVP, "data")
DIST = os.path.join(MVP, "dist")
FONT_DIR = os.path.join(MVP, "fonts")
FONT_SRC = os.path.join(FONT_DIR, "src", "PretendardVariable.ttf")  # git 제외. 받는 곳은 fonts/README.md
FONT_OUT = os.path.join(FONT_DIR, "AlfredoSans-subset.woff")          # 쓰는 글자만 남기고 이름을 바꾼 것(OFL 예약 이름)
FONT_FAMILY = "AlfredoSans"

# ---------- 지킴이: 개인 경로·바깥 호출 막기 ----------
PERSONAL_MARKERS = ("data/alfredo/personal", "Alfredo_private", "alfredo_link", "05_no-vault", "banksalad", "/.env")
OPENED: list[str] = []


class GuardError(PermissionError):
    pass


def _guard(event: str, args: tuple) -> None:
    if event == "open":
        p = args[0] if args else ""
        p = os.fsdecode(p) if isinstance(p, (bytes, os.PathLike)) else str(p)
        OPENED.append(p)
        if any(m in p for m in PERSONAL_MARKERS):
            raise GuardError(f"데모 빌드는 개인 자료를 열지 않는다: {p}")
    elif event in ("socket.connect", "socket.getaddrinfo", "urllib.Request"):
        raise GuardError(f"데모 빌드는 바깥 호출을 하지 않는다: {event}")


_GUARD_ON = False


def install_guards() -> None:
    """한 번 켜면 이 프로세스가 끝날 때까지 남는다(감사 훅은 지울 수 없다)."""
    global _GUARD_ON
    if not _GUARD_ON:
        sys.addaudithook(_guard)
        _GUARD_ON = True


install_guards()
sys.path.insert(0, ROOT)

from alfredo import __version__  # noqa: E402
from alfredo.ledger import Ledger  # noqa: E402
from alfredo.principles import check_ledger, load_rules  # noqa: E402

# ---------- 시나리오 (시연용 합성) ----------
SEED = 20261013               # 정한 뒤 바꾸지 않는다(결과가 마음에 들 때까지 시드를 고르지 않음)
HISTORY_DAYS = 200            # 범위 회고에 쓰는 과거 합성 일수
START = "2026-09-30"          # 이 날 종가를 보고 시작을 결정, 다음 날 시가에 체결
END = "2026-10-07"            # 이 날 종가에 주간 보고
CAPITAL = 10_000_000          # 가상 시작 금액(원)
FEE, SLIPPAGE = 0.0005, 0.001  # 설계서 비용표 기본(수수료 0.05%, 슬리피지 0.10%)
BOOK = "experiment"
TOP3_URL = "https://top3-crypto.vercel.app"

# 합성 가격의 성질: 연 변동성만 정하고 기대 수익은 0(수익을 가정하지 않음). 주식·채권·금은 주말에 움직이지 않는다.
ASSETS = [
    {"id": "주식", "group": "주식", "vol": 0.18, "weekend": False, "label": "주식(지수형 예시)"},
    {"id": "채권", "group": "채권", "vol": 0.06, "weekend": False, "label": "채권(지수형 예시)"},
    {"id": "금", "group": "금", "vol": 0.15, "weekend": False, "label": "금"},
    {"id": "BTC", "group": "코인", "vol": 0.50, "weekend": True, "label": "비트코인"},
    {"id": "ETH", "group": "코인", "vol": 0.65, "weekend": True, "label": "이더리움"},
    {"id": "XRP", "group": "코인", "vol": 0.80, "weekend": True, "label": "리플"},
]
GROUPS = ["주식", "채권", "금", "코인", "현금"]
COINS = [a["id"] for a in ASSETS if a["group"] == "코인"]

# 예시 템플릿(모두에게 같은 예시, 추천 아님). 근거는 TEMPLATE_BASIS.
TEMPLATES = {
    "보수": {"주식": 0.20, "채권": 0.55, "금": 0.05, "코인": 0.00, "현금": 0.20},
    "중립": {"주식": 0.40, "채권": 0.35, "금": 0.05, "코인": 0.02, "현금": 0.18},
    "적극": {"주식": 0.60, "채권": 0.33, "금": 0.05, "코인": 0.02, "현금": 0.00},
}
TEMPLATE_USED = "중립"
TEMPLATE_BASIS = [
    {"text": "주식:채권은 공개 자산배분 펀드 Vanguard LifeStrategy의 고정 비율(Income 20:80, Conservative Growth 40:60, Moderate Growth 60:40)에서 출발했습니다. Income·Conservative Growth의 단기 채권 20%는 현금 칸으로 옮겼습니다.",
     "url": "https://www.sec.gov/Archives/edgar/data/0000736054/000093247108000728/starfunds485b022008.txt"},
    {"text": "금 5%: 세계금협회(WGC, 2013-10-30 보도자료)는 주식 60·채권 40 포트폴리오의 최적 금 비중을 약 5–6%로 들었습니다. 세 템플릿 모두 5%로 두고 채권에서 뺐습니다.",
     "url": "https://www.gold.org/news-and-events/press-releases/investors-should-resist-being-seduced-short-term-headlines-when"},
    {"text": "코인 2% 이하: BlackRock Investment Institute('Sizing bitcoin in portfolios', 2024-12)는 비트코인 1–2%를 '합리적 범위'로 들고, 그보다 크면 위험 몫이 급히 커진다고 했습니다. 코인 칸 안은 BTC·ETH·XRP 같은 비중(예시)입니다.",
     "url": "https://www.blackrock.com/institutions/en-us/insights/thought-leadership/portfolio-design/sizing-bitcoin-in-portfolios"},
]
EMOTION_BUY = {"symbol": "XRP", "share": 0.03,
               "note": "하루 크게 오른 걸 보고 추가 매수", "expect": "일주일 안에 더 오를 것"}
REBAL_BAND = 0.05             # 리밸런싱 점검: 출발 배분에서 ±5%p 넘게 벗어나면 어김(이하는 지킴, 시연용 기준)
GRADE_BAND = 0.01             # 등급: 차이가 ±1%p 이내면 '기준 근처'(경계 포함)
RANGE_LOOKBACK = 180          # 범위 회고에 쓰는 일수
RANGE_BAND = (0.10, 0.90)     # 과거 7일 수익률의 80% 범위
ROUND = 6                     # 경계 비교 전에 소수 6자리로 반올림(부동소수 오차로 등급이 바뀌지 않게)


# ---------- 공개 범위: 나가는 키 목록 ----------
class PublicScopeError(ValueError):
    pass


class Map:
    """키가 데이터인 사전(예: 템플릿 이름 → 배분). keys가 있으면 그 키만 허용."""

    def __init__(self, value, keys=None):
        self.value, self.keys = value, (set(keys) if keys is not None else None)


LEAF = None
_ROW_POS = {k: LEAF for k in ("id", "label", "group", "qty", "avg_cost", "price", "value", "weight",
                               "unrealized", "unrealized_pct")}
PUBLIC_SCHEMA = {
    "meta": {k: LEAF for k in ("title", "version", "built_at", "engine", "band", "scenario", "price_note",
                               "fill_rule", "seed", "start", "end", "capital", "fee", "slippage",
                               "template_name", "rebal_band", "grade_band", "top3_url")}
            | {"template": Map(LEAF, GROUPS), "templates": Map(Map(LEAF, GROUPS), TEMPLATES),
               "template_basis": [{"text": LEAF, "url": LEAF}],
               "assets": [{"id": LEAF, "group": LEAF, "label": LEAF, "vol": LEAF, "weekend": LEAF}]},
    "portfolio": {"total": LEAF, "cash": LEAF, "return": LEAF, "positions": [_ROW_POS],
                  "groups": [{"group": LEAF, "target": LEAF, "actual": LEAF, "drift": LEAF, "ok": LEAF}],
                  "series": [{"date": LEAF, "mine": LEAF, "bm5": LEAF, "b6040": LEAF}],
                  "costs": {"fees": LEAF, "slippage": LEAF, "total": LEAF}},
    "principles": {"version": LEAF, "rate": LEAF, "ok": LEAF, "count": LEAF,
                   "rules": [{"id": LEAF, "name": LEAF, "params": Map(LEAF), "why": LEAF}],
                   "judgements": [{k: LEAF for k in ("trade_id", "date", "symbol", "note", "rule_id",
                                                     "rule_name", "ok", "detail")}]},
    "weekly": {"scorecard": [{k: LEAF for k in ("metric", "bench_name", "mine", "bench", "diff", "grade", "better")}],
               "honest": LEAF,
               "range_review": [{k: LEAF for k in ("id", "low", "high", "actual", "inside", "n_windows", "lookback_days")}],
               "range_band": [LEAF], "predictions": [{k: LEAF for k in ("trade_id", "date", "symbol", "expect",
                                                                         "price_then", "price_end", "change", "right")}],
               "corrections": [{"what": LEAF, "actual": LEAF, "note": LEAF}], "decisions": [LEAF]},
    "coins": [{"id": LEAF, "label": LEAF, "weight": LEAF, "week_change": LEAF}],
    "trades": [{k: LEAF for k in ("id", "date", "side", "symbol", "qty", "price", "fee", "note")}],
}


def public_view(obj, schema=PUBLIC_SCHEMA, path: str = "$"):
    """schema에 적은 키만 남긴 사본. 목록 밖 키·이상한 값이 있으면 멈춘다(조용히 버리지 않음)."""
    if schema is LEAF:
        if isinstance(obj, float) and not math.isfinite(obj):
            raise PublicScopeError(f"{path}: 유한수가 아니다")
        if obj is not None and not isinstance(obj, (str, int, float, bool)):
            raise PublicScopeError(f"{path}: 값은 문자·숫자·참거짓만({type(obj).__name__})")
        if isinstance(obj, str) and any(m in obj for m in PERSONAL_MARKERS):
            raise PublicScopeError(f"{path}: 개인 경로 표식이 들어 있다")
        return obj
    if isinstance(schema, Map):
        if not isinstance(obj, dict):
            raise PublicScopeError(f"{path}: 사전이어야 한다")
        bad = [k for k in obj if schema.keys is not None and k not in schema.keys]
        if bad:
            raise PublicScopeError(f"{path}: 목록 밖 키 {bad}")
        return {k: public_view(v, schema.value, f"{path}.{k}") for k, v in obj.items()}
    if isinstance(schema, list):
        if not isinstance(obj, list):
            raise PublicScopeError(f"{path}: 목록이어야 한다")
        return [public_view(v, schema[0], f"{path}[{i}]") for i, v in enumerate(obj)]
    if not isinstance(obj, dict):
        raise PublicScopeError(f"{path}: 사전이어야 한다")
    bad = [k for k in obj if k not in schema]
    if bad:
        raise PublicScopeError(f"{path}: 목록 밖 키 {bad} (내보내려면 PUBLIC_SCHEMA에 먼저 적는다)")
    return {k: public_view(v, schema[k], f"{path}.{k}") for k, v in obj.items()}


# ---------- 계산 도우미 ----------
def dates_between(a: str, b: str) -> list[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def pct(a: float, b: float) -> float:
    return a / b - 1


def quantile(xs: list[float], q: float) -> float:
    if not xs:
        raise ValueError("빈 목록의 분위수는 없다")
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def grade(diff: float | None, band: float = GRADE_BAND) -> str | None:
    """설계서 scoring.grade: 기준 이상 / 기준 근처(±1%p, 경계 포함) / 기준 미만. 값이 없거나 유한수가 아니면 None."""
    if diff is None or not math.isfinite(diff):
        return None
    d = round(diff, ROUND)
    if d > band:
        return "기준 이상"
    if d < -band:
        return "기준 미만"
    return "기준 근처"


def within_band(drift: float, band: float = REBAL_BAND) -> bool:
    """리밸런싱 점검: |차이| ≤ band 이면 지킴(경계 포함)."""
    return abs(round(drift, ROUND)) <= band


def inside_range(x: float, lo: float, hi: float) -> bool:
    """범위 회고: lo ≤ x ≤ hi 이면 안(경계 포함)."""
    return round(lo, ROUND) <= round(x, ROUND) <= round(hi, ROUND)


def mdd(series: list[float]) -> float:
    peak, worst = series[0], 0.0
    for v in series:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst


def synth_prices(seed: int = SEED) -> dict[str, dict[str, dict[str, float]]]:
    """합성 일봉 {자산: {날짜: {"open","close"}}}. 시작 100, 기대 수익 0, 연 변동성만 자산마다 다르다.

    시가 = 전날 종가 × exp(틈), 종가 = 시가 × exp(장중). 주말에 쉬는 자산은 주말에 값이 그대로다.
    """
    rng = random.Random(seed)
    days = dates_between((date.fromisoformat(START) - timedelta(days=HISTORY_DAYS)).isoformat(),
                         (date.fromisoformat(END) + timedelta(days=1)).isoformat())
    out: dict[str, dict[str, dict[str, float]]] = {}
    for a in ASSETS:
        per_year = 365 if a["weekend"] else 252
        sd = a["vol"] / math.sqrt(per_year)
        close, rows = 100.0, {}
        for d in days:
            if not a["weekend"] and date.fromisoformat(d).weekday() >= 5:
                rows[d] = {"open": close, "close": close}
                continue
            o = close * math.exp(rng.gauss(0, 0.3 * sd))
            c = o * math.exp(rng.gauss(0, 0.954 * sd))  # 0.3² + 0.954² ≈ 1 → 하루 변동성 ≈ sd
            rows[d] = {"open": round(o, 2), "close": round(c, 2)}
            close = rows[d]["close"]
        out[a["id"]] = rows
    return out


def close_ts(d: str) -> str:
    return f"{d}T15:00:00+00:00"  # 합성 일봉의 종가 시각(표시용 임의 기준: 다음 날 00:00 KST)


def open_ts(d: str) -> str:
    return f"{d}T00:00:00+00:00"


def target_weights(template: dict[str, float]) -> dict[str, float]:
    """템플릿(자산군) → 자산별 목표. 코인 칸은 BTC·ETH·XRP 같은 비중."""
    w = {}
    for a in ASSETS:
        g = a["group"]
        w[a["id"]] = template[g] / len(COINS) if g == "코인" else template[g]
    return w


# ---------- 시나리오 만들기 ----------
def build() -> dict:
    px = synth_prices()
    week = dates_between(START, END)
    for s, rows in px.items():
        missing = [d for d in week if d not in rows]
        if missing:  # 결측을 건너뛰어 옛 값과 비교하지 않는다
            raise SystemExit(f"{s} 합성 가격에 없는 날짜: {missing}")
    rules = load_rules()
    labels = {a["id"]: a["label"] for a in ASSETS}
    template = TEMPLATES[TEMPLATE_USED]
    tw = target_weights(template)

    tmp = tempfile.mkdtemp(prefix="alfredo_demo_")
    led = Ledger(os.path.join(tmp, "demo.db"), fee_rate=FEE, slippage_rate=SLIPPAGE)
    base = Ledger(os.path.join(tmp, "base.db"), fee_rate=FEE, slippage_rate=SLIPPAGE)    # 출발 배분 그대로
    b6040 = Ledger(os.path.join(tmp, "b6040.db"), fee_rate=FEE, slippage_rate=SLIPPAGE)  # 주식 60·채권 40 그대로

    def closes(d: str) -> dict[str, float]:
        return {s: px[s][d]["close"] for s in px}

    def opens(d: str) -> dict[str, float]:
        return {s: px[s][d]["open"] for s in px}

    # 1) START 종가를 보고 시작을 정하고, 다음 날 시가에 체결
    fill0 = week[1]
    plans = ((led, tw), (base, tw), (b6040, {"주식": 0.60, "채권": 0.40}))
    for L, _ in plans:
        L.deposit(BOOK, CAPITAL, ts=close_ts(START), bench_price=px["BTC"][START]["close"], note="가상 시작 금액")

    def start_buys(d: str) -> None:
        o = opens(d)
        for L, weights in plans:
            for s, w in weights.items():
                if w <= 0:
                    continue
                budget = CAPITAL * w / ((1 + SLIPPAGE) * (1 + FEE))
                L.buy(BOOK, s, budget / o[s], o[s], ts=open_ts(d), note=f"출발 배분 {w:.1%}")

    # 2) 감정 매수 장면: 체결 뒤 하루 상승률(종가 대비 종가)이 가장 큰 날 종가를 보고, 다음 날 시가에 추가 매수
    sym = EMOTION_BUY["symbol"]
    cand = [(pct(px[sym][d]["close"], px[sym][prev]["close"]), d) for prev, d in zip(week[1:], week[2:-1])]
    _, seen_day = max(cand)
    emo_day = (date.fromisoformat(seen_day) + timedelta(days=1)).isoformat()
    emo_price = px[sym][emo_day]["open"]
    emo_qty = CAPITAL * EMOTION_BUY["share"] / ((1 + SLIPPAGE) * (1 + FEE)) / emo_price

    # 날마다: 그날 시가 체결 → 그날 종가로 평가(체결 전 날짜에 미래 체결이 섞이지 않게)
    trade_meta = {}
    for d in week:
        if d == fill0:
            start_buys(d)
        if d == emo_day:
            tid = led.buy(BOOK, sym, emo_qty, emo_price, ts=open_ts(d), note=EMOTION_BUY["note"])
            trade_meta[tid] = {"expect": EMOTION_BUY["expect"], "seen": seen_day}
        for L, _ in plans:
            L.snapshot(BOOK, closes(d), ts=close_ts(d))

    p_end = closes(END)
    judgements, rate = check_ledger(led, BOOK, rules, record=True)
    total = led.total_value(BOOK, p_end)
    ret = pct(total, CAPITAL)
    bm5_val, b64_val = base.total_value(BOOK, p_end), b6040.total_value(BOOK, p_end)

    series = [{"date": a["ts"][:10], "mine": round(a["total_value"]), "bm5": round(b["total_value"]),
               "b6040": round(c["total_value"])}
              for a, b, c in zip(led.snapshots(BOOK), base.snapshots(BOOK), b6040.snapshots(BOOK))]

    trades = [dict(t) for t in led.trades(BOOK)]
    fees = sum(t["fee"] for t in trades)
    slip = sum(t["qty"] * abs(t["exec_price"] - t["price"]) for t in trades if t["side"] in ("buy", "sell"))

    positions = []
    for p in led.positions(BOOK):
        price = p_end[p.symbol]
        positions.append({"id": p.symbol, "label": labels[p.symbol], "group": next(a["group"] for a in ASSETS if a["id"] == p.symbol),
                          "qty": round(p.qty, 4), "avg_cost": round(p.avg_cost, 2), "price": price,
                          "value": round(p.qty * price), "weight": p.qty * price / total,
                          "unrealized": round(p.unrealized(price)), "unrealized_pct": pct(price, p.avg_cost)})
    cash = led.cash(BOOK)
    order = {a["id"]: i for i, a in enumerate(ASSETS)}
    positions.sort(key=lambda r: order[r["id"]])

    # 원칙 판정(코드가 판정한다. AI에는 판정이 아니라 사실만 준다: 설계서 compliance)
    rule_names = {r["id"]: r for r in rules["rules"]}
    by_id = {t["id"]: t for t in trades}
    jlist = [{"trade_id": j.trade_id, "date": by_id[j.trade_id]["ts"][:10], "symbol": by_id[j.trade_id]["symbol"],
              "note": by_id[j.trade_id]["note"], "rule_id": j.rule_id, "rule_name": rule_names[j.rule_id]["name"],
              "ok": j.ok, "detail": j.detail} for j in judgements]

    # 리밸런싱 점검: 자산군(템플릿 칸)별 지금 비중 − 출발 배분
    actual = {g: 0.0 for g in GROUPS}
    for p in positions:
        actual[p["group"]] += p["weight"]
    actual["현금"] = cash / total
    groups = [{"group": g, "target": template[g], "actual": actual[g], "drift": actual[g] - template[g],
               "ok": within_band(actual[g] - template[g])} for g in GROUPS]

    # 정직한 성적표: 한 숫자로 합치지 않고 지표마다 3등급
    bm5_ret, b64_ret = pct(bm5_val, CAPITAL), pct(b64_val, CAPITAL)
    mine_mdd = mdd([s["mine"] for s in series])
    bm5_mdd = mdd([s["bm5"] for s in series])
    scorecard = [
        {"metric": "수익률(비용 후)", "bench_name": "출발 배분 그대로", "mine": ret, "bench": bm5_ret,
         "diff": ret - bm5_ret, "grade": grade(ret - bm5_ret), "better": "높을수록"},
        {"metric": "수익률(비용 후)", "bench_name": "주식 60·채권 40 그대로", "mine": ret, "bench": b64_ret,
         "diff": ret - b64_ret, "grade": grade(ret - b64_ret), "better": "높을수록"},
        {"metric": "최대 낙폭(일 종가)", "bench_name": "출발 배분 그대로", "mine": mine_mdd, "bench": bm5_mdd,
         "diff": mine_mdd - bm5_mdd, "grade": grade(mine_mdd - bm5_mdd), "better": "0에 가까울수록"},
        {"metric": "원칙 이행률", "bench_name": "목표 90%(사용자 설정)", "mine": rate, "bench": 0.9,
         "diff": None if rate is None else rate - 0.9,
         "grade": None if rate is None else ("기준 이상" if round(rate, ROUND) >= 0.9 else "기준 미만"), "better": "높을수록"},
    ]
    n_bad = sum(1 for j in jlist if not j["ok"])
    g5 = scorecard[0]["grade"]
    if g5 == "기준 미만":
        honest = (f"이번 주 내 장부는 손대지 않은 출발 배분보다 {abs(ret - bm5_ret) * 100:.1f}%p 낮았습니다. "
                  f"원칙을 어긴 거래가 {n_bad}건 있었습니다. 한 주만으로는 방식의 효과를 말할 수 없습니다.")
    elif g5 == "기준 이상":
        honest = (f"이번 주 내 장부는 출발 배분보다 {(ret - bm5_ret) * 100:.1f}%p 높았지만, 한 주의 차이는 우연일 수 있습니다. "
                  f"원칙을 어긴 거래는 {n_bad}건입니다.")
    else:
        honest = (f"이번 주 내 장부와 출발 배분의 차이는 {(ret - bm5_ret) * 100:+.1f}%p로 ±1%p 안입니다. "
                  f"이번 주 거래의 효과는 보이지 않습니다. 원칙을 어긴 거래는 {n_bad}건입니다.")

    # 범위 회고: 시작 시점에 보여 줬을 '과거 7일 수익률 80% 범위' 안에 실제가 들어왔나
    range_review = []
    for a in ASSETS:
        s = a["id"]
        hist = [px[s][d]["close"] for d in sorted(px[s]) if d <= START][-RANGE_LOOKBACK:]
        rets = [pct(hist[i + 7], hist[i]) for i in range(len(hist) - 7)]
        lo, hi = quantile(rets, RANGE_BAND[0]), quantile(rets, RANGE_BAND[1])
        act = pct(px[s][END]["close"], px[s][START]["close"])
        range_review.append({"id": s, "low": lo, "high": hi, "actual": act, "inside": inside_range(act, lo, hi),
                             "n_windows": len(rets), "lookback_days": len(hist)})

    predictions = []
    for tid, m in trade_meta.items():
        t = by_id[tid]
        later = px[t["symbol"]][END]["close"]
        predictions.append({"trade_id": tid, "date": t["ts"][:10], "symbol": t["symbol"], "expect": m["expect"],
                            "price_then": t["price"], "price_end": later, "change": pct(later, t["price"]),
                            "right": later > t["price"]})

    corrections = [{"what": f"{r['id']} 과거 범위 {r['low']:+.1%}–{r['high']:+.1%}", "actual": f"실제 {r['actual']:+.1%}",
                    "note": "범위 밖. 범위는 예측이 아니라 과거 기록이었다는 점을 다시 적습니다."}
                   for r in range_review if not r["inside"]]

    # 다음 주에 정할 것(질문형, 최종 결정은 사용자)
    decisions = []
    for j in jlist:
        if not j["ok"]:
            decisions.append(f"{j['date'][5:].replace('-', '/')} {j['symbol']} 추가 매수가 '{j['rule_name']}' 규칙을 어겼습니다. "
                             "이유를 남길까요? 규칙을 바꾸려면 날짜와 이유를 함께 남깁니다.")
    worst = max(groups, key=lambda g: abs(g["drift"]))
    decisions.append(f"{worst['group']} 비중이 출발 배분보다 {worst['drift'] * 100:+.1f}%p 벗어났습니다"
                     f"(점검 기준 ±{REBAL_BAND:.0%}p). 그대로 둘지, 언제 맞출지 미리 적어 둘까요?")
    if g5 == "기준 미만":
        decisions.append("이번 주는 손대지 않은 출발 배분보다 낮았습니다. 다음 주에도 같은 방식으로 거래할지, "
                         "한 주로 판단하기엔 짧은지 정해 주세요.")

    coins = [{"id": s, "label": labels[s], "weight": next((p["weight"] for p in positions if p["id"] == s), 0.0),
              "week_change": pct(px[s][END]["close"], px[s][START]["close"])} for s in COINS]

    for L in (led, base, b6040):
        L.close()
    demo = {
        "meta": {
            "title": "알프레도 MVP 데모", "version": "V1",
            "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "engine": f"alfredo v{__version__} (모의 전용)",
            "band": "AI가 만든 정보이며 투자 권유가 아닙니다. 모의투자 기준입니다.",
            "scenario": (f"시연용 합성 시나리오: 가상 {CAPITAL // 10_000:,}만 원을 '{TEMPLATE_USED}' 예시 배분으로 시작해 "
                         f"한 주를 보낸 기록입니다. 가격도 합성값이며 실제 시세가 아닙니다."),
            "price_note": (f"합성 가격(시드 {SEED} 고정, 시작 100, 기대 수익 0, 자산마다 연 변동성만 다름, "
                           "주식·채권·금은 주말 휴장). 실제 시세가 아닙니다."),
            "fill_rule": "그날 종가를 보고 정하고, 다음 날 시가에 체결합니다(종가 체결은 미래 정보가 섞여 쓰지 않음).",
            "seed": SEED, "start": START, "end": END, "capital": CAPITAL, "fee": FEE, "slippage": SLIPPAGE,
            "template_name": TEMPLATE_USED, "template": template, "templates": TEMPLATES,
            "template_basis": TEMPLATE_BASIS, "rebal_band": REBAL_BAND, "grade_band": GRADE_BAND,
            "assets": [{k: a[k] for k in ("id", "group", "label", "vol", "weekend")} for a in ASSETS],
            "top3_url": TOP3_URL,
        },
        "portfolio": {"total": round(total), "cash": round(cash), "return": ret, "positions": positions,
                      "groups": groups, "series": series,
                      "costs": {"fees": round(fees), "slippage": round(slip), "total": round(fees + slip)}},
        "principles": {"version": rules.get("version"), "rate": rate, "ok": sum(1 for j in jlist if j["ok"]),
                       "count": len(jlist),
                       "rules": [{"id": r["id"], "name": r["name"], "params": r["params"], "why": r["why"]}
                                 for r in rules["rules"]],
                       "judgements": jlist},
        "weekly": {"scorecard": scorecard, "honest": honest, "range_review": range_review,
                   "range_band": list(RANGE_BAND), "predictions": predictions, "corrections": corrections,
                   "decisions": decisions[:3]},
        "coins": coins,
        "trades": [{"id": t["id"], "date": t["ts"][:10], "side": t["side"], "symbol": t["symbol"],
                    "qty": round(t["qty"], 4), "price": t["price"], "fee": round(t["fee"]), "note": t["note"]}
                   for t in trades],
    }
    return public_view(demo)


# ---------- 글꼴: 쓰는 글자만 남기고 이름을 바꾼다(OFL 예약 이름 'Pretendard') ----------
def make_font(text: str) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    if not os.path.exists(FONT_SRC):
        if os.path.exists(FONT_OUT):
            with open(FONT_OUT, "rb") as f:  # 원본이 없으면 저장소의 부분 글꼴을 그대로 쓴다
                return f.read()
        raise SystemExit(f"글꼴 원본이 없다: {FONT_SRC} (mvp/fonts/README.md 참고)")
    chars = set(text) | {chr(c) for c in range(0x20, 0x7F)}
    opts = subset.Options()
    opts.flavor = "woff"  # woff2는 brotli 모듈이 있어야 해서 zlib인 woff로 둔다
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    font = TTFont(FONT_SRC)
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in chars])
    sub.subset(font)
    for rec in font["name"].names:  # 이름 바꾸기: 저작권(0)·라이선스(13·14)는 그대로 둔다
        if rec.nameID in (0, 13, 14):
            continue
        if rec.nameID in (1, 16):
            rec.string = FONT_FAMILY
        elif rec.nameID == 4:
            rec.string = f"{FONT_FAMILY} Regular"
        elif rec.nameID in (6, 25):
            rec.string = f"{FONT_FAMILY}-Regular" if rec.nameID == 6 else FONT_FAMILY
        elif "Pretendard" in rec.toUnicode():
            rec.string = rec.toUnicode().replace("Pretendard", FONT_FAMILY)
    font.flavor = "woff"
    fd, tmp = tempfile.mkstemp(suffix=".woff")
    os.close(fd)
    font.save(tmp)
    with open(tmp, "rb") as f:
        data = f.read()
    os.remove(tmp)
    with open(FONT_OUT, "wb") as f:
        f.write(data)
    return data


def missing_glyphs(text: str, font_bytes: bytes) -> list[str]:
    """부분 글꼴에 없는 한글 글자(깨진 글자 점검용)."""
    import io

    from fontTools.ttLib import TTFont
    cmap = TTFont(io.BytesIO(font_bytes)).getBestCmap()
    return sorted({c for c in text if ("가" <= c <= "힣" or "ㄱ" <= c <= "ㆎ") and ord(c) not in cmap})


# ---------- 내보내기 ----------
DATA_TAG = '<script src="data/demo_week.js"></script>'
FONT_URL = 'url("fonts/AlfredoSans-subset.woff")'


def page_text(demo: dict) -> tuple[str, str]:
    text = json.dumps(demo, ensure_ascii=False, indent=1)
    with open(os.path.join(MVP, "index.html"), encoding="utf-8") as f:
        page = f.read()
    if DATA_TAG not in page or FONT_URL not in page:
        raise SystemExit("index.html에서 데이터 script 태그나 글꼴 주소를 찾지 못했다")
    return text, page


def main() -> int:
    demo = build()
    text, page = page_text(demo)
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "demo_week.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    with open(os.path.join(DATA, "demo_week.js"), "w", encoding="utf-8") as f:
        f.write("// build_demo.py가 만든 파일. 고치지 말고 다시 만든다.\nwindow.ALFREDO_DEMO = " + text + ";\n")

    extra = ""
    for fn in ("소개서_v2.md", "board.html", os.path.join("data", "board.js")):  # 같은 부분 글꼴을 대시보드·소개서와 같이 쓴다
        p = os.path.join(MVP, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                extra += f.read()
    font = make_font(page + text + extra)
    miss = missing_glyphs(page + text + extra, font)
    if miss:
        raise SystemExit(f"부분 글꼴에 없는 글자: {''.join(miss)}")

    # 메일 첨부용 한 파일: 데이터와 글꼴을 HTML 안에 넣는다(Gmail 등은 .js 첨부를 막는다)
    os.makedirs(DIST, exist_ok=True)
    inline = "<script>\nwindow.ALFREDO_DEMO = " + text.replace("</", "<\\/") + ";\n</script>"
    font_uri = 'url("data:font/woff;base64,' + base64.b64encode(font).decode("ascii") + '")'
    out = page.replace(DATA_TAG, inline).replace(FONT_URL, font_uri)
    with open(os.path.join(DIST, "alfredo_mvp_demo.html"), "w", encoding="utf-8") as f:
        f.write(out)
    pf, pr = demo["portfolio"], demo["principles"]
    print(f"총 평가액 {pf['total']:,}원 ({pf['return']:+.2%}) · 원칙 이행률 {pr['ok']}/{pr['count']}"
          f" · 결정 지점 {len(demo['weekly']['decisions'])}개 · 글꼴 {len(font) / 1024:.0f}KB"
          f" · 첨부 {len(out.encode()) / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
