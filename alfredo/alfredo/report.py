"""주간 보고(markdown). AI 고지(머리)·불확실성·자산·손익·벤치마크(BTC 보유 대비)·원칙 이행률·정정 기록."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import AI_NOTICE
from .ledger import Ledger
from .principles import check_ledger

BENCH = "BTC"


def _fmt(x: float | None, unit: str = "") -> str:
    return "미확인" if x is None else f"{x:,.0f}{unit}"


def _pct(x: float | None) -> str:
    return "미확인" if x is None else f"{x:+.1%}"


def benchmark_value(ledger: Ledger, book: str, bench_price_now: float | None) -> tuple[float | None, str]:
    """입금액을 전부 BTC로 바꿔 들고만 있었을 때의 지금 가치.

    입금 기록에 bench_price가 없거나 현재 BTC 가격이 없으면 None("미확인").
    """
    if bench_price_now is None:
        return None, "현재 BTC 가격 없음"
    units = 0.0
    for t in ledger.trades(book):
        if t["side"] == "deposit":
            if t["bench_price"] is None or t["bench_price"] <= 0:
                return None, f"입금 #{t['id']}에 BTC 기준가 없음"
            units += t["cash_delta"] / t["bench_price"]
        elif t["side"] == "withdraw":
            return None, "출금 기록이 있어 단순 비교 불가(v0)"
    return units * bench_price_now, "입금 시점마다 BTC로 환산해 보유"


def weekly_report(ledger: Ledger, book: str, prices: dict[str, float], rules: dict,
                  now: datetime | None = None, days: int = 7) -> str:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).replace(microsecond=0).isoformat()
    cash = ledger.cash(book)
    positions = ledger.positions(book)
    total = ledger.total_value(book, prices)
    deposits = ledger.deposits_total(book)
    realized_total = ledger.realized_pnl(book)
    realized_week = ledger.realized_pnl(book, since=since)
    unrealized = ledger.unrealized_pnl(book, prices)
    missing = [p.symbol for p in positions if p.symbol not in prices]
    ret = (total - deposits) / deposits if deposits > 0 else None
    bench_val, bench_note = benchmark_value(ledger, book, prices.get(BENCH))
    bench_ret = (bench_val - deposits) / deposits if (bench_val is not None and deposits > 0) else None
    judgements, rate = check_ledger(ledger, book, rules, record=True)
    week_trades = ledger.trades(book, since=since)

    # 직전 스냅샷(7일 이상 전) 대비
    prev = None
    for s in ledger.snapshots(book):
        if s["ts"] <= since:
            prev = s
    week_change = (total - prev["total_value"]) if prev else None

    L = []
    L.append(f"# 알프레도 주간 보고 (모의투자 · 장부 {book})")
    L.append(f"> {AI_NOTICE}")  # AI 고지는 머리(첫 3줄 안). AI기본법 31조
    L.append("")
    L.append(f"- 기준 시각: {now.replace(microsecond=0).isoformat()} (UTC)")
    L.append(f"- 기간: 최근 {days}일 (거래 {len(week_trades)}건)")
    L.append("- 성격: 가상 장부. 실제 주문·계좌 연동 없음.")
    L.append("")
    L.append("## 1. 먼저, 불확실한 것")
    L.append("- 아래 숫자는 입력된 가격과 장부 기록에 기댄다. 가격 소스가 틀리면 평가액도 틀린다.")
    if missing:
        L.append(f"- 가격 미확인 자산(평균단가로 평가함): {', '.join(missing)}")
    if bench_val is None:
        L.append(f"- 벤치마크(BTC 보유) 비교 미확인: {bench_note}")
    L.append("- 과거 성과는 앞으로를 보장하지 않는다. 이 보고는 예측이 아니라 기록이다.")
    L.append("")
    L.append("## 2. 자산")
    L.append(f"- 총 평가액: {_fmt(total, '원')} (현금 {_fmt(cash, '원')})")
    L.append(f"- 누적 입금: {_fmt(deposits, '원')} · 누적 수익률: {_pct(ret)}")
    L.append(f"- 7일 전 스냅샷 대비: {_fmt(week_change, '원') if week_change is not None else '미확인(7일 이상 된 스냅샷 없음)'}")
    L.append("")
    L.append("| 자산 | 수량 | 평균단가 | 현재가 | 평가액 | 미실현 |")
    L.append("|---|---|---|---|---|---|")
    for p in positions:
        price = prices.get(p.symbol)
        L.append(f"| {p.symbol} | {p.qty:g} | {p.avg_cost:,.0f} | {_fmt(price)} | "
                 f"{_fmt(p.qty * (price if price is not None else p.avg_cost))} | {_fmt(p.unrealized(price))} |")
    if not positions:
        L.append("| (보유 없음) | | | | | |")
    L.append("")
    L.append("## 3. 손익")
    L.append(f"- 실현 손익(누적): {_fmt(realized_total, '원')} · 이번 기간: {_fmt(realized_week, '원')}")
    L.append(f"- 미실현 손익: {_fmt(unrealized, '원')}")
    if realized_week < 0 or unrealized < 0:
        L.append("- 손실이 있다. 사실: 위 숫자. 다음 행동: 원칙 이행률 표를 보고, 규칙을 어긴 거래가 있으면 그 이유를 적는다. "
                 "규칙 자체를 바꾸려면 날짜와 이유를 남기고 바꾼다. 결정은 사용자가 한다.")
    L.append("")
    L.append("## 4. 벤치마크: BTC만 들고 있었다면")
    L.append(f"- BTC 보유 가치: {_fmt(bench_val, '원')} · 수익률: {_pct(bench_ret)}")
    if bench_ret is not None and ret is not None:
        L.append(f"- 장부 − 벤치마크: {ret - bench_ret:+.1%}p")
    L.append("")
    L.append("## 5. 원칙 이행률")
    L.append(f"- 이행률: {('%.0f%%' % (rate * 100)) if rate is not None else '판정 없음'} "
             f"(판정 {len(judgements)}건 중 준수 {sum(1 for j in judgements if j.ok)}건, 규칙 {rules.get('version', '?')})")
    bad = [j for j in judgements if not j.ok]
    if bad:
        L.append("")
        L.append("| 거래 | 규칙 | 내용 |")
        L.append("|---|---|---|")
        for j in bad:
            L.append(f"| #{j.trade_id} | {j.rule_id} | {j.detail} |")
    L.append("")
    L.append("## 6. 정정 기록")
    L.append("- 이 보고에서 틀린 숫자를 발견하면 여기에 날짜·틀린 값·바른 값을 적는다. (없음)")
    L.append("")
    L.append("")
    return "\n".join(L)
