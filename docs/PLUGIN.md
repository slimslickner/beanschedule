# Forecast Plugin

The forecast plugin generates future scheduled transactions for budgeting, visualization, and cash flow planning. Transactions appear with the `#` (forecast) flag.

## Quick Start

Add to your main ledger file:

```beancount
plugin "beanschedule.plugins.schedules"
```

The plugin will automatically:

1. Discover your schedules (looks for `schedules.yaml` or `schedules/` directory)
2. Generate forecast transactions starting from tomorrow for the next 3 months (default)
3. Include all metadata and tags from your schedule definitions

## Configuration

### Via Plugin Declaration

In your main ledger:

```beancount
# Default: 3 months ahead
plugin "beanschedule.plugins.schedules"

# Custom forecast window
plugin "beanschedule.plugins.schedules" "{'forecast_months': 6}"

# Multiple options
plugin "beanschedule.plugins.schedules" "{
  'forecast_months': 12,
  'min_forecast_date': '2026-01-01'
}"
```

JSON syntax also works:

```beancount
plugin "beanschedule.plugins.schedules" "{\"forecast_months\": 12}"
```

#### Shadow Accounts (Balance Assertion Safety)

By default, forecast transactions post to the real accounts defined in your schedule (e.g. `Assets:Bank:Checking`). If you have balance assertions on those accounts, the forecast transactions can cause them to fail.

Use shadow accounts to redirect the matched account posting to plugin-only equity accounts instead. Only the posting matching `match.account` is redirected — expense and income postings are left intact so category-level forecasting remains accurate.

**Upcoming transactions** (tomorrow and beyond):

```beancount
plugin "beanschedule.plugins.schedules" "{
  'forecast_months': 3,
  'shadow_upcoming_account': 'Equity:Schedules:Upcoming'
}"
```

**Overdue transactions** (past-due occurrences not yet in the ledger):

By default, the plugin only generates transactions from tomorrow forward. When `shadow_overdue_account` is configured, the plugin also generates overdue transactions for every past occurrence since the schedule's own `start_date` that has no matching real transaction in the ledger — no fixed lookback window, so nothing is missed:

```beancount
plugin "beanschedule.plugins.schedules" "{
  'forecast_months': 3,
  'shadow_upcoming_account': 'Equity:Schedules:Upcoming',
  'shadow_overdue_account': 'Equity:Schedules:Overdue'
}"
```

With both configured, a rent schedule that missed last month would generate:

```beancount
2026-01-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  Expenses:Housing:Rent              1500.00 USD
  Equity:Schedules:Overdue          -1500.00 USD  ; was Assets:Bank:Checking

2026-02-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  Expenses:Housing:Rent              1500.00 USD
  Equity:Schedules:Upcoming         -1500.00 USD  ; was Assets:Bank:Checking
```

This means:
- `Assets:Bank:Checking` is never touched by any forecast — balance assertions always pass
- `Expenses:Housing:Rent` accumulates normally — budgeting queries remain accurate
- `Equity:Schedules:Overdue` shows what is past-due and unaccounted for in the ledger
- `Equity:Schedules:Upcoming` shows what is expected in the coming months
- Dates that already have a real imported transaction (matched by `schedule_id`) are automatically excluded from both

### Via Config File

In `schedules/_config.yaml`:

```yaml
# How many months forward to forecast (default: 3)
forecast_months: 6

# Override the start date for forecasting (optional)
# Useful when working with historical ledger data
# Takes minimum of (tomorrow, min_forecast_date)
min_forecast_date: 2026-01-01
```

Config file values are used as defaults, but plugin arguments override them.

**Note:** The `include_past_dates` setting only affects placeholder generation in the hook (during `beangulp import`), not forecast generation in the plugin. Forecasts are always from tomorrow forward.

## Configuration Parameters

| Parameter                 | Type    | Default | Description                                                                                                      |
| ------------------------- | ------- | ------- | ---------------------------------------------------------------------------------------------------------------- |
| `forecast_months`         | integer | 3       | Months ahead from tomorrow to generate forecasts                                                                 |
| `min_forecast_date`       | date    | null    | Earliest date to consider for forecasts (min selector)                                                           |
| `shadow_upcoming_account` | string  | null    | If set, redirects the `match.account` posting on future transactions to this account                             |
| `shadow_overdue_account`  | string  | null    | If set, enables overdue generation: all past-due occurrences since the schedule's `start_date` that have no matching real transaction are generated and redirected to this account |

## Behavior

The plugin:

1. **Reads schedules** - Auto-discovers YAML schedule files
2. **Generates dates** - Calculates expected occurrence dates from tomorrow forward
3. **Creates transactions** - Generates forecast transactions (`#` flag) with:
   - All postings from your schedule
   - All metadata and tags
   - `schedule_id` metadata for tracking
4. **Respects skips** - Excludes dates marked with skip markers
5. **Excludes placeholders** - Does not duplicate placeholder generation

### Forecasts vs Placeholders

**Forecasts** (`#` flag) are generated by the **plugin** during Beancount parsing. They show expected future transactions for budgeting and cash flow planning, starting from tomorrow.

**Placeholders** (`!` flag) are generated by the **hook** during `beangulp import`. They show missing/unmatched scheduled transactions. The `include_past_dates` setting controls whether they include past missed dates.

These are separate features: you can have forecasts without placeholders, or placeholders without forecasts.

## Example Output

Given this schedule:

```yaml
id: rent-payment
match:
  account: Assets:Bank:Checking
  payee_pattern: "Landlord"
  amount: -1500.00
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
  postings:
    - account: Expenses:Housing:Rent
      amount: 1500.00
    - account: Assets:Bank:Checking
      amount: -1500.00
```

The plugin generates:

```beancount
2026-02-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  housing:
  Expenses:Housing:Rent                    1500.00 USD
  Assets:Bank:Checking                   -1500.00 USD

2026-03-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  housing:
  Expenses:Housing:Rent                    1500.00 USD
  Assets:Bank:Checking                   -1500.00 USD
```

## Use Cases

### Budgeting

See projected cash flow for upcoming months:

```bash
bean-check ledger.beancount | grep "^#"
```

Or use Fava to visualize:

```bash
fava ledger.beancount
# Navigate to Charts → Cash Flow
```

### Planning

Identify upcoming bills and plan for them:

```bash
beanschedule show rent-payment --count 6
# Shows next 6 occurrences
```

### Scenario Testing

Temporarily modify `forecast_months` to test different scenarios:

```beancount
plugin "beanschedule.plugins.schedules" "{'forecast_months': 24}"
```

Run analysis, then restore to normal.

## Integration with Fava

Forecast transactions work seamlessly with [Fava](https://github.com/beancount/fava):

1. **Cash Flow Charts** - See projected income and expenses
2. **Account Totals** - View forecast balance projections
3. **Budget Comparison** - Track actual vs. forecasted spending

Note: Forecast transactions appear in most Fava views and can be filtered out if needed.

## Disabled Schedules

Schedules with `enabled: false` are not included in forecast generation:

```yaml
id: canceled-subscription
enabled: false
# ... rest of schedule ...
```

## Conflicting Entries

If you manually create a transaction on the same date as a forecast, both will appear. Beancount doesn't de-duplicate based on content, so use different flags or manually manage forecast entries if needed.

## Troubleshooting

### Plugin Not Loading

1. **Check path**: Verify `schedules.yaml` or `schedules/` exists
2. **Check syntax**: Run `beanschedule validate schedules/`
3. **Check Beancount version**: Requires beancount >= 3.2.0

### Wrong Forecast Window

1. **Verify config**: Check both plugin args and `schedules/_config.yaml`
2. **Plugin args override** config file values
3. **Use `--verbose`**: `bean-check --verbose ledger.beancount` for debug output

### Too Many/Few Transactions

Adjust `forecast_months`:

```beancount
# Show fewer
plugin "beanschedule.plugins.schedules" "{'forecast_months': 1}"

# Show more
plugin "beanschedule.plugins.schedules" "{'forecast_months': 24}"
```

### Forecast Not Including Skipped Dates

Skip markers are automatically excluded. Verify skip marker format:

```beancount
2026-02-15 * "Landlord" "[SKIPPED] Reason"
  #skipped
  schedule_id: "rent-payment"
  schedule_skipped: "true"
  Assets:Bank:Checking
```

## Advanced: Loan Amortization Forecasts

Forecast transactions also work with amortized loans. The plugin will generate principal/interest splits automatically:

```yaml
id: mortgage-payment
# ... match, recurrence, etc.
amortization:
  principal: 300000.00
  annual_rate: 0.0675
  term_months: 360
  start_date: 2024-01-01
transaction:
  postings:
    - account: Assets:Bank:Checking
      amount: null
      role: payment
    - account: Liabilities:Mortgage
      amount: null
      role: principal
    - account: Expenses:Housing:Interest
      amount: null
      role: interest
```

Each forecasted month will have the correct principal/interest split calculated.

## See Also

- [SCHEDULES.md](SCHEDULES.md) - Schedule definition reference
- [ADVANCED.md](ADVANCED.md) - Loan amortization details
- [CLI.md](CLI.md) - Command-line tools
