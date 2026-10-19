# 글꼴 (데모·소개서)

- `AlfredoSans-subset.woff`: Pretendard 1.3.9 가변 글꼴에서 데모·소개서에 쓰는 글자만 남기고 이름을 바꾼 것. `python3 -I mvp/build_demo.py`가 다시 만든다.
- 이름을 바꾼 까닭: Pretendard는 SIL Open Font License 1.1이고 'Pretendard'가 예약 글꼴 이름(Reserved Font Name)이다. 글자를 잘라 낸 것은 수정본이라 같은 이름을 쓰지 않는다. 저작권·라이선스 이름 칸(nameID 0·13·14)은 그대로 둔다.
- 라이선스 원문: `OFL_Pretendard.txt`
- 원본(git 제외): `src/PretendardVariable.ttf` (가변 TTF 6.7MB. woff2 원본은 읽는 데 brotli 모듈이 필요해 TTF를 쓴다. 결과도 zlib인 woff)
  - 받는 곳: https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/variable/PretendardVariable.ttf
  - SHA-256 `3090ccde0442bb347aa7685d9ba8b17436a60682df6e8f92a9a670de14056e22` (2026-10-13 받음)
  - 원본이 없으면 빌드는 저장소의 부분 글꼴을 그대로 쓴다. 새 글자가 생겨 모자라면 빌드가 멈추고 원본을 받으라고 알린다.
- 화면은 데이터 주소(base64)로 글꼴을 넣는다. 바깥에서 글꼴을 받지 않는다(바깥 호출 0건).
