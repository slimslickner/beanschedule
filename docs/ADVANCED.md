# Advanced Features

This document covers advanced beanschedule capabilities: loan amortization, complex postings, and pattern detection.

## Loan Amortization

Beanschedule can automatically split loan payments into principal and interest. Two modes are available:

### Static Mode (Recommended for Standard Loans)

Use static mode when you know the original loan terms and haven't made extra payments or refinanced:

```yaml
id: mortgage-payment
enabled: true

match:
  account: Assets:Bank:Checking
  payee_pattern: "MORTGAGE|BANK LOAN"
  amount: -2150.00
  date_window_days: 3

recurrence:
  frequency: MONTHLY
  day_of_month: 1
  start_date: 2024-01-01

amortization:
  principal: 300000.00 # Original loan amount
  annual_rate: 0.0675 # 6.75% annual interest
  term_months: 360 # 30-year mortgage
  start_date: 2024-01-01 # When payments began
  payment_day_of_month: 1 # Optional: payment day if different from recurrence day
  extra_principal: 200.00 # Optional: extra principal each month

transaction:
  payee: Mortgage Lender
  narration: Monthly Mortgage Payment
  postings:
    - account: Assets:Bank:Checking
      amount: null
      role: payment # Mark as payment amount
    - account: Liabilities:Mortgage
      amount: null
      role: principal # Interest is calculated, principal is remainder
    - account: Expenses:Housing:Interest
      amount: null
      role: interest
```

**How it works:**

1. Calculates fixed monthly payment: ~$2,008.75
2. For each payment, calculates:
   - Current balance using amortization formula
   - Interest for this month
   - Principal (payment - interest)
   - Adjusts for `extra_principal` if configured
3. Updates balance and repeats

**Optional fields:**

- `payment_day_of_month` - Override the day of month for payment date generation. Useful when the schedule's recurrence day and the actual payment day differ (e.g., recurrence on day 1 but payments on day 3).
- `extra_principal` - Additional principal paid toward the loan each month, reducing payoff timeline and total interest. Use this to model accelerated payoff scenarios.

The payment is derived from the loan terms. If actual payment differs significantly, use stateful mode instead.

### Stateful Mode (Recommended for Real-World Loans)

Use stateful mode when:

- You've made extra payments
- You refinanced
- You took a payment break
- The ledger represents actual payment history

```yaml
id: student-loan
enabled: true

match:
  account: Assets:Bank:Checking
  payee_pattern: "STUDENT LOAN|LOAN SERVICER"
  amount_min: -200.00
  amount_max: -250.00
  date_window_days: 3

recurrence:
  frequency: MONTHLY
  day_of_month: 15
  start_date: 2024-01-15

amortization:
  balance_from_ledger: true # Read current balance from ledger
  annual_rate: 0.06 # 6% annual interest
  monthly_payment: 200.00 # Fixed monthly payment
  compounding: DAILY # DAILY or MONTHLY
  extra_principal: 50.00 # Optional: extra principal each month

transaction:
  payee: Student Loan Servicer
  narration: Student Loan Payment
  postings:
    - account: Assets:Bank:Checking
      amount: null
      role: payment
    - account: Liabilities:StudentLoan
      amount: null
      role: principal
    - account: Expenses:Education:Interest
      amount: null
      role: interest
```

**How it works:**

1. Reads current balance from ledger (cleared transactions only)
2. Calculates interest based on current balance and annual rate
3. Splits payment: interest + principal + extra principal
4. Forecast plugin uses this calculation for each forecasted month

**Important:** Stateful mode only counts cleared (`*`) transactions when computing balance. Forecast (`#`) and placeholder (`!`) entries are excluded so the plugin doesn't double-count its own predictions.

### Compounding Modes

**DAILY compounding** (default):

- Used for mortgages and most loans
- Interest calculated daily, compounded
- Most accurate for real mortgages

**MONTHLY compounding**:

- Used for some student loans
- Interest compounded once per month

Example:

```yaml
amortization:
  balance_from_ledger: true
  annual_rate: 0.06
  monthly_payment: 200.00
  compounding: MONTHLY # Monthly instead of daily
```

### Amortization + Forecast Plugin

The forecast plugin automatically applies amortization when generating future transactions:

```beancount
# With amortization configuration, forecasts include principal/interest splits
plugin "beanschedule.plugins.schedules"
```

Each forecasted month:

```beancount
2026-02-01 # "Mortgage Lender" "Monthly Mortgage Payment"
  Assets:Bank:Checking                   -2150.00 USD
  Liabilities:Mortgage                     400.00 USD  # Principal
  Expenses:Housing:Interest               1750.00 USD  # Interest
```

## Complex Posting Splits

For transactions with multiple fixed amounts or deductions:

### Paycheck with Deductions

```yaml
id: paycheck-main
match:
  account: Assets:Bank:Checking
  payee_pattern: "ACME CORP|MY EMPLOYER"
  amount: 3200.00
  amount_tolerance: 5.00

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
      amount: null # Use imported amount (net)
    - account: Income:Salary:Gross
      amount: -3200.00 # Gross salary
    - account: Expenses:Taxes:Federal
      amount: 450.00
    - account: Expenses:Taxes:State
      amount: 180.00
    - account: Expenses:Taxes:FICA
      amount: 250.00
    - account: Assets:Retirement:401k
      amount: 320.00
```

In this example:

- Imported amount is net: $2,000 (3200 - 450 - 180 - 250 - 320)
- All fixed deductions are specified
- Beancount balances to zero

### Credit Card with Multiple Merchants (Zerosum)

When using [beangulp's zerosum plugin](https://github.com/beancount/beangulp#zerosum), only define the source account side:

```yaml
id: cc-payment-visa
match:
  account: Assets:Bank:Checking # Source side only
  payee_pattern: "VISA|AUTOPAY"
  amount_min: -3000.00
  amount_max: -100.00

recurrence:
  frequency: MONTHLY
  day_of_month: 25
  start_date: 2024-01-25

transaction:
  payee: Visa Credit Card
  narration: Credit Card Payment
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Liabilities:CreditCard:Visa
      amount: null
```

Zerosum automatically creates the paired transfer side, so you don't need separate schedules.

### Multi-Currency Transactions

```yaml
id: international-transfer
match:
  account: Assets:Bank:USD
  payee_pattern: "WISE|TRANSFER"
  amount: -500.00

recurrence:
  frequency: MONTHLY
  day_of_month: 10
  start_date: 2024-01-10

transaction:
  payee: WISE Transfer
  narration: EUR Transfer
  postings:
    - account: Assets:Bank:USD
      amount: null # -500 USD
    - account: Assets:Bank:EUR
      amount: 500.00 # Fixed in EUR (conversion handled)
      currency: EUR
```

## Pattern Auto-Detection

### How Detection Works

Beanschedule analyzes your ledger to identify recurring patterns:

```bash
beanschedule detect ledger.beancount
```

**Algorithm:**

1. **Grouping** - Groups transactions by:
   - Account (exact match)
   - Payee (fuzzy match 0.85 threshold)
   - Amount (within tolerance)

2. **Gap Analysis** - For each group, analyzes date gaps:
   - Calculates median, mean, standard deviation
   - Identifies outliers

3. **Frequency Detection** - Maps gaps to patterns:
   - Weekly (7 days)
   - Biweekly (14 days)
   - Monthly (~30 days)
   - Quarterly (~90 days)
   - Yearly (~365 days)

4. **Confidence Scoring** - Scores based on:
   - **Coverage** (50%) - Ratio of actual to expected occurrences
   - **Regularity** (30%) - Consistency of gaps (inverse of variance)
   - **Sample Size** (20%) - More transactions = higher confidence

**Example scoring:**

```
Pattern: PROPERTY MGR payments
Coverage:    35 actual / 36 expected = 97% → score 0.50 × 0.97 = 0.49
Regularity:  Variance 0.5 days (very consistent) → score 0.30 × 1.00 = 0.30
Sample Size: 35 transactions → score 0.20 × 1.00 = 0.20
Total: 0.49 + 0.30 + 0.20 = 0.99 (99% confidence)
```

### Detection Options

```bash
beanschedule detect ledger.beancount \
  --confidence 0.75 \           # Minimum confidence threshold
  --fuzzy-threshold 0.85 \      # Payee fuzzy match threshold
  --amount-tolerance 0.05 \     # Amount variance as % (±5%)
  --min-occurrences 3 \         # Minimum transactions to consider
  --output-dir detected/ \      # Save as YAML files
  --format json                 # Output format
```

### Output Formats

**Table format (default):**

```
Confidence  Frequency  Payee              Account                 Amount
─────────────────────────────────────────────────────────────────────────
99%         Monthly    PROPERTY MGR       Assets:Bank:Checking    -2400.00
98%         Monthly    EDISON POWER       Assets:Bank:Checking     -65.00
95%         Biweekly   ACME CORPORATION   Assets:Bank:Checking    3200.00
```

**JSON format:**

```bash
beanschedule detect ledger.beancount --format json
```

```json
{
  "patterns": [
    {
      "id": "property-mgr",
      "payee": "PROPERTY MGR",
      "account": "Assets:Bank:Checking",
      "amount": -2400.0,
      "frequency": "MONTHLY",
      "confidence": 0.99,
      "occurrences": 35,
      "expected": 36
    }
  ]
}
```

### Creating Schedules from Detected Patterns

Option 1: Save as YAML files:

```bash
beanschedule detect ledger.beancount --output-dir detected/
beanschedule list detected/
cp detected/rent.yaml schedules/
cp detected/paycheck.yaml schedules/
```

Option 2: Create interactively:

```bash
beanschedule create --ledger ledger.beancount --date 2024-01-15
```

## Advanced Matching

### Regex Payee Patterns

Beanschedule uses standard Python regex with fuzzy matching (0.85 threshold):

```yaml
match:
  payee_pattern: "^PAYMENT"              # Starts with PAYMENT
  payee_pattern: "ELECTRICITY$"          # Ends with ELECTRICITY
  payee_pattern: "(?i)amazon"            # Case-insensitive
  payee_pattern: "BANK.{0,3}FEES"        # BANK FEES, BANKFEES, etc.
  payee_pattern: "AWS|AMAZON|AMZN"       # Multiple matches (OR)
```

Plus fuzzy matching:

```yaml
match:
  payee_pattern: "Amazon" # Matches AMZN, Amazin, etc.
```

### Amount Matching Strategies

**Exact with tolerance:**

```yaml
match:
  amount: -1500.00
  amount_tolerance: 10.00 # ±$10
```

**Range (for variable bills):**

```yaml
match:
  amount_min: -50.00
  amount_max: -200.00 # Electric bill varies $50-$200
```

**Percentage tolerance:**

```yaml
match:
  amount: -500.00
  amount_tolerance: 0.05 # ±5%
```

## Configuration Best Practices

### Tuning Thresholds

If too many false matches:

- Increase `fuzzy_match_threshold` (e.g., 0.85 → 0.90)
- Tighten `amount_tolerance`
- Reduce `date_window_days`

If not matching enough:

- Decrease `fuzzy_match_threshold`
- Widen `amount_tolerance`
- Increase `date_window_days`

### Testing Changes

After modifying config:

```bash
# Validate syntax
beanschedule validate schedules/

# Show impact
beanschedule show rent-payment --count 6

# Test with actual import (use --dry-run if available)
bean-extract importers/config.py documents/ | head -50
```

## See Also

- [SCHEDULES.md](SCHEDULES.md) - Schedule definitions
- [PLUGIN.md](PLUGIN.md) - Forecast plugin
- [CLI.md](CLI.md) - Command-line tools
- [CLAUDE.md](../CLAUDE.md) - Architecture notes
