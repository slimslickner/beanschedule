# CLAUDE.md

Guide for Claude Code when working on beanschedule.

## What is Beanschedule?

Beanschedule is a **beangulp hook** that automatically matches imported bank transactions to scheduled/recurring transactions and enriches them with posting details, metadata, and tags.

**Key Components**:

- `schema.py` - Pydantic data models
- `matcher.py` - Scoring algorithm (payee + amount + date)
- `recurrence.py` - Date generation (MONTHLY, WEEKLY, YEARLY, etc.)
- `loader.py` - YAML loading with auto-discovery
- `pending.py` - One-time transaction matching and enrichment
- `hook.py` - Beangulp integration + lazy matching optimization
- `cli/commands.py` - Command-line interface (validate, list, generate, init, pending, skip, etc.)
- `cli/formatters.py` - Output formatting (tables, JSON, CSV)
- `cli/builders.py` - Interactive transaction/schedule builders

## Quick Setup

```bash
# One-time
uv venv && source .venv/bin/activate && uv sync --all-extras

# Testing
uv run pytest tests/ -v
uv run pytest tests/ --cov=beanschedule --cov-report=html

# Code quality
uv run ruff check --fix beanschedule/ tests/
uv run ruff format beanschedule/ tests/
uv run ty check
```

## Code Quality Checks (REQUIRED)

**After every Python code change**, run these checks and ensure they all pass with zero errors:

```bash
uv run ruff check --fix beanschedule/ tests/
uv run ruff format beanschedule/ tests/
uv run ty check
```

All three tools must resolve with zero errors before committing. This ensures:

- Code style consistency (Ruff linter)
- Proper formatting (Ruff formatter, 88 char line length)
- Type safety (ty type checker)

## Architecture Overview

### High-Level Data Flow

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

### Module Responsibilities

| Module            | Lines | Responsibility                                                         |
| ----------------- | ----- | ---------------------------------------------------------------------- |
| `schema.py`       | ~300  | Pydantic models: Schedule, MatchCriteria, RecurrenceRule, GlobalConfig |
| `matcher.py`      | ~230  | Scoring algorithm: `TransactionMatcher.calculate_match_score()`        |
| `recurrence.py`   | ~160  | Date generation per frequency type                                     |
| `loader.py`       | ~280  | YAML loading, validation, auto-discovery                               |
| `pending.py`      | ~120  | Pending transaction matching and cleanup                               |
| `hook.py`         | ~500  | Beangulp hook integration, enrichment, lazy matching, skip detection   |
| `cli/commands.py` | ~600  | CLI: validate, list, generate, init, pending, skip, detect, create     |

### Critical Optimization: Lazy Matching

**Problem**: Checking all ledger transactions (10k+) against all schedules is slow.

**Solution** (`hook.py:_build_date_index()`): Build O(1) date lookup

```python
date_index = {date: [txn, txn, ...], ...}

# Instead of checking all 14k transactions per schedule:
transactions_in_window = date_index.get(expected_date) + nearby_dates
# Check only 10-50 relevant transactions
```

**Result**: 45s → 5-10s on M2 MacBook (14k entries, 43 schedules) = **80%+ speedup**

## Key Design Decisions

1. **Account match is mandatory** - Required for correctness, not optional
2. **Payee patterns use regex** - Standard Python `re` module, supports fuzzy matching
3. **Schedules are YAML only** - Not Python code, easier for users to maintain
4. **Weighted scoring** - Payee (40%) + Amount (40%) + Date (20%)
5. **Beangulp hook format** - Must accept `(account, directives, date_range, progress)` tuple
6. **YAML only + no Python code** - Keep configuration simple and readable
7. **Single currency** - All amounts in schedule currency

## Coding Standards & Patterns

### Code Quality Tools

- **Formatter**: Ruff (88 char line length)
- **Linter**: Ruff
- **Type Checker**: ty (Astral's type checker)
- **Tests**: pytest with 85%+ coverage target

### Key Patterns

**1. Pydantic Models** (schema.py)

All configuration/data models use Pydantic v2 with validation:

```python
from pydantic import BaseModel, Field, field_validator

class MatchCriteria(BaseModel):
    account: str
    payee_pattern: str
    amount: AmountCriteria
    date_window_days: int = Field(default=3, ge=0)

    @field_validator('payee_pattern')
    @classmethod
    def validate_regex(cls, v: str) -> str:
        re.compile(v)  # Fail fast on invalid regex
        return v
```

Pattern: Models validate at construction time. Fail fast if config is invalid.

**2. Matcher Algorithm** (matcher.py)

Weighted scoring with clear logic:

```python
def calculate_match_score(
    self,
    transaction: Transaction,
    schedule: Schedule,
    expected_date: date
) -> float:
    # Account must match (binary)
    if transaction.account != schedule.match_criteria.account:
        return 0.0

    # Weighted scores: payee (40%) + amount (40%) + date (20%)
    payee_score = self._score_payee(...)     # 0.0-1.0
    amount_score = self._score_amount(...)   # 0.0-1.0
    date_score = self._score_date(...)       # 0.0-1.0

    return 0.4 * payee_score + 0.4 * amount_score + 0.2 * date_score
```

Pattern: Clear, explicit scoring with no magic numbers. Weights documented.

**3. Date Generation** (recurrence.py)

Separate methods per frequency type:

```python
def _generate_monthly(self, start: date, end: date, rule: RecurrenceRule) -> list[date]:
    """Generate dates on specific day of month."""
    ...

def _generate_bimonthly(self, start: date, end: date, rule: RecurrenceRule) -> list[date]:
    """Every other month on specific day."""
    ...
```

Pattern: One function per frequency type. Easy to test, maintain, extend.

**4. Lazy Date Indexing** (hook.py)

Build index once, use for O(1) lookups:

```python
def _build_date_index(transactions: list[Transaction]) -> dict[date, list[Transaction]]:
    """Map date → [transactions on that date]."""
    index = defaultdict(list)
    for txn in transactions:
        index[txn.date].append(txn)
    return index

# Later: transactions_in_window = index.get(expected_date, [])
```

Pattern: Pre-compute expensive lookups. One-time O(n), reused many times.

### Logging

Use **deferred formatting** (not f-strings):

```python
# Good ✅
logger.info("Matched transaction %s with confidence %f", payee, confidence)

# Bad ❌
logger.info(f"Matched transaction {payee} with confidence {confidence}")
```

Why: Avoids string interpolation when log level is disabled.

### Validation & Error Handling

- **At boundaries**: Validate YAML input at load time (loader.py)
- **In models**: Pydantic validates at construction (schema.py)
- **Trust internal code**: Don't validate outputs from other modules
- **Explicit errors**: Use descriptive exception messages with context

### Type Hints

Required on all public functions:

```python
def calculate_match_score(
    self,
    transaction: Transaction,
    schedule: Schedule,
    expected_date: date
) -> float:
    ...
```

Optional on simple internal functions, required on complex ones.

### No Premature Abstraction

- One-time operations: don't create helpers
- Similar code appearing 2-3 times: it's OK to repeat
- Simple features: no configurability if not needed yet

## Testing Guide

### Test Structure

~390 tests with 72% coverage:

- `test_schema.py` - Pydantic model validation
- `test_matcher.py` - Scoring algorithm
- `test_hook.py` - Beangulp integration
- `test_recurrence.py` - Date generation
- `test_loader.py` - YAML loading
- `test_cli.py` - CLI commands
- `test_pending.py` - Pending transaction matching
- `test_skip_markers.py` - Skip marker detection
- `test_integration.py` - End-to-end flows

### Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Single file
uv run pytest tests/test_matcher.py -v

# Single test
uv run pytest tests/test_matcher.py::TestPayeeMatching::test_exact_payee_match -v

# With coverage
uv run pytest tests/ --cov=beanschedule --cov-report=html

# Watch mode (re-run on file changes)
uv run pytest tests/ -v --looponfail
```

### Test Fixtures (conftest.py)

```python
@pytest.fixture
def make_transaction():
    """Factory: create Transaction with defaults."""
    def _make(date=None, payee="Test", amount=100.0, account="Assets:Bank"):
        return Transaction(date=date or date.today(), ...)
    return _make

@pytest.fixture
def make_schedule():
    """Factory: create Schedule with defaults."""
    ...
```

### Writing Tests

Unit test example:

```python
def test_exact_payee_match(make_transaction, make_schedule):
    """Exact payee match scores high."""
    matcher = TransactionMatcher(GlobalConfig())
    txn = make_transaction(payee="Test Payee")
    schedule = make_schedule(payee_pattern="Test Payee")

    score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 1))

    assert score > 0.8
```

### CLI Testing (IMPORTANT)

**DO NOT manually run CLI commands** to test them:

```bash
# ❌ Don't do this
uv run beanschedule --help
uv run beanschedule validate schedules.yaml
```

**Instead, use Click's CliRunner**:

```python
from click.testing import CliRunner
from beanschedule.cli import main

def test_validate_command():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open('schedules.yaml', 'w') as f:
            f.write('schedules: []\n')

        result = runner.invoke(main, ['validate', 'schedules.yaml'])

        assert result.exit_code == 0
```

Why CliRunner is better:

- Faster (no subprocess)
- More reliable (no environment issues)
- Don't require package installation
- Can test error cases easily

Manual CLI testing is for end-user validation only.

### Coverage Target

- Aim for **85%+** coverage
- Focus on: core logic (matcher, recurrence, hook)
- Skip: tedious boilerplate, obvious paths

Check coverage:

```bash
uv run pytest tests/ --cov=beanschedule --cov-report=html
# Open htmlcov/index.html
```

## Common Commands

### Testing

```bash
# All tests
uv run pytest tests/ -v

# Single test file
uv run pytest tests/test_matcher.py -v

# With coverage report (generates htmlcov/)
uv run pytest tests/ --cov=beanschedule --cov-report=html

# Watch mode (re-run on file changes)
uv run pytest tests/ -v --looponfail
```

### Code Quality

```bash
# Check for linting issues
uv run ruff check beanschedule/ tests/

# Auto-fix linting issues
uv run ruff check --fix beanschedule/ tests/

# Format code (Ruff)
uv run ruff format beanschedule/ tests/

# Type check with ty
uv run ty check

# All checks at once
uv run ruff check beanschedule/ tests/ && uv run ruff format beanschedule/ tests/ && uv run ty check
```

### Debugging

```bash
# Run single test with print output
uv run pytest tests/test_matcher.py::TestXxx -v -s

# Run with debugger breakpoints
# (add breakpoint() in code, then run pytest)
uv run pytest tests/test_matcher.py -v -s --pdb

# Generate coverage for specific file
uv run pytest tests/ --cov=beanschedule.matcher --cov-report=term-missing
```

## Project Structure

```
beanschedule/
├── __init__.py
├── schema.py          # Pydantic models
├── matcher.py         # Scoring algorithm
├── recurrence.py      # Date generation
├── loader.py          # YAML loading
├── pending.py         # Pending transaction matching
├── hook.py            # Beangulp integration
├── cli/               # CLI commands (modular)
│   ├── __init__.py
│   ├── main.py        # CLI entry point
│   ├── commands.py    # All commands
│   ├── formatters.py  # Output formatting
│   └── builders.py    # Interactive builders
└── utils.py           # Helpers (slugify, etc.)

tests/
├── conftest.py        # Fixtures
├── test_schema.py
├── test_matcher.py
├── test_hook.py
├── test_recurrence.py
├── test_loader.py
├── test_cli.py
├── test_pending.py
├── test_skip_markers.py
└── test_integration.py

docs/
├── INDEX.md           # Documentation index
├── SCHEDULES.md       # Schedules & hook integration
├── PLUGIN.md          # Forecast plugin
├── PENDING.md         # Pending transactions
├── CLI.md             # CLI reference
└── ADVANCED.md        # Advanced features

examples/
├── schedules/         # Example schedule definitions
└── example.beancount  # Sample ledger
```

## Requirements

- **Python**: 3.11+
- **Dependencies**: See `pyproject.toml`
  - beancount >= 3.2.0
  - beangulp >= 0.2.0
  - pydantic >= 2.0.0
  - pyyaml >= 6.0
  - python-dateutil >= 2.8.0
  - click >= 8.0.0

## Quick Workflows

### Add a Feature

```bash
# 1. Create test first (TDD)
uv run pytest tests/test_matcher.py -v -s

# 2. Implement feature
# (edit beanschedule/matcher.py)

# 3. Check quality
uv run ruff check beanschedule/
uv run ty check
uv run ruff format beanschedule/

# 4. Run full test suite
uv run pytest tests/ --cov=beanschedule
```

### Fix a Bug

```bash
# 1. Write failing test that reproduces bug
uv run pytest tests/test_matcher.py::TestXxx -v -s

# 2. Debug: add breakpoint() in code
uv run pytest tests/test_matcher.py::TestXxx -v -s --pdb

# 3. Fix in source code
uv run pytest tests/test_matcher.py::TestXxx -v

# 4. Verify full test suite still passes
uv run pytest tests/
```

## Important Notes

1. **CLI Testing**: Use Click's `CliRunner` in tests, NOT manual `uv run beanschedule` commands during development.

2. **Lazy Matching Optimization**: We index transactions by date for O(1) lookups, achieving **80% speedup**.

3. **Logging**: Use deferred formatting: `logger.info("message %s", var)` NOT `logger.info(f"message {var}")`

4. **Type Hints**: Required on public functions, optional on simple internal functions.

5. **Test Coverage**: 390 passing tests, 72% overall coverage. Some pre-existing failures in date-sensitive tests.

6. **No Over-Engineering**:
   - Don't add features beyond what's asked
   - Don't create helpers for one-time operations
   - Keep solutions simple and focused

## v1.4.0 Status (Current)

✅ **Completed in v1.4.0**:

- Skip markers for intentionally skipped scheduled transactions
- Configurable forecast settings (forecast_months, min_forecast_date, include_past_dates)
- Pending transactions feature (one-time staging, auto-matching, auto-removal)
- Comprehensive logging for pending transaction processing

See ROADMAP.md for full roadmap and v1.5.0+ planned features.
