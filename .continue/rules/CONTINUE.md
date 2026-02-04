# CONTINUE Project Guide

## 1. Project Overview
BeanSchedule is a Python-based scheduling library for managing time-sensitive tasks and workflows. It appears to be a domain-specific framework for scheduling operations with potential financial amortization applications (based on STATEFUL_AMORTIZATION.md).

**Key Technologies**:
- Python 3.11+ (inferred from uv.lock and modern tooling)
- Poetry (pyproject.toml) with uv as package resolver
- Ruff (linter, indicated by .ruff_cache)
- Likely pytest (tests/ directory structure)

**Architecture**:
- Modular design with core scheduling logic in `beanschedule/`
- Example implementations in `examples/`
- Test suite in `tests/`
- Configuration-driven approach (implied by structure)

## 2. Getting Started
**Prerequisites**:
- Python 3.11 or newer
- uv (Python package installer) or Poetry
- Optional: Ruff for linting

**Installation**:
```bash
uv pip install -e .  # Preferred method
# OR
poetry install
```

**Basic Usage**:
```python
from beanschedule import Scheduler

scheduler = Scheduler()
scheduler.add_task("daily_report", "0 0 * * *", generate_report)
scheduler.run()
```

**Running Tests**:
```bash
uv run pytest  # Or poetry run pytest
```

## 3. Project Structure
```
.
├── beanschedule/       # Core library implementation
├── examples/           # Usage examples and demos
├── tests/              # Test suite (unit/integration)
├── .continue/          # Continue configuration
├── .github/            # CI/CD and GitHub actions
├── pyproject.toml      # Project metadata and dependencies
└── uv.lock             # Resolved dependencies
```

**Key Files**:
- `pyproject.toml`: Defines dependencies and build system
- `STATEFUL_AMORTIZATION.md`: Domain-specific documentation
- `TESTING.md`: Testing guidelines
- `ROADMAP.md`: Project development plan

## 4. Development Workflow
**Coding Standards**:
- PEP 8 compliant (enforced by Ruff)
- Type hints required for all public interfaces
- Docstrings in Google format

**Testing**:
- Unit tests in `tests/unit/`
- Integration tests in `tests/integration/`
- All tests must maintain 80%+ coverage

**Contribution Process**:
1. Create feature branch from main
2. Update relevant documentation
3. Run `ruff check` and `pytest`
4. Submit PR with test coverage report

## 5. Key Concepts
- **Scheduler**: Core component managing task execution
- **Amortization Engine**: Stateful financial calculation system (see STATEFUL_AMORTIZATION.md)
- **Time Specification**: Cron-like syntax with custom extensions
- **Task Dependencies**: Directed acyclic graph (DAG) support

## 6. Common Tasks
**Add New Scheduler Type**:
1. Create new module in `beanschedule/schedulers/`
2. Implement `BaseScheduler` interface
3. Register in `beanschedule/__init__.py`
4. Add corresponding tests

**Update Dependencies**:
```bash
uv pip compile  # Update lockfile
uv pip sync     # Apply changes
```

## 7. Troubleshooting
**Dependency Conflicts**:
- Run `uv pip compile --upgrade` to refresh lockfile
- Check for incompatible version ranges in pyproject.toml

**Test Failures**:
- Run with `-v` flag for verbose output
- Check for environment-specific issues (time zones, etc.)

**Linter Errors**:
- `ruff check --fix` to auto-resolve most issues
- Consult .ruff.toml for project-specific rules

## 8. References
- [Python Packaging Guide](https://packaging.python.org/)
- [Ruff Documentation](https://beta.ruff.rs/)
- [uv User Guide](https://github.com/astral-sh/uv)
- [Project ROADMAP](ROADMAP.md)
- [Amortization Implementation](STATEFUL_AMORTIZATION.md)

> **Note**: Some sections contain assumptions based on directory structure. Verify implementation details in source files before critical decisions.