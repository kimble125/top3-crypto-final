"""4시간 분석 사이클. 수집기(run_collect.sh)가 15분마다 부르지만, 새로 닫힌 4h 봉이 있을 때만 계산한다.

기획서 ver3 AI학습용 §1-1.
- conf/engine.json 의 cycle_enabled 가 false 면 아무것도 하지 않는다(--force 로 1회 실행 가능).
- 동시 실행 방지: 파일 잠금. 수동 실행과 예약 실행이 겹치면 뒤의 것은 바로 끝난다.
- 빠진 T 찾기: 이 규칙 버전의 첫 운영 T부터 최신 T까지 4시간 간격 중 저장되지 않은 T(최근 30일 안)를 모두 채운다.
  봉이 아직 안 들어왔으면 T 마감 후 60분까지 기다리고, 그 뒤에도 없으면 data_short 로 남긴다(4h 봉 자체가 없어도).
- 해설·디스코드는 '모든 종목의 행이 있는' 최신 T 에 대해서만 확정한다. 실패하면 다음 실행에서 다시 시도한다.
  그보다 앞선 T(복구한 시각) 중 해설이 없는 것은 템플릿 해설만 채운다(GPT·디스코드 없음).
- 늦게 만든 분석(분석 시각 T부터 1시간 넘게 지나 만든 것, track.ON_TIME_MS)은 채점은 하지만 운영 성적에서는 뺀다(track.summary on_time_only).
- live_start(첫 운영 분석 시각, 재현 경계)는 실행마다 확인해 비어 있으면 운영 행의 가장 이른 T 로 채운다.
- 실행마다(15분) 마지막에 지표 그래프 데이터(reports/charts/*.json)를 다시 쓴다(chart_export). 실패해도 사이클은 계속.
- 실행마다(15분) 15분 확실한 신호 상태를 다시 계산해 바뀐 봉을 기록·채점한다(strong15, 10-07). 새로 켜지거나 방향이 바뀌면
  conf/discord.json alerts.strong15 가 true 일 때만 디스코드로 보낸다. 실패해도 4시간 사이클은 계속.

사용: python3 run_cycle.py [--force]
"""
from __future__ import annotations

import fcntl
import sys
import traceback

import chart_export
import db
import ai_analysis
import ai_report
import explain
import notify
import pipeline
import strong15
import track
import trigger

FOUR_H = db.PERIOD_MS["4h"]
WAIT_MS = 60 * 60_000
LOOKBACK_MS = 30 * 86_400_000
LOCK = db.ENGINE / ".run_cycle.lock"


def _insert_missing_row(conn, sym, T, version, created):
    conn.execute("INSERT OR IGNORE INTO analyses (symbol, t_close, rules_version, mode, status, created_at) "
                 "VALUES (?,?,?,?,?,?)", (sym, T, version, "live", "data_short", created))


def fill_analyses(conn, rules, version, now) -> list[int]:
    """저장되지 않은 운영 T 를 채운다. 반환: 새로 저장한 T 목록."""
    created = db.now_ms()
    inserted = []
    for sym in rules["symbols"]:
        last4 = conn.execute("SELECT MAX(ts) FROM candles WHERE source='binance' AND symbol=? AND period='4h'",
                             (sym,)).fetchone()[0]
        expected_last = now // FOUR_H * FOUR_H          # 시계로 본 가장 최근 4h 마감
        t_last = max(last4 + FOUR_H if last4 else 0, 0)
        first = conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live' AND symbol=? AND rules_version=?",
                             (sym, version)).fetchone()[0]
        start = first if first is not None else (t_last or expected_last)
        start = max(start, expected_last - LOOKBACK_MS)
        have = {r[0] for r in conn.execute(
            "SELECT t_close FROM analyses WHERE mode='live' AND symbol=? AND rules_version=? AND t_close>=?",
            (sym, version, start))}
        missing = [T for T in range(start, expected_last + 1, FOUR_H) if T not in have]
        if not missing:
            continue
        frame = pipeline.compute(conn, sym, rules)
        for T in missing:
            waited = now - T >= WAIT_MS
            if T in frame.index:
                r = frame.loc[[T]]
                if r["status"].iloc[0] == "data_short" and not waited:
                    print(f"{sym} {db.kst_text(T)} 1h·15m 봉 대기")
                    continue
                cur = conn.executemany(pipeline.INSERT_SQL, pipeline.to_rows(r, sym, version, "live", created))
            elif waited:
                _insert_missing_row(conn, sym, T, version, created)  # 4h 봉 자체가 없음
                cur = None
                print(f"{sym} {db.kst_text(T)} 4시간봉 없음 → data_short")
            else:
                continue
            if cur is None or cur.rowcount:
                inserted.append(T)
                if cur is not None:
                    sc = r["score"].iloc[0]
                    print(f"{sym} {db.kst_text(T)} KST 분석: 점수 {'-' if sc != sc else int(sc)} "
                          f"상태 {r['status'].iloc[0]}")
        conn.commit()
    ensure_live_start(conn)
    return inserted


def ensure_live_start(conn) -> None:
    """첫 운영 분석 시각(재현 경계)이 비어 있으면 운영 행의 가장 이른 T 로 채운다. 중간에 끊겨도 다음 실행에서 복구된다."""
    if db.kv_get(conn, "live_start"):
        return
    first = conn.execute("SELECT MIN(t_close) FROM analyses WHERE mode='live'").fetchone()[0]
    if first is not None:
        db.kv_set(conn, "live_start", db.utc_iso(int(first)))


def complete_ts(conn, version, n_symbols, since_ms=None) -> list[int]:
    """모든 종목의 행이 있는 운영 T(오름차순)."""
    r = conn.execute("SELECT t_close FROM analyses WHERE mode='live' AND rules_version=? AND t_close>=? "
                     "GROUP BY t_close HAVING COUNT(DISTINCT symbol)=? ORDER BY t_close",
                     (version, since_ms or 0, n_symbols)).fetchall()
    return [x[0] for x in r]


def latest_complete_t(conn, version, n_symbols):
    ts = complete_ts(conn, version, n_symbols)
    return ts[-1] if ts else None


def backfill_explanations(conn, version, n_symbols, latest, now) -> int:
    """최신 T 앞의 완성된 T 중 해설이 없는 것(최근 30일)을 템플릿 해설로 채운다. 반환: 채운 수."""
    have = {x[0] for x in conn.execute("SELECT t_close FROM explanations WHERE rules_version=?", (version,))}
    todo = [t for t in complete_ts(conn, version, n_symbols, now - LOOKBACK_MS) if t < latest and t not in have]
    for t in todo:
        explain.explain(conn, t, version, allow_gpt=False)
    return len(todo)


def run(force: bool = False) -> int:
    eng = db.load_json("engine.json")
    if not eng.get("cycle_enabled") and not force:
        print("엔진 사이클 꺼짐(conf/engine.json cycle_enabled=false)")
        return 0
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("다른 사이클이 실행 중이라 이번 실행은 건너뜀")
        return 0
    try:
        rules = db.load_json("rules_v3.json")
        version = db.rules_version(rules)
        conn = db.connect()
        db.save_rules_snapshot(conn, version, rules)
        now = db.now_ms()
        inserted = fill_analyses(conn, rules, version, now)
        scored = track.score_pending(conn, "live")
        ensure_live_start(conn)
        try:   # 15분 확실한 신호(10-07): 상태 기록·채점. 새로 켜지거나 바뀐 것만 디스코드(설정이 켜져 있을 때)
            s15 = strong15.run(conn, rules, version, now)
            if s15["new"]:
                print("15분 확실한 신호: " + ", ".join(
                    f"{notify.SHORT.get(r['symbol'], r['symbol'])} {db.kst_text(r['t_close'], '%H:%M')} {r['kind']} "
                    f"{strong15.LABEL[r['dir']]}" for r in s15["new"]))
                al15 = notify.alerts15(conn, s15["new"], now=now)
                if al15:
                    print(f"15분 알림: {', '.join(al15)}")
            if s15["scored"]:
                print(f"15분 채점 {s15['scored']}건")
        except Exception as exc:  # noqa: BLE001 — 4시간 판정과 별개. 다음 실행에서 다시
            print(f"15분 확실한 신호 실패(다음 실행에서 재시도): {type(exc).__name__}: {exc}")
            traceback.print_exc()
        try:   # 정기 AI 분석(10-12, 정미님 6대 분류): 하루 2번(trigger.json ai_schedule_kst_hours). 트리거 게이트보다 먼저 돌려 같은 시각의 즉시 분석과 겹치지 않게(검토 아이디어 5)
            made = ai_analysis.run_scheduled(conn, rules["symbols"], now, trigger.load_conf().get("ai_schedule_kst_hours", [9, 21]))
            if made:
                print("AI 분석: " + ", ".join(f"{notify.SHORT.get(r['symbol'], r['symbol'])} "
                                              + (f"실패({r.get('code')}: {r['note'] or ''})" if r['source'] not in ai_analysis.OK_SOURCES
                                                 else r['body']['trend_direction'] + (f"(Claude 대체 {r['model']}, Codex {r['fallback_from']})"
                                                                                      if r['source'] == 'claude' else ""))
                                              for r in made))
        except Exception as exc:  # noqa: BLE001
            print(f"AI 분석 실패(다음 정기 시각에 다시): {type(exc).__name__}: {exc}")
        try:   # 트리거(10-12): 기술 조건 사건 → 12시간 금지 → 공식은 AI 추세 일치까지. 공식만 디스코드
            tg = trigger.run_live(conn, rules, version, now)
            for c in tg.get("checks", []):
                print(f"트리거 확인 {notify.SHORT.get(c['symbol'], c['symbol'])} {db.kst_text(c['t_bar'], '%H:%M')} "
                      f"{'Long' if c['dir'] > 0 else 'Short'} → {c['result']}")
            for r in tg.get("tech", []):
                print(f"기술 조건 트리거 {notify.SHORT.get(r['symbol'], r['symbol'])} {db.kst_text(r['t_bar'], '%H:%M')}")
            sent = notify.send_triggers(conn, version)
            if sent:
                print(f"공식 트리거 디스코드: {', '.join(sent)}")
        except Exception as exc:  # noqa: BLE001 — 다음 실행에서 다시
            print(f"트리거 실패(다음 실행에서 재시도): {type(exc).__name__}: {exc}")
            traceback.print_exc()
        T = latest_complete_t(conn, version, len(rules["symbols"]))
        if T is not None:
            try:
                n_old = backfill_explanations(conn, version, len(rules["symbols"]), T, now)
                if n_old:
                    print(f"지난 시각 해설 {n_old}건(템플릿)")
            except Exception as exc:  # noqa: BLE001
                print(f"지난 시각 해설 실패(다음 실행에서 재시도): {type(exc).__name__}")
            ex = None
            try:
                ex = explain.explain(conn, T, version)          # 이미 있으면 그대로 돌려줌
            except Exception as exc:  # noqa: BLE001 — 다음 실행에서 다시 시도
                print(f"해설 실패(다음 실행에서 재시도): {type(exc).__name__}")
            if ex is not None:
                st = notify.notify(conn, T, version, ex)     # 이미 보냈거나 저장했으면 skip, 실패는 재시도
                print(f"{db.kst_text(T)} 해설: {ex['source']} · 디스코드: {st}")
                try:   # 확신도 ±100·확실한 신호 알림(10-06 P5)
                    al = notify.alerts(conn, T, version, ex)
                    if al:
                        print(f"{db.kst_text(T)} 알림: {', '.join(al)}")
                except Exception as exc:  # noqa: BLE001
                    print(f"알림 실패: {type(exc).__name__}")
            try:   # AI 심층 리포트(10-06 P4). 이미 있으면(실패 기록 포함) 다시 부르지 않는다
                rep = ai_report.make(conn, T, version)
                print(f"{db.kst_text(T)} AI 리포트: {'있음' if rep else '없음'}")
            except Exception as exc:  # noqa: BLE001
                print(f"AI 리포트 실패: {type(exc).__name__}")
        try:   # 화면용 트리거·AI 분석 JSON(reports/trigger_board.json)
            trigger.export_board(conn, rules, version)
        except Exception as exc:  # noqa: BLE001
            print(f"트리거 화면 데이터 실패(다음 실행에서 재시도): {type(exc).__name__}: {exc}")
        try:
            chart_export.export_all(conn, rules, version)
        except Exception as exc:  # noqa: BLE001 — 그래프는 판정과 별개. 다음 실행에서 다시 씀
            print(f"그래프 데이터 실패(다음 실행에서 재시도): {type(exc).__name__}")
        db.kv_set(conn, "engine_last_run", now)
        print(f"채점 {scored}건 · 새 분석 {len(inserted)}건 · 규칙 {version}")
        conn.close()
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == "__main__":
    sys.exit(run(force="--force" in sys.argv))
