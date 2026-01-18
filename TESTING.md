# Beanschedule Test Suite Implementation

## Overview

A comprehensive test suite for beanschedule with beangulp integration has been implemented. The test suite provides extensive coverage of core functionality and is designed to support productionalization and CI/CD integration.

## Implementation Status

### ✅ Completed (77 tests, 47% coverage)

#### 1. **conftest.py** - Test Fixtures and Helpers

- Transaction builders (`make_transaction`, `make_posting`)
- Schedule builders (`make_schedule`, `make_match_criteria`, `make_recurrence_rule`)
- Configuration fixtures (`make_global_config`, `make_schedule_file`)
- File fixtures (`temp_schedule_dir`, `temp_schedule_file`)
- Assertion helpers (`assert_transaction_enriched`, `assert_posting_amounts`)

#### 2. **test_schema.py** - Pydantic Model Validation (34 tests, 100% coverage)

- **TestMatchCriteria** (5 tests)
  - Valid match criteria creation
  - Amount tolerance validation
  - Date window validation

- **TestRecurrenceRule** (11 tests)
  - Monthly, weekly, yearly, bimonthly, interval frequencies
  - Day/month/interval range validation
  - Invalid value rejection

- **TestTransactionTemplate** (4 tests)
  - Metadata schedule_id requirement
  - Additional metadata handling

- **TestSchedule** (4 tests)
  - Valid schedule creation
  - ID mismatch validation
  - Schedule_id consistency checks

- **TestGlobalConfig** (5 tests)
  - Default configuration
  - Threshold bounds validation
  - Custom placeholder flag support

- **TestMissingTransactionConfig** (2 tests)
  - Default and custom configuration

- **TestScheduleFile** (2 tests)
  - Empty and populated schedule files

#### 3. **test_matcher.py** - Matching Algorithm (28 tests, 88% coverage)

- **TestPayeeMatching** (6 tests)
  - Exact payee match
  - Fuzzy matching with similarity
  - Regex pattern matching
  - Case-insensitive matching
  - Empty payee handling

- **TestAmountMatching** (8 tests)
  - Exact amount match
  - Amount within tolerance (linear decay)
  - Amount outside tolerance
  - Range-based matching
  - Null amount (matches anything)
  - Zero tolerance (exact only)

- **TestDateMatching** (3 tests)
  - Exact date match
  - Date within window
  - Date outside window

- **TestAccountMatching** (3 tests)
  - Required account match
  - Account mismatch returns 0.0
  - Account mismatch fails overall score

- **TestWeightedScoring** (3 tests)
  - Perfect match (1.0)
  - Partial match (0-1 range)
  - Weighted formula (40% payee, 40% amount, 20% date)

- **TestFindBestMatch** (5 tests)
  - Single candidate above threshold
  - No match below threshold
  - Best score selection from multiple candidates
  - Threshold boundary behavior
  - Empty candidate list

#### 4. **test_hook.py** - Beangulp Hook Integration (15 tests, 88% coverage)

- **TestScheduleHook** (4 tests)
  - No schedules found
  - No enabled schedules
  - Empty entries list
  - Non-transaction entries handling

- **TestHookEntryFormats** (1 test)
  - 4-tuple format support

- **TestTransactionMatching** (2 tests)
  - Single transaction matching
  - No match keeps original

- **TestTransactionEnrichment** (4 tests)
  - Metadata addition (schedule_id, matched_date, confidence)
  - Tag merging
  - Payee override
  - Narration override

- **TestPlaceholderCreation** (2 tests)
  - Placeholder creation for missing transactions
  - Placeholder disabled scenario

- **TestMultipleFiles** (1 test)
  - Multiple file processing

- **TestPostingReplacement** (1 test)
  - Posting replacement from schedule template

### 📋 Pending Implementation

#### 5. **test_recurrence.py** - Date Generation (est. 25 tests)

Expected tests for all 5 frequency types:

- MONTHLY: day of month, leap year handling, invalid days
- BIMONTHLY: multiple days per month
- WEEKLY: day of week, intervals (biweekly, etc.)
- YEARLY: annual dates, leap year
- INTERVAL: every N months

Date range clipping and edge cases

#### 6. **test_loader.py** - Schedule Loading (est. 20 tests)

- File mode loading (single schedules.yaml)
- Directory mode loading (_config.yaml + *.yaml files)
- Auto-discovery paths (env vars, current dir, parent dir)
- Error handling (missing files, invalid YAML, validation errors)
- Enabled/disabled schedule filtering
- Duplicate ID detection

#### 7. **test_cli.py** - CLI Commands (est. 15 tests)

- `validate` command
- `list` command with formats
- `generate` command
- `init` command
- `migrate` command

#### 8. **test_beangulp_integration.py** - End-to-End (est. 10 tests)

- Full import workflow
- Hook registration in HOOKS list
- Real importer integration
- Beangulp format compatibility

## Test File Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures
├── test_schema.py                   # 34 tests ✅
├── test_matcher.py                  # 28 tests ✅
├── test_hook.py                     # 15 tests ✅
├── test_recurrence.py              # Pending (25 tests)
├── test_loader.py                  # Pending (20 tests)
├── test_cli.py                     # Pending (15 tests)
├── test_beangulp_integration.py    # Pending (10 tests)
└── fixtures/
    ├── schedules/                   # Test schedule YAML files
    │   ├── _config.yaml
    │   ├── monthly-rent.yaml
    │   ├── bimonthly-paycheck.yaml
    │   ├── weekly-gym.yaml
    │   └── yearly-subscription.yaml
    └── beangulp/
        ├── config.py
        └── schedules/
```

## Coverage Summary

### Current Coverage (77 tests)

| Module | Coverage | Tests | Status |
|--------|----------|-------|--------|
| schema.py | 100% | 34 | ✅ Complete |
| matcher.py | 88% | 28 | ✅ Complete |
| hook.py | 88% | 15 | ✅ Complete |
| types.py | 100% | - | ✅ Validation |
| **init**.py | 100% | - | ✅ Export |
| recurrence.py | 37% | 0 | 📋 Pending |
| loader.py | 10% | 0 | 📋 Pending |
| cli.py | 0% | 0 | 📋 Pending |
| **Total** | **47%** | **77** | **In Progress** |

### Coverage Target

- **Overall:** 85%+ (ambitious: 90%)
- **Core modules** (matcher, hook, recurrence, loader): 90%+
- **Schema validation:** 100%
- **CLI:** 75%+ (some interactive portions excluded)

## Running the Tests

### Run all tests

```bash
uv run pytest tests/ -v
```

### Run specific test file

```bash
uv run pytest tests/test_schema.py -v
```

### Run with coverage report

```bash
uv run pytest tests/ --cov=beanschedule --cov-report=html --cov-report=term-missing
```

### Run specific test

```bash
uv run pytest tests/test_matcher.py::TestPayeeMatching::test_exact_payee_match -v
```

## Key Testing Patterns Used

### 1. Fixture-Based Builders

All test data is created using builder functions in conftest.py:

```python
txn = sample_transaction(date(2024, 1, 15), "Landlord", "Assets:Bank:Checking", Decimal("-1500.00"))
schedule = sample_schedule(payee_pattern="Landlord", amount=Decimal("-1500.00"))
```

### 2. Mocking External Dependencies

Hook tests mock `load_schedules_file()` to provide controlled test scenarios:

```python
with patch("beanschedule.hook.load_schedules_file", return_value=schedule_file):
    result = schedule_hook(extracted_entries)
```

### 3. Real YAML Files for Integration Tests

Test schedule YAML files are provided for loader and integration tests:

- `tests/fixtures/schedules/_config.yaml` - Global configuration
- `tests/fixtures/schedules/monthly-rent.yaml` - Example schedules

### 4. Assertion Helpers

Custom assertions for cleaner test code:

```python
assert_transaction_enriched(txn, expected_schedule_id="rent")
assert_posting_amounts(txn, {"Assets:Bank:Checking": Decimal("-1500.00")})
```

## Critical Test Coverage Areas

### ✅ Implemented

1. **Pydantic Schema Validation** - All model constraints tested
2. **Matching Algorithm** - All scoring components (account, payee, amount, date)
3. **Hook Integration** - Entry processing, enrichment, placeholders
4. **Transaction Enrichment** - Metadata, tags, payee/narration override

### 📋 Pending (High Priority)

1. **Recurrence** - All 5 frequency types with edge cases
2. **File Loading** - Both directory and file modes
3. **End-to-End** - Real beangulp workflow
4. **CLI Commands** - All command validation and output

## Edge Cases Covered

### ✅ Already Tested

- Account mismatch fails entire match
- Score below threshold returns None
- Empty transaction list
- Non-transaction entries (Open, Close, Balance)
- Tag merging with duplicates
- Payee/narration override
- Placeholder creation for missing transactions

### 📋 To Test

- Day 31 in February (invalid)
- Leap year February 29
- Score exactly at threshold (0.80)
- Empty/null field handling
- Multiple files with different accounts
- Disabled schedules
- Regex pattern error handling

## Continuous Integration Setup

Ready for GitHub Actions CI/CD with:

```yaml
- Python 3.9 through 3.13
- Run pytest with coverage
- Generate coverage reports
- Fail on coverage < 85%
- Run linting (ruff, black, mypy)
```

## Next Steps

1. Implement `test_recurrence.py` (25 tests) - Date generation for all frequency types
2. Implement `test_loader.py` (20 tests) - File/directory loading
3. Implement `test_cli.py` (15 tests) - CLI commands
4. Implement `test_beangulp_integration.py` (10 tests) - End-to-end scenarios
5. Run full suite and achieve 85%+ coverage target
6. Commit and prepare for productionalization

## Notes

- All tests use `pytest` with fixtures
- Test data uses realistic examples from production use cases
- Mocking is used judiciously - real files for integration, mocks for unit isolation
- Tests are designed to be fast (<1 second for full suite)
- Coverage reports generated in HTML format for easy review

---

**Implementation Date:** January 2026
**Current Status:** 77 tests, 47% coverage - Foundation complete, core functionality tested
