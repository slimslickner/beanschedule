# Pending Transactions

Pending transactions let you stage one-time items that haven't posted yet. They auto-match and enrich when imported, then are automatically removed (one-time use).

## Use Case

You make an online purchase that won't post for a few days. You want to pre-define the exact splits so when it imports, it's automatically categorized correctly.

```bash
# You plan to spend on 2026-02-20:
beanschedule pending create \
  --account Assets:Checking \
  --amount -89.99 \
  --date 2026-02-20 \
  --payee "Amazon" \
  --narration "Wireless headphones"

# When it imports (maybe 2-3 days later), it automatically matches and enriches
# Then is removed from pending (one-time use)
```

## Setup

### Default Location

Beanschedule looks for `pending.beancount` in this order:

1. `BEANSCHEDULE_PENDING` environment variable
2. `pending.beancount` in current directory
3. `pending.beancount` in parent directory

### Custom Location

```bash
export BEANSCHEDULE_PENDING=/path/to/my/pending.beancount
beanschedule pending list
```

### Create Directory

If you prefer a dedicated location:

```bash
mkdir -p ledger/pending
export BEANSCHEDULE_PENDING=ledger/pending.beancount
```

## CLI Usage

### Create a Pending Transaction

Interactive mode (prompts for splits):

```bash
beanschedule pending create \
  --account Assets:Checking \
  --amount -89.99 \
  --date 2026-02-20 \
  --payee "Amazon" \
  --narration "Wireless headphones"
```

This prompts:

```
Account 1: Assets:Checking (-89.99 USD) [auto-filled]
Account 2 narration: Bose headphones
Account 2: Expenses:Electronics:Audio (89.99 USD)
Account 2: Expenses:Electronics:Audio (89.99 USD)
Account 3 narration: Shipping
Account 3: Expenses:Shopping:Shipping (0.00 USD)
Continue adding accounts? (y/n): n
```

Creates:

```beancount
2026-02-20 ! "Amazon" "Wireless headphones (not yet charged)"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics:Audio  85.00 USD
    narration: "Bose QuietComfort 45 headphones"
  Expenses:Shopping:Shipping  4.99 USD
    narration: "Standard shipping"
```

### List Pending Transactions

```bash
beanschedule pending list
beanschedule pending list --file my-pending.beancount  # Specify file directly
```

Output:

```
PENDING TRANSACTIONS (2)

2026-02-20: Amazon - -89.99 USD (3 postings)
  Wireless headphones (not yet charged)

2026-02-22: Whole Foods - -127.45 USD (2 postings)
  Groceries (not yet charged)
```

### Clean Up

Remove empty pending file:

```bash
beanschedule pending clean
beanschedule pending clean --file my-pending.beancount  # Specify file directly

# Preview without making changes
beanschedule pending clean --dry-run
```

## Manual Entry

If you prefer editing the file directly:

```beancount
2026-02-20 ! "Amazon" "Wireless headphones (not yet charged)"
  #pending
  Assets:Checking  -89.99 USD
  Expenses:Electronics:Audio  85.00 USD
    narration: "Bose QuietComfort 45 headphones"
  Expenses:Shopping:Shipping  4.99 USD
    narration: "Standard shipping"
```

**Requirements:**

- Flag must be `!` (pending flag)
- Must have `#pending` tag
- Amount must be specified (no null amounts)
- No metadata required
- Posting-level `narration:` is standard Beancount posting metadata syntax (indented under a posting) because the `;;` notation from autobean.narration will not work otherwise.

## Recommended Ledger Setup

Because the schedule hook **removes matched entries from `pending.beancount`** during import, you should keep pending transactions out of the ledger file that beangulp reads. The recommended approach is to use two entry-point files:

```
ledger/
  main.bean                # Full ledger (daily use, Fava, reporting)
  main_no_plugins.bean     # Import-only ledger (beangulp reads this)
  pending.bean             # Pending transactions (auto-managed)
  accounts.bean
  2025.bean
  ...
```

**`main.bean`** — your full ledger for Fava, reporting, and day-to-day use:

```beancount
include "accounts.bean"
include "2025.bean"
include "pending.beancount"

plugin "beanschedule.plugins.schedules" "{'forecast_months': 3}"
plugin "beancount.plugins.zerosum"
```

**`main_no_plugins.bean`** — a stripped-down entry point used only by beangulp:

```beancount
include "accounts.bean"
include "2025.bean"

; No plugins — zerosum and schedules would interfere with import matching
; No pending.beancount — the hook manages it directly and deletes matched entries
```

Point your beangulp importer config at the no-plugins file:

```python
# importers/config.py
from beanschedule import schedule_hook

LEDGER = "main_no_plugins.bean"
HOOKS = [schedule_hook]
```

**Why this matters:**

- **No `pending.beancount` include** — the hook reads `pending.beancount` directly and removes matched entries. If beangulp also parses it via `include`, the hook would see pending entries as both pending *and* existing ledger transactions, causing conflicts
- **No plugins** — plugins like zerosum and the schedules forecast plugin generate synthetic transactions that can interfere with the hook's matching logic during import
- **Separate concerns** — `main.bean` is for viewing your complete financial picture; `main_no_plugins.bean` is purely for feeding clean data to the import pipeline

## How It Works

1. **Create** - You create an entry in `pending.beancount` with splits
2. **Stage** - Entry sits with `#pending` tag, waiting for import
3. **Import** - Run beangulp import as normal
4. **Match** - Hook matches on:
   - Account (exact match)
   - Amount (exact match)
   - Date (±4 days by default)
5. **Enrich** - Hook:
   - Replaces pending tag with matched transaction's splits
   - Adds `pending_matched_date` metadata showing when it was matched
6. **Cleanup** - Matched pending entry is automatically removed from the file

**Metadata:** After enrichment, matched transactions include `pending_matched_date` metadata with the import date, useful for tracking when pending transactions cleared.

## Matching Logic

Pending transactions match based on:

| Criteria | Rule                     |
| -------- | ------------------------ |
| Account  | Must match exactly       |
| Amount   | Must match exactly       |
| Date     | Within ±4 days (default) |

**Example:**

Pending entry:

```beancount
2026-02-20 ! "Amazon" "Headphones"
  Assets:Checking  -89.99 USD
  Expenses:Electronics:Audio  89.99 USD
```

Imported transaction:

```beancount
2026-02-22 * "AMZN PURCHASE" ""
  Assets:Checking  -89.99 USD
```

**Result:** ✓ Matches (account and amount exact, date within ±4 days)

Enriched:

```beancount
2026-02-22 * "Amazon" "Headphones"
  Assets:Checking  -89.99 USD
  Expenses:Electronics:Audio  89.99 USD
```

Pending entry is removed.

## Logging

The hook provides detailed logging:

```
[INFO] ======================================================================
[INFO] PENDING TRANSACTIONS - LOADED (3)
[INFO] ======================================================================
[INFO]   • 2026-02-20: Amazon - -89.99 USD (3 postings)
[INFO]   • 2026-02-22: Whole Foods - -127.45 USD (2 postings)
[INFO] ======================================================================

[INFO] ✓ Matched pending transaction: 2026-02-20 (Amazon) - -89.99 USD | 3 postings

[WARNING] ======================================================================
[WARNING] PENDING TRANSACTIONS - UNMATCHED (1 open)
[WARNING] ======================================================================
[WARNING]   • 2026-03-01 (in 9 days): Netflix - -15.99 USD
[WARNING] ======================================================================
```

This tells you:

- ✓ How many pending transactions were loaded
- ✓ Which ones matched during import
- ⚠ Which ones are still waiting (with relative date)

## Examples

### Online Purchase (Multiple Splits)

```beancount
2026-02-20 ! "Amazon" "Laptop stand (not yet charged)"
  #pending
  Assets:Checking                       -79.99 USD
  Expenses:Office:Equipment             75.00 USD
  Expenses:Office:Shipping               4.99 USD
```

### Restaurant with Tax/Tip

```beancount
2026-02-25 ! "Restaurant Name" "Dinner (not yet charged)"
  #pending
  Assets:Checking                      -32.15 USD
  Expenses:Food:Dining                 -27.00 USD
  Expenses:Taxes:Sales                  -2.00 USD
  Expenses:Tips                         -3.15 USD
```

### Subscription Starting Soon

```beancount
2026-03-01 ! "Subscription Service" "Annual subscription (not yet charged)"
  #pending
  Assets:Checking                     -119.99 USD
  Expenses:Subscriptions:Annual        119.99 USD
```

### Split Payment

```beancount
2026-02-28 ! "Best Buy" "Electronics (not yet charged)"
  #pending
  Assets:CreditCard:Visa              -299.99 USD
  Assets:CreditCard:AmEx              -200.00 USD
  Expenses:Electronics:Computer        499.99 USD
```

## Troubleshooting

### Transaction Not Matching

**Check these in order:**

1. **Account mismatch**: Is the pending account exactly the same as the imported account?

   ```beancount
   # ✓ Correct
   Assets:Bank:Checking (pending)
   Assets:Bank:Checking (imported)

   # ✗ Won't match
   Assets:Checking (pending)
   Assets:Bank:Checking (imported)
   ```

2. **Amount mismatch**: Is the pending amount exactly the same?

   ```beancount
   # ✓ Correct
   Assets:Checking  -89.99 USD (pending)
   Assets:Checking  -89.99 USD (imported)

   # ✗ Won't match
   Assets:Checking  -89.99 USD (pending)
   Assets:Checking  -90.00 USD (imported)
   ```

3. **Date out of range**: Is the date within ±4 days?

   ```beancount
   # ✓ Match
   2026-02-20 (pending) vs 2026-02-22 (imported) = 2 days

   # ✗ No match
   2026-02-20 (pending) vs 2026-02-26 (imported) = 6 days (outside ±4)
   ```

4. **Check logs**: Look for unmatched pending warnings during import

### Transaction Matched But Not Removed

If a pending transaction is matched but not removed:

1. **Check file permissions**: Ensure the file is writable
2. **Check logging**: Look for errors in import output
3. **Manual cleanup**: Remove from `pending.beancount` if the import succeeded

## See Also

- [SCHEDULES.md](SCHEDULES.md) - Scheduled recurring transactions
- [CLI.md](CLI.md) - Command-line tools
- `examples/pending.beancount` - More examples
