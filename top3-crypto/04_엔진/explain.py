"""해설: 계산 결과를 2~3문장으로. 기획서 ver3 AI학습용 §1-8.

- 기본은 템플릿(결정적 문장). conf/explain.json 의 enabled=true 일 때만 GPT 호출.
  provider: "codex_cli"(10-04 호연 G1: ChatGPT Plus 로그인된 Codex CLI로 codex_model 호출, 추가 결제 없음, Plus 사용량에서 차감)
  또는 "openai_api"(OPENAI_API_KEY 필요, 유료. 호연 확인: API 데이터 공유를 켜면 하루 무료 토큰이 있을 수 있음).
- GPT 는 **숫자를 쓰지 않는다**(점수·가격·지표 값은 화면과 템플릿이 코드 값으로 보여 준다). 그래서 숫자를 지어낼 길이 없다.
  허용하는 숫자 표현은 시간대(4시간·1시간·15분)뿐이다.
- GPT 결과는 종목 집합·방향·확실한 신호 여부·금지 표현·길이 검사를 모두 통과해야 쓰고, 하나라도 실패하면 템플릿으로 바꾸고 이유를 남긴다.
- 방향·점수·확실한 신호는 코드가 정한 값이며 LLM 은 바꾸지 않는다.
- v2(10-06 호연 P3 "규칙이 낮으면 발전시켜줘"): v1은 숫자를 막아 템플릿을 다시 쓰는 데 그쳤다. v2는 입력에 사실을 더 넣고
  (지표 전환 시각, 확실한 신호까지 남은 지표, 24시간 변동·위치, 과거 같은 점수 성적, 신호가 켜진 시각),
  숫자는 **입력에 있는 숫자만** 쓰게 검사한다. "X가 Y로 바뀌면 확실한 신호"처럼 지켜볼 조건 문장은 따로 검사한다.
  conf prompt_version 이 explain_v2 로 시작하면 v2.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

import db
import pipeline

NAMES = {"BTCUSDT": "비트코인", "ETHUSDT": "이더리움", "XRPUSDT": "리플"}
DIR_WORD = {1: "Long", -1: "Short", 0: "방향 없음"}
FNG_KO = {"Extreme Fear": "극단적 공포", "Fear": "공포", "Neutral": "중립", "Greed": "탐욕", "Extreme Greed": "극단적 탐욕"}
TIMEFRAME_TOKENS = re.compile(r"(4\s*시간|1\s*시간|15\s*분)")
KOREAN_NUMERAL = re.compile(r"[일이삼사오육칠팔구십백천만억조]+\s*(달러|원|퍼센트|%|배|개|만|억)")
KOREAN_NUM_WORD = re.compile(r"[일이삼사오육칠팔구](십|백|천|만|억)|(십|백|천)[일이삼사오육칠팔구]")  # 칠십일, 구만 등
KOREAN_NUM_SAFE = re.compile(r"이만(큼|하|한|해)")  # 일상어 예외
UNIT_WORDS = re.compile(r"퍼센트|포인트|달러")  # 숫자 없이 단위만 써도 수치를 말하는 것으로 본다
# 방향어. 10-04 GPT-6.1 Sol 재현: "상승세"·"강세" 같은 말이 빠져 있었음 → 추가(잘못 거르면 템플릿으로 바뀔 뿐이라 넓게 잡음)
# "방향 없음"도 방향 값으로 본다(10-04 Fable 재현: "Stochastic·StochRSI는 방향 없음, VPCI는 Short"를 모순으로 거부했음)
DIR_TOKEN = re.compile(r"long|short|롱|숏|(?:상승|하락|오름|내림)\s*(?:방향|쪽|우세|세)|강세|약세|방향\s*없음", re.IGNORECASE)
# 방향어를 부정하면("Long이 아닙니다") 어느 방향인지 검사할 수 없어 거부한다
DIR_NEGATED = re.compile("(?:" + DIR_TOKEN.pattern + r")(?:\s*우세)?\S{0,3}\s*(?:아니|아닙|아님|없)", re.IGNORECASE)
# 고유어 숫자. 드문 말은 어디서나, 흔한 말(하나·열 등)은 점수·값 뒤에서만 본다
NATIVE_NUM = re.compile(r"스물|서른|마흔|예순|일흔|여든|아흔")
NATIVE_NUM_AFTER = re.compile(r"(점수|값|가격|지수|수치)\S{0,2}\s*(?:(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열|쉰)(?![가-힣]{2})"
                              r"|(?:한|두|세|네)\s*(?:점|개|배|자리|단계|칸))")   # "한 방향"처럼 수량이 아닌 말은 통과(10-04 Fable)
# 확실한 신호를 부정하는 말(같은 문장 안, 12글자 안)
STRONG_NEGATED = re.compile(r"확실한\s*신호[^.!?\n]{0,12}?(?:아니|아닙|아님|없|어렵|못)")
NUM_WORD_AFTER = re.compile(r"(점수|값|가격|지수|수치)\S{0,2}\s*[일이삼사오육칠팔구십백천만억]+\s*(입니다|이다|이고|이며|점|으로|로|$|[.,])")
DOUBLE_NEG = re.compile(r"아니지\s*않|아닌\s*것은\s*아니")


def _dir_word(tok: str) -> str:
    t = tok.lower()
    if t.startswith("방향"):
        return "방향 없음"
    return "Long" if (t == "long" or t == "롱" or t.startswith(("상승", "오름", "강세"))) else "Short"
# 지표 이름(또는 시간대) → snapshot 키. StochRSI 를 Stochastic 보다 먼저 본다.
# 묶음(②)을 가리키는 말을 먼저 찾아 지운다. 10-04 Luna 리허설: "스토캐스틱 RSI와 스토캐스틱 조합은 방향 없음"의
# "스토캐스틱 조합"(= 묶음, 방향 없음)을 Stochastic(Short)으로 읽어 맞는 문장을 거부했음.
IND_NAMES = [("stoch_pair_1h", r"(?:Stochastic|스토캐스틱)\s*(?:조합|묶음|쌍)|1\s*시간\s*(?:조건|묶음)"),   # "스토캐스틱 RSI 조합"은 StochRSI로 읽음(Fable 반례)
             ("stochrsi_1h", r"StochRSI|스토캐스틱\s*RSI"), ("stochastic_1h", r"Stochastic|스토캐스틱"),
             ("macd_4h", r"MACD|4\s*시간"), ("vpci_15m", r"VPCI|15\s*분"), ("stoch_pair_1h", r"1\s*시간")]


def signed(n) -> str:
    return f"+{n}" if n > 0 else (f"−{abs(n)}" if n < 0 else "0")


def _rules_for(conn, version):
    r = conn.execute("SELECT rules_json FROM rules_versions WHERE rules_version=?", (version,)).fetchone()
    return json.loads(r[0]) if r else db.load_json("rules_v3.json")


def fng_class_for(conn, t_close: int) -> str | None:
    """T 에 쓴 공포탐욕 값(기준일 < T 인 마지막 값)과 같은 날의 공식 분류만 붙인다. 그날 분류를 모르면 None.
    찾는 곳: fng_latest(최신 1건), fng_class_recent(수집기가 남긴 최근 14일 {기준일 ms: 분류})."""
    day = conn.execute("SELECT MAX(ts) FROM series WHERE source='alternative.me' AND metric='fear_greed' AND ts<?",
                       (t_close,)).fetchone()[0]
    if day is None:
        return None
    c = None
    try:
        latest = json.loads(db.kv_get(conn, "fng_latest") or "{}")
        if int(latest.get("timestamp", -1)) == int(day):
            c = latest.get("classification")
        if c is None:
            c = json.loads(db.kv_get(conn, "fng_class_recent") or "{}").get(str(int(day)))
    except (ValueError, TypeError):
        return None
    return FNG_KO.get(c, c) if c else None


def snapshot(conn, t_close: int, version: str) -> dict:
    rules = _rules_for(conn, version)
    rows = conn.execute(
        "SELECT symbol, close, score, strong, strong_dir, macd_dir, sto_state, srsi_state, pair_dir, vpci_dir, "
        "fng, status FROM analyses WHERE mode='live' AND t_close=? AND rules_version=? ORDER BY symbol",
        (t_close, version)).fetchall()
    items, fng = [], None
    for (sym, close, score, strong, sdir, md, ss, rs, pdir, vd, fv, status) in rows:
        fng = fv if fv is not None else fng
        ok = status == "ok" and score is not None
        items.append({
            "symbol": sym, "name": NAMES.get(sym, sym), "status": status,
            "score": score if ok else None,
            "label": pipeline.label(score if ok else None, strong or 0, sdir or 0, md, pdir, vd, rules.get("weights")),
            "strong": bool(strong) if ok else False,
            "macd_4h": DIR_WORD[md or 0], "stochastic_1h": DIR_WORD[ss or 0], "stochrsi_1h": DIR_WORD[rs or 0],
            "stoch_pair_1h": DIR_WORD[pdir or 0], "vpci_15m": DIR_WORD[vd or 0],
            "pair_mode": rules.get("stoch_pair", {}).get("mode", "zone_event"),
        })
    return {"t_close_kst": db.kst_text(t_close, "%Y-%m-%d %H:%M KST"), "rules_status": rules.get("status"),
            "fear_greed": {"value": fng, "classification_ko": fng_class_for(conn, t_close)}, "items": items}


def _pair_reason(it) -> str:
    a, b = it["stochastic_1h"], it["stochrsi_1h"]
    if a == "방향 없음" and b == "방향 없음":
        if it.get("pair_mode") == "kd_state":
            return "Stochastic과 StochRSI 모두 %K가 %D와 같은 쪽으로 움직이지 않아(위에서 오르거나 아래에서 내리지 않아) 1시간 조건이 비어 있습니다."
        return "Stochastic과 StochRSI 모두 아직 기준(80 이상·20 이하) 교차가 없어 1시간 조건이 비어 있습니다."
    if a == "방향 없음" or b == "방향 없음":
        return "Stochastic과 StochRSI 중 하나만 방향이 있어 1시간 조건이 비어 있습니다."
    return "Stochastic과 StochRSI의 방향이 서로 달라 1시간 조건이 비어 있습니다."


def template_text(it) -> str:
    if it["status"] != "ok" or it["score"] is None:
        return f"{it['name']}: 데이터가 부족하거나 지표 계산 준비 중이라 이번 분석은 점수를 내지 않았습니다."
    name, m, p, v = it["name"], it["macd_4h"], it["stoch_pair_1h"], it["vpci_15m"]
    sc = signed(it["score"])
    if it["strong"]:
        return f"{name}: 네 지표가 모두 {m} 방향이라 가중 점수 {sc}, 확실한 신호입니다."
    if it["label"].startswith("MACD만"):
        return (f"{name}: MACD(4시간)만 {m}이고 Stochastic·StochRSI(1시간)와 VPCI(15분)는 {p}입니다. "
                f"MACD 가중치가 커서 가중 점수는 {sc}({m} 쪽)이며 확실한 신호는 아닙니다.")
    s = (f"{name}: MACD(4시간) {m}, Stochastic·StochRSI(1시간) {p}, VPCI(15분) {v}입니다. "
         f"가중 점수 {sc}")
    s += ", 방향이 없습니다." if it["score"] == 0 else f"로 {it['label']}이지만 확실한 신호는 아닙니다."
    if p == "방향 없음":
        s += " " + _pair_reason(it)
    return s


def template(snap: dict) -> dict:
    out = [{"symbol": it["symbol"], "text": template_text(it)} for it in snap["items"]]
    f = snap["fear_greed"]
    overall = ""
    if f["value"] is not None:
        cls = f.get("classification_ko")
        overall = f"공포탐욕지수는 {int(f['value'])}" + (f"({cls}, alternative.me)입니다." if cls else "(alternative.me)입니다.")
    if snap.get("rules_status") == "temp":
        overall = (overall + " " if overall else "") + "임시 규칙으로 계산한 결과입니다."
    return {"items": out, "overall": overall.strip()}


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _mentioned(span: str) -> list[str]:
    """구간 안에 이름이 나온 지표의 snapshot 키. Stochastic·StochRSI 가 나오면 '1시간'(묶음)은 따로 보지 않는다."""
    keys, rest = [], span
    for key, pat in IND_NAMES:
        if key == "stoch_pair_1h" and ("stochastic_1h" in keys or "stochrsi_1h" in keys) and pat == IND_NAMES[-1][1]:
            continue   # 뒤쪽 "1시간"만으로는 묶음인지 알 수 없을 때
        if re.search(pat, rest, re.IGNORECASE):   # vpci·macd 처럼 소문자도(10-04 Sol 재현)
            if key not in keys:
                keys.append(key)
            rest = re.sub(pat, " ", rest, flags=re.IGNORECASE)  # StochRSI 를 지운 뒤 Stochastic 을 찾는다
    return keys


def direction_conflict(text: str, src: dict) -> str | None:
    """문장 속 Long/Short 가 입력과 어긋나는지. 방향 단어마다 그 앞(같은 문장, 직전 방향 단어 뒤)에 나온 지표를 본다.
    지표 이름이 있으면 그 지표의 방향과, 없으면 종목 판정(label)의 방향과 같아야 한다."""
    label = src["label"]
    side = "Long" if label in ("Long 우세", "확실한 신호 Long", "MACD만 Long") else (
        "Short" if label in ("Short 우세", "확실한 신호 Short", "MACD만 Short") else (
            "방향 없음" if "방향 없음" in label else None))
    for sent in re.split(r"[.!?\n]", text):
        start = 0
        for m in DIR_TOKEN.finditer(sent):
            word = _dir_word(m.group(0))
            keys = _mentioned(sent[start:m.start()])
            start = m.end()
            if keys:
                for k in keys:
                    if src.get(k) != word:
                        return f"방향 모순({k} {src.get(k)} ↔ {word})"
            elif side != word:
                return f"방향 모순(판정 {label} ↔ {word})"
    return None


IND_LABEL = {"macd_4h": "MACD(4시간)", "stoch_pair_1h": "1시간 조건(Stochastic·StochRSI)", "vpci_15m": "VPCI(15분)"}
H4 = db.PERIOD_MS["4h"]; M15 = db.PERIOD_MS["15m"]


def _ago(t_close: int, ms) -> str | None:
    """전환 시각을 'MM-DD HH:MM'(KST)로. 없으면 None."""
    return db.kst_text(int(ms)) if ms else None


def snapshot_v2(conn, t_close: int, version: str) -> dict:
    """v1 입력 + 사실 몇 가지(모두 코드가 계산). 해설이 쓸 수 있는 숫자는 이 안의 숫자뿐이다."""
    snap = snapshot(conn, t_close, version)
    try:
        replay = json.loads((db.ENGINE / "reports" / "replay_summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        replay = {}
    same = replay.get("rules_version") == version
    hints = replay.get("score_hint_reference", {}) if same else {}
    ref = replay.get("periods", {}).get("reference", {})
    snap["next_analysis_kst"] = db.kst_text(t_close + H4, "%H:%M")
    for it in snap["items"]:
        sym = it["symbol"]
        a = conn.execute("SELECT macd_last_cross, sto_last_event, srsi_last_event, vpci_last_cross, close, strong, strong_dir "
                         "FROM analyses WHERE mode='live' AND rules_version=? AND symbol=? AND t_close=?",
                         (version, sym, t_close)).fetchone()
        if not a or it["score"] is None:
            continue
        it["changed_at_kst"] = {"macd_4h": _ago(t_close, a[0]), "stochastic_1h": _ago(t_close, a[1]),
                                "stochrsi_1h": _ago(t_close, a[2]), "vpci_15m": _ago(t_close, a[3])}
        side = 1 if it["score"] > 0 else -1 if it["score"] < 0 else 0
        dirs = {"macd_4h": it["macd_4h"], "stoch_pair_1h": it["stoch_pair_1h"], "vpci_15m": it["vpci_15m"]}
        want = DIR_WORD[side]
        it["side"] = want
        # 확실한 신호까지 남은 지표(점수 쪽과 다른 묶음). 확실한 신호가 아니고 방향이 있을 때만
        it["to_strong"] = [] if it["strong"] or side == 0 else [IND_LABEL[k] for k, v in dirs.items() if v != want]
        if not it["strong"] and side != 0 and not it["to_strong"]:
            # 10-06 순서 조건: 세 단계가 같은 방향이지만 VPCI 가 정렬보다 먼저 돌았음
            it["note"] = ("세 단계가 같은 방향이지만 VPCI(15분)가 4시간·1시간이 맞춰지기 전에 돌아서, "
                          "조건서대로 VPCI가 다시 돌 때까지 확실한 신호가 아닙니다.")
        # 24시간 가격(15분봉): 분석 시각 종가 대비 24시간 전 종가, 그 사이 고가·저가 중 어디쯤인지
        rows = conn.execute("SELECT ts, high, low, close FROM candles WHERE source='binance' AND symbol=? AND period='15m' "
                            "AND ts>=? AND ts<? ORDER BY ts", (sym, t_close - 86_400_000 - M15, t_close)).fetchall()
        if len(rows) == 97:
            base, win, last = rows[0][3], rows[1:], rows[-1][3]
            hi, lo = max(r[1] for r in win), min(r[2] for r in win)
            pos = (last - lo) / (hi - lo) if hi > lo else 0.5
            it["price_24h"] = {"change_pct": round(100 * (last / base - 1), 2),
                               "position": "고가 근처" if pos >= 0.8 else "저가 근처" if pos <= 0.2 else "중간"}
        h = hints.get(sym, {}).get(str(it["score"]))
        if h and it["score"] != 0:
            up = h["up_pct"]
            it["past_same_score"] = {"period": f"{ref.get('from', '')}–{ref.get('to', '')}", "n": h["n"],
                                     "same_direction_pct": up if it["score"] > 0 else round(100 - up, 1)}
        if it["strong"]:
            # 확실한 신호가 같은 방향으로 이어진 첫 분석 시각
            hist = conn.execute("SELECT t_close, strong, strong_dir FROM analyses WHERE mode='live' AND rules_version=? "
                                "AND symbol=? AND t_close<=? ORDER BY t_close DESC LIMIT 60", (version, sym, t_close)).fetchall()
            since = t_close
            for t, st, sd in hist:
                if st and sd == a[6]:
                    since = t
                else:
                    break
            it["strong_since_kst"] = db.kst_text(since)
            prev = conn.execute("SELECT close FROM candles WHERE source='binance' AND symbol=? AND period='4h' AND ts=?",
                                (sym, since - 7 * H4)).fetchone()
            first = conn.execute("SELECT close FROM analyses WHERE mode='live' AND rules_version=? AND symbol=? AND t_close=?",
                                 (version, sym, since)).fetchone()
            if prev and first and prev[0]:
                mv = round(100 * a[6] * (first[0] / prev[0] - 1), 2)
                it["moved_before_signal"] = f"신호 방향으로 {mv}%" if mv >= 0 else f"신호 반대 방향으로 {abs(mv)}%"
    return snap


# 입력 항목 이름(영어 키)이 문장에 나오면 거부. 10-06 17:00 실제 사례: "공포탐욕지수는 탐욕이며 value는 73입니다"
KEY_NAMES = re.compile(r"(?<![A-Za-z_])(value|label|side|to_strong|classification\w*|price_24h|past_same_score|changed_at_kst|strong_since_kst|moved_before_signal|next_analysis_kst)(?![A-Za-z_])", re.IGNORECASE)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
COND = re.compile(r"(바뀌면|돌아서면|전환되면|바뀐다면|맞춰지면|같아지면)")


def _allowed_numbers(snap: dict) -> set[str]:
    """입력 JSON 에 나오는 숫자(쉼표 없이). 시간대 4·1·15 와 '24시간'의 24 포함."""
    text = json.dumps(snap, ensure_ascii=False)
    nums = {n.replace(",", "") for n in NUM.findall(text)}
    out = set()
    for n in nums:
        out.add(n)
        if "." in n:
            out.add(n.rstrip("0").rstrip("."))
    return out | {"4", "1", "15", "24"}


def _check_numbers(t: str, allowed: set[str]) -> str | None:
    for n in NUM.findall(t):
        k = n.replace(",", "")
        if k not in allowed and k.rstrip("0").rstrip(".") not in allowed:
            return f"입력에 없는 숫자: {n}"
    return None


def _check_conditional(sent: str, src: dict) -> str | None:
    """'X가 Y로 바뀌면 확실한 신호 Y' 같은 조건 문장: 확실한 신호가 아닐 때만, 방향어는 점수 쪽과 같고, 이름이 나온 지표는
    점수 쪽과 이미 같은 지표이거나 to_strong 에 있는 지표여야 한다."""
    if src.get("strong") or src.get("side") in (None, "방향 없음"):
        return "조건 문장을 쓸 수 없는 상태"
    for m in DIR_TOKEN.finditer(sent):
        if _dir_word(m.group(0)) != src["side"]:
            return "조건 문장의 방향이 점수 쪽과 다름"
    names = {"macd_4h": "MACD(4시간)", "stoch_pair_1h": "1시간 조건(Stochastic·StochRSI)",
             "stochastic_1h": "1시간 조건(Stochastic·StochRSI)", "stochrsi_1h": "1시간 조건(Stochastic·StochRSI)",
             "vpci_15m": "VPCI(15분)"}
    for k in _mentioned(sent):
        if names[k] not in src.get("to_strong", []) and src.get(k if k in src else "stoch_pair_1h") != src["side"]:
            return f"조건 문장의 지표가 맞지 않음({k})"
    return None


def validate(body: dict, snap: dict, conf: dict) -> str | None:
    """GPT 결과 검사. 문제 있으면 이유 문자열, 없으면 None. (템플릿에는 쓰지 않는다: 템플릿은 코드 값으로 만든다)"""
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return "items 비어 있음"
    want = [it["symbol"] for it in snap["items"]]
    got = [it.get("symbol") for it in items]
    if sorted(got) != sorted(want) or len(set(got)) != len(got):
        return "종목 집합 불일치"
    forb = [_norm(w) for w in conf.get("forbidden", [])]
    limit = int(conf.get("max_chars_per_symbol", 200))
    texts = [(it.get("symbol"), it.get("text", "")) for it in items] + [(None, body.get("overall", ""))]
    by_sym = {it["symbol"]: it for it in snap["items"]}
    v2 = str(conf.get("prompt_version", "")).startswith("explain_v2")
    allowed = _allowed_numbers(snap) if v2 else None
    for sym, t in texts:
        if not isinstance(t, str):
            return "문장 형식 오류"
        if sym is not None and (not t.strip() or len(t) > limit):
            return "길이 위반"
        nt = _norm(t)
        for w in forb:
            if w and w in nt:
                return f"금지 표현: {w}"
        bare = KOREAN_NUM_SAFE.sub("", t)
        if v2:
            bad = _check_numbers(t, allowed)
            if bad:
                return bad
        if v2 and KEY_NAMES.search(t):
            return "입력 항목 이름이 그대로 나옴"
        if v2 and (KOREAN_NUMERAL.search(bare) or KOREAN_NUM_WORD.search(bare) or UNIT_WORDS.search(t)
                   or NATIVE_NUM.search(t)):
            return "한글 숫자·단위 말 사용(숫자는 입력 값 그대로)"
        if not v2 and (re.search(r"\d", TIMEFRAME_TOKENS.sub("", t)) or KOREAN_NUMERAL.search(bare)
                or KOREAN_NUM_WORD.search(bare) or UNIT_WORDS.search(t) or NUM_WORD_AFTER.search(bare)
                or NATIVE_NUM.search(t) or NATIVE_NUM_AFTER.search(t)):
            return "숫자 사용(숫자는 코드가 표시)"
        if DOUBLE_NEG.search(t):
            return "이중 부정(뜻이 모호함)"
        if DIR_NEGATED.search(t):
            return "방향 부정(뜻이 모호함)"
        if sym is None:
            # 전체 요약에는 방향·확실한 신호를 쓰지 않는다(종목 문장에서만, 검사 가능한 범위로)
            if DIR_TOKEN.search(t) or re.search(r"확실한\s*신호|상승\s*우세|하락\s*우세", t):
                return "전체 요약에 방향 언급"
            continue
        src = by_sym[sym]
        if v2:   # 조건 문장은 따로 검사하고, 나머지 검사에서는 뺀다
            keep = []
            for sent in re.split(r"(?<=[.!?])\s+|\n", t):
                if COND.search(sent):
                    bad = _check_conditional(sent, src)
                    if bad:
                        return bad
                else:
                    keep.append(sent)
            t = " ".join(keep)
        # 확실한 신호가 아닌데 "확실한 신호"라고 쓰려면 부정이 붙어야 한다(부정 표현은 강한 신호 쪽과 같은 범위로, 10-04 Fable)
        if not src["strong"] and re.search(r"확실한\s*신호", t) and not STRONG_NEGATED.search(t):
            return "확실한 신호 아님"
        if src["strong"] and "확실한 신호" not in t:
            return "확실한 신호 누락"
        if src["strong"] and STRONG_NEGATED.search(t):
            return "확실한 신호인데 부정함"
        long_side = src["label"] in ("Long 우세", "확실한 신호 Long", "MACD만 Long")
        short_side = src["label"] in ("Short 우세", "확실한 신호 Short", "MACD만 Short")
        if (long_side and re.search(r"하락\s*우세", t)) or (short_side and re.search(r"상승\s*우세", t)):
            return "방향 모순"
        conflict = direction_conflict(t, src)
        if conflict:
            return conflict
    return None


SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "overall"],
    "properties": {
        "items": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["symbol", "text"],
            "properties": {"symbol": {"type": "string"}, "text": {"type": "string"}}}},
        "overall": {"type": "string"},
    },
}


def call_gpt(conf: dict, snap: dict) -> dict:
    prompt = (db.ENGINE / conf["prompt_file"]).read_text(encoding="utf-8")
    payload = {
        "model": conf["model"],
        "input": [{"role": "system", "content": prompt},
                  {"role": "user", "content": json.dumps(snap, ensure_ascii=False)}],
        "text": {"format": {"type": "json_schema", "name": "explanation", "strict": True, "schema": SCHEMA}},
    }
    req = urllib.request.Request(conf["endpoint"], data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=conf.get("timeout_sec", 60)) as r:
        resp = json.loads(r.read().decode("utf-8"))
    for out in resp.get("output", []):
        for c in out.get("content", []) or []:
            if c.get("type") == "output_text":
                return json.loads(c["text"])
    raise ValueError("응답에 output_text 없음")


def _codex_env() -> dict:
    """Codex에 넘기는 환경 변수는 최소한만. 10-05 01:00 첫 운영 리허설이 240초 시간 초과로 실패했는데, explain()이 먼저
    .env를 읽어 OPENAI_API_KEY가 환경에 들어간 상태였다. Codex는 OPENAI_API_KEY·CODEX_API_KEY가 있으면 그것을 인증으로
    쓰므로(ChatGPT Plus 로그인 대신 유료 API) 비밀값은 하나도 넘기지 않는다. 로그인은 ~/.codex/auth.json(HOME 기준)."""
    keep = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR")
    env = {k: os.environ[k] for k in keep if os.environ.get(k)}
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    return env


def _tail(text) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return " ".join((text or "").split())[-300:]


def call_codex(conf: dict, snap: dict) -> dict:
    """Codex CLI(ChatGPT Plus 로그인)로 해설 생성. 빈 임시 폴더에서 읽기 전용으로 돌리고 세션 기록을 남기지 않는다
    (--ephemeral). 출력 모양은 SCHEMA로 강제하고, 검사(validate)는 API 경로와 똑같이 거친다."""
    prompt = (db.ENGINE / conf["prompt_file"]).read_text(encoding="utf-8")
    msg = (prompt + "\n\n## 입력(JSON)\n" + json.dumps(snap, ensure_ascii=False)
           + "\n\n파일을 읽거나 명령을 실행하지 말고, 위 입력만으로 스키마에 맞는 JSON 하나만 답하라.")
    with tempfile.TemporaryDirectory() as d:
        schema, out = Path(d) / "schema.json", Path(d) / "out.json"
        schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        # --ignore-user-config: 전역 config.toml(플러그인 19개·notify 앱 실행)을 싣지 않는다. 10-04 실측: 토큰 10,439 → 6,805,
        # 10초 → 4초. 전역 ~/.codex/AGENTS.md는 그래도 실리는데, 따로 CODEX_HOME을 두면 로그인 토큰이 갈라질 위험이 있어 그대로 둠.
        cmd = [conf.get("codex_bin", "codex"), "exec", "--ignore-user-config", "-m", conf["codex_model"],
               "-c", f"model_reasoning_effort={conf.get('codex_effort', 'low')}",
               "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", d,
               "--output-schema", str(schema), "-o", str(out), "-"]
        timeout = conf.get("codex_timeout_sec", 240)
        try:
            r = subprocess.run(cmd, input=msg, text=True, capture_output=True, timeout=timeout, env=_codex_env())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"codex 시간 초과 {timeout}초: {_tail(exc.stderr)}") from None
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"codex 종료 코드 {r.returncode}: {_tail(r.stderr)}")   # 로그인 만료·사용량 한도 등 원인
        return json.loads(out.read_text(encoding="utf-8"))


def explain(conn, t_close: int, version: str, allow_gpt: bool = True) -> dict:
    """해설을 만들어 explanations 에 저장(이미 있으면 그대로 돌려줌).
    allow_gpt=False 면 템플릿만(복구한 지난 시각). conf shadow=true 면 GPT 결과를 검사해 기록만 하고 화면·디스코드는 템플릿을 쓴다."""
    row = conn.execute("SELECT body_json, source, model FROM explanations WHERE t_close=? AND rules_version=?",
                       (t_close, version)).fetchone()
    if row:
        return {"body": json.loads(row[0]), "source": row[1], "model": row[2]}
    conf = db.load_json("explain.json")
    v2 = str(conf.get("prompt_version", "")).startswith("explain_v2")
    snap = snapshot_v2(conn, t_close, version) if v2 else snapshot(conn, t_close, version)
    db.load_env()
    source, model, note, shadow = "template", None, None, None
    body = template(snap)
    shadow_mode = bool(conf.get("shadow"))
    via_codex = conf.get("provider", "openai_api") == "codex_cli"
    gpt_model = conf["codex_model"] if via_codex else conf["model"]
    if not allow_gpt:
        note = "지난 시각 복구: 템플릿만"
    elif not conf.get("short_gpt", True):
        note = "짧은 해설 GPT 끔(10-12: AI 분석은 ai_analysis 가 하루 2번)"
    elif conf.get("enabled") and (via_codex or os.environ.get("OPENAI_API_KEY")):
        try:
            cand = call_codex(conf, snap) if via_codex else call_gpt(conf, snap)
            reason = validate(cand, snap, conf)
            if shadow_mode:
                shadow = json.dumps(cand, ensure_ascii=False)
                note = f"리허설({gpt_model}): 검사 {'통과' if reason is None else '실패 · ' + reason}"
            elif reason is None:
                body, source, model = cand, "gpt", gpt_model
            else:
                note = f"GPT 결과 사용 안 함: {reason}"
        except Exception as exc:  # noqa: BLE001
            note = f"GPT 호출 실패({gpt_model}): {type(exc).__name__} {str(exc)[:200]}"
    elif conf.get("enabled"):
        note = "OPENAI_API_KEY 없음"
    conn.execute(
        "INSERT OR IGNORE INTO explanations (t_close, rules_version, source, model, prompt_version, body_json, "
        "input_json, note, shadow_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (t_close, version, source, model, conf.get("prompt_version") if (source == "gpt" or shadow) else None,
         json.dumps(body, ensure_ascii=False), json.dumps(snap, ensure_ascii=False), note, shadow, db.now_ms()))
    conn.commit()
    return {"body": body, "source": source, "model": model}
