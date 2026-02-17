# Beanschedule

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/slimslickner/beanschedule/workflows/tests/badge.svg)](https://github.com/slimslickner/beanschedule/actions)

**Scheduled transaction framework for Beancount** — automatically match, enrich, and forecast recurring transactions.

Beanschedule is a [beangulp](https://github.com/beancount/beangulp) hook that:

- Matches imported bank transactions to your defined recurring schedules
- Enriches matched transactions with complete posting splits, metadata, and tags
- Generates placeholder transactions for expected payments that didn't occur
- Forecasts future scheduled transactions for budgeting and visualization via a Beancount plugin
- Stages one-time pending transactions that auto-match and enrich when imported

## Quick Start

### 1. Define Your Schedules

Create a `schedules/` directory with recurring transaction definitions:

```yaml
# schedules/rent.yaml
id: rent-payment
match:
  account: Assets:Bank:Checking
  payee_pattern: "PROPERTY MGR|Property Manager"
  amount: -1500.00
recurrence:
  frequency: MONTHLY
  day_of_month: 1
  start_date: 2024-01-01
transaction:
  payee: Property Manager
  narration: Monthly Rent
  postings:
    - account: Assets:Bank:Checking
      amount: null
    - account: Expenses:Housing:Rent
      amount: null
```

See [SCHEDULES.md](docs/SCHEDULES.md) for detailed documentation.

### 2. Integrate with Beangulp

Add to your `importers/config.py`:

```python
from beanschedule import schedule_hook

HOOKS = [schedule_hook]
```

Now when you import transactions, matched ones are automatically enriched with complete splits and metadata.

### 3. (Optional) Add Forecast Plugin

Add to your main ledger to generate future scheduled transactions:

```beancount
plugin "beanschedule.plugins.schedules"
```

See [PLUGIN.md](docs/PLUGIN.md) for configuration options.

## Core Features

| Feature                  | Purpose                                                 | Documentation                     |
| ------------------------ | ------------------------------------------------------- | --------------------------------- |
| **Schedules & Hook**     | Define recurring transactions and auto-enrich on import | [SCHEDULES.md](docs/SCHEDULES.md) |
| **Forecast Plugin**      | Generate future scheduled transactions for budgeting    | [PLUGIN.md](docs/PLUGIN.md)       |
| **Pending Transactions** | Stage one-time items before they post                   | [PENDING.md](docs/PENDING.md)     |
| **CLI Tools**            | Validate, list, generate, and manage schedules          | [CLI.md](docs/CLI.md)             |
| **Advanced Features**    | Loan amortization, complex matches, auto-detection      | [ADVANCED.md](docs/ADVANCED.md)   |

## Installation

Install from GitHub:

```bash
pip install git+https://github.com/slimslickner/beanschedule.git
```

**Requirements**: Python 3.11+, beancount >= 3.2.0, beangulp >= 0.2.0

**Note**: Beanschedule is not yet published to PyPI. See [ROADMAP.md](ROADMAP.md) for future plans.

## Example

**Before** (imported from bank):

```beancount
2024-01-01 * "PROPERTY MGR" ""
  Assets:Bank:Checking                   -1500.00 USD
```

**After** (matched and enriched):

```beancount
2024-01-01 * "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  Assets:Bank:Checking                   -1500.00 USD
  Expenses:Housing:Rent                   1500.00 USD
```

## Highlights

- **Fuzzy matching** with weighted scoring (payee 40%, amount 40%, date 20%)
- **Flexible recurrence patterns** (monthly, weekly, bi-weekly, quarterly, yearly, custom)
- **Loan amortization** with automatic principal/interest splits
- **Skip markers** for intentionally skipped occurrences
- **Missing transaction detection** with placeholder generation
- **One-time pending transactions** that auto-match on import
- **Pattern auto-detection** from existing ledgers
- **CLI validation and testing** tools

## Contributing

Contributions welcome! Please open an issue or pull request.

## License

MIT License — see [LICENSE](LICENSE) for details.
