"""Vercel 배포용 스냅샷 만들기 (2026-10-03, 호연 결정 ㄷ).

맥의 보드 서버(127.0.0.1:8765)에서 화면에 필요한 응답을 모두 받아 `05_프론트/dist/`에 정적 파일로 쓴다.
- dist/ = 화면 파일(index.html·app.js·chart.js·style.css) + config.js + data/(스냅샷) + data/meta.json(저장 시각) + vercel.json
- 배포된 화면은 같은 주소의 /api 를 쓰고, Vercel 이 그것을 맥의 Funnel 주소로 넘긴다(vercel.json rewrites). 브라우저가 Funnel 에
  직접 가지 않으므로 Tailscale 안 기기의 크롬 로컬 네트워크 차단도 없다(10-04 GPT-6.1 Sol 제안). 맥이 꺼져 있으면 data/ 를 쓴다(app.js getJSON).
- 비밀값은 넣지 않는다. 보드 API 가 내려주는 공개 정보만.
- 공개 범위(10-13 결정 84-A): 모든 요청에 X-Top3-Public: 1 을 붙여 공개 응답(scope=public)으로만 만든다.
  보드 서버가 공개 응답을 주지 않으면(옛 코드로 떠 있음 등) 저장본을 만들지 않고 멈춘다.

사용: python3 03_백엔드/scripts/export_snapshot.py   (배포까지는 deploy_vercel.sh)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "05_프론트" / "app"
PREVIEW = ROOT / "05_프론트" / "시안" / "2026-10-06"   # 지금 공유 중인 시안(바꾸면 /preview/ 내용이 바뀜)
# 10-13 공개 범위(84-A): 10-06 시안 b.html 말풍선에 옛 점수의 지표 조합·가중치가 적혀 있어 공개 배포에 싣지 않는다.
# V4가 시안을 대신한다. 다시 올리려면 True(조건 문장을 먼저 지울 것).
PUBLISH_PREVIEW = False
DIST = ROOT / "05_프론트" / "dist"
API = os.environ.get("TOP3_EXPORT_API", "http://127.0.0.1:8765")   # 다른 포트의 시험 서버로 만들어 볼 때만 바꿈
LIVE_API = os.environ.get("TOP3_LIVE_API", "https://<운영-맥>.<tailnet>.ts.net")   # 공개 저장소: 운영 주소는 환경 변수로
KST = dt.timezone(dt.timedelta(hours=9))
BOARD_API = ["/api/board", "/api/engine", "/api/replay", "/api/analyses", "/api/study", "/api/study/:name",
             "/api/chart/:symbol"]
PUBLIC_HEADERS = {"X-Top3-Public": "1"}   # 보드 API(app/public_scope.py)가 이 머리글을 보고 공개 응답만 준다
# 학습 차단 요청(기획안 v5 6절 4): AI 학습용 수집기에 수집하지 말라고 요청한다. 지키지 않는 수집기도 있어 보장은 아니다
AI_CRAWLERS = ("GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "CCBot", "PerplexityBot", "Bytespider", "Amazonbot",
               "Applebot-Extended")


# 보안 헤더(2026-10-20, 멘토 보안 코멘트 반영): 남의 사이트에 끼워 넣기(클릭재킹) 막기, 파일 형식 추측 막기, 쓰지 않는 기기 권한 끄기,
# AI 학습 거부 표시. 스크립트 출처 제한(CSP 전체)은 화면이 깨질 위험이 있어 frame-ancestors 만 둔다.
SECURITY_HEADERS = [
    {"key": "X-Content-Type-Options", "value": "nosniff"},
    {"key": "X-Frame-Options", "value": "DENY"},
    {"key": "Content-Security-Policy", "value": "frame-ancestors 'none'"},
    {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
    {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=(), payment=(), usb=()"},
    {"key": "X-Robots-Tag", "value": "noai, noimageai"},
]


def robots_txt() -> str:
    blocks = [f"User-agent: {ua}\nDisallow: /\n" for ua in AI_CRAWLERS] + ["User-agent: *\nAllow: /\n"]
    return "# Top 3 Crypto: AI 학습용 수집 차단 요청(robots.txt, 보장 아님)\n" + "\n".join(blocks)


class NotPublic(RuntimeError):
    """보드 API 가 공개 응답이 아닌 것(scope≠public)을 줌."""


def get(path: str):
    req = urllib.request.Request(API + path, headers=PUBLIC_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    # scope 를 싣는 응답(보드·데이터 상태·그래프·지난 분석·재현)은 공개 응답이어야 한다. /api/board 는 scope 가 꼭 있어야 함
    scope = data.get("scope") if isinstance(data, dict) else None
    if scope not in (None, "public") or (path.split("?")[0] == "/api/board" and scope != "public"):
        raise NotPublic(f"{path}: 공개 응답이 아닙니다(scope={scope!r}). 보드 서버를 새 코드로 다시 띄운 뒤 실행하세요.")
    return data


def write(rel: str, obj) -> None:
    p = DIST / "data" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    def gen(b: dict) -> tuple:   # 4시간 분석 시각 + V4(확신도·Core Condition·AI) 내보낸 시각(10-13 GPT 검토)
        return b.get("t_close"), (b.get("v4") or {}).get("generated_at")
    for _ in range(2):   # 내보내는 사이 엔진이 새 분석을 쓰면 시점이 섞이므로 한 번 더(10-04 GPT-6.1 Sol)
        t_before = gen(get("/api/board"))
        export()
        if gen(get("/api/board")) == t_before:
            break
        print("내보내는 사이 새 분석이 나와 다시 만듭니다")
    return 0


def export() -> None:
    board = get("/api/board")              # 서버가 살아 있는지 먼저 확인(죽어 있으면 여기서 실패)
    if DIST.exists():                       # .vercel(프로젝트 연결 정보)만 남기고 다시 만든다
        for p in DIST.iterdir():
            if p.name != ".vercel":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    DIST.mkdir(parents=True, exist_ok=True)
    for f in sorted(APP.iterdir()):    # 화면 파일 전부(10-07 now15.js, V5 view5.js 등). config.js 는 아래에서 덮어씀
        if f.is_file() and f.suffix in (".html", ".js", ".css"):
            shutil.copy2(f, DIST / f.name)
    if (APP / "img").is_dir():
        shutil.copytree(APP / "img", DIST / "img")
    # 화면 시안(10-06 호연 P3: 조원과 카톡으로 공유) → /preview/. 시안 파일의 ../../app/ 경로를 배포본 기준 ../ 로 바꾼다
    if PUBLISH_PREVIEW and PREVIEW.is_dir():
        (DIST / "preview").mkdir()
        for f in PREVIEW.iterdir():
            if f.suffix in (".html", ".css", ".js"):
                (DIST / "preview" / f.name).write_text(f.read_text(encoding="utf-8").replace("../../app/", "../"), encoding="utf-8")
    (DIST / "config.js").write_text(
        "// 배포본 설정(export_snapshot.py 가 씀). 실시간은 같은 주소의 /api(Vercel 이 Funnel 로 넘김), 안 되면 data/ 스냅샷\n"
        f"window.TOP3_CONFIG = {json.dumps({'liveApi': ''})};\n", encoding="utf-8")
    write("board.json", board)
    write("engine.json", get("/api/engine"))
    write("replay.json", get("/api/replay"))
    # 화면과 같은 조건(limit=120, 종목별·전체, 현재 규칙·전체 규칙)으로 따로 저장(10-04 GPT-6.1 Sol: 전체 200개를 거르면 종목별 120개가 안 됨)
    for sym in [""] + [s["symbol"] for s in board.get("symbols", [])]:
        for allv in (False, True):
            q = "limit=120" + (f"&symbol={sym}" if sym else "") + ("&all_versions=true" if allv else "")
            write(f"analyses{'_' + sym if sym else ''}{'_all' if allv else ''}.json", get("/api/analyses?" + q))
    for s in board.get("symbols", []):
        for d in (1, 3, 7):
            write(f"chart_{s['symbol']}_{d}.json", get(f"/api/chart/{s['symbol']}?days={d}"))
    study = get("/api/study")
    write("study.json", study)
    for doc in study.get("data", []):
        write(f"study/{doc['name']}.json", get("/api/study/" + urllib.parse.quote(doc["name"])))
    now = dt.datetime.now(KST)
    write("meta.json", {"saved_at": now.isoformat(timespec="seconds"), "saved_kst": now.strftime("%m-%d %H:%M"),
                        "board_t_close_kst": board.get("t_close_kst")})
    (DIST / ".vercelignore").write_text(".env*\n.gitignore\n", encoding="utf-8")  # Vercel CLI 가 만드는 토큰 파일은 올리지 않음
    (DIST / "robots.txt").write_text(robots_txt(), encoding="utf-8")
    (DIST / "vercel.json").write_text(json.dumps({
        # 화면이 쓰는 경로만 맥으로 넘긴다(10-04 Claude Fable: /api/* 전체를 넘기면 다른 API 도 공개 주소로 열림)
        "rewrites": [{"source": src, "destination": LIVE_API + src} for src in BOARD_API],
        "headers": [{"source": "/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}] + SECURITY_HEADERS}]
    }, indent=1), encoding="utf-8")
    n = sum(1 for _ in (DIST / "data").rglob("*.json"))
    print(f"스냅샷 {n}개 파일 → {DIST} (저장 {now:%m-%d %H:%M} KST)")


if __name__ == "__main__":
    sys.exit(main())
