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
- `hook.py` - Beangulp integration + lazy matching optimization
- `cli.py` - Command-line interface (validate, list, generate, init)

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

## Important Notes

1. **CLI Testing**: Use Click's `CliRunner` in tests, NOT manual `uv run beanschedule` commands during development. Manual testing is only for end-user validation.

2. **Lazy Matching Optimization**: We index transactions by date for O(1) lookups, achieving **80% speedup** (45s → 5-10s on large ledgers).

3. **Logging**: Use deferred formatting: `logger.info("message %s", var)` NOT `logger.info(f"message {var}")`

4. **Type Hints**: Required on public functions, optional on simple internal functions.

5. **Test Coverage**: 77 tests, 86% coverage (test_schema, test_matcher, test_hook complete; test_recurrence, test_loader, test_cli pending).

## Key Design Decisions

- Account match is mandatory for correctness
- Payee patterns use regex (standard Python `re`)
- Schedules are YAML only (not Python code)
- Weighted scoring: Payee (40%) + Amount (40%) + Date (20%)

See `.continue/rules/architecture.md` for full architecture details.

## ROADMAP (January 2026)

High-priority next steps:
1. Fix logging f-strings → deferred formatting
2. Implement payee pattern compilation (40-50% speedup)
3. Complete test coverage (recurrence, loader, CLI, end-to-end)
4. Pre-release: CONTRIBUTING.md, CODE_OF_CONDUCT.md, CHANGELOG.md, GitHub Actions

See ROADMAP.md for full details.
