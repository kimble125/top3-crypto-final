"""가상 장부(sqlite). 실보유 거울 장부(mirror)와 실험 장부(experiment)를 book 열로 구분한다.

실제 주문 코드는 없다. 모든 매수·매도는 장부 안의 숫자만 바꾼다.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

BOOKS = ("mirror", "experiment")
CASH = "KRW"  # 현금은 holdings 표에 symbol=CASH 행으로 둔다

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
  book TEXT NOT NULL, symbol TEXT NOT NULL,
  qty REAL NOT NULL DEFAULT 0, avg_cost REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (book, symbol));
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book TEXT NOT NULL, ts TEXT NOT NULL,
  side TEXT NOT NULL,              -- deposit | withdraw | buy | sell
  symbol TEXT NOT NULL, qty REAL NOT NULL,
  price REAL NOT NULL,             -- 요청 가격(deposit은 1)
  exec_price REAL NOT NULL,        -- 슬리피지 반영 체결 가격
  fee REAL NOT NULL DEFAULT 0,
  cash_delta REAL NOT NULL,        -- 현금 변화(+입금/매도, -출금/매수)
  realized REAL NOT NULL DEFAULT 0,-- 매도 실현 손익(수수료 차감)
  bench_price REAL,                -- 입금 시점 벤치마크 가격(없으면 NULL)
  note TEXT);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book TEXT NOT NULL, ts TEXT NOT NULL,
  cash REAL NOT NULL, total_value REAL NOT NULL,
  unrealized REAL NOT NULL, realized_total REAL NOT NULL,
  positions_json TEXT NOT NULL, prices_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS principles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book TEXT NOT NULL, trade_id INTEGER NOT NULL,
  rule_id TEXT NOT NULL, ok INTEGER NOT NULL,
  detail TEXT, ts TEXT NOT NULL);
"""


class LedgerError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Position:
    symbol: str
    qty: float
    avg_cost: float

    def market_value(self, price: float | None) -> float | None:
        return None if price is None else self.qty * price

    def unrealized(self, price: float | None) -> float | None:
        return None if price is None else (price - self.avg_cost) * self.qty


class Ledger:
    """fee_rate·slippage_rate는 비율(0.0005 = 0.05%)."""

    def __init__(self, db_path: str, fee_rate: float = 0.0005, slippage_rate: float = 0.0):
        if fee_rate < 0 or slippage_rate < 0:
            raise LedgerError("수수료·슬리피지는 0 이상이어야 한다")
        self.db_path = db_path
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---------- 조회 ----------
    @staticmethod
    def _check_book(book: str) -> None:
        if book not in BOOKS:
            raise LedgerError(f"장부는 {BOOKS} 중 하나여야 한다: {book}")

    def cash(self, book: str) -> float:
        row = self.conn.execute("SELECT qty FROM holdings WHERE book=? AND symbol=?", (book, CASH)).fetchone()
        return float(row["qty"]) if row else 0.0

    def position(self, book: str, symbol: str) -> Position | None:
        row = self.conn.execute("SELECT symbol, qty, avg_cost FROM holdings WHERE book=? AND symbol=? AND qty>0",
                                (book, symbol)).fetchone()
        return Position(row["symbol"], float(row["qty"]), float(row["avg_cost"])) if row else None

    def positions(self, book: str) -> list[Position]:
        rows = self.conn.execute("SELECT symbol, qty, avg_cost FROM holdings WHERE book=? AND symbol<>? AND qty>0 ORDER BY symbol",
                                 (book, CASH)).fetchall()
        return [Position(r["symbol"], float(r["qty"]), float(r["avg_cost"])) for r in rows]

    def trades(self, book: str, since: str | None = None) -> list[sqlite3.Row]:
        sql, params = "SELECT * FROM trades WHERE book=?", [book]
        if since:
            sql += " AND ts>=?"
            params.append(since)
        return self.conn.execute(sql + " ORDER BY id", params).fetchall()

    def realized_pnl(self, book: str, since: str | None = None) -> float:
        sql, params = "SELECT COALESCE(SUM(realized),0) s FROM trades WHERE book=? AND side='sell'", [book]
        if since:
            sql += " AND ts>=?"
            params.append(since)
        return float(self.conn.execute(sql, params).fetchone()["s"])

    def deposits_total(self, book: str) -> float:
        r = self.conn.execute("SELECT COALESCE(SUM(cash_delta),0) s FROM trades WHERE book=? AND side IN ('deposit','withdraw')",
                              (book,)).fetchone()
        return float(r["s"])

    def unrealized_pnl(self, book: str, prices: dict[str, float]) -> float:
        """가격이 없는 자산은 0으로 센다(보고에서 '미확인'으로 따로 표시)."""
        return sum((p.unrealized(prices.get(p.symbol)) or 0.0) for p in self.positions(book))

    def total_value(self, book: str, prices: dict[str, float]) -> float:
        """가격 없는 자산은 평균단가로 평가한다."""
        v = self.cash(book)
        for p in self.positions(book):
            v += p.qty * prices.get(p.symbol, p.avg_cost)
        return v

    # ---------- 기록 ----------
    def _set_holding(self, book: str, symbol: str, qty: float, avg_cost: float, ts: str) -> None:
        self.conn.execute(
            "INSERT INTO holdings(book,symbol,qty,avg_cost,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(book,symbol) DO UPDATE SET qty=excluded.qty, avg_cost=excluded.avg_cost, updated_at=excluded.updated_at",
            (book, symbol, qty, avg_cost, ts))

    def _insert_trade(self, **kw) -> int:
        cols = ",".join(kw)
        cur = self.conn.execute(f"INSERT INTO trades({cols}) VALUES({','.join('?' * len(kw))})", tuple(kw.values()))
        return int(cur.lastrowid)

    def deposit(self, book: str, amount: float, ts: str | None = None, bench_price: float | None = None,
                note: str | None = None) -> int:
        self._check_book(book)
        if amount <= 0:
            raise LedgerError("입금액은 0보다 커야 한다")
        ts = ts or now_iso()
        self._set_holding(book, CASH, self.cash(book) + amount, 1.0, ts)
        tid = self._insert_trade(book=book, ts=ts, side="deposit", symbol=CASH, qty=amount, price=1.0,
                                 exec_price=1.0, fee=0.0, cash_delta=amount, realized=0.0,
                                 bench_price=bench_price, note=note)
        self.conn.commit()
        return tid

    def withdraw(self, book: str, amount: float, ts: str | None = None, note: str | None = None) -> int:
        self._check_book(book)
        if amount <= 0 or amount > self.cash(book) + 1e-9:
            raise LedgerError("출금액이 0 이하이거나 현금보다 크다")
        ts = ts or now_iso()
        self._set_holding(book, CASH, self.cash(book) - amount, 1.0, ts)
        tid = self._insert_trade(book=book, ts=ts, side="withdraw", symbol=CASH, qty=amount, price=1.0,
                                 exec_price=1.0, fee=0.0, cash_delta=-amount, realized=0.0, bench_price=None, note=note)
        self.conn.commit()
        return tid

    def buy(self, book: str, symbol: str, qty: float, price: float, ts: str | None = None, note: str | None = None) -> int:
        """모의 매수. 수수료는 취득원가에 포함한다."""
        self._check_book(book)
        if symbol == CASH or qty <= 0 or price <= 0:
            raise LedgerError("매수 수량·가격은 0보다 커야 한다")
        ts = ts or now_iso()
        exec_price = price * (1 + self.slippage_rate)
        cost = qty * exec_price
        fee = cost * self.fee_rate
        cash = self.cash(book)
        if cost + fee > cash + 1e-9:
            raise LedgerError(f"현금 부족: 필요 {cost + fee:,.0f}, 보유 {cash:,.0f}")
        pos = self.position(book, symbol)
        old_qty, old_avg = (pos.qty, pos.avg_cost) if pos else (0.0, 0.0)
        new_qty = old_qty + qty
        new_avg = (old_qty * old_avg + cost + fee) / new_qty
        self._set_holding(book, CASH, cash - cost - fee, 1.0, ts)
        self._set_holding(book, symbol, new_qty, new_avg, ts)
        tid = self._insert_trade(book=book, ts=ts, side="buy", symbol=symbol, qty=qty, price=price,
                                 exec_price=exec_price, fee=fee, cash_delta=-(cost + fee), realized=0.0,
                                 bench_price=None, note=note)
        self.conn.commit()
        return tid

    def sell(self, book: str, symbol: str, qty: float, price: float, ts: str | None = None, note: str | None = None) -> int:
        """모의 매도. 실현 손익 = 체결대금 − 수수료 − 취득원가."""
        self._check_book(book)
        if qty <= 0 or price <= 0:
            raise LedgerError("매도 수량·가격은 0보다 커야 한다")
        pos = self.position(book, symbol)
        if not pos or qty > pos.qty + 1e-12:
            raise LedgerError(f"보유 수량 부족: {symbol}")
        ts = ts or now_iso()
        exec_price = price * (1 - self.slippage_rate)
        proceeds = qty * exec_price
        fee = proceeds * self.fee_rate
        realized = proceeds - fee - qty * pos.avg_cost
        self._set_holding(book, CASH, self.cash(book) + proceeds - fee, 1.0, ts)
        self._set_holding(book, symbol, pos.qty - qty, pos.avg_cost if pos.qty - qty > 1e-12 else 0.0, ts)
        tid = self._insert_trade(book=book, ts=ts, side="sell", symbol=symbol, qty=qty, price=price,
                                 exec_price=exec_price, fee=fee, cash_delta=proceeds - fee, realized=realized,
                                 bench_price=None, note=note)
        self.conn.commit()
        return tid

    def snapshot(self, book: str, prices: dict[str, float], ts: str | None = None) -> int:
        self._check_book(book)
        ts = ts or now_iso()
        positions = [{"symbol": p.symbol, "qty": p.qty, "avg_cost": p.avg_cost,
                      "price": prices.get(p.symbol), "value": p.qty * prices.get(p.symbol, p.avg_cost)}
                     for p in self.positions(book)]
        cur = self.conn.execute(
            "INSERT INTO snapshots(book,ts,cash,total_value,unrealized,realized_total,positions_json,prices_json) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (book, ts, self.cash(book), self.total_value(book, prices), self.unrealized_pnl(book, prices),
             self.realized_pnl(book), json.dumps(positions, ensure_ascii=False), json.dumps(prices, ensure_ascii=False)))
        self.conn.commit()
        return int(cur.lastrowid)

    def snapshots(self, book: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM snapshots WHERE book=? ORDER BY ts, id", (book,)).fetchall()

    def record_principle(self, book: str, trade_id: int, rule_id: str, ok: bool, detail: str, ts: str | None = None) -> None:
        self.conn.execute("DELETE FROM principles WHERE book=? AND trade_id=? AND rule_id=?", (book, trade_id, rule_id))
        self.conn.execute("INSERT INTO principles(book,trade_id,rule_id,ok,detail,ts) VALUES(?,?,?,?,?,?)",
                          (book, trade_id, rule_id, int(ok), detail, ts or now_iso()))
        self.conn.commit()

    def principle_rows(self, book: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM principles WHERE book=? ORDER BY trade_id, rule_id", (book,)).fetchall()
