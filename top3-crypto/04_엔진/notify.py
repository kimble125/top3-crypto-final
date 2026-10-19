"""디스코드 전달. 기획서 ver3 AI학습용 §1-12.

- conf/discord.json mode: dry_run(기본, discord_log 에 저장만) / send(웹훅 전송).
- 같은 (T, 규칙 버전)은 한 번만: 전송 전에 discord_log 에 'sending' 행을 먼저 넣어 자리를 잡는다(원자적).
  실패(failed)는 최대 3번까지 다음 실행에서 다시 시도한다. 외부 요청 중에는 DB 쓰기 트랜잭션을 잡고 있지 않는다.
- 직전 분석 대비 확실한 신호가 새로 생기거나 방향이 바뀐 종목이 있으면 첫 줄에 강조.
- 규칙·로직 버전이 바뀌어 같은 시각을 다시 계산한 경우 머리말에 "규칙 변경으로 다시 계산"을 붙이고 ★ 줄은 뺀다
  (직전 분석이 다른 버전이라 '새로'가 성립하지 않음). 확정 규칙(final)의 첫 메시지는 "확정 규칙 첫 분석"을 붙인다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

import db
import pipeline
from replay import CHASE_WARN_PCT   # 추격 주의 기준(보드와 같음)

SHORT = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "XRPUSDT": "XRP"}
ARROW = {1: "▲", -1: "▼", 0: "·"}
FOUR_H = db.PERIOD_MS["4h"]
MAX_ATTEMPTS = 3
STUCK_MS = 30 * 60_000


def signed(n: int) -> str:
    """화면과 같은 표기: +71, −14, 0."""
    return f"+{n}" if n > 0 else (f"−{abs(n)}" if n < 0 else "0")


def strong_changes(conn, t_close: int, version: str) -> tuple[list[str], bool]:
    """(새로 생기거나 바뀐 확실한 신호 목록, 직전 분석이 있었는지)."""
    q = ("SELECT symbol, strong, strong_dir FROM analyses WHERE mode='live' AND t_close=? AND rules_version=? "
         "AND status='ok'")
    cur = {s: (st, sd) for s, st, sd in conn.execute(q, (t_close, version))}
    prev = {s: (st, sd) for s, st, sd in conn.execute(q, (t_close - FOUR_H, version))}
    out = [f"{SHORT.get(s, s)} {'Long' if sd > 0 else 'Short'}"
           for s, (st, sd) in sorted(cur.items()) if st and prev.get(s) != (st, sd)]
    return out, bool(prev)


def chase_note(move: float | None) -> str:
    """확실한 신호 줄 끝에 붙이는 '추격 주의' 문구(10-04 E2). move = 직전 24시간 신호 방향 움직임(%)."""
    if move is None or move != move:
        return ""
    note = f" · 켜지기 전 24시간 {move:+.1f}%"
    return note + (" · 추격 주의" if move >= _warn_pct() else "")


def _warn_pct() -> float:
    """보드와 같은 기준: 재현 요약(replay_summary.json chase.warn_pct)이 있으면 그 값, 없으면 replay 상수."""
    try:
        return float(json.loads((db.ENGINE / "reports" / "replay_summary.json").read_text(encoding="utf-8"))["chase"]["warn_pct"])
    except (OSError, ValueError, KeyError, TypeError):
        return CHASE_WARN_PCT


def _move_24h(conn, sym: str, t_close: int, close: float | None, sdir: int) -> float | None:
    """T 종가와 24시간 전(4시간봉 6개 전) 종가로 신호 방향 움직임(%). 보드(board.py chg_24h_pct)와 같은 봉."""
    r = conn.execute("SELECT close FROM candles WHERE source='binance' AND symbol=? AND period='4h' AND ts=?",
                     (sym, t_close - 7 * FOUR_H)).fetchone()
    if not r or not r[0] or not close:
        return None
    return 100 * (close / r[0] - 1) * sdir


BOARD_URL = "https://top3-crypto.vercel.app"


def _ai_line(text: str | None) -> str | None:
    """AI 해설에서 '지켜볼 것' 한 문장(…바뀌면 / …아닙니다 / 켜져 있으며)만 골라 한 줄로. 없으면 None."""
    if not text:
        return None
    sents = [x.strip() for x in text.replace("\n", " ").split(". ") if x.strip()]
    for s_ in sents[1:]:
        if any(k in s_ for k in ("바뀌면", "다시 돌", "켜져", "켜지기 전")):
            return s_.rstrip(".") + "."
    return None


def build_message(conn, t_close: int, version: str, explanation: dict | None) -> str:
    """디스코드 메시지(10-06 P4 고침: 휴대폰에서 읽기 쉽게, 지표는 세 단계, AI가 쓴 '지켜볼 것' 한 줄, 보드 주소)."""
    snap = conn.execute("SELECT rules_json FROM rules_versions WHERE rules_version=?", (version,)).fetchone()
    rules = json.loads(snap[0]) if snap else db.load_json("rules_v3.json")
    head = f"**Top 3 · {db.kst_text(t_close)} 분석**"
    done = "status IN ('sent','dry_run')"
    redo = conn.execute(f"SELECT 1 FROM discord_log WHERE t_close=? AND rules_version<>? AND {done} LIMIT 1",
                        (t_close, version)).fetchone() is not None
    first_final = rules.get("status") == "final" and conn.execute(
        f"SELECT 1 FROM discord_log WHERE rules_version=? AND {done} LIMIT 1", (version,)).fetchone() is None
    if first_final:
        head += " · 확정 규칙 첫 분석"
    if redo:
        head += " · 규칙 변경으로 다시 계산"
    lines = [head]
    ch, had_prev = strong_changes(conn, t_close, version)
    if ch and not redo:
        lines.append(("★ 새 확실한 신호: " if had_prev else "★ 확실한 신호: ") + ", ".join(ch))
    ai = {it["symbol"]: it["text"] for it in ((explanation or {}).get("body") or {}).get("items", [])} \
        if (explanation or {}).get("source") == "gpt" else {}
    for sym, score, st, sd, md, pd_, vd, status, close in conn.execute(
            "SELECT symbol, score, strong, strong_dir, macd_dir, pair_dir, vpci_dir, status, close "
            "FROM analyses WHERE mode='live' AND t_close=? AND rules_version=? ORDER BY symbol", (t_close, version)):
        name = SHORT.get(sym, sym)
        if status != "ok" or score is None:
            lines.append(f"{name}  데이터 부족")
            continue
        lab = pipeline.label(score, st, sd, md, pd_, vd, rules.get("weights"))
        lines.append(f"{'🟢' if st and sd > 0 else '🔴' if st and sd < 0 else '·'} **{name}**  {signed(score)}  {lab}   "
                     f"4시간{ARROW[md]} 1시간{ARROW[pd_]} 15분{ARROW[vd]}"
                     + (chase_note(_move_24h(conn, sym, t_close, close, sd)) if st else ""))
        al = _ai_line(ai.get(sym))
        if al:
            lines.append(f"　└ {al}")
    f = conn.execute("SELECT value FROM series WHERE source='alternative.me' AND metric='fear_greed' AND ts<=? "
                     "ORDER BY ts DESC LIMIT 1", (t_close,)).fetchone()
    tail = f"공포탐욕 {int(f[0])}" if f else ""
    lines.append(" · ".join(x for x in (tail, f"다음 분석 {db.kst_text(t_close + FOUR_H, '%H:%M')}") if x))
    lines.append(f"{BOARD_URL}  ·  정보 제공용이며 투자 권유가 아닙니다.")
    return "\n".join(lines)[:1990]


def _claim(conn, t_close: int, version: str, body: str) -> bool:
    """전송할 자리를 잡는다. 이미 보냈거나(sent·dry_run) 보내는 중이거나 재시도 한도를 넘으면 False."""
    now = db.now_ms()
    cur = conn.execute("INSERT OR IGNORE INTO discord_log (t_close, rules_version, status, body, note, created_at, "
                       "attempts) VALUES (?,?,'sending',?,NULL,?,1)", (t_close, version, body, now))
    if cur.rowcount == 0:
        # 실패한 것, 또는 'sending' 으로 30분 넘게 멈춘 것(전송 중 프로세스가 죽음)만 다시 잡는다
        cur = conn.execute("UPDATE discord_log SET status='sending', body=?, attempts=attempts+1, created_at=? "
                           "WHERE t_close=? AND rules_version=? AND attempts<? AND "
                           "(status='failed' OR (status='sending' AND created_at<?))",
                           (body, now, t_close, version, MAX_ATTEMPTS, now - STUCK_MS))
    conn.commit()
    return cur.rowcount == 1


def notify(conn, t_close: int, version: str, explanation: dict | None) -> str:
    conf = db.load_json("discord.json")
    if not conf.get("regular", True):   # 정기(4시간마다) 메시지를 끄고 알림만 받을 때
        return "regular_off"
    body = build_message(conn, t_close, version, explanation)
    if not _claim(conn, t_close, version, body):
        return "skip"
    status, note = "dry_run", None
    if conf.get("mode") == "send":
        db.load_env()
        url = os.environ.get("DISCORD_WEBHOOK_URL")
        status, note = ("failed", "DISCORD_WEBHOOK_URL 없음") if not url else _post(url, body, conf.get("timeout_sec", 15))
    final = note in ("HTTP 401", "HTTP 403", "HTTP 404")  # 웹훅 주소 문제: 반복 재시도하지 않음
    conn.execute("UPDATE discord_log SET status=?, note=?, attempts=CASE WHEN ? THEN ? ELSE attempts END "
                 "WHERE t_close=? AND rules_version=?", (status, note, final, MAX_ATTEMPTS, t_close, version))
    conn.commit()
    return status


def _post(url: str, body: str, timeout: int):
    data = json.dumps({"content": body}).encode("utf-8")
    for attempt in range(2):
        # User-Agent 가 없으면 디스코드(Cloudflare)가 403 error 1010 으로 막는다(10-06 첫 실제 전송에서 확인)
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json", "User-Agent": "Top3Crypto (https://top3-crypto.vercel.app, 1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                return "sent", None
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                try:
                    wait = float(json.loads(e.read().decode("utf-8")).get("retry_after", 2))
                except ValueError:
                    wait = 2.0
                time.sleep(min(wait, 30))
                continue
            return "failed", f"HTTP {e.code}"  # 404 등은 같은 실행에서 재시도하지 않는다(디스코드 안내)
        except Exception as exc:  # noqa: BLE001
            return "failed", type(exc).__name__
    return "failed", "429 반복"


# ---------- 확신도 ±100·확실한 신호 알림(10-06 호연 P5) ----------
M15 = db.PERIOD_MS["15m"]


def _prev_row(conn, sym: str, t_close: int, version: str):
    """직전 분석(T−4시간). 같은 규칙 버전이 없으면(규칙이 막 바뀜) 그 시각의 가장 최근 버전."""
    q = ("SELECT score, strong, strong_dir FROM analyses WHERE mode='live' AND symbol=? AND t_close=? AND status='ok' "
         "ORDER BY rules_version=? DESC, created_at DESC LIMIT 1")
    return conn.execute(q, (sym, t_close - FOUR_H, version)).fetchone()


def alert_candidates(conn, t_close: int, version: str) -> list[tuple[str, str]]:
    """(종목, 종류). 확신도가 새로 ±100이 됐거나(부호가 바뀐 경우 포함) 확실한 신호가 새로 켜지거나 방향이 바뀐 종목."""
    out = []
    for sym, score, st, sd in conn.execute(
            "SELECT symbol, score, strong, strong_dir FROM analyses WHERE mode='live' AND t_close=? AND rules_version=? "
            "AND status='ok' AND score IS NOT NULL ORDER BY symbol", (t_close, version)):
        prev = _prev_row(conn, sym, t_close, version)
        new_strong = bool(st) and (prev is None or (prev[1], prev[2]) != (1, sd))
        new_100 = abs(score) == 100 and (prev is None or prev[0] is None or prev[0] != score)
        if new_strong:
            out.append((sym, "strong"))
        elif new_100:
            out.append((sym, "score100"))
    return out


def _market(conn, sym: str) -> dict | None:
    rows = conn.execute("SELECT ts, high, low, close FROM candles WHERE source='binance' AND symbol=? AND period='15m' "
                        "ORDER BY ts DESC LIMIT 97", (sym,)).fetchall()
    if len(rows) < 97 or rows[0][0] - rows[96][0] != 86_400_000:
        return None
    win = rows[:96]
    return {"price": rows[0][3], "at": rows[0][0] + M15, "high": max(r[1] for r in win), "low": min(r[2] for r in win),
            "chg_pct": 100 * (rows[0][3] / rows[96][3] - 1)}


def _news_for(conn, sym: str, n: int = 3) -> list[tuple]:
    """최근 24시간 그 코인 뉴스(제목·출처·시각·주소). 없으면 코인 시장 전체 뉴스."""
    short = SHORT.get(sym, sym)
    since = db.now_ms() - 86_400_000
    rows = conn.execute("SELECT title, publisher, published_at, url FROM news WHERE published_at>=? AND (','||symbols||',') "
                        "LIKE ? ORDER BY published_at DESC LIMIT ?", (since, f"%,{short},%", n)).fetchall()
    if rows:
        return [("코인", *r) for r in rows]
    return [("시장", *r) for r in conn.execute(
        "SELECT title, publisher, published_at, url FROM news WHERE published_at>=? AND symbols='CRYPTO' "
        "ORDER BY published_at DESC LIMIT ?", (since, min(n, 2))).fetchall()]


def build_alert(conn, sym: str, kind: str, t_close: int, version: str, explanation: dict | None, news_n: int = 3) -> str:
    snap = conn.execute("SELECT rules_json FROM rules_versions WHERE rules_version=?", (version,)).fetchone()
    rules = json.loads(snap[0]) if snap else db.load_json("rules_v3.json")
    score, st, sd, md, pd_, vd, close = conn.execute(
        "SELECT score, strong, strong_dir, macd_dir, pair_dir, vpci_dir, close FROM analyses WHERE mode='live' AND symbol=? "
        "AND t_close=? AND rules_version=?", (sym, t_close, version)).fetchone()
    name = SHORT.get(sym, sym)
    side = "Long" if score > 0 else "Short"
    if st:
        head = f"{'🟢' if sd > 0 else '🔴'} **{name} 확실한 신호 {side}** · 확신도 {signed(score)}"
    else:
        why = ("15분 VPCI가 4시간·1시간이 맞춰지기 전에 돌아서 아직 확실한 신호 아님" if md == pd_ == vd != 0
               else "확실한 신호 아님")
        head = f"🔶 **{name} 확신도 {signed(score)}** · {why}"
    lines = [head, f"{db.kst_text(t_close)} 분석 · 4시간{ARROW[md]} 1시간{ARROW[pd_]} 15분{ARROW[vd]}"
             + (chase_note(_move_24h(conn, sym, t_close, close, sd)) if st else "")]
    mk = _market(conn, sym)
    if mk:
        dec = 4 if sym == "XRPUSDT" else 2
        lines.append(f"현재가 ${mk['price']:,.{dec}f} ({db.kst_text(mk['at'], '%H:%M')}) · 24시간 {mk['chg_pct']:+.2f}% · "
                     f"고가 {mk['high']:,.{dec}f} / 저가 {mk['low']:,.{dec}f}")
    if (explanation or {}).get("source") == "gpt":
        txt = {it["symbol"]: it["text"] for it in explanation["body"].get("items", [])}.get(sym)
        al = _ai_line(txt)
        if al and not ("맞춰지기 전" in al and "맞춰지기 전" in head):   # 머리줄과 같은 말이면 뺌
            lines.append(f"└ {al}")
    news = _news_for(conn, sym, news_n)
    if news:
        lines.append("관련 뉴스" if news[0][0] == "코인" else "코인 시장 뉴스(이 코인 뉴스 없음)")
        for _, title, pub, at, url in news:
            lines.append(f"• {title} — {pub or ''} · {db.kst_text(at, '%H:%M')} <{url}>")
    lines.append(f"<{BOARD_URL}> · 정보 제공용이며 투자 권유가 아닙니다.")
    return "\n".join(lines)[:1990]


def alerts(conn, t_close: int, version: str, explanation: dict | None) -> list[str]:
    """알림 대상마다 한 번씩(같은 T·종목은 한 번). 반환: '종목:상태' 목록."""
    conf = db.load_json("discord.json")
    acf = conf.get("alerts", {})
    if not acf.get("enabled", True):
        return []
    out = []
    for sym, kind in alert_candidates(conn, t_close, version):
        if kind == "score100" and not acf.get("score100", False):   # 10-06 P7: 확실한 신호일 때만
            continue
        body = build_alert(conn, sym, kind, t_close, version, explanation, acf.get("news_n", 3))
        status = _deliver(conn, conf, t_close, sym, version, kind, body)
        if status is not None:
            out.append(f"{SHORT.get(sym, sym)}:{status}")
    return out


def _deliver(conn, conf: dict, t_close: int, sym: str, version: str, kind: str, body: str) -> str | None:
    """discord_alerts 에 자리를 잡고(같은 (t_close, 종목, kind)은 한 번) 보낸다. 이미 있으면 None, 아니면 상태.
    10-07: kind 가 PK 에 들어가 4시간봉 마감 T 에 15분 알림(strong15)과 4시간 알림(strong)이 서로 자리를 뺏지 않는다."""
    cur = conn.execute("INSERT OR IGNORE INTO discord_alerts (t_close, symbol, rules_version, kind, status, body, created_at) "
                       "VALUES (?,?,?,?, 'sending', ?, ?)", (t_close, sym, version, kind, body, db.now_ms()))
    conn.commit()
    if cur.rowcount == 0:
        return None                        # 이미 보냈거나 보내는 중
    status, note = "dry_run", None
    if conf.get("mode") == "send":
        db.load_env()
        url = os.environ.get("DISCORD_WEBHOOK_URL")
        status, note = ("failed", "DISCORD_WEBHOOK_URL 없음") if not url else _post(url, body, conf.get("timeout_sec", 15))
    conn.execute("UPDATE discord_alerts SET status=?, note=? WHERE t_close=? AND symbol=? AND kind=?",
                 (status, note, t_close, sym, kind))
    conn.commit()
    return status


# ---------- 15분 확실한 신호 알림(10-07) ----------
LABEL15 = {1: "롱 확실", -1: "숏 확실", 0: "없음"}


def build_alert15(conn, row: dict, news_n: int = 3) -> str:
    """strong15 의 새 행(on·flip) 하나로 메시지. 4시간 알림과 같은 꼴이되 '지금(15분 기준)' 표시."""
    sym, d, t = row["symbol"], int(row["dir"]), int(row["t_close"])
    name = SHORT.get(sym, sym)
    side = "Long" if d > 0 else "Short"
    head = f"{'🟢' if d > 0 else '🔴'} **{name} 지금(15분 기준) 확실한 신호 {side}**"
    why = "방향 바뀜" if row.get("kind") == "flip" else "새로 켜짐"
    lines = [head, f"{db.kst_text(t)} 15분봉 마감 · {why} · 4시간 판정과 별개로 15분마다 다시 봄"]
    mk = _market(conn, sym)
    if mk:
        dec = 4 if sym == "XRPUSDT" else 2
        lines.append(f"현재가 ${mk['price']:,.{dec}f} ({db.kst_text(mk['at'], '%H:%M')}) · 24시간 {mk['chg_pct']:+.2f}% · "
                     f"고가 {mk['high']:,.{dec}f} / 저가 {mk['low']:,.{dec}f}")
    try:
        news = _news_for(conn, sym, news_n)
    except sqlite3.OperationalError:       # news 표가 없는 DB(시험용)에서도 알림 본문은 만든다
        news = []
    if news:
        lines.append("관련 뉴스" if news[0][0] == "코인" else "코인 시장 뉴스(이 코인 뉴스 없음)")
        for _, title, pub, at, url in news:
            lines.append(f"• {title} — {pub or ''} · {db.kst_text(at, '%H:%M')} <{url}>")
    lines.append(f"<{BOARD_URL}> · 정보 제공용이며 투자 권유가 아닙니다.")
    return "\n".join(lines)[:1990]


ALERT15_MAX_AGE_MS = 2 * db.PERIOD_MS["15m"]   # 이보다 오래된 봉의 바뀜은 보내지 않음(첫 실행·규칙 버전 바뀜 때 7일치 메워 넣는 행 → 알림 폭주 방지)


def alerts15(conn, new_rows: list[dict], conf: dict | None = None, now: int | None = None) -> list[str]:
    """15분 확실한 신호가 새로 켜지거나(on) 방향이 바뀐(flip) 행마다 한 번. conf/discord.json alerts.strong15 가 true 일 때만
    (기본 false). off·init 은 보내지 않고, 지금보다 ALERT15_MAX_AGE_MS(30분) 넘게 지난 봉(지난 기록 메워 넣기)도 보내지 않는다.
    반환: '종목:상태' 목록."""
    conf = conf if conf is not None else db.load_json("discord.json")
    acf = conf.get("alerts", {})
    if not acf.get("enabled", True) or not acf.get("strong15", False):
        return []
    now = now if now is not None else db.now_ms()
    out = []
    for row in new_rows:
        if row.get("kind") not in ("on", "flip") or now - int(row["t_close"]) > ALERT15_MAX_AGE_MS:
            continue
        body = build_alert15(conn, row, acf.get("news_n", 3))
        status = _deliver(conn, conf, int(row["t_close"]), row["symbol"], row["rules_version"], "strong15", body)
        if status is not None:
            out.append(f"{SHORT.get(row['symbol'], row['symbol'])}:{status}")
    return out


def _set_webhook_from_clipboard() -> str:
    """클립보드(pbpaste)의 웹훅 주소를 저장소 .env 의 DISCORD_WEBHOOK_URL 에 넣는다. 주소는 화면에 찍지 않는다."""
    import re
    import subprocess
    url = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+", url):
        return "클립보드에 디스코드 웹훅 주소가 없습니다(https://discord.com/api/webhooks/… 를 복사한 뒤 다시)."
    env = db.REPO / ".env"
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    lines = [x for x in lines if not x.startswith("DISCORD_WEBHOOK_URL=")] + [f"DISCORD_WEBHOOK_URL={url}"]
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env.chmod(0o600)
    return f"저장함: DISCORD_WEBHOOK_URL=…{url[-6:]} (.env, 다른 사람은 못 읽게 권한 600)"


if __name__ == "__main__":
    # 손으로: python3 notify.py --set-webhook | --preview | --test
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "--preview"
    if arg == "--set-webhook":
        print(_set_webhook_from_clipboard())
        raise SystemExit(0)
    c = db.connect(readonly=True)
    t, v = c.execute("SELECT t_close, rules_version FROM analyses WHERE mode='live' ORDER BY t_close DESC, created_at DESC LIMIT 1").fetchone()
    r = c.execute("SELECT source, body_json FROM explanations WHERE t_close=? AND rules_version=?", (t, v)).fetchone()
    ex = {"source": r[0], "body": json.loads(r[1])} if r else None
    msg = build_message(c, t, v, ex)
    if arg == "--preview":
        print(msg)
    elif arg == "--alert-test":   # 알림 형식 시험: 후보(없으면 첫 종목) 하나를 '[시험]'을 붙여 보낸다(기록 안 남김)
        cands = alert_candidates(c, t, v) or [("BTCUSDT", "score100")]
        db.load_env()
        print(_post(os.environ["DISCORD_WEBHOOK_URL"], "[시험] " + build_alert(c, cands[0][0], cands[0][1], t, v, ex), 15))
    elif arg == "--alert-preview":   # 이 분석에서 알림이 갈 종목과 내용(보내지 않음)
        for sym, kind in alert_candidates(c, t, v) or [(s_, "미리보기") for (s_,) in c.execute(
                "SELECT symbol FROM analyses WHERE mode='live' AND t_close=? AND rules_version=? LIMIT 1", (t, v))]:
            print(f"--- {sym} {kind}"); print(build_alert(c, sym, kind, t, v, ex))
    elif arg == "--test":   # 연결 시험: 지금 메시지를 '[시험]'을 붙여 한 번 보낸다(discord_log 에 남기지 않음)
        db.load_env()
        url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not url:
            print("DISCORD_WEBHOOK_URL 없음: 먼저 python3 notify.py --set-webhook")
        else:
            print(_post(url, "[시험] " + msg, 15))


# ---------- 트리거 알림(2026-10-12 리팩토링, 정미님 10-07: 디스코드는 결과만) ----------
RESEND_MS = 60 * 60_000


def fmt_price(p: float) -> str:
    """정미님 예시(Open U$ 83,885.9)처럼. 가격이 작은 코인은 소수 자리를 늘린다."""
    a = abs(p)
    return f"{p:,.1f}" if a >= 1000 else f"{p:,.2f}" if a >= 10 else f"{p:,.4f}"


SHORT_ACTION = "Long 보유 시 빠질 때(선물 1배면 Short 진입)"


def trigger_message(symbol: str, d: int, entry: float, issued_at: int) -> str:
    """정미님 10-07 예: '✅ 2026-10-01 13:11:13 매매 트리거 Long 발생 Open U$ 83,885.9.' — 세 코인이라 코인 이름을 붙인다.
    V5(기획안 v5 5절, 정미님 구상 "Short은 빠질 때"): Long 은 '진입', Short 은 'Long 보유 시 빠질 때(선물 1배면 Short 진입)'.
    채점은 Short 쪽 최대수익률로 하므로 현물만 쓰는 사람에게 Short 알림은 'Long 정리' 신호다(화면 설명 · 시연에서 나눠 말함)."""
    t = db.kst_text(issued_at, "%Y-%m-%d %H:%M:%S")
    act = "Long 진입" if d > 0 else f"Short · {SHORT_ACTION}"
    return f"✅ {t} {SHORT.get(symbol, symbol)} 매매 트리거 {act} · Open U$ {fmt_price(entry)}"


def send_triggers(conn, version: str, now: int | None = None, post=None) -> list[str]:
    """보내지 않은 공식 트리거(track=ai, live)를 보낸다. 실패는 1시간 안에서만 다음 실행에 다시 보낸다.
    반환: '심볼 상태' 목록. post(url, body, timeout) 는 시험용."""
    import trigger
    if not trigger.load_conf().get("discord", {}).get("send_official", True):
        return []
    conf = db.load_json("discord.json")
    now = now if now is not None else db.now_ms()
    rows = conn.execute("SELECT symbol, t_bar, dir, entry, issued_at FROM triggers WHERE mode='live' AND track='ai' "
                        "AND rules_version=? AND issued_at > ? AND (discord_status IS NULL OR discord_status='failed' "
                        "OR (discord_status='sending' AND discord_at < ?)) ORDER BY t_bar",
                        (version, now - RESEND_MS, now - STUCK_MS)).fetchall()
    out = []
    for sym, t_bar, d, entry, issued in rows:
        body = trigger_message(sym, int(d), float(entry), int(issued))
        cur = conn.execute("UPDATE triggers SET discord_status='sending', discord_body=?, discord_at=? WHERE symbol=? AND "
                           "track='ai' AND mode='live' AND rules_version=? AND t_bar=? AND (discord_status IS NULL OR "
                           "discord_status IN ('failed','sending'))", (body, now, sym, version, t_bar))
        conn.commit()
        if cur.rowcount != 1:
            continue
        status, note = "dry_run", None
        if conf.get("mode") == "send":
            db.load_env()
            url = os.environ.get("DISCORD_WEBHOOK_URL")
            if not url:
                status = "failed"
            else:
                status, note = (post or _post)(url, body, conf.get("timeout_sec", 15))
        conn.execute("UPDATE triggers SET discord_status=?, discord_at=? WHERE symbol=? AND track='ai' AND mode='live' "
                     "AND rules_version=? AND t_bar=?", (status, db.now_ms() if post is None else now, sym, version, t_bar))
        conn.commit()
        out.append(f"{SHORT.get(sym, sym)} {status}" + (f"({note})" if note else ""))
    return out
