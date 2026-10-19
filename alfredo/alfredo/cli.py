"""알프레도 모의투자 CLI.

모든 명령은 모의(가상 장부)이며, 실제 주문·자동매매·계좌 연동 코드는 없다.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import AI_NOTICE, __version__
from .ledger import BOOKS, Ledger, LedgerError
from .principles import DEFAULT_RULES_PATH, check_ledger, load_rules
from .prices import PriceSourceError, make_source
from .report import BENCH, weekly_report

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.environ.get("ALFREDO_DATA", os.path.join(PROJECT_ROOT, "data", "alfredo"))

EPILOG = ("경계: 모든 명령은 모의투자(가상 장부)다. 실제 주문·자동매매·거래소 계좌 연동 코드는 없다. "
          "가격 소스는 읽기 전용(fixed 고정값 / upbit 공개 시세 / top3 수집 DB). " + AI_NOTICE)


def _parse_fixed(items: list[str] | None) -> dict[str, float]:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--price 형식은 SYMBOL=가격: {it}")
        k, v = it.split("=", 1)
        out[k.strip().upper()] = float(v)
    return out


def _prices(args, symbols: list[str]) -> dict[str, float]:
    src = make_source(args.source, _parse_fixed(args.price))
    if not src.available():
        print(f"[경고] 가격 소스 {args.source} 비활성. 가격 없는 자산은 평균단가로 평가한다.", file=sys.stderr)
        return {}
    try:
        return src.get_prices(symbols)
    except PriceSourceError as e:
        print(f"[경고] {e}. 가격 없는 자산은 평균단가로 평가한다.", file=sys.stderr)
        return {}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="alfredo", description="알프레도 모의투자 엔진 v%s (모의 전용)" % __version__,
                                epilog=EPILOG)
    p.add_argument("--db", default=os.path.join(DEFAULT_DATA, "alfredo.db"), help="장부 sqlite 경로")
    p.add_argument("--book", default="experiment", choices=BOOKS, help="mirror=실보유 거울, experiment=실험")
    p.add_argument("--fee", type=float, default=0.0005, help="수수료 비율(기본 0.05%%)")
    p.add_argument("--slippage", type=float, default=0.0, help="슬리피지 비율")
    p.add_argument("--source", default="fixed", choices=["fixed", "upbit", "top3"], help="가격 소스(읽기 전용)")
    p.add_argument("--price", action="append", metavar="SYMBOL=가격", help="fixed 소스 가격(여러 번)")
    p.add_argument("--rules", default=DEFAULT_RULES_PATH, help="사전등록 규칙 JSON")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="장부 파일·표 만들기")
    d = sub.add_parser("deposit", help="모의 입금(원)")
    d.add_argument("amount", type=float)
    d.add_argument("--note")
    for name, help_ in (("buy", "모의 매수(실제 주문 아님)"), ("sell", "모의 매도(실제 주문 아님)")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("symbol")
        s.add_argument("qty", type=float)
        s.add_argument("at", type=float, help="가격(원)")
        s.add_argument("--note")
    sub.add_parser("snapshot", help="현재 평가액 스냅샷 저장")
    r = sub.add_parser("report", help="주간 보고 md 출력")
    r.add_argument("--out", help="저장 경로(없으면 표준출력)")
    r.add_argument("--days", type=int, default=7)
    sub.add_parser("principles-check", help="거래마다 규칙 준수 판정과 이행률")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    led = Ledger(args.db, fee_rate=args.fee, slippage_rate=args.slippage)
    book = args.book
    try:
        if args.cmd == "init":
            print(f"장부 준비됨: {args.db} (모의 전용)")
        elif args.cmd == "deposit":
            bench = _prices(args, [BENCH]).get(BENCH)
            tid = led.deposit(book, args.amount, bench_price=bench, note=args.note)
            print(f"입금 #{tid} {args.amount:,.0f}원 → 현금 {led.cash(book):,.0f}원"
                  + ("" if bench else " (BTC 기준가 없음: 벤치마크 비교 미확인)"))
        elif args.cmd in ("buy", "sell"):
            fn = led.buy if args.cmd == "buy" else led.sell
            tid = fn(book, args.symbol.upper(), args.qty, args.at, note=args.note)
            pos = led.position(book, args.symbol.upper())
            print(f"모의 {args.cmd} #{tid} {args.symbol.upper()} {args.qty:g} @ {args.at:,.0f} → "
                  f"현금 {led.cash(book):,.0f}원, 보유 {pos.qty if pos else 0:g}")
        elif args.cmd == "snapshot":
            syms = [p.symbol for p in led.positions(book)] + [BENCH]
            prices = _prices(args, syms)
            sid = led.snapshot(book, prices)
            print(f"스냅샷 #{sid} 총 평가액 {led.total_value(book, prices):,.0f}원")
        elif args.cmd == "report":
            syms = [p.symbol for p in led.positions(book)] + [BENCH]
            md = weekly_report(led, book, _prices(args, syms), load_rules(args.rules),
                               now=datetime.now(timezone.utc), days=args.days)
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(md)
                print(f"보고 저장: {args.out}")
            else:
                print(md)
        elif args.cmd == "principles-check":
            js, rate = check_ledger(led, book, load_rules(args.rules))
            for j in js:
                print(f"#{j.trade_id} {j.rule_id} {'준수' if j.ok else '위반'}: {j.detail}")
            print(f"이행률: {('%.0f%%' % (rate * 100)) if rate is not None else '판정 없음'} ({len(js)}건)")
    except LedgerError as e:
        print(f"[오류] {e}", file=sys.stderr)
        return 1
    finally:
        led.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
