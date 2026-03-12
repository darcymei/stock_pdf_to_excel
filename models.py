from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class TradeDetail:
    stock_code: str
    stock_name: str
    exchange: str
    currency: str
    date: str
    time: str
    settlement_date: str
    quantity: int
    price: float
    amount: float
    net_amount: float
    direction: str  # "BUY" or "SELL"


@dataclass
class TransactionGroup:
    direction: str  # "BUY" or "SELL"
    currency: str
    total_quantity: int
    total_amount: float
    total_net_amount: float
    details: List[TradeDetail] = field(default_factory=list)
    fees: Dict[str, float] = field(default_factory=dict)
    fee_subtotal: float = 0.0


@dataclass
class ExcelRow:
    date: str
    stock_code: str
    stock_name: str
    exchange: str
    quantity: int
    unit_price: float
    direction: str  # "BUY" or "SELL"
    fees: float
    currency: str
    total_net_amount: float
