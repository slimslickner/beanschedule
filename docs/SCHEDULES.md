# Schedules & Beangulp Hook

This document covers how to define recurring transactions and integrate them with beangulp for automatic import enrichment.

## Quick Setup

### 1. Create a Schedules Directory

```bash
mkdir schedules
```

### 2. Create Config File

Create `schedules/_config.yaml`:

```yaml
# Matching behavior
fuzzy_match_threshold: 0.80 # Minimum match score (0.0-1.0)
default_date_window_days: 3 # Allow ±N days for date matching
default_amount_tolerance_percent: 0.02 # Allow ±2% for amount matching

# Placeholder generation
placeholder_flag: "!" # Flag for missing transactions

# Forecast configuration (optional)
forecast_months: 3 # Look N months ahead for plugin
min_forecast_date: null # Override start date (optional)
include_past_dates: false # Generate placeholders for past dates
```

### 3. Create Your First Schedule

Create `schedules/rent.yaml`:

```yaml
id: rent-payment
enabled: true

match:
  account: Assets:Bank:Checking
  payee_pattern: "Property Manager|Landlord"
  amount: -1500.00
  amount_tolerance: 0.00 # Exact amount
  date_window_days: 2 # Allow ±2 days

recurrence:
  frequency: MONTHLY
  day_of_month: 1
  start_date: 2024-01-01

transaction:
  payee: Property Manager
  narration: Monthly Rent
  tags:
    - housing
  metadata:
    schedule_id: rent-payment
    category: housing
  postings:
    - account: Assets:Bank:Checking
      amount: null # Use imported amount
    - account: Expenses:Housing:Rent
      amount: null

missing_transaction:
  create_placeholder: true
  flag: "!"
  narration_prefix: "[MISSING]"
```

### 4. Integrate with Beangulp

Add to your `importers/config.py`:

```python
from beanschedule import schedule_hook

# ... your importer configuration ...

HOOKS = [schedule_hook]
```

Now imports will automatically match and enrich transactions based on your schedules!

## Understanding Matching

Beanschedule uses a weighted scoring algorithm to match imported transactions to schedules:

- **Payee match**: 40% (regex patterns and fuzzy matching)
- **Amount match**: 40% (exact, tolerance, or range-based)
- **Date match**: 20% (day difference with linear decay)

**Example scoring:**

```
Payee: "PROPERTY MGR" matches "Property Manager"         → 0.95 × 0.40 = 0.38
Amount: -1500.00 matches -1500.00 (exact)                → 1.00 × 0.40 = 0.40
Date: 2 days difference (within window)                  → 0.90 × 0.20 = 0.18
Total score: 0.38 + 0.40 + 0.18 = 0.96 ✓ (threshold 0.80)
```

## Schedule Configuration

### Match Section

Defines how to identify the imported transaction:

| Option                      | Type    | Required | Description                               |
| --------------------------- | ------- | -------- | ----------------------------------------- |
| `account`                   | string  | ✓        | Account to match (must be exact)          |
| `payee_pattern`             | regex   | ✓        | Regex pattern for payee matching          |
| `amount`                    | decimal | ✗        | Exact amount to match                     |
| `amount_min` / `amount_max` | decimal | ✗        | Range for variable amounts                |
| `amount_tolerance`          | decimal | ✗        | ±tolerance for amount matching            |
| `date_window_days`          | integer | ✗        | ±days for date matching (default: config) |

**Payee Patterns (Regex):**

```yaml
# Simple alternation
payee_pattern: "Landlord|Property Manager|Rental Mgmt"

# Case-insensitive
payee_pattern: "(?i)^electric"

# Partial match
payee_pattern: "BANK"  # matches "YOUR BANK", "THE BANK CO", etc.

# Fuzzy matching also applies (0.85 threshold)
payee_pattern: "Amazon"  # matches "AMZN", "Amazon Prime", etc.
```

**Amount Matching:**

```yaml
# Option 1: Exact amount
amount: -1500.00
amount_tolerance: 0.00

# Option 2: With fixed tolerance (absolute amount in dollars/currency)
amount: -1500.00
amount_tolerance: 10.00   # ±$10 (fixed amount)

# Option 3: Use default percentage tolerance from config
# If amount_tolerance is omitted, falls back to default_amount_tolerance_percent
amount: -1500.00
# Uses default_amount_tolerance_percent: 0.02 from _config.yaml (±2%)

# Option 4: Range (e.g., variable utility bill)
amount_min: -50.00
amount_max: -200.00
```

**Note:** If you specify `amount_tolerance` in your schedule, it overrides the percentage default from config. The tolerance can be either a fixed amount (e.g., 10.00) or a percentage (e.g., 0.05 for ±5%), depending on how it's specified in your config.

### Recurrence Section

Defines when the transaction occurs:

```yaml
# Monthly on 15th
recurrence:
  frequency: MONTHLY
  day_of_month: 15
  start_date: 2024-01-15

# Bi-monthly (twice per month)
recurrence:
  frequency: BIMONTHLY
  days_of_month: [5, 20]
  start_date: 2024-01-05

# Weekly
recurrence:
  frequency: WEEKLY
  day_of_week: FRI
  start_date: 2024-01-05

# Bi-weekly (every 2 weeks)
recurrence:
  frequency: WEEKLY
  interval: 2
  day_of_week: FRI
  start_date: 2024-01-05

# Quarterly (every 3 months)
recurrence:
  frequency: INTERVAL
  interval_months: 3
  day_of_month: 10
  start_date: 2024-01-10

# Yearly
recurrence:
  frequency: YEARLY
  month: 9
  day_of_month: 15
  start_date: 2024-09-15
```

### Transaction Section

Defines how to enrich matched transactions:

```yaml
transaction:
  payee: Property Manager # Overrides payee from import
  narration: Monthly Rent # Overrides narration from import
  tags:
    - housing
  metadata:
    schedule_id: rent-payment # Recommended: track which schedule matched
    category: housing
    property: main-residence
  postings:
    - account: Assets:Bank:Checking
      amount: null # null = use imported amount
    - account: Expenses:Housing:Rent
      amount: null
```

### Complex Postings

For transactions with multiple splits or fixed amounts:

```yaml
transaction:
  payee: My Employer
  narration: Paycheck
  postings:
    - account: Assets:Bank:Checking
      amount: null # Use imported amount
    - account: Income:Salary:Gross
      amount: -3200.00 # Fixed amount
    - account: Expenses:Taxes:Federal
      amount: 450.00 # Fixed amount
    - account: Expenses:Taxes:State
      amount: 180.00
    - account: Assets:Retirement:401k
      amount: 320.00
```

### Missing Transaction Placeholders

When an expected transaction doesn't occur, beanschedule can create a placeholder:

```yaml
missing_transaction:
  create_placeholder: true # Enable placeholder creation
  flag: "!" # Placeholder flag
  narration_prefix: "[MISSING]" # Optional prefix
```

**Output example:**

```beancount
2024-01-20 ! "Safe Driver Insurance" "[MISSING] Auto Insurance Premium"
  schedule_id: "insurance-auto"
  Assets:Bank:Checking                    -125.00 USD
  Expenses:Insurance:Auto                  125.00 USD
```

## Skipping Occurrences

Mark specific dates as intentionally skipped (e.g., you paid early, took a break):

**Using the CLI:**

```bash
beanschedule skip rent-payment 2024-03-01 --reason "Paid early"
```

**Manual entry:**

```beancount
2024-03-01 * "Landlord" "[SKIPPED] Paid early"
  #skipped
  schedule_id: "rent-payment"
  schedule_skipped: "true"
  Assets:Bank:Checking
```

Skip markers are recognized by any of these methods:

- Flag `*` with `#skipped` tag (recommended - matches CLI generation)
- `schedule_skipped` metadata key
- Flag `S` (legacy/alternative)

Skip markers prevent placeholder creation for intentionally skipped dates.

## Examples

### Monthly Bill

```yaml
id: electric-bill
match:
  account: Assets:Bank:Checking
  payee_pattern: "Electric|Edison|Power Co"
  amount_min: -50.00
  amount_max: -200.00
  date_window_days: 5
recurrence:
  frequency: MONTHLY
  day_of_month: 15
  start_date: 2024-01-15
transaction:
  payee: Electric Company
  narration: Electric Bill
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Expenses:Utilities:Electric
      amount: null
```

### Biweekly Paycheck

```yaml
id: paycheck-main
match:
  account: Assets:Bank:Checking
  payee_pattern: "ACME CORP|MY EMPLOYER"
  amount: 3200.00
  amount_tolerance: 5.00
  date_window_days: 1
recurrence:
  frequency: WEEKLY
  interval: 2
  day_of_week: FRI
  start_date: 2024-01-05
transaction:
  payee: ACME Corp
  narration: Paycheck
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Income:Salary
      amount: -3200.00
```

### Quarterly Dividend

```yaml
id: dividend-vtsax
match:
  account: Assets:Investment:Vanguard
  payee_pattern: "Vanguard|VTSAX"
  amount_min: 100.00
  amount_max: 500.00
recurrence:
  frequency: INTERVAL
  interval_months: 3
  day_of_month: 15
  start_date: 2024-03-15
transaction:
  payee: Vanguard
  narration: VTSAX Dividend
  postings:
    - account: Assets:Investment:Vanguard
      amount: null
    - account: Income:Investment:Dividend
      amount: null
```

## Troubleshooting

### Transaction Not Matching

1. **Check payee pattern**: Does the imported payee match your regex?

   ```bash
   beanschedule list schedules/ -v
   ```

2. **Verify amount**: Is the imported amount within tolerance?

3. **Check date**: Is the transaction within the date window?

4. **Review scoring**: Enable debug logging:
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

### Placeholder Not Creating

1. **Check enabled**: Is `missing_transaction.create_placeholder: true`?

2. **Check forecast window**: Placeholders only generate within the forecast window (default 3 months ahead)

3. **Check skips**: If a skip marker exists for that date, no placeholder will be created

## See Also

- [PLUGIN.md](PLUGIN.md) - Forecast plugin configuration
- [ADVANCED.md](ADVANCED.md) - Loan amortization, pattern detection
- [CLI.md](CLI.md) - Command-line tools
