# Beanschedule Roadmap

Roadmap for open-sourcing beanschedule with focus on code quality, documentation, and release readiness.

---

## Current Status

| Metric | Value | Target |
|--------|-------|--------|
| **Version** | v1.2.0 | v1.3.0 (Open Source Release) |
| **Test Coverage** | 86% | 90%+ |
| **Type Hints** | ~90% | 100% |
| **Docstrings** | ~85% | 100% |

### What's Working

- Core matching & enrichment with 80%+ performance optimization
- Pattern discovery (`beanschedule detect`)
- Loan amortization (static and stateful modes)
- CLI commands: `validate`, `list`, `show`, `generate`, `create`, `detect`, `amortize`, `init`
- 86% test coverage across all modules

---

## Open Source Release Checklist

### Critical (Blocking Release)

| Task | Status | Notes |
|------|--------|-------|
| Fix README URLs | ❌ | Change `yourusername` → `slimslickner` |
| Fix README Python version | ❌ | Says "3.9+" but requires 3.11+ |
| Remove dead README links | ❌ | `docs/` directory doesn't exist |
| Create CONTRIBUTING.md | ❌ | Referenced but missing |
| Create CHANGELOG.md | ❌ | Referenced in pyproject.toml |
| Create CODE_OF_CONDUCT.md | ❌ | Standard for open source |
| Create SECURITY.md | ❌ | Security policy |
| Add GitHub Actions CI | ❌ | `.github/workflows/` is empty |
| Move ruff to dev deps | ❌ | Currently in runtime dependencies |
| Remove dead code | ❌ | `_match_ledger_transactions()` in hook.py |

### High Priority (Should Fix Before Release)

| Task | Status | Notes |
|------|--------|-------|
| Create `constants.py` | ❌ | Extract 15+ magic strings |
| Extract `slugify` to utils.py | ❌ | Circular import risk in detector.py |
| Add issue templates | ❌ | Bug report, feature request |
| Add PR template | ❌ | Standard checklist |
| Consolidate duplicate code | ❌ | `_generate_bimonthly` == `_generate_monthly_on_days` |
| Add helper `load_schedules_from_path()` | ❌ | Reduce CLI duplication |

### Medium Priority (Polish)

| Task | Status | Notes |
|------|--------|-------|
| Split cli.py into submodules | ❌ | 1,733 lines - too large |
| Make tests deterministic | ❌ | Inject `today` instead of `date.today()` |
| Add edge case tests | ❌ | Leap year, empty inputs, boundaries |
| Add regex complexity validation | ❌ | Prevent ReDoS attacks |
| Fix type hint gaps | ❌ | ~10% missing |

---

## Code Quality Issues

### Magic Strings to Extract

Create `beanschedule/constants.py`:

```python
# Synthetic filepaths
SYNTHETIC_SCHEDULES_FILEPATH = "<schedules>"

# Config files
CONFIG_FILENAME = "_config.yaml"

# Date handling
DATE_BUFFER_DAYS = 7
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = 365

# Frequency detection thresholds (days)
WEEKLY_GAP_RANGE = (6, 8)
BIWEEKLY_GAP_RANGE = (12, 16)
MONTHLY_GAP_RANGE = (25, 35)
QUARTERLY_GAP_RANGE = (85, 95)
YEARLY_GAP_RANGE = (355, 375)

# Default values
DEFAULT_MISSING_PREFIX = "[MISSING]"
DEFAULT_DATE_WINDOW_DAYS = 3
```

### Dead Code to Remove

| File | Function/Code | Reason |
|------|---------------|--------|
| `hook.py:448-525` | `_match_ledger_transactions()` | Never called, duplicates `_match_ledger_transactions_lazy()` |
| `recurrence.py:157-181` | `_generate_bimonthly()` | Identical to `_generate_monthly_on_days()` |

### Duplicate Code to Consolidate

**CLI schedule loading** (appears 5+ times):
```python
# Extract to loader.py
def load_schedules_from_path(path: Path) -> Optional[ScheduleFile]:
    """Load schedules from file or directory path."""
    if path.is_file():
        return load_schedules_file(path)
    elif path.is_dir():
        return load_schedules_from_directory(path)
    return None
```

### Architecture Improvements

**Split `cli.py` (1,733 lines) into:**
- `cli/commands.py` - Click command definitions
- `cli/formatters.py` - Output formatting (table, CSV, JSON)
- `cli/builders.py` - Schedule construction helpers

**Fix circular import:**
- Move `slugify()` from `cli.py` to `utils.py`
- `detector.py:686` imports from cli at runtime

---

## Test Improvements

### Missing Edge Case Tests

| Module | Test Cases Needed |
|--------|-------------------|
| `recurrence.py` | Leap year (Feb 29), DST transitions, end_date == start_date |
| `matcher.py` | Empty payee strings, None posting units, negative date window |
| `loader.py` | Circular imports, deeply nested directories, symlinks |
| `detector.py` | Single transaction groups, all same-day transactions |

### Test Quality Issues

| Issue | Location | Fix |
|-------|----------|-----|
| Time-dependent tests | `hook.py:660` | Inject `today` parameter instead of `date.today()` |
| Deprecated fixture | `conftest.py:119` | `make_match_criteria` uses deprecated `amount` field |
| Missing assertions | `test_hook.py` | Some tests only check no exception raised |

---

## Documentation Fixes

### README.md Issues

| Line | Issue | Fix |
|------|-------|-----|
| 6, 583-584 | Wrong username | `yourusername` → `slimslickner` |
| 552-557 | Dead links | Remove `docs/` references or create directory |
| 561 | Wrong Python version | "3.9+" → "3.11+" |
| 571 | Missing file | Create CONTRIBUTING.md |

### Files to Create

1. **CONTRIBUTING.md** - Development setup, PR guidelines, code style
2. **CHANGELOG.md** - Version history (use Keep a Changelog format)
3. **CODE_OF_CONDUCT.md** - Contributor Covenant
4. **SECURITY.md** - Security policy and reporting

---

## Performance Optimizations

### Completed

| Optimization | Impact | Status |
|--------------|--------|--------|
| Lazy matching (date index) | 80%+ speedup | ✅ |
| Regex pattern caching | 40-50% speedup | ✅ |
| Fuzzy match caching | 10-20% speedup | ✅ |

**Baseline** (M2 MacBook, 14,874 entries, 43 schedules): ~5-10 seconds

### Remaining Opportunities

| Optimization | Impact | Effort | Priority |
|--------------|--------|--------|----------|
| Skip ledger matching when no `schedule_id` | 5-10% | Trivial | High |
| Recurrence result caching | 10-15% | Low | Medium |
| Bulk transaction filtering by account | 20-30% | Medium | Medium |
| Parallel processing | 2-3x | High | Future |

---

## Feature Roadmap

### v1.3.0 - Open Source Release

Focus: Code quality, documentation, CI/CD

- [ ] All critical release checklist items
- [ ] All high priority code quality fixes
- [ ] GitHub Actions CI pipeline
- [ ] PyPI package registration

### v1.4.0 - Polish

- [ ] Dry-run mode (`--dry-run` flag)
- [ ] One-time/ad-hoc schedules (`ONCE` frequency)
- [ ] `beanschedule quick` - guided schedule creation
- [ ] CSV export for matched transactions
- [ ] Interactive fuzzy match confirmation

### v1.5.0 - Enhanced Flexibility

- [ ] Optional account matching (match any account if not specified)
- [ ] Conditional schedule instances (skip based on conditions)
- [ ] Schedule statistics command (coverage report, match rates)
- [ ] Advanced amortization (ARM, balloon payments, interest-only periods)

### v2.0.0+ - Future Vision

- [ ] Multi-currency support
- [ ] Parallel processing for independent schedules
- [ ] Plugin system for custom matchers
- [ ] Incremental/watch mode
- [ ] Integration with other accounting tools

---

## Known Limitations

### Current

1. **Ledger must fit in memory** - Not suitable for 100k+ entries
2. **No multi-currency support** - All amounts in schedule currency
3. **Regex patterns only** - No glob patterns for payees
4. **No transaction dependencies** - Can't express "this depends on that"
5. **Static amortization overrides are experimental** - Use stateful mode instead

### By Design

1. Schedules are YAML (not Python) for simplicity
2. No automatic posting generation beyond templates
3. Hook-based integration (not direct beancount plugin)

---

## Completed Features

<details>
<summary>v1.0.0 - Core (Click to expand)</summary>

- Hook signature alignment with beangulp
- Support for checking schedules against existing ledger entries
- Placeholder generation (4-tuple beangulp format)
- Flexible recurrence: MONTHLY, WEEKLY, YEARLY, INTERVAL, BIMONTHLY
- Smart amount matching: exact, tolerance, range-based
- Regex and fuzzy payee matching
- Lazy matching optimization (80%+ speedup)
- Payee pattern compilation & caching
- Unit tests for core matching (28/28 passing)

</details>

<details>
<summary>v1.1.0 - Pattern Discovery (Click to expand)</summary>

- `beanschedule create` - Interactive schedule creation
- `beanschedule detect` - Auto-detect recurring patterns
- `beanschedule show` - Display schedule details
- Commands: `list`, `validate`, `generate`, `init`
- Basic amortization schedules (PMT formula)
- Explicit `role` fields for postings
- Pattern detection tests (38/38 passing)
- Integration tests (11+ examples)

</details>

<details>
<summary>v1.2.0 - Stateful Amortization (Click to expand)</summary>

- `balance_from_ledger` mode for amortization
- Compounding: MONTHLY and DAILY
- Cleared + pending transaction balance computation
- Negative amortization detection
- Stale-balance warnings
- Removed dead `plugins/forecast.py`
- Fixed amount-tolerance matcher tests
- Fixed `make_schedule` fixture kwargs

</details>

---

## Questions for Users (Post-Release)

1. What's your ledger size? (prioritize performance work)
2. What matching scenarios fail most often? (improve fuzzy logic)
3. Would you use bulk export/review features?
4. Interest in dry-run / preview before commit?
5. Multi-currency ledgers? (common request?)
6. How do you bootstrap schedules? (manual YAML or detect?)
