# Beanschedule

[![PyPI version](https://badge.fury.io/py/beanschedule.svg)](https://pypi.org/project/beanschedule/)
[![Python Support](https://img.shields.io/pypi/pyversions/beanschedule.svg)](https://pypi.org/project/beanschedule/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/yourusername/beanschedule/workflows/tests/badge.svg)](https://github.com/yourusername/beanschedule/actions)

**Scheduled transaction framework for Beancount** - automatically match, enrich, and track recurring transactions.

Beanschedule is a [beangulp](https://github.com/beancount/beangulp) hook that intelligently matches imported transactions to your defined schedule of recurring transactions (rent, paycheck, subscriptions, etc.) and enriches them with complete posting information, metadata, and tags.

## Features

- **Automatic Matching** - Fuzzy matching with weighted scoring (payee 40%, amount 40%, date 20%)
- **Transaction Enrichment** - Add metadata, tags, and complete posting splits to imported transactions
- **Missing Transaction Detection** - Create placeholder transactions for expected payments that didn't occur
- **Flexible Recurrence Patterns** - Monthly, bi-monthly, weekly, bi-weekly, yearly, and custom intervals
- **Smart Amount Matching** - Fixed amounts with tolerance, range matching, or null amounts
- **Beangulp Integration** - Drop-in hook for your existing import workflow
- **CLI Tools** - Validate, test, and debug your schedules with built-in commands
- **Preserves ML Training Data** - Compatible with smart_importer for machine learning predictions

## Quick Start

### Installation

```bash
pip install beanschedule
```

### 1. Create Your First Schedule

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

### 2. Integrate with Beangulp

Add to your `importers/config.py`:

```python
from beanschedule import schedule_hook

# ... your importer configuration ...

HOOKS = [schedule_hook]
```

### 3. Run Your Imports

```bash
bean-extract importers/config.py documents/ > output.beancount
```

Matched transactions will be enriched with complete posting information and metadata. Missing expected transactions will appear with the `!` flag.

## Before and After Example

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

## Recurrence Types

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

## CLI Tools

Beanschedule includes a command-line interface for managing and testing schedules:

```bash
# Validate schedule files
beanschedule validate schedules/

# List all schedules
beanschedule list schedules/

# Generate expected occurrence dates
beanschedule generate mortgage-payment 2024-01-01 2024-12-31

# Initialize example schedules
beanschedule init my-schedules/

# Migrate single YAML to directory structure
beanschedule migrate schedules.yaml schedules/
```

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

## Examples

See the [examples/](examples/) directory for:

- 10 example schedule files covering different scenarios
- Sample `example.beancount` ledger
- Detailed README with usage tips

## Documentation

- **Installation Guide** - [docs/installation.md](docs/installation.md)
- **Quick Start** - [docs/quickstart.md](docs/quickstart.md)
- **User Guide** - [docs/user-guide.md](docs/user-guide.md)
- **Schedule Format Reference** - [docs/schedule-format.md](docs/schedule-format.md)
- **Recurrence Patterns** - [docs/recurrence-patterns.md](docs/recurrence-patterns.md)
- **Troubleshooting** - [docs/troubleshooting.md](docs/troubleshooting.md)

## How It Works

1. **Load Schedules** - Reads schedule definitions from YAML files
2. **Extract Date Range** - Determines date range from imported transactions
3. **Generate Expected Dates** - Calculates when each schedule should occur
4. **Match Transactions** - Scores imported transactions against expected occurrences
5. **Enrich Matches** - Adds metadata, tags, and posting templates to matched transactions
6. **Create Placeholders** - Generates placeholder transactions for missing expected payments

## Matching Algorithm

Beanschedule uses a weighted scoring system:

- **Payee match**: 40% (supports regex patterns and fuzzy matching)
- **Amount match**: 40% (exact, tolerance, or range-based)
- **Date match**: 20% (uses day difference with linear decay)

Default threshold: 0.80 (configurable)

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
