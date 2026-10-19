"""확신도(대시보드 KPI). v2: 2026-10-14 호연 결정(기획안 v5 4절), v1: 10-13 호연 P5·P6.

정미님 참고 프롬프트(10-11) '2. Confidence': "Confidence %는 분석에 사용된 신호들의 일치 정도를 종합하여 산출합니다."
판단 순서: ① 가격 위치 ② MACD ③ Stochastic ④ StochRSI ⑤ Open Interest ⑥ Coinbase Premium ⑦ Fear & Greed ⑧ News,
"하나의 지표만으로 Long 또는 Short를 결정하지 않습니다", 모멘텀이 약해지면 "Confidence는 낮추고".
정미님 구상(호연 전달) "기술 50 + 정성 50", 10-13 회의 "확률로 · 10%부터 90%". 수식·묶음 안 가중치는 우리 가정(정미님 확인 대기).

- 신호마다 x ∈ [−1, 1](+ Long, − Short). 읽는 법은 v1 그대로(모멘텀이 약해지는 신호는 ±0.5, 자료가 없거나 범위 밖이면 None).
- 묶음 둘: 기술 지표(가격 위치 8 · MACD 7 · Stochastic 6 · StochRSI 5)와 시장 자료(OI 8 · 코인베이스 프리미엄 7 · 공포탐욕 6 ·
  뉴스 방향 5). 묶음 점수 = 100 · Σ w·x ÷ Σ w(쓴 신호), 소수 첫째 자리로 반올림(0.5는 0에서 먼 쪽, 화면 식으로 손계산이 맞게).
- 묶음 충족률(쓴 가중치 ÷ 26)이 50% 미만이면 그 묶음을 뺀다. D = 남은 묶음 점수를 GROUP_SHARE 로 가중 평균(기본 반반) → 정수로
  반올림 → Long 확률 p = 50 + 0.4 × D 를 다시 정수로(10–90%). 두 묶음 모두 빠지면 숫자를 보류('자료 부족').
- 등급(p): 46–54 중립, 55–65·35–45 약한, 66–77·23–34 우세, 78 이상·22 이하 강한. 표시는 우세한 쪽의 확률(side_pct).
- 뉴스 방향: 12시간 안의 가장 최근 성공한 AI 분석(gpt·claude)이 낸 news_bias(기사 표지를 코드가 합친 값, ai_analysis.news_bias).
  관련 기사가 없으면(n = 0) 중립이 아니라 자료 없음.
- VPCI 는 넣지 않는다(Core Condition 의 마지막 단계이고 판단 순서 8개에 없음).

입력은 AI 분석과 같은 사실(ai_analysis.build_input)이고 AI 는 부르지 않는다(15분마다 계산, 같은 입력이면 같은 값).
트리거·채점·과거 재현에는 쓰지 않는다. 2차 회의의 '기술 지표 4개 가중 점수'는 검증 화면에 '기술 점수'로 남는다.
"""
from __future__ import annotations

import math
from fractions import Fraction

VERSION = "conf_v2"
GROUP_MIN_COVERAGE = 50   # 묶음 충족률(%)이 이보다 낮으면 그 묶음을 뺀다
NEWS_FRESH_MS = 12 * 3_600_000   # 뉴스 방향은 이 시간 안의 AI 분석만
TECH = [("price", "가격 위치", 8), ("macd", "MACD 4시간", 7), ("stoch", "Stochastic 1시간", 6), ("stochrsi", "StochRSI 1시간", 5)]
MARKET = [("oi", "미결제약정(OI)", 8), ("premium", "코인베이스 프리미엄", 7), ("fng", "공포탐욕지수", 6), ("news", "뉴스 방향", 5)]
GROUPS = (("tech", "기술 지표", TECH), ("market", "시장 자료", MARKET))
GROUP_SHARE = {"tech": 0.5, "market": 0.5}   # 묶음 몫(미래에 0:100 같은 비율로 바꿀 수 있게)
SIGNALS = TECH + MARKET
SHORT_NAME = {"price": "가격 위치", "macd": "MACD", "stoch": "Stochastic", "stochrsi": "StochRSI",
              "oi": "OI", "premium": "코인베이스 프리미엄", "fng": "공포탐욕", "news": "뉴스 방향"}
TOTAL_W = sum(w for _, _, w in SIGNALS)      # 52


def _sgn(x: float, eps: float = 0.0) -> int:
    return 1 if x > eps else -1 if x < -eps else 0


def _num(v, lo: float | None = None, hi: float | None = None):
    """유한한 숫자만(범위가 있으면 그 안만). 아니면 None — 그 신호는 자료 없음."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or (lo is not None and f < lo) or (hi is not None and f > hi):
        return None
    return f


def _pos(v):
    v = _num(v)
    return v if v is not None and v > 0 else None


def _round(v: float) -> int:
    """0.5는 0에서 먼 쪽으로(파이썬 round의 짝수 반올림을 쓰지 않음)."""
    return int(math.copysign(math.floor(abs(v) + 0.5), v))


def _fmt(v) -> str:
    """가격·지표 값: 1000 이상 정수, 10 이상 소수 둘째, 그 밖 넷째 자리. 음수는 '−'."""
    if v is None:
        return "-"
    a = abs(v)
    return f"{v:,.{0 if a >= 1000 else 2 if a >= 10 else 4}f}".replace("-", "−")


def _pct(v: float, nd: int = 2) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.{nd}f}%"


def read_price(inp: dict):
    pc = inp.get("price_context") or {}
    px, ema, mid = _pos(inp.get("current_price")), _pos(pc.get("ema20_4h")), _pos(pc.get("bb_mid_4h"))
    if None in (px, ema, mid):
        return None
    a, b = _sgn(px - ema), _sgn(px - mid)
    if a == b and a != 0:
        return a, f"현재가 {_fmt(px)} {'>' if a > 0 else '<'} EMA20 {_fmt(ema)}·중심선 {_fmt(mid)}", \
            "EMA20·볼린저 중심선 위" if a > 0 else "EMA20·볼린저 중심선 아래"
    return 0, f"현재가 {_fmt(px)} · EMA20 {_fmt(ema)} · 중심선 {_fmt(mid)}", "EMA20과 중심선 사이"


def read_macd(inp: dict):
    m = (inp.get("technical") or {}).get("macd_4h") or {}
    mac, sig, hist = _num(m.get("macd")), _num(m.get("signal")), _num(m.get("histogram"))
    raw = list(m.get("histogram_recent") or [])
    last2 = [_num(x) for x in raw[-2:]] if len(raw) >= 2 else [None, None]
    if None in (mac, sig):
        return None
    d = _sgn(mac - sig)
    if d == 0:
        return 0, f"MACD {_fmt(mac)} = 시그널", "시그널과 같음"
    val = f"MACD {_fmt(mac)} · 시그널 {_fmt(sig)} · 히스토그램 {_fmt(hist)}"
    side = "시그널 위" if d > 0 else "시그널 아래"
    if None in last2:                  # 최근·직전 히스토그램이 둘 다 있어야 커지는지 줄어드는지 본다(C6)
        return float(d), val, side
    prev, cur = last2
    if d * (cur - prev) < 0:           # 그 방향의 힘이 줄어듦(Long이면 히스토그램 감소, Short이면 증가)
        return d * 0.5, val, side + " · 히스토그램 축소(모멘텀 약화)"
    return float(d), val, side + (" · 히스토그램 확대" if cur != prev else " · 히스토그램 보합")


def read_stoch(inp: dict):
    s = (inp.get("technical") or {}).get("stoch_1h") or {}
    k, dd = _num(s.get("k"), 0, 100), _num(s.get("d"), 0, 100)
    if None in (k, dd):
        return None
    d = _sgn(k - dd)
    if d == 0:
        return 0, f"%K {k:.1f} · %D {dd:.1f}", "%K = %D"
    if d < 0 and k <= 20:
        return -0.5, f"%K {k:.1f} · %D {dd:.1f}", "%K < %D, 20 아래 과매도권(반등 위험)"
    if d > 0 and k >= 80:
        return 0.5, f"%K {k:.1f} · %D {dd:.1f}", "%K > %D, 80 위 과매수권(조정 위험)"
    return float(d), f"%K {k:.1f} · %D {dd:.1f}", "%K > %D" if d > 0 else "%K < %D"


def read_stochrsi(inp: dict):
    s = (inp.get("technical") or {}).get("stochrsi_1h") or {}
    raw = list(s.get("k_recent") or [])
    if len(raw) < 2:
        return None
    prev, k = _num(raw[-2], 0, 100), _num(raw[-1], 0, 100)
    if None in (prev, k):              # 최근·직전 봉이 둘 다 있어야 비교한다(결측을 건너뛰지 않음, C2)
        return None
    d = _sgn(k - prev, 1.0)            # 변화가 1 이하이면 보합
    val = f"%K {prev:.1f} → {k:.1f}"
    if d == 0:
        return 0, val, "보합"
    if d < 0 and k <= 20:
        return -0.5, val, "내림, 20 아래 과매도권(반등 위험)"
    if d > 0 and k >= 80:
        return 0.5, val, "오름, 80 위 과매수권(조정 위험)"
    return float(d), val, "오름" if d > 0 else "내림"


def read_oi(inp: dict):
    o = inp.get("open_interest") or {}
    oi, pr = _num(o.get("oi_change_pct")), _num(o.get("price_change_pct"))
    if None in (oi, pr):
        return None
    d = _sgn(pr, 0.1)                  # 가격 변화가 ±0.1% 이하이면 방향 없음
    val = f"OI {_pct(oi)} · 가격 {_pct(pr)} (24시간)"
    if d == 0:
        return 0, val, "가격 변화 거의 없음"
    o = _sgn(oi, 0.1)                  # OI 변화가 ±0.1% 이하이면 보합(C4)
    if o > 0:
        return float(d), val, "신규 Long 유입" if d > 0 else "신규 Short 유입"
    if o < 0:
        return d * 0.5, val, "Short 청산(약한 상승)" if d > 0 else "Long 청산(약한 하락)"
    return d * 0.5, val, "OI 거의 그대로(새 자금 없음)"


def read_premium(inp: dict):
    c = inp.get("coinbase_premium") or {}
    v, tr = _num(c.get("value_pct")), c.get("trend") or ""
    if v is None:
        return None
    d = _sgn(v, 0.005)                 # ±0.005% 이하이면 0
    val = f"{_pct(v, 3)} · {tr}"
    if d == 0:
        return 0, val, "거의 0"
    against = (d > 0 and tr == "하락") or (d < 0 and tr == "상승")
    note = ("양수(미국 현물 수요 우위)" if d > 0 else "음수(미국 현물 수요 약함)") + (", 추세는 반대" if against else "")
    return d * (0.5 if against else 1.0), val, note


def read_fng(inp: dict):
    f = inp.get("fear_greed") or {}
    now, y = _num(f.get("now"), 0, 100), _num(f.get("yesterday"), 0, 100)
    if None in (now, y):
        return None
    ch = now - y
    d = _sgn(ch, 2.5)                  # 하루 변화가 2 이하(정수 지수)이면 보합
    val = f"{int(now)}({f.get('now_class') or ''}) · 전날 {int(y)}"
    if d == 0:
        return 0, val, "전날과 비슷"
    if d > 0 and now >= 75:
        return 0.5, val, "오름, 극단적 탐욕(과열)"
    if d < 0 and now <= 25:
        return -0.5, val, "내림, 극단적 공포"
    return float(d), val, "심리 개선" if d > 0 else "심리 냉각"


NEWS_WORD = {1: "긍정 +1", 0: "중립 0", -1: "부정 −1"}


def read_news(inp: dict):
    """뉴스 방향(AI 분석의 기사 표지를 코드가 합친 값). board()가 12시간 안 분석의 news_bias 를 `_news`로 넣는다."""
    nw = inp.get("_news")
    if not isinstance(nw, dict):
        return None
    x, n = nw.get("x"), nw.get("n")
    if x not in (-1, 0, 1) or not isinstance(n, int) or n <= 0:
        return None
    when = nw.get("created_kst") or ""
    return float(x), f"{NEWS_WORD[x]} · 기사 {n}건" + (f" · {when} 분석" if when else ""), "AI가 붙인 기사 표지를 합친 방향"


READERS = {"price": read_price, "macd": read_macd, "stoch": read_stoch, "stochrsi": read_stochrsi,
           "oi": read_oi, "premium": read_premium, "fng": read_fng, "news": read_news}


def _round1(v: float) -> float:
    """소수 첫째 자리 반올림, 0.5는 0에서 먼 쪽."""
    return math.copysign(math.floor(abs(v) * 10 + 0.5 + 1e-9) / 10, v) + 0.0


def _rhalf(v: Fraction) -> int:
    """분수를 정수로, 0.5는 0에서 먼 쪽(부동소수점 꼬리 없이 정확하게, Fable 검토 10-14 지적 1)."""
    return (-1 if v < 0 else 1) * math.floor(abs(v) + Fraction(1, 2))


def combine(scores10: dict, share: dict) -> tuple[Fraction, int, Fraction, int]:
    """남은 묶음 점수(10배 정수, 예: +86.5 → 865)를 몫으로 가중 평균 → (D_raw, D, p_raw, p). 모두 정확한 분수 산술.
    예: 기술 −98.6 · 시장 +49.6 → D_raw −24.5 → D −25(부동소수점으로는 −24.499… → −24 로 어긋났음)."""
    wsum = sum(Fraction(str(share[k])) for k in scores10)
    d_raw = sum(Fraction(str(share[k])) * Fraction(v, 10) for k, v in scores10.items()) / wsum
    d = _rhalf(d_raw)
    p_raw = 50 + Fraction(2, 5) * d
    return d_raw, d, p_raw, min(90, max(10, _rhalf(p_raw)))


def level_of(p: int) -> str:
    """Long 확률 p(10–90)의 등급. 46–54 neutral, 55–65·35–45 low, 66–77·23–34 medium, 78 이상·22 이하 high."""
    d = abs(p - 50)
    return "neutral" if d <= 4 else "low" if d <= 15 else "medium" if d <= 27 else "high"


def label_of(p: int | None) -> str:
    if p is None:
        return "자료 부족"
    lv = level_of(p)
    if lv == "neutral":
        return "중립"
    side = "Long" if p >= 50 else "Short"
    return {"low": f"약한 {side}", "medium": f"{side} 우세", "high": f"강한 {side}"}[lv]


def _x(x: float) -> str:
    return "0" if x == 0 else f"{x:+g}".replace("-", "−")


def _s1(v: float) -> str:
    """묶음 점수 표시: +86.5 · −11.5 · 0.0"""
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.1f}"


def _num_txt(v: float) -> str:
    """식 안의 수: 정수면 정수, 아니면 소수 둘째 자리까지(끝 0 뺌). 음수는 '−'."""
    t = f"{abs(v):.2f}".rstrip("0").rstrip(".")
    return ("−" if v < 0 else "") + t


def _g(v: float) -> str:
    """식 안의 묶음 점수: 86.5 · −11.5 · 50.0(부호 + 는 붙이지 않음)."""
    return ("−" if v < 0 else "") + f"{abs(v):.1f}"


def _paren(v: float, f) -> str:
    return f"({f(v)})" if v < 0 else f(v)


def _group_text(name: str, rows: list[dict], g: dict) -> str:
    used = [r for r in rows if r["used"]]
    if not used:
        return f"{name}: 자료 없음"
    terms = " + ".join(f"{r['w']}×({_x(r['x'])})" for r in used)
    tail = "" if g["used"] else f" (충족률 {g['coverage_pct']}%, {GROUP_MIN_COVERAGE}% 미만이라 뺌)"
    return f"{name} ({terms}) ÷ {sum(r['w'] for r in used)} × 100 = {_s1(g['score'])}{tail}"


def compute(inp: dict | None, share: dict | None = None) -> dict | None:
    """build_input 결과 하나로 확신도를 계산한다. 쓸 수 있는 신호가 하나도 없으면 None."""
    if not inp:
        return None
    share = share or GROUP_SHARE
    rows, groups, texts, score10 = [], {}, [], {}
    for gkey, gname, sigs in GROUPS:
        g_rows, num, used_w, missing = [], Fraction(0), 0, []
        for key, name, w in sigs:
            got = READERS[key](inp)
            if got is None:
                why = inp.get("_news_why") if key == "news" else None
                g_rows.append({"key": key, "name": name, "group": gkey, "w": w, "x": None, "used": False,
                               "value": "-", "note": f"{why or '자료 없음'}(점수 제외)"})
                missing.append(SHORT_NAME[key])
                continue
            x, val, note = got
            g_rows.append({"key": key, "name": name, "group": gkey, "w": w, "x": x, "used": True, "value": val, "note": note})
            num += Fraction(w) * Fraction(x)
            used_w += w
        total = sum(w for _, _, w in sigs)
        cov = 100 * used_w / total
        score10[gkey] = _rhalf(1000 * num / used_w) if used_w else None     # 묶음 점수 × 10(정확한 반올림)
        score = None if score10[gkey] is None else score10[gkey] / 10
        ok = used_w > 0 and cov >= GROUP_MIN_COVERAGE and float(share.get(gkey, 0) or 0) > 0
        groups[gkey] = {"score": score, "coverage_pct": _round(cov), "used": ok, "missing": missing}
        texts.append(_group_text(gname, g_rows, groups[gkey]))
        rows += g_rows
    if not any(r["used"] for r in rows):
        return None
    names = {k: n for k, n, _ in GROUPS}
    live = [k for k, _, _ in GROUPS if groups[k]["used"]]
    dropped = [k for k, _, _ in GROUPS if not groups[k]["used"]]
    used_all = sum(r["w"] for r in rows if r["used"])
    out = {"version": VERSION, "coverage_pct": _round(100 * used_all / TOTAL_W), "groups": groups,
           "missing": [m for k, _, _ in GROUPS for m in groups[k]["missing"]],
           "signals": rows, "ref_t": inp.get("_ref_t"), "ref_kst": inp.get("ref_kst"), "price": inp.get("current_price")}
    if dropped and live:
        gone = dropped[0]
        if not float(share.get(gone, 0) or 0) > 0:          # 설정으로 뺀 묶음(미래 0:100 비율)
            out["note"] = f"{names[live[0]]}만으로 계산(설정)"
        else:
            out["note"] = (f"{names[gone]} 부족: {'·'.join(groups[gone]['missing']) or '자료'} 없음 → {names[live[0]]}만")
        rest = groups[live[0]]["missing"]              # 남은 묶음에서 빠진 신호도 적는다(Fable 검토 지적 7)
        if rest:
            out["note"] += f" · {'·'.join(rest)} 없음"
    elif out["missing"] and live:
        out["note"] = f"{'·'.join(out['missing'])} 없음"
    else:
        out["note"] = None
    if not live:
        out.update({"p_long": None, "side": None, "side_pct": None, "level": None, "label": label_of(None),
                    "score": None, "support_pct": None, "note": "두 묶음 모두 자료 부족",
                    "formula": " · ".join(texts) + " · 두 묶음 모두 충족률 50% 미만이라 보류"})
        return out
    wsum = sum(float(share[k]) for k in live)
    d_frac, d, p_frac, p = combine({k: score10[k] for k in live}, share)
    d_raw, p_raw = float(d_frac), float(p_frac)
    side = "Long" if p >= 50 else "Short"
    s = 1 if side == "Long" else -1
    support = None
    if p != 50:
        sup = {}
        for k in live:
            used = [r for r in rows if r["group"] == k and r["used"]]
            sup[k] = sum(r["w"] * max(s * r["x"], 0) for r in used) / sum(r["w"] for r in used)
        support = _round(100 * sum(float(share[k]) * sup[k] for k in live) / wsum)
    gs = [groups[k]["score"] for k in live]
    if len(live) == 1:
        d_txt = f"D = {_g(gs[0])}"
    elif len({float(share[k]) for k in live}) == 1:
        d_txt = "D = (" + " + ".join(_g(v) if i == 0 or v >= 0 else f"({_g(v)})" for i, v in enumerate(gs)) + f") ÷ {len(live)}"
        d_txt += f" = {_num_txt(d_raw)}"
    else:
        d_txt = "D = " + " + ".join(f"{_num_txt(float(share[k]) / wsum)} × {_paren(groups[k]['score'], _g)}" for k in live)
        d_txt += f" = {_num_txt(d_raw)}"
    if _num_txt(d_raw) != _num_txt(d):
        d_txt += f" → {_num_txt(d)}"
    p_txt = f"확신도 = 50 + 0.4 × {_paren(d, _num_txt)} = {_num_txt(p_raw)}" + ("%" if _num_txt(p_raw) == str(p) else f" → {p}%")
    out.update({"p_long": p, "side": side, "side_pct": p if p >= 50 else 100 - p, "level": level_of(p), "label": label_of(p),
                "score": d, "support_pct": support, "formula": " · ".join(texts + [d_txt, p_txt])})
    return out


def _news_for(conn, symbol: str, now: int) -> tuple[dict | None, str]:
    """(입력에 넣을 뉴스 방향, 없을 때 까닭). 가장 최근의 성공한 AI 분석이 12시간 안이고 관련 기사가 있을 때만."""
    import ai_analysis
    import db
    got = ai_analysis.latest(conn, symbol, until=now)
    if got is None:
        return None, "AI 분석 없음"
    if not 0 <= now - int(got["created_at"]) <= NEWS_FRESH_MS:
        return None, "12시간 안 AI 분석 없음"
    nb = (got.get("body") or {}).get("news_bias")
    if not isinstance(nb, dict):
        return None, "기사 표지 없음(V5 전 분석)"
    if not isinstance(nb.get("n"), int) or nb["n"] <= 0 or nb.get("x") not in (-1, 0, 1):
        return None, "관련 기사 없음"
    return {"x": int(nb["x"]), "n": int(nb["n"]), "created_kst": db.kst_text(int(got["created_at"]), "%m-%d %H:%M")}, ""


def board(conn, symbols, now: int) -> dict:
    """화면용: 코인별 확신도. 계산이 실패하거나 자료가 없는 코인은 None이고, 까닭은 `_errors`에 남긴다(화면 '⚠ 상태')."""
    import ai_analysis
    out, errors = {}, {}
    for s in symbols:
        try:
            inp = ai_analysis.build_input(conn, s, now)
            if inp is not None:
                try:
                    nw, why = _news_for(conn, s, now)
                except Exception as e:  # noqa: BLE001 — 뉴스 방향을 못 읽어도 나머지 신호로 계산한다
                    nw, why = None, f"뉴스 방향 읽기 실패({type(e).__name__})"
                inp = dict(inp, _news=nw, _news_why=why or None)
            out[s] = compute(inp)
            if out[s] is None:
                errors[s] = "자료 없음"
        except Exception as e:  # noqa: BLE001 — 한 코인 실패가 다른 코인·보드 전체를 막지 않게
            out[s] = None
            errors[s] = f"계산 실패({type(e).__name__})"
    if errors:
        out["_errors"] = errors
    return out
