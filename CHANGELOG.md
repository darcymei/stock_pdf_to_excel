# Changelog

## 2026-04-27 — Fix June statement (6月结单) PDF parsing

### Bug Fix 1: Ghost transactions from multi-fill orders

**Problem**: When a buy/sell order is filled in multiple lots (e.g., 2,000 + 18,000 shares), the parser produced ghost rows with empty stock code/name for the 2nd+ fill lines.

**Root Cause**: The corporate-format parser (`RE_DIR_STOCK`) created a `pending_detail` with summary quantity from the direction line. The first SEHK fill line filled in exchange/date but did not update qty/price/amount. After the time line finalized `pending_detail`, subsequent fill lines had no stock context to inherit from, creating empty-stock detail rows.

**Fix** (in `parser.py`):
- First fill line now also updates qty/price/amount/net_amount from the actual fill data
- Added `last_corp_stock` variable to track stock_code/stock_name across fill lines
- Additional fill lines (after time-line finalization) create new `pending_detail` entries inheriting stock info from `last_corp_stock`
- `last_corp_stock` is cleared on new direction groups and fee lines

**Affected stocks in 6月结单**: 01133 (2+18k fills), 00883 (9k+1k fills), 02722 (30k+18k fills)

### Bug Fix 2: IPO allotment records not detected due to bold text

**Problem**: IPO records in the 資產進出 section were not matched because bold PDF text extraction produced doubled characters (e.g., `增增加加` instead of `增加`, `港港股股IPO公公` instead of `港股IPO公`).

**Root Cause**: Two issues:
1. `parse_ipo()` did not apply `_deduplicate_line()` to input lines
2. `_deduplicate_bold_text()` only handled tokens where ALL characters were doubled (even length). Mixed tokens like `港港股股IPO公公` (doubled CJK + non-doubled Latin "IPO") failed dedup due to odd length

**Fix** (in `parser.py`):
- Enhanced `_deduplicate_bold_text()` with a CJK-pair fallback: when whole-token dedup doesn't apply, scan character-by-character and skip consecutive duplicate CJK characters
- Applied `_deduplicate_line()` in `parse_ipo()` to each line before regex matching and section header detection

**Result**: 4 IPO records now correctly detected (3288 海天味業, 2617 藥捷安康-B, 2050 三花智控, 6603 IFBH)

### Verification

| PDF | Result |
|-----|--------|
| 6月结单.pdf | 0 empty stock_code rows; 4 IPO records detected |
| 5月结单.pdf | No regression (01133, qty=20,000) |
| 2026_02.pdf | No regression |
| 2026_03.pdf | No regression |
