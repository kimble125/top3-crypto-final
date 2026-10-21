"""알프레도 MVP 대시보드 만들기 (V2, 2026-10-13 호연 지시: Top3 대시보드를 바탕으로 코인·주식·기타 탭).

- 탭: 코인(BTC·ETH·XRP) · 주식(지수형 예시) · 기타(금·채권·달러). 나머지 탭(AI 분석·공부·설정)은 Top3 자리를 그대로 둔다.
- 가격: 시드 고정 **합성** 일봉(실제 시세 아님, 막힌작업 10-08 9번 B). 빌드 중 개인 경로·바깥 호출은 build_demo의 지킴이가 막는다.
- 확신도(알프레도 v0, 표시 전용): 신호마다 x ∈ [−1, 1]을 내고 가중 평균 × 100. 가중치는 모두 1(근거 있는 가중치를 정하기 전).
  자료 없는 신호는 분모에서 빼고, 자료가 50% 미만이면 숫자를 보류한다(Top3 확신도의 '구조'만 빌림. Top3 신호 순서·가중치는 쓰지 않음).
  - 기술적: 추세(50·200일 이동평균), MACD(일봉)
  - 정량(퀀트 강의 Part 2 팩터 개념): 시계열 모멘텀 12-1개월, 3개월 모멘텀
  - 정성: 뉴스·시황 해석 자리(AI 연결 전이라 예시값, 'AI 추정(예시)' 표시)
  - 점수 제외: 변동성 국면 배지(Aside rep_261013_alf01 B2: 확신도에 넣지 않음), RSI는 그래프에만(같은 rep C6)

실행(저장소 루트에서): python3 -I mvp/build_board.py
결과: mvp/data/board.json, mvp/dist/alfredo_mvp_board.html(데이터·글꼴을 넣은 한 파일)
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

MVP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, MVP)
import build_demo as B  # noqa: E402  (지킴이·글꼴·공개 범위 도구를 같이 쓴다)

SEED = 20261013
END = "2026-10-13"
DAYS = 460                     # 12-1개월 모멘텀(252+21 거래일)과 200일선을 낼 만큼
SHOW_DAYS = 180

TABS = {
    "coin": {"name": "코인", "note": "Top3 Crypto와 같은 세 코인. 실제 Top3 확신도(조원 기준)는 Top3 화면에서 봅니다.",
             "assets": [("BTC", "비트코인", 0.55, True, 0.5), ("ETH", "이더리움", 0.70, True, 0.0), ("XRP", "리플", 0.85, True, -0.5)]},
    "stock": {"name": "주식", "note": "지수형 예시입니다. 개별 종목은 다루지 않습니다.",
              "assets": [("KOSPI200", "국내 주식(지수형 예시)", 0.20, False, 0.5), ("SP500", "미국 주식(지수형 예시)", 0.17, False, 0.0),
                         ("NDX100", "미국 기술주(지수형 예시)", 0.24, False, -0.5)]},
    "other": {"name": "기타", "note": "금·채권·달러처럼 주식·코인 밖의 자산입니다.",
              "assets": [("GOLD", "금", 0.15, False, 0.5), ("BOND", "채권(지수형 예시)", 0.06, False, 0.0), ("USD", "달러(원화 기준)", 0.08, False, -0.5)]},
}
QUAL_NOTE = {1.0: "긍정적 해석 우세", 0.5: "약한 긍정", 0.0: "엇갈림", -0.5: "약한 부정", -1.0: "부정적 해석 우세"}


# ---------- 합성 일봉 ----------
def synth(seed_key: str, vol: float, weekend: bool) -> list[dict]:
    rng = random.Random(f"{SEED}-{seed_key}")
    end = date.fromisoformat(END)
    days = [(end - timedelta(days=DAYS - 1 - i)) for i in range(DAYS)]
    sd = vol / math.sqrt(365 if weekend else 252)
    drift = rng.choice([-1, 1]) * rng.uniform(0.0, 0.12) * sd   # 구간마다 다른 흐름(기대 수익 가정 아님, 시드로 고정)
    close, rows = 100.0, []
    for i, d in enumerate(days):
        if i % 90 == 0:
            drift = rng.choice([-1, 1]) * rng.uniform(0.0, 0.12) * sd
        if not weekend and d.weekday() >= 5:
            continue
        o = close * math.exp(rng.gauss(0, 0.3 * sd))
        c = o * math.exp(drift + rng.gauss(0, 0.954 * sd))
        hi = max(o, c) * math.exp(abs(rng.gauss(0, 0.4 * sd)))
        lo = min(o, c) * math.exp(-abs(rng.gauss(0, 0.4 * sd)))
        rows.append({"d": d.isoformat(), "o": round(o, 2), "h": round(hi, 2), "l": round(lo, 2), "c": round(c, 2)})
        close = c
    return rows


# ---------- 지표(순수 함수) ----------
def sma(xs: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(xs: list[float], n: int) -> list[float]:
    k, out = 2 / (n + 1), []
    for i, x in enumerate(xs):
        out.append(x if i == 0 else x * k + out[-1] * (1 - k))
    return out


def macd(xs: list[float]) -> tuple[list[float], list[float], list[float]]:
    m = [a - b for a, b in zip(ema(xs, 12), ema(xs, 26))]
    s = ema(m, 9)
    return m, s, [a - b for a, b in zip(m, s)]


def rsi_wilder(xs: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(xs)
    if len(xs) <= n:
        return out
    gains = [max(xs[i] - xs[i - 1], 0) for i in range(1, len(xs))]
    losses = [max(xs[i - 1] - xs[i], 0) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for i in range(n, len(xs)):
        if i > n:
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def round_away(x: float) -> int:
    """0.5는 0에서 먼 쪽으로(Top3 검토 교훈)."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def label_of(score: int | None) -> str:
    if score is None:
        return "자료 부족"
    if score >= 50:
        return "상승 쪽 신호 우세"
    if score >= 20:
        return "약한 상승 쪽"
    if score > -20:
        return "중립"
    if score > -50:
        return "약한 하락 쪽"
    return "하락 쪽 신호 우세"


# ---------- 신호와 확신도 ----------
def signals(rows: list[dict], qual: float | None, weekend: bool) -> tuple[list[dict], dict]:
    c = [r["c"] for r in rows]
    n = len(c)
    s50, s200 = sma(c, 50)[-1], sma(c, 200)[-1]
    m, sg, hist = macd(c)
    per_month = 30 if weekend else 21
    sig = []

    if s50 is None or s200 is None:
        sig.append({"group": "기술적", "name": "추세", "tf": "50·200일선", "x": None, "note": "자료 부족"})
    else:
        above = (c[-1] > s50) + (c[-1] > s200) + (s50 > s200)
        x = {3: 1.0, 2: 0.5, 1: -0.5, 0: -1.0}[above]
        sig.append({"group": "기술적", "name": "추세", "tf": "50·200일선", "x": x,
                    "note": f"가격 {'>' if c[-1] > s50 else '<'} 50일선 · 50일선 {'>' if s50 > s200 else '<'} 200일선"})
    up, rising = m[-1] > sg[-1], hist[-1] > hist[-2]
    x = (1.0 if rising else 0.5) if up else (-1.0 if not rising else -0.5)
    sig.append({"group": "기술적", "name": "MACD", "tf": "일봉", "x": x,
                "note": f"시그널선 {'위' if up else '아래'} · 막대 {'커짐' if rising == up else '줄어듦'}"})

    def mom(lb: int, skip: int) -> float | None:
        if n <= lb:
            return None
        return c[-1 - skip] / c[-1 - lb] - 1

    r121 = mom(12 * per_month, per_month)
    sig.append({"group": "정량", "name": "시계열 모멘텀", "tf": "12-1개월", "x": None if r121 is None else (0.0 if abs(r121) < 0.02 else math.copysign(1.0, r121)),
                "note": "자료 부족" if r121 is None else f"{r121 * 100:+.1f}%"})
    r3 = mom(3 * per_month, 0)
    sig.append({"group": "정량", "name": "3개월 모멘텀", "tf": "3개월", "x": None if r3 is None else (0.0 if abs(r3) < 0.02 else math.copysign(0.5 if abs(r3) < 0.08 else 1.0, r3)),
                "note": "자료 부족" if r3 is None else f"{r3 * 100:+.1f}%"})
    sig.append({"group": "정성", "name": "뉴스·시황 해석", "tf": "AI 추정(예시)", "x": qual,
                "note": "AI 연결 전이라 손으로 넣은 예시값" + ("" if qual is None else f" · {QUAL_NOTE[qual]}")})

    # 점수에 넣지 않는 배지: 변동성 국면(20일 연환산 vs 1년 중앙값)
    rets = [math.log(c[i] / c[i - 1]) for i in range(1, n)]
    ann = math.sqrt(365 if weekend else 252)
    v20 = (sum(x * x for x in rets[-20:]) / 20) ** 0.5 * ann
    hist_v = sorted((sum(x * x for x in rets[i - 20:i]) / 20) ** 0.5 * ann for i in range(20, len(rets)))[-(12 * per_month):]
    med = sorted(hist_v)[len(hist_v) // 2]
    regime = "높음" if v20 > 1.3 * med else "낮음" if v20 < 0.77 * med else "보통"
    badge = {"vol20": v20, "vol_med": med, "regime": regime}
    return sig, badge


def confidence(sig: list[dict]) -> dict:
    used = [s for s in sig if s["x"] is not None]
    cover = len(used) / len(sig)
    terms = " + ".join(f"1×({s['x']:+g})" for s in used)
    if cover < 0.5:
        return {"score": None, "side_pct": None, "side": None, "label": label_of(None), "coverage": cover, "formula": f"자료 {cover:.0%} < 50% → 숫자 보류"}
    raw = sum(s["x"] for s in used) / len(used) * 100
    score = round_away(raw)
    shown = "0" if score == 0 else f"{score:+d}"
    p_up = 50 + score / 2
    side_pct = round_away(max(p_up, 100 - p_up))
    side = "상승" if p_up >= 50 else "하락"
    label = "중립" if side_pct <= 54 else f"{side} 쪽 우세" if side_pct >= 65 else f"약한 {side} 쪽"
    return {"score": score, "side_pct": side_pct, "side": side, "label": label, "coverage": cover,
            "formula": f"점수 = ({terms}) ÷ {len(used)} × 100 = {shown} → 우세 쪽 % = 50 + |점수| ÷ 2 = {side_pct}%"}


def group_sub(sig: list[dict]) -> str:
    out = []
    for g, short in (("기술적", "기술"), ("정량", "정량"), ("정성", "정성")):
        xs = [s["x"] for s in sig if s["group"] == g and s["x"] is not None]
        if not xs:
            continue
        m = sum(xs) / len(xs)
        out.append(f"{short} {'상승' if m > 0.25 else '하락' if m < -0.25 else '중립'}")
    return " · ".join(out)


def spark7(sym: str, rows: list[dict], weekend: bool) -> list[float]:
    """최근 7일 가격선(하루 6점, 4시간 간격 느낌). 날마다 전날 종가에서 그날 종가로 가는 합성 다리(브라운 다리)."""
    rng = random.Random(f"{SEED}-{sym}-spark")
    last = rows[-8:]
    sd = 0.6 * abs(math.log(last[-1]["c"] / last[0]["c"])) / 7 + 0.004
    out = [last[0]["c"]]
    for prev, cur in zip(last, last[1:]):
        walk, w = [], 0.0
        for _ in range(6):
            w += rng.gauss(0, sd / math.sqrt(6))
            walk.append(w)
        for k in range(1, 7):  # 끝점이 그날 종가가 되게 다리를 놓는다
            t = k / 6
            out.append(round(prev["c"] * math.exp(math.log(cur["c"] / prev["c"]) * t + walk[k - 1] - t * walk[-1]), 2))
    return out


def summary(name: str, sig: list[dict], conf: dict, badge: dict) -> str:
    """코드가 신호로 쓰는 요약(AI 문장 아님). 사고팔 시점을 말하지 않는다."""
    pos = [s["name"] for s in sig if s["x"] and s["x"] > 0]
    neg = [s["name"] for s in sig if s["x"] and s["x"] < 0]
    parts = [f"{name}의 신호 {len([s for s in sig if s['x'] is not None])}개 중"]
    parts.append(f" 상승 쪽은 {', '.join(pos) if pos else '없음'}, 하락 쪽은 {', '.join(neg) if neg else '없음'}입니다.")
    parts.append(f" 확신도는 {conf['label']}({'보류' if conf['side_pct'] is None else str(conf['side_pct']) + '%'}).")
    parts.append(f" 변동성은 1년 중앙값 대비 {badge['regime']}(20일 연환산 {badge['vol20'] * 100:.0f}%)이라 점수에는 넣지 않고 따로 적습니다.")
    parts.append(" 신호가 같은 방향을 가리키는 정도일 뿐, 사고팔 시점을 뜻하지 않습니다.")
    return "".join(parts)


def build() -> dict:
    tabs = {}
    for key, t in TABS.items():
        assets = []
        for sym, name, vol, weekend, qual in t["assets"]:
            rows = synth(sym, vol, weekend)
            sig, badge = signals(rows, qual, weekend)
            conf = confidence(sig)
            c = [r["c"] for r in rows]
            m, sg, _ = macd(c)
            rsi = rsi_wilder(c)
            s50, s200 = sma(c, 50), sma(c, 200)
            k = -SHOW_DAYS
            chg = c[-1] / c[-2] - 1
            assets.append({
                "id": sym, "name": name, "price": c[-1], "chg": c[-1] - c[-2], "chg_pct": chg,
                "hi_1d": rows[-1]["h"], "lo_1d": rows[-1]["l"],
                "conf": conf, "signals": sig, "badge": badge, "summary": summary(name, sig, conf, badge),
                "sub": group_sub(sig), "spark": spark7(sym, rows, weekend),
                "series": {"d": [r["d"] for r in rows[k:]], "c": c[k:], "s50": [None if v is None else round(v, 2) for v in s50[k:]],
                           "s200": [None if v is None else round(v, 2) for v in s200[k:]],
                           "macd": [round(v, 4) for v in m[k:]], "sig": [round(v, 4) for v in sg[k:]],
                           "rsi": [None if v is None else round(v, 2) for v in rsi[k:]]},
            })
        tabs[key] = {"name": t["name"], "note": t["note"], "assets": assets}
    return {
        "meta": {"title": "알프레도 MVP 대시보드", "version": "V3", "end": END, "seed": SEED,
                 "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                 "band": "AI가 만든 정보이며 투자 권유가 아닙니다. 모의투자 기준입니다.",
                 "price_note": f"합성 일봉(시드 {SEED} 고정, 시작 100). 실제 시세가 아닙니다.",
                 "top3_url": B.TOP3_URL,
                 "method": ("확신도는 신호가 같은 방향을 가리키는 정도입니다(−100–+100, 확률·추천 아님). 신호마다 −1–+1로 읽고 "
                            "가중치는 모두 1로 평균합니다. 자료 없는 신호는 분모에서 빼고, 자료가 50% 미만이면 숫자를 보류합니다. "
                            "정량 신호는 퀀트 강의의 시계열 모멘텀 개념을 참고했고, 변동성 국면은 점수에 넣지 않습니다. "
                            "카드의 %는 Top3처럼 '우세 쪽 %'(50 + |점수| ÷ 2, 54% 이하는 중립)입니다."),
                 "chat_note": ("입력한 문장은 GPT(OpenAI)로 보내집니다. 개인 정보·계좌·금액은 적지 마세요. "
                               "답은 AI가 만든 정보이며 투자 권유가 아닙니다.")},
        "tabs": tabs,
    }


_L = B.LEAF
_SIG = {k: _L for k in ("group", "name", "tf", "x", "note")}
_SER = B.Map([_L], ["d", "c", "s50", "s200", "macd", "sig", "rsi"])
BOARD_SCHEMA = {
    "meta": {k: _L for k in ("title", "version", "end", "seed", "built_at", "band", "price_note", "top3_url", "method", "chat_note")},
    "tabs": B.Map({"name": _L, "note": _L, "assets": [{
        **{k: _L for k in ("id", "name", "price", "chg", "chg_pct", "hi_1d", "lo_1d", "summary", "sub")},
        "spark": [_L],
        "conf": {k: _L for k in ("score", "side_pct", "side", "label", "coverage", "formula")},
        "signals": [_SIG], "badge": {k: _L for k in ("vol20", "vol_med", "regime")}, "series": _SER}]}, list(TABS)),
}

DATA_TAG = '<script src="data/board.js"></script>'


def main() -> int:
    board = B.public_view(build(), BOARD_SCHEMA)
    text = json.dumps(board, ensure_ascii=False, separators=(",", ":"))
    os.makedirs(B.DATA, exist_ok=True)
    with open(os.path.join(B.DATA, "board.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(board, ensure_ascii=False, indent=1) + "\n")
    with open(os.path.join(B.DATA, "board.js"), "w", encoding="utf-8") as f:
        f.write("// build_board.py가 만든 파일. 고치지 말고 다시 만든다.\nwindow.ALFREDO_BOARD = " + text + ";\n")
    with open(os.path.join(MVP, "board.html"), encoding="utf-8") as f:
        page = f.read()
    if DATA_TAG not in page or B.FONT_URL not in page:
        raise SystemExit("board.html에서 데이터 태그나 글꼴 주소를 찾지 못했다")
    extra = ""
    for fn in ("index.html", "소개서_v2.md", os.path.join("data", "demo_week.js")):
        p = os.path.join(MVP, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                extra += f.read()
    font = B.make_font(page + text + extra)
    miss = B.missing_glyphs(page + text, font)
    if miss:
        raise SystemExit(f"부분 글꼴에 없는 글자: {''.join(miss)}")
    inline = "<script>\nwindow.ALFREDO_BOARD = " + text.replace("</", "<\\/") + ";\n</script>"
    font_uri = 'url("data:font/woff;base64,' + base64.b64encode(font).decode("ascii") + '")'
    out = page.replace(DATA_TAG, inline).replace(B.FONT_URL, font_uri)  # 로고는 board.html 안의 SVG(10-19, Top3 로고 대신)
    os.makedirs(B.DIST, exist_ok=True)
    with open(os.path.join(B.DIST, "alfredo_mvp_board.html"), "w", encoding="utf-8") as f:
        f.write(out)
    for k, t in board["tabs"].items():
        print(t["name"], " · ".join(f"{a['id']} {a['conf']['side_pct']}% {a['conf']['label']}" if a["conf"]["score"] is not None else f"{a['id']} 보류" for a in t["assets"]))
    print(f"첨부 {len(out.encode()) / 1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
