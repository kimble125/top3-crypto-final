"""AI 심층 리포트(10-06 호연 P4): 4시간 분석마다 세 단락을 쓴다.

- technical(정량): 세 코인의 기술 지표 상태와 지켜볼 것.
- qualitative(정성): 최근 24시간 뉴스 제목에 보이는 이슈, 가격 모멘텀(24시간·7일), 공포탐욕지수 흐름.
- record(성적): 운영 기록과 과거 재현을 표본 수와 함께.
입력은 모두 코드가 계산한 사실이고, 글이 쓸 수 있는 숫자는 입력에 있는 숫자뿐이다(explain v2 와 같은 검사).
판정(Long/Short·확실한 신호)은 바꾸지 않고, 예측·권유·인과 단정(…때문에 올랐다)은 하지 않는다.
검사에 떨어지면 리포트를 보여 주지 않는다(화면은 "준비 중"). 호출은 Codex CLI(ChatGPT Plus, explain.json 설정).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import db
import explain

PROMPT = "prompts/ai_report_v1.md"
# 네이버 검색 API 약관(2026-09-07 시행 특약 2.3): 받은 데이터를 AI에 넣지 않는다(ai_analysis.AI_NEWS_EXCLUDE 와 같은 값)
NEWS_EXCLUDE = ("naver_news",)
PROMPT_VERSION = "ai_report_v1.0"
H4 = db.PERIOD_MS["4h"]
ON_TIME = db.PERIOD_MS["1h"]
LIMITS = {"technical": 380, "qualitative": 420, "record": 280}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["technical", "qualitative", "record"],
          "properties": {k: {"type": "string"} for k in LIMITS}}
CAUSAL = re.compile(r"때문에|덕분에|여파|영향으로|탓에|호재|악재")
# 입력 항목 이름(영어 키)이 문장에 그대로 나오면 거부. 한글이 붙어도 잡히게 영문자 경계만 본다("value는 73", 10-06 실제 사례)
KEY_WORDS = re.compile(r"(?<![A-Za-z_])(value|label|strong|to_strong|side|classification\w*|price_\w+|record_\w+|technical|qualitative|now_class|seven_days_ago)(?![A-Za-z_])", re.IGNORECASE)


def _record(conn, version: str) -> dict:
    """운영 성적(확실한 신호·방향). 분석 시각에서 1시간 안에 만든 분석만(보드와 같은 기준)."""
    def one(where, p):
        r = conn.execute(
            "SELECT SUM(a.strong=1 AND o.strong_hit IS NOT NULL), SUM(o.strong_hit=1), SUM(o.hit IS NOT NULL), SUM(o.hit=1), "
            "SUM(a.strong=1 AND o.base_hit IS NOT NULL), SUM(a.strong=1 AND o.base_hit=1) "
            "FROM analyses a LEFT JOIN outcomes o ON o.symbol=a.symbol AND o.t_close=a.t_close "
            "AND o.rules_version=a.rules_version AND o.mode=a.mode "
            f"WHERE a.mode='live' AND a.status='ok' AND a.created_at < a.t_close + {ON_TIME} {where}", p).fetchone()
        ss, sh, dc, dh, bs, bh = [x or 0 for x in r]
        return {"strong_scored": ss, "strong_hit": sh, "direction_scored": dc, "direction_hit": dh,
                "same_time_always_long_hit": bh, "same_time_always_long_scored": bs}
    since = conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live' AND rules_version=?", (version,)).fetchone()[0]
    first = conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live'").fetchone()[0]
    out = {"current_rules": dict(one("AND a.rules_version=?", (version,)), since_kst=db.kst_text(since)),
           "all_rules": dict(one("", ()), since_kst=db.kst_text(first), note="규칙이 바뀐 기록을 합친 것")}
    try:
        rep = json.loads((db.ENGINE / "reports" / "replay_summary.json").read_text(encoding="utf-8"))
        chk = rep.get("periods", {}).get("check") if rep.get("rules_version") == version else None
    except (OSError, ValueError):
        chk = None
    if chk:
        rows = chk["rows"]
        ss = sum(r["strong_scored"] for r in rows); sh = sum(r["strong_hit"] for r in rows)
        bs = sum(r.get("strong_base_scored") or 0 for r in rows); bh = sum(r.get("strong_base_hit") or 0 for r in rows)
        out["past_replay"] = {"period": f"{chk['from']}–{str(chk.get('to_exclusive_kst', ''))[:10]}",
                              "strong_scored": ss, "strong_hit_pct": round(100 * sh / ss, 1) if ss else None,
                              "same_time_always_long_pct": round(100 * bh / bs, 1) if bs else None,
                              "note": "같은 규칙을 과거에 적용한 재현(운영 기록 아님)"}
    return out


def _price(conn, sym: str, t_close: int) -> dict | None:
    rows = conn.execute("SELECT ts, close FROM candles WHERE source='binance' AND symbol=? AND period='4h' AND ts IN (?,?,?)",
                        (sym, t_close - H4, t_close - 7 * H4, t_close - 43 * H4)).fetchall()
    c = {ts: v for ts, v in rows}
    now, d1, d7 = c.get(t_close - H4), c.get(t_close - 7 * H4), c.get(t_close - 43 * H4)
    if not now:
        return None
    return {"change_24h_pct": round(100 * (now / d1 - 1), 2) if d1 else None,
            "change_7d_pct": round(100 * (now / d7 - 1), 2) if d7 else None}


def build_input(conn, t_close: int, version: str) -> dict:
    snap = explain.snapshot_v2(conn, t_close, version)
    coins = []
    for it in snap["items"]:
        if it.get("score") is None:
            coins.append({"symbol": it["symbol"], "name": it["name"], "label": it["label"]})
            continue
        coins.append({k: it.get(k) for k in ("symbol", "name", "score", "label", "strong", "macd_4h", "stoch_pair_1h",
                                             "vpci_15m", "to_strong", "note", "strong_since_kst") if it.get(k) is not None}
                     | {"momentum": _price(conn, it["symbol"], t_close)})
    fng = [(t, v) for t, v in conn.execute(
        "SELECT ts, value FROM series WHERE source='alternative.me' AND metric='fear_greed' AND ts<=? ORDER BY ts DESC LIMIT 8",
        (t_close,)).fetchall()]
    fear = {"now": int(fng[0][1]) if fng else None, "now_class": snap["fear_greed"].get("classification_ko"),
            "seven_days_ago": int(fng[-1][1]) if len(fng) >= 8 else None}
    news = [{"title": t, "publisher": p or "", "time_kst": db.kst_text(pa)} for t, p, pa in conn.execute(
        "SELECT title, publisher, published_at FROM news WHERE published_at BETWEEN ? AND ? "
        "AND COALESCE(source, '') NOT IN (%s) ORDER BY published_at DESC LIMIT 10" % ",".join("?" * len(NEWS_EXCLUDE)),
        (t_close - 86_400_000, t_close, *NEWS_EXCLUDE)).fetchall()]
    return {"t_close_kst": snap["t_close_kst"], "next_analysis_kst": snap.get("next_analysis_kst"), "coins": coins,
            "fear_greed": fear, "news_24h": news, "record": _record(conn, version)}


def validate(body: dict, inp: dict, conf: dict) -> str | None:
    allowed = explain._allowed_numbers(inp)
    forb = [explain._norm(w) for w in conf.get("forbidden", [])]
    for k, limit in LIMITS.items():
        t = body.get(k)
        if not isinstance(t, str) or not t.strip():
            return f"{k} 비어 있음"
        if len(t) > limit:
            return f"{k} 길이 위반"
        nt = explain._norm(t)
        for w in forb:
            if w and w in nt:
                return f"금지 표현: {w}"
        bad = explain._check_numbers(t, allowed)
        if bad:
            return f"{k}: {bad}"
        bare = explain.KOREAN_NUM_SAFE.sub("", t)
        # 정성 단락은 뉴스 제목을 옮기므로("1.50달러선", "1만개") 단위·한글 숫자 검사는 하지 않는다(숫자는 위에서 입력과 대조)
        if k != "qualitative" and (explain.KOREAN_NUMERAL.search(bare) or explain.KOREAN_NUM_WORD.search(bare) or explain.UNIT_WORDS.search(t)):
            return f"{k}: 한글 숫자·단위 말"
        if CAUSAL.search(t):
            return f"{k}: 인과 단정 표현"
        if KEY_WORDS.search(t):
            return f"{k}: 입력 항목 이름이 그대로 나옴"
    return None


def call_codex(conf: dict, inp: dict) -> dict:
    prompt = (db.ENGINE / PROMPT).read_text(encoding="utf-8")
    msg = (prompt + "\n\n## 입력(JSON)\n" + json.dumps(inp, ensure_ascii=False)
           + "\n\n파일을 읽거나 명령을 실행하지 말고, 위 입력만으로 스키마에 맞는 JSON 하나만 답하라.")
    with tempfile.TemporaryDirectory() as d:
        schema, out = Path(d) / "schema.json", Path(d) / "out.json"
        schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
        cmd = [conf.get("codex_bin", "codex"), "exec", "--ignore-user-config", "-m", conf["codex_model"],
               "-c", f"model_reasoning_effort={conf.get('codex_effort', 'medium')}",
               "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", d,
               "--output-schema", str(schema), "-o", str(out), "-"]
        r = subprocess.run(cmd, input=msg, text=True, capture_output=True, timeout=conf.get("codex_timeout_sec", 240),
                           env=explain._codex_env())
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"codex 종료 코드 {r.returncode}: {explain._tail(r.stderr)}")
        return json.loads(out.read_text(encoding="utf-8"))


def make(conn, t_close: int, version: str, tries: int = 2) -> dict | None:
    """리포트를 만들어 ai_reports 에 저장(이미 있으면 그대로). 검사 실패면 한 번 더 시도하고, 그래도 실패면 note 만 남긴다."""
    row = conn.execute("SELECT source, body_json FROM ai_reports WHERE t_close=? AND rules_version=?", (t_close, version)).fetchone()
    if row:
        return json.loads(row[1]) if row[1] else None
    conf = db.load_json("explain.json")
    if not conf.get("enabled") or conf.get("provider") != "codex_cli" or conf.get("deep_report", True) is False:
        return None   # 10-12: 정미님 6대 분류 AI 분석(ai_analysis)으로 바뀜
    inp = build_input(conn, t_close, version)
    body, note = None, None
    for _ in range(tries):
        try:
            cand = call_codex(conf, inp)
            why = validate(cand, inp, conf)
        except Exception as exc:  # noqa: BLE001
            cand, why = None, f"호출 실패 {type(exc).__name__} {str(exc)[:150]}"
        if why is None:
            body, note = cand, None
            break
        note = why
    conn.execute("INSERT OR IGNORE INTO ai_reports (t_close, rules_version, source, model, prompt_version, body_json, "
                 "input_json, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (t_close, version, "gpt" if body else "none", conf["codex_model"], PROMPT_VERSION,
                  json.dumps(body, ensure_ascii=False) if body else None, json.dumps(inp, ensure_ascii=False), note,
                  db.now_ms()))
    conn.commit()
    return body


if __name__ == "__main__":   # 손으로: python3 ai_report.py  → 최신 분석의 리포트(없으면 만듦)
    c = db.connect()
    t, v = c.execute("SELECT t_close, rules_version FROM analyses WHERE mode='live' ORDER BY t_close DESC, created_at DESC LIMIT 1").fetchone()
    print(json.dumps(make(c, t, v), ensure_ascii=False, indent=1))
    print(c.execute("SELECT note FROM ai_reports WHERE t_close=? AND rules_version=?", (t, v)).fetchone())
