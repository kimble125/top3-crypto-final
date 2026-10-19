// 15분 확실한 신호 카드 글자(10-07). 실행: node 05_프론트/tests/now15.test.js
const assert = require("assert");
const N = require("../app/now15.js");

// 옛 저장본(now15 없음) → 줄을 그리지 않음
assert.strictEqual(N.line(null), null);
assert.strictEqual(N.line(undefined), null);
// 표는 있지만 기록 없음 → "없음", 시각 없음
assert.deepStrictEqual(N.line({ dir: 0, since_hm: null, since_today: null }), { label: "없음", cls: "zero", since: "", dir: 0 });
// 오늘 켜짐 → HH:MM부터
assert.deepStrictEqual(N.line({ dir: 1, since_hm: "10:30", since_kst: "10-07 10:30", since_today: true }),
  { label: "롱 확실", cls: "up", since: "10:30부터", dir: 1 });
// 어제 바뀜 → 날짜까지
assert.deepStrictEqual(N.line({ dir: -1, since_hm: "22:45", since_kst: "10-06 22:45", since_today: false }),
  { label: "숏 확실", cls: "down", since: "10-06 22:45부터", dir: -1 });
// 꺼짐도 바뀐 시각을 보여 준다
assert.strictEqual(N.line({ dir: 0, since_hm: "09:00", since_today: true }).since, "09:00부터");
// 알림 키는 종목·시각·방향으로 구분
assert.notStrictEqual(N.key("BTCUSDT", { t_close: "a", dir: 1 }), N.key("BTCUSDT", { t_close: "a", dir: -1 }));
assert.strictEqual(N.key("BTCUSDT", { t_close: "a", dir: 1 }), "BTCUSDT|15|a|1");
// 라벨 표는 백엔드 LABEL15 와 같다
assert.deepStrictEqual(N.LABEL, { "1": "롱 확실", "-1": "숏 확실", "0": "없음" });
console.log("now15.test.js: 모두 통과");
