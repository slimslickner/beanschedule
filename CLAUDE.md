# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start Commands

```bash
# Setup
uv venv
source .venv/bin/activate  # or: . .venv/bin/activate.fish for fish shell
uv sync --all-extras

# Testing
uv run pytest tests/ -v                                                    # All tests
uv run pytest tests/test_matcher.py -v                                    # Single file
uv run pytest tests/test_matcher.py::TestPayeeMatching::test_exact_payee_match -v  # Single test
uv run pytest tests/ --cov=beanschedule --cov-report=html                # Coverage report

# Code Quality
uv run ruff check beanschedule/ tests/                                    # Lint
uv run ruff format beanschedule/ tests/                                   # Format
uv run mypy beanschedule/                                                 # Type check
```

**Note**: Do NOT manually test CLI commands during development (e.g., `uv run beanschedule --help`). Use Click's `CliRunner` fixture in unit tests instead. Manual CLI testing is only for end-user validation, not for verifying code changes.

## Architecture Overview

Beanschedule is a **beangulp hook** that automatically matches imported bank transactions to scheduled/recurring transactions and enriches them with complete posting information, metadata, and tags.

### High-Level Flow

1. **Hook Entry** (`hook.py:schedule_hook()`)
   - Called by beangulp during import with `extracted_entries_list` and optional `existing_entries`
   - Returns modified entries with enriched transactions and placeholders

2. **Schedule Loading** (`loader.py`)
   - Supports two modes: single `schedules.yaml` file or directory `schedules/` with `_config.yaml`
   - Auto-discovery: env vars → current dir → importers parent dir
   - Returns `ScheduleFile` with global config and list of Schedule objects

3. **Recurrence Generation** (`recurrence.py`)
   - For each schedule, generates expected transaction dates within date range
   - Supports: MONTHLY, WEEKLY, YEARLY, BIMONTHLY, INTERVAL frequencies
   - Uses `dateutil.rrule` for robust date math (handles leap years, DST, etc.)

4. **Transaction Matching** (`matcher.py`)
   - Weighted scoring algorithm: Payee (40%) + Amount (40%) + Date (20%)
   - Account match required (fail if mismatch)
   - Fuzzy matching for payees (via `difflib.SequenceMatcher`) and regex support
   - Returns best match if score ≥ threshold

5. **Transaction Enrichment** (`hook.py`)
   - Adds `schedule_id`, `schedule_matched_date`, `schedule_confidence` metadata
   - Merges tags, can override payee/narration
   - Replaces postings with schedule template postings

6. **Placeholder Creation** (`hook.py`)
   - For expected schedule occurrences with no match, creates placeholder transactions
   - Flag configurable (`!` by default), narration prefix `[MISSING]`
   - Prevents duplicate placeholders by checking `schedule_id` metadata in ledger

### Key Modules

- **`schema.py`** (120 lines) - Pydantic models with validation
  - `MatchCriteria` - Account, payee pattern, amount, date window
  - `RecurrenceRule` - Frequency, dates, interval rules
  - `Schedule` - Complete schedule definition
  - `GlobalConfig` - Thresholds, defaults, behavior
  - `ScheduleFile` - Loaded file with config + schedules

- **`matcher.py`** (230 lines) - Matching algorithm
  - `TransactionMatcher.calculate_match_score()` - Main scoring logic
  - Supports regex patterns and fuzzy matching
  - Amount matching: exact, tolerance (linear decay), range

- **`recurrence.py`** (160 lines) - Date generation
  - `RecurrenceEngine.generate()` - Main entry point
  - Separate methods per frequency type (monthly, weekly, yearly, etc.)
  - Clamps dates to effective range

- **`loader.py`** (280 lines) - YAML loading and validation
  - Two modes: file (`schedules.yaml`) or directory (`schedules/`)
  - `load_schedules_file(path)` - Load and validate
  - `load_schedules_from_directory(path)` - Load with `_config.yaml`
  - `find_schedules_location()` - Auto-discovery

- **`hook.py`** (450 lines) - Beangulp integration
  - `schedule_hook()` - Main hook function
  - `_generate_expected_occurrences()` - Orchestrates recurrence generation
  - `_build_date_index()` - **Lazy matching optimization**: O(1) date→transactions lookup
  - Handles ledger entries to prevent duplicate placeholders

- **`cli.py`** (350 lines) - Command-line interface
  - `validate` - Validate schedule YAML files
  - `list` - List schedules with filters
  - `generate` - Create expected dates for a schedule (date range)
  - `init` - Initialize example schedules

### Critical Optimization: Lazy Matching

From ROADMAP.md: **80%+ speedup achieved** by only checking transactions within date windows.

```python
# hook.py:_build_date_index()
date_index = {date: [txn, txn, ...], ...}  # O(n) once

# For each schedule occurrence:
transactions_in_window = date_index.get(expected_date) + nearby dates
# Instead of checking all 14k ledger transactions, check ~10-50
```

Performance baseline (M2 MacBook, 14,874 entries, 43 schedules):

- Before: ~45 seconds
- After lazy matching: ~5-10 seconds ✅

## Data Flow Example

**Input**: Imported bank transaction

```beancount
2024-01-01 * "PROPERTY MGR" ""
  Assets:Bank:Checking                   -1500.00 USD
```

**Process**:

1. Load schedule: `rent-payment` with payee pattern `"Property Manager|Landlord"`, amount `-1500.00`
2. Generate expected dates: 1st of each month in range
3. Match: Jan 1 ✓ (date matches), "PROPERTY MGR" ✓ (fuzzy match), -1500 ✓ (amount matches) → score 0.92
4. Enrich: Add metadata + postings from template

**Output**:

```beancount
2024-01-01 * "Property Manager" "Monthly Rent"
  schedule_id: "rent-payment"
  schedule_matched_date: 2024-01-01
  schedule_confidence: 0.92
  Assets:Bank:Checking                   -1500.00 USD
  Expenses:Housing:Rent                   1500.00 USD
```

## Testing Strategy

Test structure (77 tests, 86% coverage):

- **`test_schema.py`** (34 tests) - Pydantic model validation ✅
- **`test_matcher.py`** (28 tests) - Scoring algorithm ✅
- **`test_hook.py`** (15 tests) - Beangulp integration ✅
- **`test_recurrence.py`** (pending) - Date generation
- **`test_loader.py`** (pending) - YAML loading
- **`test_cli.py`** (pending) - CLI commands
- **`test_beangulp_integration.py`** (pending) - End-to-end

Fixtures in `tests/conftest.py`:

- `make_transaction()`, `make_schedule()` - Test builders
- `temp_schedule_dir`, `temp_schedule_file` - Temp files
- `assert_transaction_enriched()` - Custom assertions

### CLI Testing (IMPORTANT)

**DO NOT manually run CLI commands to test them** (e.g., `uv run beanschedule --help`). Instead, use Click's `CliRunner` fixture in unit tests:

```python
from click.testing import CliRunner
from beanschedule.cli import main

def test_beanschedule_help():
    runner = CliRunner()
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'Beanschedule' in result.output

def test_validate_command():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Set up test files
        result = runner.invoke(main, ['validate', 'schedules.yaml'])
        assert result.exit_code == 0
```

**Why**: Manual CLI testing (`uv run beanschedule ...`) is for end-user validation, not for verifying code correctness. Unit tests with `CliRunner` are faster, more reliable, and don't require package installation.

### Example Unit Test

```python
def test_exact_payee_match(sample_transaction, sample_schedule):
    matcher = TransactionMatcher(GlobalConfig())
    score = matcher.calculate_match_score(
        sample_transaction,  # payee="Test Payee"
        sample_schedule,     # payee_pattern="Test Payee"
        date(2024, 1, 1)
    )
    assert score > 0.8  # Passes when payee matches exactly
```

### Integration Tests

Integration tests use real `examples/` directory:

- Real schedules in `examples/schedules/`
- Real ledger in `examples/example.beancount`
- Tests verify matching behavior on realistic data

## Common Development Tasks

### Add a New Recurrence Frequency

1. Add enum value to `FrequencyType` in `types.py`
2. Add generation method to `RecurrenceEngine` in `recurrence.py`
3. Add tests in `test_recurrence.py`
4. Document in README.md

### Fix a Matching Bug

1. Write failing test in `test_matcher.py` or `test_hook.py`
2. Debug with: `uv run pytest tests/test_matcher.py::TestXxx -v -s`
3. Fix in `matcher.py` (scoring logic) or `loader.py` (validation)
4. Verify coverage: `uv run pytest tests/ --cov=beanschedule`

### Optimize Performance

High-priority improvements from ROADMAP.md:

- **Payee pattern compilation** (40-50% speedup) - Pre-compile regex in `TransactionMatcher.__init__`
- **Fuzzy match caching** (10-20% speedup) - Cache `SequenceMatcher` results by payee
- **Skip unnecessary ledger matching** (5-10% speedup) - Check if any ledger transactions have `schedule_id` metadata

Current bottleneck: Payee pattern compilation and fuzzy matching via `SequenceMatcher` (5-10s for large ledgers).

## Key Constraints & Design Decisions

1. **Beangulp Hook Format** - Must accept 4-tuple entries: `(account, directives, date_range, progress)`
2. **Ledger Blocking** - Transactions with `schedule_id` metadata block placeholders (prevents duplicates)
3. **Account Required** - Account match is mandatory in `MatchCriteria` (design decision for correctness)
4. **Regex Over Glob** - Payee patterns use regex, not glob patterns (standard Python `re` module)
5. **YAML Only** - Schedules are YAML, not Python (for distribution simplicity)
6. **No Multi-Currency** - All amounts assumed in schedule currency (limitation documented in ROADMAP)

## Dependencies & Environment

- **Python**: 3.11+ (tested 3.11-3.13)
- **Build**: `setuptools>=68.0`, modern `pyproject.toml` (PEP 517)
- **Package Layout**: Flat-layout with `beanschedule/` at root (not src-layout)
- **Core**: `beancount>=3.2.0`, `beangulp>=0.2.0`, `pydantic>=2.0.0`, `pyyaml>=6.0`
- **Date Math**: `python-dateutil>=2.8.0` (for `rrule`)
- **CLI**: `click>=8.0.0`
- **Dev**: `pytest>=7.0.0`, `ruff>=0.14.13`, `mypy>=1.0.0`

Virtual environment uses `uv` (fast Python package installer). Activate:

```bash
source .venv/bin/activate        # bash/zsh
. .venv/bin/activate.fish        # fish
```

## Code Quality Standards

From `pyproject.toml`:

- **Line length**: 100 characters
- **Linter**: Ruff (strict mode) - E,F,I,N,UP,B,A,COM,C4,DTZ,ISC,ICN,G,PIE,T20,Q,RSE,RET,SLF,SIM,TID,ARG,PTH,ERA,PL,RUF
- **Format**: Black (compatible with Ruff)
- **Type hints**: `mypy` in check mode (not strict)
- **Logging**: Use deferred formatting (`logger.info("...", var)` not f-strings) ⭐ ROADMAP priority
- **Tests**: Pytest with fixtures, 85%+ coverage target

Known issues:

- **Logging**: Some f-strings in logging calls (ROADMAP priority to fix for performance)
- **Recurrence tests**: Pending (test_recurrence.py not implemented yet)
- **CLI tests**: Pending (test_cli.py not implemented yet)

## ROADMAP Status (January 2026)

**Current Version**: 1.0.0 (Beta → Production Ready)

High-priority next steps:

1. Fix logging f-strings → deferred formatting (ruff violation)
2. Implement payee pattern compilation (40-50% speedup)
3. Complete test coverage: recurrence, loader, CLI, end-to-end
4. Pre-release checklist: CONTRIBUTING.md, CODE_OF_CONDUCT.md, CHANGELOG.md, GitHub Actions

See ROADMAP.md for full feature roadmap and performance optimization plan.
