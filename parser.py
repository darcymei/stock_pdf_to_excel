import re
from typing import List, Optional
import pdfplumber

from models import TradeDetail, TransactionGroup


def _deduplicate_bold_text(line: str) -> str:
    """Detect and fix doubled characters from bold PDF text extraction.

    Some PDFs render bold text in a way that pdfplumber extracts each character
    twice consecutively (e.g. '交交易易' instead of '交易').
    """
    if len(line) < 2:
        return line
    # Check if the line follows the doubled pattern: every pair of adjacent
    # characters at even positions are identical
    chars = list(line)
    if len(chars) % 2 == 0:
        is_doubled = all(chars[i] == chars[i + 1] for i in range(0, len(chars), 2))
        if is_doubled:
            return "".join(chars[i] for i in range(0, len(chars), 2))

    # CJK-pair fallback: handle mixed tokens like '港港股股IPO公公'
    # where CJK chars are doubled but Latin chars are not
    result = []
    j = 0
    has_dedup = False
    while j < len(chars):
        result.append(chars[j])
        if j + 1 < len(chars) and _is_cjk(chars[j]) and chars[j] == chars[j + 1]:
            j += 2  # skip the duplicate
            has_dedup = True
        else:
            j += 1
    if has_dedup:
        return "".join(result)
    return line


def _deduplicate_line(line: str) -> str:
    """Apply de-duplication to individual tokens in a line.

    Handles lines where some tokens are doubled (bold) and others are not,
    e.g. '買買入入開開倉倉 01133(哈爾濱電 HKD 20,000 5.3000 106,000.00 -106,163.93'
    """
    tokens = line.split()
    result = []
    for token in tokens:
        deduped = _deduplicate_bold_text(token)
        result.append(deduped)
    return " ".join(result)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
            0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


def parse_number(s: str) -> float:
    return float(s.replace(",", ""))


def parse_int(s: str) -> int:
    return int(s.replace(",", ""))


# Regex patterns
RE_DIRECTION = re.compile(
    r"^(買入開倉|賣出平倉)\s+(HKD|USD|CNH|SGD)\s+"
    r"([\d,]+)\s+([\d,.]+)\s+([\d,.]+)\s+(-?[\d,.]+)$"
)

# Tail pattern: exchange currency date date qty price amount net_amount
RE_DETAIL_TAIL = re.compile(
    r"([A-Z][A-Z0-9]+|FUTU OTC)\s+"
    r"(HKD|USD|CNH|SGD)\s+"
    r"(\d{4}/\d{2}/\d{2})\s+(\d{4}/\d{2}/\d{2})\s+"
    r"([\d,]+)\s+([\d,.]+)\s+([\d,.]+)\s+(-?[\d,.]+)$"
)

RE_FEE = re.compile(r"佣金:\s*([\d,.]+).*小計:\s*([\d,.]+)")

RE_TIME = re.compile(r"^(\d{2}:\d{2}:\d{2})$")

# Continuation line: name_suffix) time
RE_CONTINUATION = re.compile(r"^(.+?)\)\s+(\d{2}:\d{2}:\d{2})$")

RE_END_SECTION = re.compile(r"^成交金額合計")

# Combined direction + stock code line (account 3862 corporate format)
# e.g. "買入開倉 01133(哈爾濱電 HKD 20,000 5.3000 106,000.00 -106,163.93"
RE_DIR_STOCK = re.compile(
    r"^(買入開倉|賣出平倉)\s+"
    r"([\w.]+)\((.+?)(\))?\s+"
    r"(HKD|USD|CNH|SGD)\s+"
    r"([\d,]+)\s+([\d,.]+)\s+([\d,.]+)\s+(-?[\d,.]+)$"
)

# Page header lines to skip
RE_PAGE_HEADER = re.compile(
    r"^(保證金綜合帳戶|買賣方向\s+代碼名稱|製備日期|交易所/市場)"
)

RE_PERIOD_LINE = re.compile(r"^\d{4}/\d{2}$")


def parse_fee_line(line: str) -> dict:
    """Parse a fee line into a dict of fee_name -> amount, plus 小計."""
    fees = {}
    for m in re.finditer(r"([\u4e00-\u9fff]+(?:[\u4e00-\u9fff]*)?)\s*:\s*([\d,.]+)", line):
        fees[m.group(1)] = parse_number(m.group(2))
    return fees


def extract_transaction_text(pdf_path: str) -> str:
    """Extract and clean text from the transaction section of the PDF."""
    lines_all = []
    in_section = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Apply per-token de-duplication for bold text
                normalized = _deduplicate_line(line)

                if not in_section:
                    if "交易-股票和股票期權" in normalized:
                        in_section = True
                    continue

                if RE_END_SECTION.match(normalized):
                    return "\n".join(lines_all)

                # Skip page headers
                if RE_PAGE_HEADER.match(normalized):
                    continue
                if RE_PERIOD_LINE.match(normalized):
                    continue

                lines_all.append(normalized)

    return "\n".join(lines_all)


def parse_pdf(pdf_path: str) -> List[TransactionGroup]:
    """Parse a Futu Securities PDF statement and return transaction groups."""
    text = extract_transaction_text(pdf_path)
    if not text:
        raise ValueError("未找到交易明细区段（交易-股票和股票期權）")

    lines = text.split("\n")
    groups: List[TransactionGroup] = []
    current_group: Optional[TransactionGroup] = None
    pending_detail: Optional[dict] = None  # detail waiting for time on next line

    def finalize_pending(time_str: str = ""):
        nonlocal pending_detail
        if pending_detail and current_group:
            direction_str = "BUY" if current_group.direction == "買入開倉" else "SELL"
            detail = TradeDetail(
                stock_code=pending_detail["stock_code"],
                stock_name=pending_detail["stock_name"],
                exchange=pending_detail["exchange"],
                currency=pending_detail["currency"],
                date=pending_detail["date"],
                time=time_str,
                settlement_date=pending_detail["settlement_date"],
                quantity=pending_detail["quantity"],
                price=pending_detail["price"],
                amount=pending_detail["amount"],
                net_amount=pending_detail["net_amount"],
                direction=direction_str,
            )
            current_group.details.append(detail)
        pending_detail = None

    last_corp_stock = None  # track stock info from corporate-format lines

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for direction line (standard format)
        m_dir = RE_DIRECTION.match(line)
        if m_dir:
            # Finalize any pending detail from previous group
            finalize_pending()
            last_corp_stock = None
            current_group = TransactionGroup(
                direction=m_dir.group(1),
                currency=m_dir.group(2),
                total_quantity=parse_int(m_dir.group(3)),
                total_amount=parse_number(m_dir.group(5)),
                total_net_amount=parse_number(m_dir.group(6)),
            )
            groups.append(current_group)
            i += 1
            continue

        # Check for combined direction + stock line (corporate format)
        m_ds = RE_DIR_STOCK.match(line)
        if m_ds:
            finalize_pending()
            last_corp_stock = None
            currency = m_ds.group(5)
            current_group = TransactionGroup(
                direction=m_ds.group(1),
                currency=currency,
                total_quantity=parse_int(m_ds.group(6)),
                total_amount=parse_number(m_ds.group(8)),
                total_net_amount=parse_number(m_ds.group(9)),
            )
            groups.append(current_group)
            stock_code = m_ds.group(2)
            stock_name = m_ds.group(3)
            name_complete = m_ds.group(4) is not None
            pending_detail = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "name_complete": name_complete,
                "exchange": "",
                "currency": currency,
                "date": "",
                "settlement_date": "",
                "quantity": parse_int(m_ds.group(6)),
                "price": parse_number(m_ds.group(7)),
                "amount": parse_number(m_ds.group(8)),
                "net_amount": parse_number(m_ds.group(9)),
            }
            last_corp_stock = {"stock_code": stock_code, "stock_name": stock_name}
            i += 1
            continue

        # Check for fee line
        m_fee = RE_FEE.match(line)
        if m_fee and current_group:
            finalize_pending()
            last_corp_stock = None
            fees = parse_fee_line(line)
            current_group.fees = fees
            current_group.fee_subtotal = fees.get("小計", 0.0)
            i += 1
            continue

        # Check for detail line (has exchange+currency+dates+numbers at end)
        m_tail = RE_DETAIL_TAIL.search(line)
        if m_tail and current_group:
            prefix = line[: m_tail.start()].strip()

            if not prefix and pending_detail and not pending_detail["exchange"]:
                # Corporate format: first fill line follows direction+stock line
                pending_detail["exchange"] = m_tail.group(1)
                pending_detail["date"] = m_tail.group(3)
                pending_detail["settlement_date"] = m_tail.group(4)
                pending_detail["quantity"] = parse_int(m_tail.group(5))
                pending_detail["price"] = parse_number(m_tail.group(6))
                pending_detail["amount"] = parse_number(m_tail.group(7))
                pending_detail["net_amount"] = parse_number(m_tail.group(8))
                i += 1
                continue

            if not prefix and last_corp_stock:
                # Corporate format: additional fill line for the same stock
                finalize_pending()
                pending_detail = {
                    "stock_code": last_corp_stock["stock_code"],
                    "stock_name": last_corp_stock["stock_name"],
                    "name_complete": True,
                    "exchange": m_tail.group(1),
                    "currency": m_tail.group(2),
                    "date": m_tail.group(3),
                    "settlement_date": m_tail.group(4),
                    "quantity": parse_int(m_tail.group(5)),
                    "price": parse_number(m_tail.group(6)),
                    "amount": parse_number(m_tail.group(7)),
                    "net_amount": parse_number(m_tail.group(8)),
                }
                i += 1
                continue

            finalize_pending()

            # Parse stock code and name from prefix
            # Could be: "01712(龍資源)" (complete) or "00836(華潤電" (wrapped)
            code_match = re.match(r"^([\w.]+)\((.+?)(\))?$", prefix)
            if code_match:
                stock_code = code_match.group(1)
                stock_name = code_match.group(2)
                name_complete = code_match.group(3) is not None
            else:
                stock_code = prefix
                stock_name = ""
                name_complete = True

            pending_detail = {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "name_complete": name_complete,
                "exchange": m_tail.group(1),
                "currency": m_tail.group(2),
                "date": m_tail.group(3),
                "settlement_date": m_tail.group(4),
                "quantity": parse_int(m_tail.group(5)),
                "price": parse_number(m_tail.group(6)),
                "amount": parse_number(m_tail.group(7)),
                "net_amount": parse_number(m_tail.group(8)),
            }
            i += 1
            continue

        # Check for time-only line
        m_time = RE_TIME.match(line)
        if m_time and pending_detail:
            finalize_pending(m_time.group(1))
            i += 1
            continue

        # Check for continuation line: "name_suffix) time"
        m_cont = RE_CONTINUATION.match(line)
        if m_cont and pending_detail and not pending_detail["name_complete"]:
            name_suffix = m_cont.group(1)
            existing = pending_detail["stock_name"]
            if existing and name_suffix and not _is_cjk(existing[-1]) and not _is_cjk(name_suffix[0]):
                pending_detail["stock_name"] = existing + " " + name_suffix
            else:
                pending_detail["stock_name"] = existing + name_suffix
            pending_detail["name_complete"] = True
            if last_corp_stock:
                last_corp_stock["stock_name"] = pending_detail["stock_name"]
            finalize_pending(m_cont.group(2))
            i += 1
            continue

        # Check for name-only continuation: "name_suffix)" without time
        if pending_detail and not pending_detail["name_complete"] and line.endswith(")"):
            name_suffix = line[:-1]
            existing = pending_detail["stock_name"]
            if existing and name_suffix and not _is_cjk(existing[-1]) and not _is_cjk(name_suffix[0]):
                pending_detail["stock_name"] = existing + " " + name_suffix
            else:
                pending_detail["stock_name"] = existing + name_suffix
            pending_detail["name_complete"] = True
            if last_corp_stock:
                last_corp_stock["stock_name"] = pending_detail["stock_name"]
            i += 1
            continue

        # Skip unrecognized lines
        i += 1

    # Finalize any remaining pending detail
    finalize_pending()

    return groups


def parse_ipo(pdf_path: str) -> List[dict]:
    """Extract IPO allotment records from the 資產進出 section."""
    RE_IPO_LINE = re.compile(
        r"^(\d{4}/\d{2}/\d{2})\s+增加\s+港股IPO公\s+"
        r"(\w[\w.]*)\((.+?)\)\s+(HKD|USD)\s+"
        r"\+([\d,]+)\s+\+([\d,.]+)"
    )
    results = []
    in_section = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            lines = text.split("\n")
            for j, line in enumerate(lines):
                line = _deduplicate_line(line.strip())
                if "資產進出" in line:
                    in_section = True
                    continue
                if in_section and ("融資總覽" in line or "期末概覽" in line):
                    in_section = False
                    continue
                if not in_section:
                    continue

                m = RE_IPO_LINE.match(line)
                if m:
                    date = m.group(1)
                    stock_code = m.group(2)
                    stock_name = m.group(3)
                    currency = m.group(4)
                    quantity = parse_int(m.group(5))
                    amount = parse_number(m.group(6))
                    results.append({
                        "date": date,
                        "stock_code": stock_code.lstrip("0") or stock_code,
                        "stock_name": stock_name,
                        "exchange": _map_exchange(currency),
                        "quantity": quantity,
                        "unit_price": round(amount / quantity, 4),
                        "direction": "BUY",
                        "fees": 100.0,
                        "currency": currency,
                        "total_net_amount": round(amount + 100, 2),
                    })
    return results


def _map_exchange(currency: str) -> str:
    return "HKG" if currency == "HKD" else "US" if currency == "USD" else "SG" if currency == "SGD" else currency


def groups_to_rows(groups: List[TransactionGroup], pdf_path: str = "") -> List[dict]:
    """Convert transaction groups to flat rows for Excel output.

    Merges rows with the same stock, date, and direction into one row.
    Includes IPO allotment records if pdf_path is provided.
    """
    # First pass: collect all detail rows
    raw = []
    for group in groups:
        for detail in group.details:
            if detail.direction == "BUY":
                fee = abs(detail.net_amount) - detail.amount
            else:
                fee = detail.amount - detail.net_amount
            raw.append({
                "date": detail.date,
                "stock_code": detail.stock_code.lstrip("0") or detail.stock_code,
                "stock_name": detail.stock_name,
                "exchange": _map_exchange(detail.currency),
                "quantity": detail.quantity,
                "amount": detail.amount,
                "direction": detail.direction,
                "fees": round(fee, 2),
                "currency": detail.currency,
                "total_net_amount": detail.net_amount,
            })

    # Second pass: merge by (stock_code, date, direction)
    from collections import OrderedDict
    merged = OrderedDict()
    for r in raw:
        key = (r["stock_code"], r["date"], r["direction"])
        if key not in merged:
            merged[key] = {
                "date": r["date"],
                "stock_code": r["stock_code"],
                "stock_name": r["stock_name"],
                "exchange": r["exchange"],
                "quantity": r["quantity"],
                "total_amount": r["amount"],
                "direction": r["direction"],
                "fees": r["fees"],
                "currency": r["currency"],
                "total_net_amount": r["total_net_amount"],
            }
        else:
            m = merged[key]
            m["quantity"] += r["quantity"]
            m["total_amount"] += r["amount"]
            m["fees"] = round(m["fees"] + r["fees"], 2)
            m["total_net_amount"] += r["total_net_amount"]

    # Build final rows with average unit price
    rows = []
    for m in merged.values():
        rows.append({
            "date": m["date"],
            "stock_code": m["stock_code"],
            "stock_name": m["stock_name"],
            "exchange": m["exchange"],
            "quantity": m["quantity"],
            "unit_price": round(m["total_amount"] / m["quantity"], 4),
            "direction": m["direction"],
            "fees": m["fees"],
            "currency": m["currency"],
            "total_net_amount": round(abs(m["total_net_amount"]), 2),
        })

    # Append IPO records
    if pdf_path:
        ipo_rows = parse_ipo(pdf_path)
        rows.extend(ipo_rows)

    # Sort by date
    rows.sort(key=lambda r: r["date"])

    return rows
