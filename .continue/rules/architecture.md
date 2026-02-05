---
description: High-level architecture and data flow for beanschedule
---

# Architecture Overview

## What is Beanschedule?

Beanschedule is a **beangulp hook** that automatically enriches bank transactions by matching them to scheduled/recurring transactions from a YAML config. It adds posting details, metadata, and creates placeholders for expected but unmatched transactions.

## High-Level Data Flow

```
1. Hook Entry (hook.py:schedule_hook)
   ↓
2. Load Schedules (loader.py)
   ↓
3. Generate Expected Dates (recurrence.py)
   ↓
4. Match Transactions (matcher.py)
   ↓
5. Enrich + Create Placeholders (hook.py)
```

### Key Steps

**1. Schedule Loading**
- Supports: single `schedules.yaml` or directory `schedules/` with `_config.yaml`
- Auto-discovers in: env vars → current dir → parent dir
- Returns: `ScheduleFile` with global config + Schedule objects

**2. Recurrence Generation**
- For each schedule, generates expected transaction dates
- Supports: MONTHLY, WEEKLY, YEARLY, BIMONTHLY, INTERVAL
- Uses `dateutil.rrule` (handles leap years, DST correctly)

**3. Transaction Matching**
- Weighted scoring: Payee (40%) + Amount (40%) + Date (20%)
- Account match required (mandatory)
- Fuzzy matching via `difflib.SequenceMatcher` + regex support
- Returns best match if score ≥ threshold

**4. Enrichment**
- Adds metadata: `schedule_id`, `schedule_matched_date`, `schedule_confidence`
- Merges tags, can override payee/narration
- Replaces postings with schedule template postings

**5. Placeholder Creation**
- Creates missing transactions for expected schedule dates with no match
- Checks `schedule_id` metadata in ledger to prevent duplicates
- Configurable flag (`!` by default) and narration prefix (`[MISSING]`)

## Module Structure

| Module | Lines | Responsibility |
|--------|-------|-----------------|
| `schema.py` | 120 | Pydantic models: Schedule, MatchCriteria, RecurrenceRule, GlobalConfig |
| `matcher.py` | 230 | Scoring algorithm: `TransactionMatcher.calculate_match_score()` |
| `recurrence.py` | 160 | Date generation per frequency type |
| `loader.py` | 280 | YAML loading, validation, auto-discovery |
| `hook.py` | 450 | Beangulp hook integration, enrichment, lazy matching |
| `cli.py` | 350 | CLI: validate, list, generate, init commands |

## Critical Optimization: Lazy Matching

**Problem**: Checking all ledger transactions (10k+) against all schedules is slow.

**Solution** (`hook.py:_build_date_index()`): Build O(1) date lookup
```python
date_index = {date: [txn, txn, ...], ...}

# Instead of checking all 14k transactions per schedule:
transactions_in_window = date_index.get(expected_date) + nearby_dates
# Check only 10-50 relevant transactions
```

**Result**: 45s → 5-10s on M2 MacBook (14k entries, 43 schedules) = **80%+ speedup**

## Design Constraints

1. **Beangulp Hook Format** - Must accept: `(account, directives, date_range, progress)`
2. **Ledger Blocking** - `schedule_id` metadata prevents duplicate placeholders
3. **Account Required** - Account match is mandatory for correctness
4. **Regex Patterns** - Payee patterns use regex (not glob)
5. **YAML Only** - Schedules in YAML (not Python code)
6. **Single Currency** - All amounts in schedule currency

## Example Data Flow

**Input**:
```beancount
2024-01-01 * "PROPERTY MGR" ""
  Assets:Bank:Checking  -1500.00 USD
```

**Process**:
1. Load schedule: `rent-payment`, pattern `"Property Manager|Landlord"`, amount `-1500.00`
2. Generate: Expected 1st of each month
3. Match: Jan 1 ✓ (date), "PROPERTY MGR" ✓ (fuzzy), -1500 ✓ (amount) → score 0.92
4. Enrich: Add metadata + postings

**Output**:
```beancount
2024-01-01 * "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  schedule_matched_date: 2024-01-01
  schedule_confidence: 0.92
  Assets:Bank:Checking                   -1500.00 USD
  Expenses:Housing:Rent                   1500.00 USD
```
