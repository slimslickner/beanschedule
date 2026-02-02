# Beanschedule

[![PyPI version](https://badge.fury.io/py/beanschedule.svg)](https://pypi.org/project/beanschedule/)
[![Python Support](https://img.shields.io/pypi/pyversions/beanschedule.svg)](https://pypi.org/project/beanschedule/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/yourusername/beanschedule/workflows/tests/badge.svg)](https://github.com/yourusername/beanschedule/actions)

**Scheduled transaction framework for Beancount** - automatically match, enrich, and track recurring transactions.

Beanschedule is a [beangulp](https://github.com/beancount/beangulp) hook that intelligently matches imported transactions to your defined schedule of recurring transactions (rent, paycheck, subscriptions, etc.) and enriches them with complete posting information, metadata, and tags.

## Features

- **Pattern Discovery** - Auto-detect recurring transaction patterns from your ledger
- **Automatic Matching** - Fuzzy matching with weighted scoring (payee 40%, amount 40%, date 20%)
- **Transaction Enrichment** - Add metadata, tags, and complete posting splits to imported transactions
- **Forecast Generation** - Generate future transactions for budgeting and visualization (Beancount plugin)
- **Missing Transaction Detection** - Create placeholder transactions for expected payments that didn't occur
- **Flexible Recurrence Patterns** - Monthly, bi-monthly, weekly, bi-weekly, yearly, and custom intervals
- **Smart Amount Matching** - Fixed amounts with tolerance, range matching, or null amounts
- **Beangulp Integration** - Drop-in hook for your existing import workflow
- **CLI Tools** - Validate, test, debug, and auto-discover schedules with built-in commands
- **Preserves ML Training Data** - Compatible with smart_importer for machine learning predictions

## Quick Start

### Installation

```bash
pip install beanschedule
```

### Getting Started (Recommended)

Start by auto-discovering recurring patterns from your existing ledger:

```bash
# Step 1: Detect recurring patterns
beanschedule detect ledger.beancount --output-dir schedules/

# Step 2: Review and customize detected patterns
beanschedule list schedules/

# Step 3: Integrate with Beangulp (see Setup section below)
```

This creates a `schedules/` directory with auto-generated schedule files. If you prefer manual setup instead, see the [Manual Setup](#manual-setup) section.

## How It Works

1. **Load Schedules** - Reads schedule definitions from YAML files
2. **Extract Date Range** - Determines date range from imported transactions
3. **Generate Expected Dates** - Calculates when each schedule should occur
4. **Match Transactions** - Scores imported transactions against expected occurrences using weighted scoring
5. **Enrich Matches** - Adds metadata, tags, and posting templates to matched transactions
6. **Create Placeholders** - Generates placeholder transactions for missing expected payments

### Matching Algorithm

Beanschedule uses a weighted scoring system:

- **Payee match**: 40% (supports regex patterns and fuzzy matching)
- **Amount match**: 40% (exact, tolerance, or range-based)
- **Date match**: 20% (uses day difference with linear decay)

Default threshold: 0.80 (configurable)

## Understanding Schedules

### Recurrence Types

Beanschedule supports multiple recurrence patterns:

### Monthly

```yaml
recurrence:
  frequency: MONTHLY
  day_of_month: 5
  start_date: 2024-01-01
```

### Bi-monthly (twice per month)

```yaml
recurrence:
  frequency: BIMONTHLY
  days_of_month: [5, 20]
  start_date: 2024-01-01
```

### Bi-weekly (every 2 weeks)

```yaml
recurrence:
  frequency: WEEKLY
  interval: 2
  day_of_week: FRI
  start_date: 2024-01-05
```

### Quarterly (every 3 months)

```yaml
recurrence:
  frequency: INTERVAL
  interval_months: 3
  day_of_month: 10
  start_date: 2024-01-10
```

### Yearly

```yaml
recurrence:
  frequency: YEARLY
  month: 9
  day_of_month: 15
  start_date: 2024-09-15
```

## Manual Setup

If you prefer to create schedules manually instead of auto-discovering them:

### Step 1: Create Your First Schedule

Create a `schedules/` directory with a `_config.yaml` and your first schedule:

```bash
mkdir schedules
```

Create `schedules/_config.yaml`:

```yaml
fuzzy_match_threshold: 0.80
default_date_window_days: 3
default_amount_tolerance_percent: 0.02
placeholder_flag: '!'
```

Create `schedules/rent.yaml`:

```yaml
id: rent-payment
enabled: true
match:
  account: Assets:Bank:Checking
  payee_pattern: "Property Manager|Landlord"
  amount: -1500.00
  amount_tolerance: 0.00
  date_window_days: 2
recurrence:
  frequency: MONTHLY
  day_of_month: 1
  start_date: 2024-01-01
transaction:
  payee: Property Manager
  narration: Monthly Rent
  tags: []
  metadata:
    schedule_id: rent-payment
  postings:
    - account: Assets:Bank:Checking
      amount: null  # Use imported amount
    - account: Expenses:Housing:Rent
      amount: null
missing_transaction:
  create_placeholder: true
  flag: '!'
  narration_prefix: '[MISSING]'
```

### Step 2: Integrate with Beangulp

Add to your `importers/config.py`:

```python
from beanschedule import schedule_hook

# ... your importer configuration ...

HOOKS = [schedule_hook]
```

### Step 3: Run Your Imports

```bash
bean-extract importers/config.py documents/ > output.beancount
```

Matched transactions will be enriched with complete posting information and metadata. Missing expected transactions will appear with the `!` flag.

## Example Output

**Before** (imported from bank):

```beancount
2024-01-01 * "PROPERTY MGR" ""
  Assets:Bank:Checking                   -1500.00 USD
```

**After** (matched and enriched by beanschedule):

```beancount
2024-01-01 * "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  schedule_matched_date: 2024-01-01
  schedule_confidence: 0.92
  Assets:Bank:Checking                   -1500.00 USD
  Expenses:Housing:Rent                   1500.00 USD
```

## Forecast Transactions

In addition to matching imported transactions, beanschedule can generate **forecast transactions** for budgeting and visualization. The forecast plugin reads your YAML schedules and generates future transactions with the `#` flag.

### Using the Forecast Plugin

Add the plugin to your main ledger file:

```beancount
plugin "beanschedule.plugins.schedules"
```

Or specify a custom schedule file path:

```beancount
plugin "beanschedule.plugins.schedules" "path/to/schedules.yaml"
```

### What It Does

The plugin:

1. Reads your YAML schedules (auto-discovers `schedules.yaml` or `schedules/` directory)
2. Generates forecast transactions for the next 12 months
3. Returns them with the `#` flag (forecast flag)
4. Includes all metadata and tags from your schedule definitions

### Example Forecast Output

```beancount
2024-02-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  category: "housing"
  rent:
  recurring:
  Expenses:Housing:Rent                   1500.00 USD
  Assets:Bank:Checking                   -1500.00 USD

2024-03-01 # "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  category: "housing"
  rent:
  recurring:
  Expenses:Housing:Rent                   1500.00 USD
  Assets:Bank:Checking                   -1500.00 USD
```

### Visualization

Forecast transactions integrate seamlessly with Beancount visualization tools like [Fava](https://github.com/beancount/fava), allowing you to:

- See projected cash flow for upcoming months
- Visualize future expenses by category
- Plan for seasonal variations in spending
- Track expected vs. actual spending

**Note**: Forecast transactions are generated dynamically when you load your ledger with `bean-check` or Fava. They don't need to be manually updated - just modify your YAML schedules and reload.

## Auto-Discovering Patterns

### How Pattern Detection Works

Beanschedule can automatically analyze your ledger to find recurring transaction patterns:

```bash
# Detect all recurring patterns with default settings (60% confidence minimum)
beanschedule detect ledger.beancount

# Detect patterns with higher confidence threshold
beanschedule detect ledger.beancount --confidence 0.80

# Generate YAML schedule files for detected patterns
beanschedule detect ledger.beancount --output-dir detected-schedules/

# Get results in JSON format for processing
beanschedule detect ledger.beancount --format json
```

**Example Output:**

```
Detected 15 recurring patterns:

Confidence  Frequency  Payee                      Account                     Amount  Count
──────────────────────────────────────────────────────────────────────────────────────────
99%         Monthly    BANK FEES                  Assets:US:BofA:Checking       4.00    36
99%         Monthly    EDISON POWER               Assets:US:BofA:Checking      65.00    35
98%         Monthly    RiverBank Properties       Assets:US:BofA:Checking    2400.00    35
98%         Quarterly  Chase:Slate                Liabilities:US:Chase:Slate   812.10     3

To manually create schedules for detected patterns, use `beanschedule create`:
Examples for top patterns:

  99% confidence - BANK FEES
    beanschedule create --ledger ledger.beancount --date 2013-01-04

  99% confidence - EDISON POWER
    beanschedule create --ledger ledger.beancount --date 2013-01-09
```

### Detection Algorithm

1. **Grouping** - Groups transactions by account, payee (fuzzy match 0.85), and amount tolerance (±5%)
2. **Gap Analysis** - Analyzes date gaps between transactions (median, mean, standard deviation)
3. **Frequency Detection** - Maps gaps to frequency types (weekly, monthly, quarterly, yearly)
4. **Confidence Scoring** - Scores patterns based on:
   - Coverage (50%) - ratio of actual to expected occurrences
   - Regularity (30%) - consistency of gaps (inverse of variance)
   - Sample Size (20%) - more transactions = higher confidence

### Detection Options

- `--confidence` - Minimum confidence threshold (0.0-1.0, default: 0.60)
- `--fuzzy-threshold` - Payee fuzzy match threshold (0.0-1.0, default: 0.85)
- `--amount-tolerance` - Amount variance tolerance as % (default: 0.05 = ±5%)
- `--min-occurrences` - Minimum transactions to consider a pattern (default: 3)
- `--output-dir` - Save detected patterns as YAML schedule files
- `--format` - Output format: `table` or `json`

## Advanced Features

### Complex Posting Splits

Define detailed posting templates with fixed amounts:

```yaml
postings:
  - account: Assets:Bank:Checking
    amount: null  # Use imported amount
  - account: Income:Salary:Gross
    amount: -3200.00
  - account: Expenses:Taxes:Federal
    amount: 450.00
  - account: Expenses:Taxes:State
    amount: 180.00
  - account: Assets:Retirement:401k
    amount: 320.00
```

### Range-Based Amount Matching

For variable bills like utilities:

```yaml
match:
  account: Assets:Bank:Checking
  payee_pattern: "Electric Company"
  amount_min: -50.00
  amount_max: -200.00
```

### Metadata and Tags

Add custom metadata and tags for organization:

```yaml
transaction:
  payee: Property Manager
  narration: Monthly Rent
  tags:
    - property-main-home
  metadata:
    schedule_id: rent-payment
    property: main-residence
    lease_term: 12-months
```

### Missing Transaction Placeholders

When an expected transaction doesn't occur, beanschedule creates a placeholder:

```beancount
2024-01-20 ! "Safe Driver Insurance" "[MISSING] Auto Insurance Premium"
  schedule_id: "insurance-auto"
  Assets:Bank:Checking                    -125.00 USD
  Expenses:Insurance:Auto                  125.00 USD
```

### Zerosum Transfers (Credit Card Payments)

When using the [zerosum plugin](https://github.com/beancount/beangulp#zerosum) for balancing transfers, **schedule only the source transaction** (typically the checking account withdrawal). The zerosum plugin automatically creates the paired transaction, so you don't need separate schedules for each side.

**Example: Monthly credit card payment**

Create a single schedule for the checking account outflow:

```yaml
id: cc-payment-visa
enabled: true
match:
  account: Assets:Bank:Checking
  payee_pattern: "VISA|AUTOPAY"
  amount_min: -3000.00
  amount_max: -100.00
  date_window_days: 3
recurrence:
  frequency: MONTHLY
  day_of_month: 25
  start_date: 2024-01-25
transaction:
  payee: Visa Credit Card
  narration: Credit Card Payment
  metadata:
    schedule_id: cc-payment-visa
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Liabilities:CreditCard:Visa
      amount: null
```

The zerosum plugin will create both postings automatically (Assets:Checking → Equity:ZeroSum:Transfers and Liabilities:CreditCard → Equity:ZeroSum:Transfers). You get the benefits of scheduled transaction tracking without maintaining duplicate schedule definitions.

## CLI Commands

Beanschedule provides command-line tools for managing and debugging schedules:

```bash
# Detect recurring patterns in your ledger (auto-discovery)
beanschedule detect ledger.beancount [--confidence 0.75] [--output-dir dir/] [--format json|table]

# Validate schedule files for syntax and configuration errors
beanschedule validate schedules/
beanschedule validate schedules.yaml

# List all schedules with details
beanschedule list schedules/ [--format table|json] [--enabled-only]

# Show detailed information about a specific schedule
beanschedule show rent-payment [--count N]

# Generate expected occurrence dates for a schedule
beanschedule generate rent-payment 2024-01-01 2024-12-31

# Create a schedule interactively from a ledger transaction
beanschedule create --ledger ledger.beancount --date 2024-01-15

# Initialize a new schedules directory with examples
beanschedule init [my-schedules/]
```

### Shell Tab Completion

Enable tab completion for schedule IDs to improve CLI usability:

**Bash (4.4+)**:

```bash
eval "$(_BEANSCHEDULE_COMPLETE=bash_source beanschedule)"
# Add to ~/.bashrc for persistence
```

**Zsh**:

```bash
eval "$(_BEANSCHEDULE_COMPLETE=zsh_source beanschedule)"
# Add to ~/.zshrc for persistence
```

**Fish**:

```bash
_BEANSCHEDULE_COMPLETE=fish_source beanschedule | source
# Add to ~/.config/fish/completions/ for persistence
```

Once enabled, you can tab-complete schedule IDs:

```bash
beanschedule show r<TAB>      # → rent-payment
beanschedule generate m<TAB>  # → mortgage-payment
```

## Examples & Documentation

See the [examples/](examples/) directory for:

- 10 example schedule files covering different scenarios
- Sample `example.beancount` ledger
- Detailed README with usage tips

Additional documentation:

- **Installation Guide** - [docs/installation.md](docs/installation.md)
- **Quick Start** - [docs/quickstart.md](docs/quickstart.md)
- **User Guide** - [docs/user-guide.md](docs/user-guide.md)
- **Schedule Format Reference** - [docs/schedule-format.md](docs/schedule-format.md)
- **Recurrence Patterns** - [docs/recurrence-patterns.md](docs/recurrence-patterns.md)
- **Troubleshooting** - [docs/troubleshooting.md](docs/troubleshooting.md)

## Requirements

- Python 3.9+
- beancount >= 3.2.0
- beangulp >= 0.2.0
- pyyaml >= 6.0
- python-dateutil >= 2.8.0
- pydantic >= 2.0.0
- click >= 8.0.0

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

Built for the [Beancount](https://github.com/beancount/beancount) plain text accounting ecosystem.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/beanschedule/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/beanschedule/discussions)
- **Email**: Contact the maintainers

---

Made with ❤️ for the plain text accounting community
