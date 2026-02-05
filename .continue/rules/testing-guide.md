---
description: Guide to testing beanschedule with pytest and fixtures
---

# Testing Guide

## Test Structure

77 tests, 86% coverage:

| File | Tests | Status | Focus |
|------|-------|--------|-------|
| `test_schema.py` | 34 | ✅ Complete | Pydantic model validation |
| `test_matcher.py` | 28 | ✅ Complete | Scoring algorithm |
| `test_hook.py` | 15 | ✅ Complete | Beangulp integration |
| `test_recurrence.py` | — | Pending | Date generation |
| `test_loader.py` | — | Pending | YAML loading |
| `test_cli.py` | — | Pending | CLI commands |
| `test_beangulp_integration.py` | — | Pending | End-to-end flow |

## Running Tests

```bash
# All tests
uv run pytest tests/ -v

# Single file
uv run pytest tests/test_matcher.py -v

# Single test
uv run pytest tests/test_matcher.py::TestPayeeMatching::test_exact_payee_match -v

# With coverage
uv run pytest tests/ --cov=beanschedule --cov-report=html
```

## Test Fixtures

From `conftest.py`:

```python
# Builders for test data
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

# Temp files
@pytest.fixture
def temp_schedule_file(tmp_path):
    """Create temp schedules.yaml for testing."""
    ...

@pytest.fixture
def temp_schedule_dir(tmp_path):
    """Create temp schedules/ directory with _config.yaml."""
    ...

# Custom assertions
@pytest.fixture
def assert_transaction_enriched():
    """Assert transaction has required metadata."""
    def _assert(txn, schedule_id, confidence):
        assert txn.meta.get('schedule_id') == schedule_id
        assert txn.meta.get('schedule_confidence') == confidence
    return _assert
```

## Writing Tests

### Unit Test: Payee Matching

```python
def test_exact_payee_match(make_transaction, make_schedule):
    """Exact payee match scores high."""
    matcher = TransactionMatcher(GlobalConfig())
    txn = make_transaction(payee="Test Payee")
    schedule = make_schedule(payee_pattern="Test Payee")

    score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 1))

    assert score > 0.8
```

### Unit Test: Fuzzy Matching

```python
def test_fuzzy_payee_match(make_transaction, make_schedule):
    """Similar payees (typos, abbreviations) match."""
    matcher = TransactionMatcher(GlobalConfig())
    txn = make_transaction(payee="PROPERTY MGR")
    schedule = make_schedule(payee_pattern="Property Manager")

    score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 1))

    assert 0.7 < score < 0.95  # Fuzzy match, not perfect
```

### Unit Test: Regex Patterns

```python
def test_regex_payee_pattern(make_transaction, make_schedule):
    """Regex patterns match multiple payees."""
    matcher = TransactionMatcher(GlobalConfig())
    txn = make_transaction(payee="LANDLORD INC")
    schedule = make_schedule(payee_pattern="(Landlord|Property Manager|Owner)")

    score = matcher.calculate_match_score(txn, schedule, date(2024, 1, 1))

    assert score > 0.8
```

### Integration Test: Full Enrichment

```python
def test_full_enrichment_flow(make_transaction, make_schedule, assert_transaction_enriched):
    """End-to-end: match → enrich with postings."""
    txn = make_transaction(date=date(2024, 1, 1), amount=-1500.0)
    schedule = make_schedule(amount=-1500.0)

    enriched = _enrich_transaction(txn, schedule)

    assert_transaction_enriched(enriched, "rent-payment", confidence=0.92)
    assert len(enriched.postings) == 2  # Assets + Expenses
```

## Important: CLI Testing

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
        # Set up test files
        with open('schedules.yaml', 'w') as f:
            f.write('schedules: []\n')

        result = runner.invoke(main, ['validate', 'schedules.yaml'])

        assert result.exit_code == 0
```

**Why**: CliRunner tests are:
- Faster (no subprocess)
- More reliable (no environment issues)
- Don't require package installation
- Can test error cases easily

Manual CLI testing is for end-user validation only.

## Integration Tests

Integration tests use real examples:

```python
def test_real_examples(temp_schedule_dir):
    """Use real schedules/ and example.beancount."""
    schedules = load_schedules_from_directory(
        'examples/schedules/'
    )
    ledger = load_beancount_file('examples/example.beancount')

    # Verify matching behavior on realistic data
    assert schedules.config.threshold > 0
    assert len(schedules.schedules) > 0
```

## Coverage Target

- Aim for **85%+** coverage
- Focus on: core logic (matcher, recurrence, hook)
- Skip: tedious boilerplate, obvious paths

Check coverage:
```bash
uv run pytest tests/ --cov=beanschedule --cov-report=html
# Open htmlcov/index.html
```

## Test Philosophy

1. **Test behavior, not implementation** - Changes should not break tests unless behavior changed
2. **Fail fast** - Validate inputs in tests before complex assertions
3. **Clear names** - Test function names describe the scenario
4. **Fixtures for reuse** - Use conftest.py factories, not repeated setup
5. **One assertion focus** - Each test has one main idea (can have multiple assertions supporting it)
