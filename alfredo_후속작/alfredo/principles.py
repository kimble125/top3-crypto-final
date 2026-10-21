"""사전등록 규칙(JSON) 로드와 원칙 이행률 계산.

거래마다 규칙 준수 여부를 판정한다. 규칙이 해당하지 않는 거래(예: 입금, 매도)는 세지 않는다.
이행률 = 준수 판정 수 / 전체 판정 수. 판정이 하나도 없으면 None.

판정은 장부의 거래 기록을 처음부터 재생(replay)해서 "그 거래 직전·직후 상태"로 한다.
재생 중 다른 자산의 평가 가격은 그 자산의 마지막 거래 가격(없으면 평균단가)을 쓴다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .ledger import CASH, Ledger

DEFAULT_RULES_PATH = os.path.join(os.path.dirname(__file__), "conf", "principles_v0.json")


class PrinciplesError(Exception):
    pass


@dataclass
class Judgement:
    trade_id: int
    rule_id: str
    ok: bool
    detail: str


def load_rules(path: str | None = None) -> dict:
    path = path or DEFAULT_RULES_PATH
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "rules" not in data or not isinstance(data["rules"], list):
        raise PrinciplesError("규칙 파일에 rules 배열이 없다")
    for r in data["rules"]:
        for k in ("id", "type", "params"):
            if k not in r:
                raise PrinciplesError(f"규칙에 {k}가 없다: {r}")
    return data


# ---------- 개별 규칙 ----------
# 각 함수는 (ok, detail) 또는 None(해당 없음)을 돌려준다.
# state: {"cash": float, "pos": {symbol: {"qty","avg_cost"}}, "last_price": {symbol: price}}

def _total_value(state: dict, overrides: dict[str, float] | None = None) -> float:
    v = state["cash"]
    for s, p in state["pos"].items():
        price = (overrides or {}).get(s, state["last_price"].get(s, p["avg_cost"]))
        v += p["qty"] * price
    return v


def rule_max_weight(params: dict, trade: dict, before: dict, after: dict):
    if trade["side"] != "buy":
        return None
    cap = float(params["max_weight"])
    sym = trade["symbol"]
    total = _total_value(after, {sym: trade["price"]})
    if total <= 0:
        return None
    weight = after["pos"][sym]["qty"] * trade["price"] / total
    return weight <= cap + 1e-9, f"{sym} 매수 후 비중 {weight:.1%} (상한 {cap:.0%})"


def rule_stop_loss(params: dict, trade: dict, before: dict, after: dict):
    if trade["side"] != "buy":
        return None
    sym = trade["symbol"]
    pos = before["pos"].get(sym)
    if not pos or pos["qty"] <= 0:
        return None  # 첫 매수에는 손절선이 없다
    loss = (pos["avg_cost"] - trade["price"]) / pos["avg_cost"]
    limit = float(params["loss_pct"])
    ok = loss < limit - 1e-9
    return ok, f"{sym} 평균단가 대비 {-loss:+.1%}에서 추가 매수 (손절선 −{limit:.0%})"


def rule_add_buy(params: dict, trade: dict, before: dict, after: dict):
    if trade["side"] != "buy":
        return None
    sym = trade["symbol"]
    pos = before["pos"].get(sym)
    if not pos or pos["qty"] <= 0:
        return None
    dip = (pos["avg_cost"] - trade["price"]) / pos["avg_cost"]
    need = float(params["min_dip_pct"])
    return dip >= need - 1e-9, f"{sym} 평균단가 대비 {-dip:+.1%}에서 추가 매수 (조건 −{need:.0%} 이하)"


RULE_TYPES = {"max_weight": rule_max_weight, "stop_loss": rule_stop_loss, "add_buy": rule_add_buy}


# ---------- 재생과 판정 ----------
def _apply(state: dict, t: dict) -> dict:
    s = {"cash": state["cash"], "pos": {k: dict(v) for k, v in state["pos"].items()},
         "last_price": dict(state["last_price"])}
    side, sym = t["side"], t["symbol"]
    s["cash"] += t["cash_delta"]
    if side in ("buy", "sell"):
        s["last_price"][sym] = t["price"]
        p = s["pos"].setdefault(sym, {"qty": 0.0, "avg_cost": 0.0})
        if side == "buy":
            cost = -t["cash_delta"]  # 수수료 포함
            nq = p["qty"] + t["qty"]
            p["avg_cost"] = (p["qty"] * p["avg_cost"] + cost) / nq
            p["qty"] = nq
        else:
            p["qty"] -= t["qty"]
            if p["qty"] <= 1e-12:
                del s["pos"][sym]
    return s


def judge_trades(trades: list[dict], rules: dict) -> list[Judgement]:
    out: list[Judgement] = []
    state = {"cash": 0.0, "pos": {}, "last_price": {}}
    for t in trades:
        after = _apply(state, t)
        for r in rules["rules"]:
            fn = RULE_TYPES.get(r["type"])
            if fn is None:
                raise PrinciplesError(f"모르는 규칙 유형: {r['type']}")
            if r.get("applies_to") and t["side"] not in r["applies_to"]:
                continue
            res = fn(r["params"], t, state, after)
            if res is not None:
                out.append(Judgement(t["id"], r["id"], bool(res[0]), res[1]))
        state = after
    return out


def compliance_rate(judgements: list[Judgement]) -> float | None:
    if not judgements:
        return None
    return sum(1 for j in judgements if j.ok) / len(judgements)


def check_ledger(ledger: Ledger, book: str, rules: dict, record: bool = True) -> tuple[list[Judgement], float | None]:
    trades = [dict(r) for r in ledger.trades(book)]
    js = judge_trades(trades, rules)
    if record:
        for j in js:
            ledger.record_principle(book, j.trade_id, j.rule_id, j.ok, j.detail)
    return js, compliance_rate(js)
