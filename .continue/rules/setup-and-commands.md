# Setup & Common Commands

## Initial Setup

```bash
# Create virtual environment (one-time)
uv venv

# Activate (bash/zsh)
source .venv/bin/activate

# Activate (fish)
. .venv/bin/activate.fish

# Install dependencies (one-time)
uv sync --all-extras
```

## Common Commands

### Testing

```bash
# All tests
uv run pytest tests/ -v

# Single test file
uv run pytest tests/test_matcher.py -v

# Single test
uv run pytest tests/test_matcher.py::TestPayeeMatching::test_exact_payee_match -v

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

# Type check with mypy
uv run mypy beanschedule/

# All checks at once
uv run ruff check beanschedule/ tests/ && uv run ruff format beanschedule/ tests/ && uv run mypy beanschedule/
```

### CLI Development

**For testing**: Use pytest with Click's CliRunner (see `.continue/rules/testing-guide.md`)

```bash
# ✅ Correct - test via CliRunner
uv run pytest tests/test_cli.py -v

# ❌ Avoid - manual testing is only for end-user validation
uv run beanschedule --help
uv run beanschedule validate schedules.yaml
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
├── hook.py            # Beangulp integration
├── cli/               # CLI commands (modular)
│   ├── __init__.py
│   ├── main.py        # CLI entry point
│   ├── validate.py    # validate command
│   ├── list.py        # list command
│   └── generate.py    # generate command
└── utils.py           # Helpers (slugify, etc.)

tests/
├── conftest.py        # Fixtures
├── test_schema.py
├── test_matcher.py
├── test_hook.py
└── test_integration.py

examples/
├── schedules/         # Example schedule definitions
└── example.beancount  # Sample ledger

docs/
└── .continue/rules/   # Continue IDE documentation
```

## Virtual Environment

Uses `uv` (fast Python package installer):

```bash
# Create venv in project
uv venv

# Install from pyproject.toml
uv sync --all-extras

# Add a dependency
uv add requests

# Add dev dependency
uv add --dev black pytest
```

To deactivate and switch back to system Python:
```bash
deactivate
```

## Environment Variables

- `BEANSCHEDULE_DIR`: Path to schedules directory (overrides auto-discovery)
- `DEBUG`: Set to `1` for verbose logging

```bash
export BEANSCHEDULE_DIR=~/my-schedules
export DEBUG=1
uv run beanschedule validate
```

## Key Dependencies

| Dependency | Role | Version |
|------------|------|---------|
| `beancount` | Ledger parsing | 3.2.0+ |
| `beangulp` | Hook integration | 0.2.0+ |
| `pydantic` | Data validation | 2.0.0+ |
| `pyyaml` | Schedule loading | 6.0+ |
| `python-dateutil` | Date math | 2.8.0+ |
| `click` | CLI framework | 8.0.0+ |
| `pytest` | Testing | 7.0.0+ |
| `ruff` | Linting & formatting | 0.14.13+ |
| `mypy` | Type checking | 1.0.0+ |

## Python Version

- **Minimum**: Python 3.11
- **Tested**: 3.11, 3.12, 3.13

Check version:
```bash
python --version
```

## Quick Workflows

### Add a Feature

```bash
# 1. Create test first (TDD)
uv run pytest tests/test_matcher.py -v -s

# 2. Implement feature
# (edit beanschedule/matcher.py)

# 3. Check quality
uv run ruff check beanschedule/
uv run mypy beanschedule/
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

### Check Code Quality Before Commit

```bash
# One-liner for full validation
uv run pytest tests/ && \
uv run ruff check beanschedule/ tests/ && \
uv run ruff format beanschedule/ tests/ && \
uv run mypy beanschedule/
```

See `.continue/rules/coding-standards.md` and `.continue/rules/testing-guide.md` for details.
