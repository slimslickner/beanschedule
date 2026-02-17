# CLAUDE.md

Guide for Claude Code when working on this repository.

**See `.continue/rules/` for detailed documentation (also used by Continue and Roo Code IDE extensions).**

## Quick Links

- **Architecture & Data Flow** → `.continue/rules/architecture.md`
- **Coding Standards & Patterns** → `.continue/rules/coding-standards.md`
- **Testing Guide** → `.continue/rules/testing-guide.md`
- **Setup & Commands** → `.continue/rules/setup-and-commands.md`
- **API Reference** → `.continue/rules/api-reference.md`

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
uv run ruff check beanschedule/ tests/ && uv run mypy beanschedule/
```

See `.continue/rules/setup-and-commands.md` for full reference.

## Code Quality Checks

**REQUIRED**: After every Python code change, run the following checks and ensure they all pass with zero errors:

```bash
uv run ruff check --fix beanschedule/ tests/
uv run ruff format beanschedule/ tests/
uv run ty check
```

These checks ensure code style consistency, proper formatting, and type safety. All three must resolve with zero errors before committing changes.

## Important Notes

1. **CLI Testing**: Use Click's `CliRunner` in tests, NOT manual `uv run beanschedule` commands during development. Manual testing is only for end-user validation.

2. **Lazy Matching Optimization**: We index transactions by date for O(1) lookups, achieving **80% speedup** (45s → 5-10s on large ledgers).

3. **Logging**: Use deferred formatting: `logger.info("message %s", var)` NOT `logger.info(f"message {var}")`

4. **Type Hints**: Required on public functions, optional on simple internal functions.

5. **Test Coverage**: 371 passing tests, 72% overall coverage (367 core tests + 24 pending transaction tests). Pre-existing 2 failures in date-sensitive amortization tests.

## Key Design Decisions

- Account match is mandatory for correctness
- Payee patterns use regex (standard Python `re`)
- Schedules are YAML only (not Python code)
- Weighted scoring: Payee (40%) + Amount (40%) + Date (20%)

See `.continue/rules/architecture.md` for full architecture details.

## v1.4.0 Status (Current)

✅ **Completed in v1.4.0**:

- Skip markers for intentionally skipped scheduled transactions
- Configurable forecast settings (forecast_months, min_forecast_date, include_past_dates)
- Pending transactions feature (one-time staging, auto-matching, auto-removal)
- Comprehensive logging for pending transaction processing
- All pending transaction tests passing (24/24)

See ROADMAP.md for full roadmap and v1.5.0+ planned features.
