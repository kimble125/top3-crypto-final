// V5 화면 계산(10-14): 확신도 conf_v2 · AI 분석 v5 · 공포탐욕 사건 · 7일 선의 글자·좌표를 만드는 순수 함수 모음.
// 브라우저(window.Top3View5)와 node 시험(module.exports) 양쪽에서 쓴다. DOM·esc 는 모른다: 돌려주는 글은 모두 날것이라 app.js 가 esc() 를 거친다.
// 어떤 칸이든 없거나 null 일 수 있다(옛 V4 자료 conf_v1, 옛 AI 분석, 공개 응답). 예외를 던지지 않고 빈 값을 돌려준다.
(function (root) {
  "use strict";
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const FACTORS = { price: "가격 위치", macd: "MACD", stoch: "Stochastic", stochrsi: "StochRSI", oi: "미결제약정", premium: "코인베이스 프리미엄", fng: "공포탐욕", news: "뉴스" };
  const FACTOR_ORDER = Object.keys(FACTORS);
  const dirWord = (d) => (d > 0 ? "Long" : d < 0 ? "Short" : "중립");
  const dirCls = (d) => (d > 0 ? "up" : d < 0 ? "down" : "zero");
  const sgn = (v) => (v > 0 ? "+" : v < 0 ? "−" : "");
  // 소수 한 자리 부호 글자: +86.5 · −11.5 · 0.0
  const fmt1 = (v) => (num(v) == null ? "–" : `${sgn(v)}${Math.abs(v).toFixed(1)}`);

  // 묶음 방향: 점수 ≥ 10 Long, ≤ −10 Short, 그 사이 중립(7절 2 D). 점수가 없으면 null
  function groupDir(score) {
    const s = num(score);
    return s == null ? null : s >= 10 ? 1 : s <= -10 ? -1 : 0;
  }

  // ---------- 확신도 ----------
  const isV2 = (c) => !!c && (c.version === "conf_v2" || "p_long" in c || "side_pct" in c);
  // 카드·근거·로고가 같이 쓰는 한 가지 모양. v2: 우세 쪽 % · v1(옛 자료): 부호 있는 점수 · 없으면 '–'
  function confView(c) {
    if (!c) return { v: 0, held: true, big: "–", unit: "", cls: "zero", dir: 0, label: "", side: "" };
    if (isV2(c)) {
      const p = num(c.p_long);
      const pct = num(c.side_pct) != null ? c.side_pct : p == null ? null : p >= 50 ? p : 100 - p;
      if (pct == null) return { v: 2, held: true, big: "–", unit: "", cls: "zero", dir: 0, label: c.label || "자료 부족", side: "" };
      const side = c.side === "Short" ? "Short" : c.side === "Long" ? "Long" : (p != null && p < 50 ? "Short" : "Long");
      const neutral = c.level === "neutral" || (c.level == null && pct <= 54);
      const dir = neutral ? 0 : side === "Short" ? -1 : 1;
      return { v: 2, held: false, big: String(Math.round(pct)), unit: "%", cls: dirCls(dir), dir, label: c.label || "", side };
    }
    const sc = num(c.score);
    if (sc == null) return { v: 1, held: true, big: "–", unit: "", cls: "zero", dir: 0, label: c.label || "", side: "" };
    const dir = Math.abs(sc) < 10 ? 0 : sc > 0 ? 1 : -1;
    return { v: 1, held: false, big: `${sgn(sc)}${Math.abs(sc)}`, unit: "", cls: dirCls(dir), dir, label: c.label || "", side: dir > 0 ? "Long" : dir < 0 ? "Short" : "" };
  }
  // 로고 '3'과 같은 색을 쓰는 방향(홈): 확신도 side, 중립·자료 없음은 0
  const confDir = (c) => confView(c).dir;
  // AI 분석 탭의 로고 방향: 그 코인 최신 분석의 trend_direction
  const aiDir = (body) => (body && body.trend_direction === "Long" ? 1 : body && body.trend_direction === "Short" ? -1 : 0);

  // 카드 아랫줄 회색 글: 묶음이 빠졌으면 note("시장 자료 부족: … → 기술 지표만"), 아니면 "기술 Long · 시장 자료 중립".
  // '뉴스 방향 없음'처럼 묶음이 남은 가벼운 note 는 근거 카드에만 둔다(10-14 Fable 검토 아이디어 C: '뉴스가 없어서 중립'으로 읽힘).
  // used 가 없는 옛 응답은 note 를 그대로 보인다
  function confSub(c) {
    if (!c) return { text: "", note: false };
    if (!isV2(c)) return { text: "", note: false };
    const g = c.groups || {};
    const hasUsed = ["tech", "market"].some((k) => g[k] && typeof g[k].used === "boolean");
    const dropped = ["tech", "market"].some((k) => g[k] && g[k].used === false);
    if (c.note && (dropped || !hasUsed)) return { text: String(c.note), note: true };
    const part = (name, grp) => {
      const d = grp ? groupDir(grp.score) : null;
      return d == null ? null : `${name} ${dirWord(d)}`;
    };
    const t = part("기술", g.tech), m = part("시장 자료", g.market);
    return { text: [t, m].filter(Boolean).join(" · "), note: false };
  }

  // ---------- AI 분석 ----------
  // 홈 AI 카드: AI 가 설명한 비중 상위 n 개(비중 큰 순, 같으면 항목 순서)
  function topFactors(fw, n) {
    if (!fw || typeof fw !== "object") return [];
    const rows = [];
    FACTOR_ORDER.forEach((k, i) => {
      const f = fw[k];
      const pct = f && num(f.weight_pct);
      if (pct != null) rows.push({ key: k, name: FACTORS[k], dir: f.direction > 0 ? 1 : f.direction < 0 ? -1 : 0, pct, i });
    });
    rows.sort((a, b) => b.pct - a.pct || a.i - b.i);
    return rows.slice(0, n == null ? 3 : n);
  }
  // 근거 줄 맨 끝 'AI 25%'
  const aiPct = (fw, key) => {
    const f = fw && fw[key];
    return f && num(f.weight_pct) != null ? f.weight_pct : null;
  };

  // 뉴스 방향 한 줄: 긍정 +1 · 부정 −1 · 중립 0 · 기사 n건. news_bias 가 없으면 null(옛 분석), 기사 없음(x=null)은 {none:true}
  function newsBias(body) {
    const nb = body && body.news_bias;
    if (!nb || typeof nb !== "object") return null;
    const n = num(nb.n) || 0;
    if (nb.x == null || n === 0) return { none: true, x: null, n, text: "관련 기사 없음", cls: "zero" };
    const x = nb.x > 0 ? 1 : nb.x < 0 ? -1 : 0;
    return { none: false, x, n, text: `${x > 0 ? "긍정 +1" : x < 0 ? "부정 −1" : "중립 0"}`, cls: dirCls(x) };
  }

  // 엇갈림(7절 4 C): 기술 묶음 방향과 AI 추세가 반대일 때만. 이유 = 기술 밖 4항목 중 AI 방향과 같은 방향, 비중 큰 순 최대 2개
  const REASON_WORD = {
    news: (d) => (d > 0 ? "긍정" : "부정"),
    fng: (d) => (d > 0 ? "개선" : "악화"),
    oi: (d) => (d > 0 ? "Long" : "Short"),
    premium: (d) => (d > 0 ? "Long" : "Short"),
  };
  function divergence(c, body) {
    if (!c || !body) return null;
    const tech = groupDir(c.groups && c.groups.tech && c.groups.tech.score);
    const ai = aiDir(body);
    if (!tech || !ai || tech === ai) return null;
    const fw = body.factor_weights || {};
    const reasons = ["oi", "premium", "fng", "news"].map((k, i) => ({ k, i, f: fw[k] }))
      .filter((r) => r.f && r.f.direction === ai && num(r.f.weight_pct) != null)
      .sort((a, b) => b.f.weight_pct - a.f.weight_pct || a.i - b.i).slice(0, 2)
      .map((r) => ({ key: r.k, name: FACTORS[r.k], word: REASON_WORD[r.k](ai), pct: r.f.weight_pct }));
    return { tech, ai, reasons };
  }
  // "엇갈림: 기술 지표 Short · AI Long — AI가 설명한 근거: 뉴스(긍정, 25%) · 공포탐욕(개선, 14%)"
  function divergenceText(dv) {
    if (!dv) return "";
    const head = `엇갈림: 기술 지표 ${dirWord(dv.tech)} · AI ${dirWord(dv.ai)}`;
    if (!dv.reasons.length) return head;
    return `${head} — AI가 설명한 근거: ${dv.reasons.map((r) => `${r.name}(${r.word}, ${r.pct}%)`).join(" · ")}`;
  }

  // AI 분석 3절: 기사별 표지와 제목 짝짓기(news_items 와 news_ref 는 id 로 잇는다). 옛 분석(키 없음)은 빈 배열
  const REL = { coin: "코인", market: "시장", none: "무관" };
  function newsRows(body) {
    const items = body && Array.isArray(body.news_items) ? body.news_items : [];
    const ref = {};
    (body && Array.isArray(body.news_ref) ? body.news_ref : []).forEach((r) => { if (r && r.id != null) ref[r.id] = r; });
    return items.filter((it) => it && typeof it === "object").map((it) => {
      const r = ref[it.id] || {};
      const dir = it.direction > 0 ? 1 : it.direction < 0 ? -1 : 0;
      const imp = Math.min(3, Math.max(1, Math.round(num(it.importance) || 1)));
      return { id: it.id, title: r.title || "", publisher: r.publisher || "", time: r.time || "", rel: REL[it.relevance] ? it.relevance : "none", relText: REL[it.relevance] || "무관",
        dir, dirText: dir > 0 ? "긍정" : dir < 0 ? "부정" : "중립", cls: dirCls(dir), imp };
    });
  }

  // ---------- ⚠ 상태 탭 ----------
  const REASON = { limit: "사용 한도", timeout: "시간 초과", invalid: "검사 실패", error: "오류" };
  const retryTxt = (lt) => (lt && lt.retry_at_kst ? `(${lt.retry_at_kst}${lt.retry_est ? "(추정)" : ""} 이후 다시 시도)` : "");
  // ai = board.v4.ai. 돌려주는 글은 날것(esc 는 app.js)
  function aiStatusLines(ai) {
    const out = [];
    Object.entries(ai || {}).forEach(([sym, node]) => {
      if (String(sym).startsWith("_") || !node || !node.last_try) return;
      const lt = node.last_try, short = String(sym).replace("USDT", "");
      if (lt.ok) {
        if (lt.fallback_from) out.push(`${short} AI 분석: ${REASON[lt.fallback_from] || "오류"}${retryTxt(lt)} · Claude로 대신 분석함`);
        return;
      }
      const prev = node.latest ? " · 이전 분석을 보여 줌" : "";
      if (lt.code) out.push(`${short} AI 분석: ${REASON[lt.code] || "오류"}${retryTxt(lt)}${prev}`);
      else out.push(`${short} AI 분석의 마지막 시도(${lt.created_kst || "-"})가 실패했습니다${prev}`);
    });
    return out;
  }
  // AI 분석 탭 머리 줄: 마지막 시도가 실패했을 때 짧은 이유
  function failWord(lt) {
    if (!lt || lt.ok) return "";
    return lt.code ? REASON[lt.code] || "오류" : "실패";
  }

  // ---------- 공포탐욕 사건 · 그래프 ----------
  const sdelta = (v) => (num(v) == null ? "" : `${sgn(v)}${Math.abs(v)}`);
  // fng.events 를 날짜순으로 번호 붙여 목록 글로. series 에 날짜가 있으면 idx(그래프 점 자리)
  function fngEvents(fng) {
    const series = (fng && fng.series) || [];
    const at = {};
    series.forEach((s, i) => { at[s.date] = i; });
    const evs = ((fng && fng.events) || []).filter((e) => e && e.date).slice().sort((a, b) => String(a.date).localeCompare(String(b.date))).slice(0, 8);
    return evs.map((e, k) => {
      const v = num(e.value), d = num(e.delta);
      const btc = num(e.btc_chg_pct);
      return { n: k + 1, date: e.date, md: String(e.date).slice(5), idx: e.date in at ? at[e.date] : null, value: v, delta: d,
        prev: v != null && d != null ? v - d : null, deltaText: sdelta(d), cls: dirCls(d || 0),
        // 지수 날짜 D의 값은 앞 UTC 하루(btc_date = D−1)의 시장을 반영하므로 비트코인 등락·뉴스는 btc_date 의 것: "10-12 BTC −2.3%"
        btcDate: e.btc_date ? String(e.btc_date).slice(5) : "",
        btc: btc == null ? "" : `${e.btc_date ? `${String(e.btc_date).slice(5)} ` : ""}BTC ${sgn(btc)}${Math.abs(btc)}%`, news: (e.news || []).filter((n) => n && n.title).slice(0, 2), note: e.news_note || "" };
    });
  }
  // 그래프 좌표: 최대 560×140, 50 점선, 7일마다 날짜(맨 오른쪽 = 가장 최근에서 거꾸로), 사건 점
  function fngLayout(fng, width) {
    const series = (fng && fng.series) || [];
    if (series.length < 2) return null;
    const W = Math.max(280, Math.min(560, Math.round(width || 560))), H = 140;
    const pl = 12, pr = 28, pt = 14, pb = 24;   // 오른쪽 여백: '50' 글자 자리
    const n = series.length;
    const x = (i) => pl + (i / (n - 1)) * (W - pl - pr);
    const y = (v) => pt + (1 - Math.min(100, Math.max(0, v)) / 100) * (H - pt - pb);
    const f1 = (v) => v.toFixed(1);
    const d = series.map((s, i) => `${i ? "L" : "M"}${f1(x(i))},${f1(y(num(s.value) == null ? 50 : s.value))}`).join("");
    const ticks = [];
    for (let i = n - 1; i >= 0; i -= 7) ticks.push({ i, x: x(i), label: String(series[i].date).slice(5) });
    ticks.reverse();
    const dots = fngEvents(fng).filter((e) => e.idx != null && e.value != null).map((e) => ({ n: e.n, x: x(e.idx), y: y(e.value) }));
    return { W, H, d, y50: y(50), yb: H - pb, gx1: pl, gx2: W - pr + 4, ticks, dots, last: { x: x(n - 1), y: y(num(series[n - 1].value) == null ? 50 : series[n - 1].value) } };
  }

  // ---------- 카드 7일 가격선 ----------
  // spark = [{t, close}] 4시간봉 종가. 끝점 좌표를 함께 돌려준다. 점이 2개 미만이면 null(자리만 둠)
  function sparkLayout(spark, W, H) {
    const pts = (Array.isArray(spark) ? spark : []).map((p) => num(p && p.close)).filter((v) => v != null);
    if (pts.length < 2) return null;
    W = W || 160; H = H || 64;
    const px = 4, py = 4;
    const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1;
    const xy = pts.map((v, i) => [px + (i / (pts.length - 1)) * (W - 2 * px), py + (1 - (v - lo) / span) * (H - 2 * py)]);
    return { W, H, d: xy.map(([a, b], i) => `${i ? "L" : "M"}${a.toFixed(1)},${b.toFixed(1)}`).join(""), ex: xy[xy.length - 1][0], ey: xy[xy.length - 1][1] };
  }

  // ---------- 검증 화면(맥에서 직접 연 화면) ----------
  // 성공 기준 글: 엔진이 주는 thr_text("BTC x% · ETH y% · XRP z%(수수료 포함)")를 그대로. 옛 자료(success_pct 가 숫자)는 예전 글
  function thrText(c) {
    if (!c) return "";
    if (typeof c.thr_text === "string" && c.thr_text) return c.thr_text;
    if (num(c.success_pct) != null) return `+${c.success_pct}%(수수료 왕복 ${(2 * (num(c.fee_pct_per_side) || 0)).toFixed(1)}% 뺌)`;
    return "";
  }
  // 성적표 '24시간 창' 칸: "60% · 반대 50% (n)". 표본이 없으면 '-'
  function fix24Cell(x) {
    if (!x || !(num(x.fix24_n) > 0) || num(x.fix24_success_pct) == null) return "-";
    return `${x.fix24_success_pct}%${num(x.fix24_opp_pct) == null ? "" : ` · 반대 ${x.fix24_opp_pct}%`} (${x.fix24_n})`;
  }
  // 최근 트리거 한 줄의 24시간 창 결과: {word, pct(순수익, 없으면 null), key}. 결과가 아직 없으면 '진행 중'
  function fix24Row(r) {
    const res = r && r.fix24_result;
    return { key: res === "success" || res === "fail" ? res : "open", word: res === "success" ? "성공" : res === "fail" ? "실패" : "진행 중", pct: r && num(r.fix24_net_pct) != null ? r.fix24_net_pct : null };
  }

  const api = { thrText, fix24Cell, fix24Row, FACTORS, FACTOR_ORDER, REASON, dirWord, dirCls, fmt1, groupDir, isV2, confView, confDir, aiDir, confSub, topFactors, aiPct, newsBias, divergence, divergenceText,
    newsRows, aiStatusLines, failWord, fngEvents, fngLayout, sparkLayout };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Top3View5 = api;
})(typeof window !== "undefined" ? window : globalThis);
