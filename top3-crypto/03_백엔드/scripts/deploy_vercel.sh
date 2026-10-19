#!/bin/bash
# 보드 스냅샷을 만들어 Vercel 에 올립니다(2026-10-03, 호연 결정 ㄷ).
# - 맥이 켜져 있는 동안 1시간마다 launchd 가 부릅니다: install_snapshot_deploy.command
# - 배포된 화면은 맥의 실시간 API(Funnel)를 먼저 쓰고, 맥이 꺼져 있으면 마지막 스냅샷을 보여 줍니다.
# - Vercel 로그인은 이 맥의 Vercel CLI 로그인을 씁니다(토큰을 명령줄에 넣지 않음: 프로세스 목록에 보일 수 있어서, 10-04 GPT-6.1 Sol).
# 사용: deploy_vercel.sh            → 실제 주소(https://top3-crypto.vercel.app)에 배포
#       deploy_vercel.sh --preview  → 미리보기 주소에 배포(Vercel 로그인한 사람만 열림. 단 프로젝트 첫 배포는 Vercel이 실제 주소로 올림)
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DIST="$REPO/05_프론트/dist"
PROJECT="top3-crypto"
VERCEL="vercel@62"
MODE="--prod"
[ "${1:-}" = "--preview" ] && MODE=""

stamp() { date "+%Y-%m-%d %H:%M:%S"; }
echo "[$(stamp)] 시작 ${MODE:-preview}"

PY="$REPO/03_백엔드/.venv/bin/python"
[ -x "$PY" ] || PY="/usr/bin/python3"
STATUS="$REPO/03_백엔드/logs/snapshot-deploy.status.json"   # 데이터 상태 탭이 읽음(/api/engine)
mkdir -p "$(dirname "$STATUS")"
record() {   # record ok|fail "메시지"  — 마지막 성공·실패 시각을 남긴다(값 안에 비밀값 없음)
  "$PY" - "$STATUS" "$1" "$2" <<'EOF'
import json, sys, time
path, kind, msg = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(open(path))
except Exception:
    d = {}
now = int(time.time() * 1000)
if kind == "ok":
    d.update(last_ok_ms=now, last_url=msg, last_error=None)
else:
    d.update(last_fail_ms=now, last_error=msg[:120])
json.dump(d, open(path, "w"), ensure_ascii=False)
EOF
}
trap 'record fail "중간에 멈춤(로그 확인)"' ERR

# 바뀐 것이 있을 때만 배포(10-06 호연 P3 "신호가 나올 때만 배포"). Vercel 무료 한도는 하루 100번.
# 기준: 새 분석 시각·확실한 신호·15분 확실한 신호(10-07)·공식 트리거·AI 분석·Core Condition(10-12)·확신도(10-13)가 바뀌었거나, 화면 파일(app·시안)이 바뀌었거나, 마지막 배포가 3시간 넘었을 때.
# 손으로 강제로 올리려면 FORCE=1 deploy_vercel.sh
SIG_FILE="$REPO/03_백엔드/logs/snapshot-deploy.sig"
SIG="$("$PY" - "$REPO" <<'EOF'
import hashlib, json, sys, urllib.request
from pathlib import Path
repo = Path(sys.argv[1])
b = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/board", timeout=30))
h = hashlib.sha256(json.dumps([b.get("t_close"), b.get("rules", {}).get("version"),
                               [(s["symbol"], s.get("strong"), s.get("strong_dir"),
                                 # 15분 확실한 신호(10-07)가 바뀌어도 배포. now15 가 없는 옛 응답에서는 None
                                 (s.get("now15") or {}).get("dir"), (s.get("now15") or {}).get("t_close"))
                                for s in b.get("symbols", [])],
                               # 10-12: 공식 트리거(시각·결과)·AI 분석 시각·Core Condition 상태가 바뀌어도 배포(검토: AI 글이 최대 3시간 늦던 것)
                               [(r.get("symbol"), r.get("t_bar"), r.get("result")) for r in ((b.get("v4") or {}).get("recent") or {}).get("official", [])[:5]],
                               sorted(((k, ((x or {}).get("latest") or {}).get("created_at")) for k, x in ((b.get("v4") or {}).get("ai") or {}).items())),
                               sorted(((k, (x or {}).get("state")) for k, x in ((b.get("v4") or {}).get("core") or {}).items() if not k.startswith("_"))),
                               # 10-13 V4: 확신도(KPI) 점수가 바뀌어도 배포(launchd가 1시간마다 부르므로 많아야 하루 24번)
                               sorted(((k, (x or {}).get("score")) for k, x in ((b.get("v4") or {}).get("confidence") or {}).items() if not k.startswith("_")))]).encode())
for d in (repo / "05_프론트" / "app", repo / "05_프론트" / "시안" / "2026-10-06"):
    for f in sorted(d.rglob("*")):
        if f.is_file():
            h.update(f.name.encode()); h.update(f.read_bytes())
print(h.hexdigest()[:16])
EOF
)"
LAST_OK_AGE=$("$PY" -c "import json,time,sys
try: d=json.load(open(sys.argv[1])); print(int(time.time()-d.get('last_ok_ms',0)/1000))
except Exception: print(999999)" "$STATUS")
if [ -z "${FORCE:-}" ] && [ -n "$MODE" ] && [ "$SIG" = "$(cat "$SIG_FILE" 2>/dev/null)" ] && [ "$LAST_OK_AGE" -lt 10800 ]; then
  echo "[$(stamp)] 바뀐 것 없음, 배포 건너뜀(마지막 배포 $(( LAST_OK_AGE / 60 ))분 전)"
  exit 0
fi
"$PY" "$HERE/export_snapshot.py"

cd "$DIST"
if [ ! -f .vercel/project.json ]; then            # 처음 한 번: 프로젝트 만들고(이미 있으면 넘어감) 이 폴더에 연결
  npx --yes "$VERCEL" project add "$PROJECT" || true
  npx --yes "$VERCEL" link --yes --project "$PROJECT"
fi
# 로그인 토큰이 만료돼 있으면 CLI 가 갱신하면서 같은 실행의 배포가 "Not authorized"로 실패한 적이 있음(10-04 00:07,
# 토큰은 약 8시간마다 갱신[추정]). 그래서 먼저 whoami 로 갱신시키고, 배포가 실패하면 20초 뒤 한 번 더 한다.
npx --yes "$VERCEL" whoami >/dev/null 2>&1 || true
deploy() { npx --yes "$VERCEL" deploy $MODE --yes; }
if ! OUT="$(deploy)"; then
  echo "[$(stamp)] 배포 실패, 20초 뒤 한 번 더"
  sleep 20
  OUT="$(deploy)"
fi
# 출력 형식이 실행 환경마다 달라(터미널은 주소 한 줄, AI 도구 안에서는 JSON) 주소만 골라 낸다
URL="$(printf '%s\n' "$OUT" | grep -oE 'https://[A-Za-z0-9.-]+\.vercel\.app' | tail -1 || true)"
trap - ERR
record ok "$URL"
[ -n "$MODE" ] && echo "$SIG" > "$SIG_FILE"
echo "[$(stamp)] 배포 완료 $URL"
