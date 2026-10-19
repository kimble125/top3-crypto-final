// 15분 확실한 신호(10-07) 화면 글자. 브라우저(window.Top3Now15)와 node 시험(module.exports) 양쪽에서 쓴다.
// 보드 API 의 symbols[].now15 = {dir, label, kind, t_close, since_kst, since_hm, since_today} (없으면 null = 옛 저장본·표 없음).
(function (root) {
  "use strict";
  const LABEL = { "1": "롱 확실", "-1": "숏 확실", "0": "없음" };   // 03_백엔드/app/board.py LABEL15 와 같음
  const cls = (d) => (d > 0 ? "up" : d < 0 ? "down" : "zero");
  // 카드 한 줄: "지금(15분 기준): 롱 확실 · 10:30부터". 바뀐 시각이 오늘이 아니면 날짜까지(10-06 22:45부터).
  function line(n) {
    if (!n) return null;
    const d = Number(n.dir || 0);
    const label = LABEL[String(d)] || LABEL["0"];
    // kind=init 은 첫 기록(또는 규칙 버전 변경) 때 구간 첫 봉에서 '이미 켜져 있던' 상태라 켜진 시각을 모름 → "이전부터"
    if (n.kind === "init") return { label, cls: cls(d), since: d ? "이전부터" : "", dir: d };
    const since = n.since_today === false && n.since_kst ? n.since_kst : n.since_hm;
    return { label, cls: cls(d), since: since ? `${since}부터` : "", dir: d };
  }
  // 브라우저 알림 중복 방지 키: 종목·바뀐 시각·방향
  const key = (symbol, n) => `${symbol}|15|${n && n.t_close}|${n && n.dir}`;
  const api = { LABEL, line, key };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Top3Now15 = api;
})(typeof window !== "undefined" ? window : globalThis);
