# Beanschedule Roadmap

Pre-release checklist and performance optimization opportunities before open sourcing.

---

## Status Overview

**Current Version**: v1.1.0 (Stable)
**Next Milestone**: v1.2.0 (Polish & Advanced Features)
**Vision**: v2.0.0+ (Advanced Capabilities)

| Item | Status | Version |
|------|--------|---------|
| Core matching & enrichment | ✅ Complete | v1.0 |
| Pattern discovery (detect) | ✅ Complete | v1.1 |
| Performance optimization | ✅ 80%+ speedup achieved | v1.0-v1.1 |
| Quality & testing | ✅ 86% coverage | v1.0-v1.1 |
| Error handling improvements | 🔄 Planned | v1.2 |
| Dry-run mode | 🔄 Planned | v1.2 |

---

## Completed Features (v1.0.0 - Core)

### Matching & Enrichment

- [x] Hook signature alignment with beangulp (accepting `existing_entries` directly)
- [x] Support for checking schedules against existing ledger entries
- [x] Placeholder generation format (always 4-tuple for beangulp compatibility)
- [x] Flexible recurrence patterns: MONTHLY, WEEKLY, YEARLY, INTERVAL, BIMONTHLY
- [x] Smart amount matching: exact, tolerance, range-based
- [x] Regex and fuzzy payee matching

### Code Quality & Performance

- [x] Lazy matching optimization (80%+ speedup verified)
- [x] Payee pattern compilation & caching (40-50% additional speedup)
- [x] Fix logging to use deferred formatting (not f-strings)
- [x] Resolve ruff linting errors (91/99 violations fixed)
- [x] Type hints completion (100% coverage)
- [x] Comprehensive docstrings for all modules

### Testing

- [x] Unit tests for core matching logic (28/28 passing)
- [x] Lazy matching tested and verified (80%+ speedup confirmed)
- [x] Removed dead code (unused fixtures)

---

## Completed Features (v1.1.0 - Pattern Discovery)

### New CLI Commands

- [x] **`beanschedule create`** - Interactive schedule creation from ledger transaction
  - All 5 recurrence frequency types (MONTHLY, WEEKLY, YEARLY, INTERVAL, BIMONTHLY)
  - Match criteria customization with sensible defaults
  - YAML preview and confirmation workflow

- [x] **`beanschedule detect`** - Auto-detect recurring transaction patterns
  - Hierarchical transaction grouping (account → fuzzy payee → amount tolerance)
  - Gap analysis with median/mean/std dev calculation
  - Frequency detection: weekly, bi-weekly, monthly, quarterly, yearly
  - Confidence scoring based on coverage (50%) + regularity (30%) + sample size (20%)
  - Descriptive schedule IDs combining payee + frequency
  - Full account names in output (no truncation)
  - Integration with `beanschedule create` via command suggestions
  - 38 comprehensive unit tests with 90% code coverage

- [x] **`beanschedule show`** - Display schedule details and next transactions
  - Shows recurrence pattern and match account
  - Displays next N scheduled transaction dates (default: 5)

- [x] Other commands: `list`, `validate`, `generate`, `init`

### Testing & Quality

- [x] Pattern detection tests (38/38 passing)
  - Transaction grouping (7 tests)
  - Gap analysis (4 tests)
  - Frequency detection (6 tests)
  - Confidence scoring (4 tests)
  - Full detection pipeline (7 tests)
  - Edge cases (5 tests)
- [x] Integration tests using real examples (11+ tests)
- [x] Code coverage: 86% total

---

## In Progress / Next Up

### v1.2.0 - Polish & Advanced Features

#### High Priority

- [ ] Error handling improvements
  - [ ] Graceful handling of invalid schedule YAML syntax
  - [ ] Better error messages for misconfigured matching criteria
  - [ ] Validation of recurrence rules at load time

- [ ] Dry-run mode (`--dry-run` flag for testing without committing)

#### Medium Priority

- [ ] Edge case testing
  - [ ] Leap year handling in recurrence
  - [ ] DST transitions
  - [ ] Schedules with no transactions in ledger

- [ ] CSV export for matched transactions

- [ ] Interactive mode for confirming fuzzy matches above threshold

- [ ] Performance: Skip unnecessary ledger matching (5-10% speedup)
  - Logic: If no transactions in ledger have `schedule_id` metadata, skip ledger matching

### v1.3.0 - Enhanced Flexibility

- [ ] Remove account matching limitation
  - Allow schedules to match from any account (not just the configured one)
  - Add optional `match.account` field (if present, enforce; if absent, match any account)

- [ ] Conditional schedule instances (skip if conditions not met)
  - Skip generating a scheduled instance if conditions are not met
  - Use cases: skip transfer if credit card balance is zero

- [ ] Schedule statistics command (coverage report, match rates over time)

---

## Performance Optimizations

### Completed

**Lazy Matching Strategy** (80%+ speedup)
- Built date→transaction index from ledger once
- For each schedule occurrence, only check transactions within `date_window_days`
- Reduced comparisons from 14k*43 to ~300-500*43

**Payee Pattern Compilation** (40-50% speedup)
- Added regex pattern caching in `TransactionMatcher.__init__`
- Lazy compilation on first use with cache reuse
- Fuzzy match result caching keyed by (payee, pattern) tuples

**Performance Baseline** (M2 MacBook Pro, 14,874 ledger entries, 43 schedules)
- Before lazy matching: ~45 seconds
- After lazy matching: ~5-10 seconds
- Target after remaining optimizations: ~2-3 seconds

### Remaining Opportunities

| Item | Impact | Effort | Status |
|------|--------|--------|--------|
| Skip ledger matching when no `schedule_id` | 5-10% | Trivial | ⏳ v1.2 |
| Bulk transaction filtering (filter by account) | 20-30% | Medium | ⏳ v1.3 |
| Recurrence caching | 10-15% | Low | ⏳ v1.3+ |
| Batch scoring (vectorized operations) | 15-25% | Medium-High | ⏳ v2.0 |
| Parallel processing | 2-3x | High | ⏳ v2.0 |
| Incremental mode | Minimal | Medium | ⏳ v2.0 |

**Current Bottleneck**: Payee pattern matching and fuzzy matching via `SequenceMatcher` (takes ~1-2s of the 5-10s total)

---

## Testing & Quality Status

### Code Coverage: 86%

| Component | Status | Coverage |
|-----------|--------|----------|
| Matcher | ✅ | 28/28 tests passing |
| Detector | ✅ | 38/38 tests passing, 90% coverage |
| Schema | ✅ | 34/34 tests passing |
| Hook | ✅ | 15/15 tests passing |
| Integration | ✅ | 11+ examples tested |

### Remaining Test Gaps

- [ ] Performance benchmarks (with/without optimizations)
- [ ] Regression testing for schedule formats
- [ ] CLI command tests
- [ ] Recurrence generation edge cases
- [ ] Loader validation

### Pre-Release Quality Checklist

- [x] Type hints: 100% coverage
- [x] Docstrings: All modules documented
- [x] Logging: Deferred formatting throughout
- [x] Linting: 91/99 violations resolved (ruff)
- [ ] CI/CD: GitHub Actions pipeline
- [ ] Code coverage reporting: codecov integration

---

## Known Limitations

### Current

1. **Ledger must fit in memory** - Not suitable for extremely large ledgers (100k+ entries)
2. **No multi-currency support** - Assumes all amounts in schedule currency
3. **Regex patterns only** - No glob patterns for payees
4. **Date matching only on exact date** - No "Nth weekday of month" rules
5. **No transaction dependencies** - Can't express "this payment depends on that income"

### By Design

1. No automatic posting generation beyond templates
2. No integration with beancount plugins directly (hook-based only)
3. Schedules are YAML (not Python) for simplicity and distribution

---

## Before Open Source Release

### Required

- [ ] MIT License badge in README ✅ (already present)
- [ ] CONTRIBUTING.md with development setup
- [ ] CODE_OF_CONDUCT.md
- [ ] CHANGELOG.md tracking all changes
- [ ] Security policy (SECURITY.md)
- [ ] GitHub issue templates
- [ ] Pull request template

### Highly Recommended

- [ ] PyPI package registration (currently local-only)
- [ ] GitHub Actions for automated testing
- [ ] Code coverage reporting (codecov)
- [ ] Release automation (semantic-release)
- [ ] Example configurations for common use cases

### Nice-to-Have

- [ ] Discord/community discussion space
- [ ] Blog post explaining the tool
- [ ] Video demo

---

## Documentation Roadmap

### Completed

- [x] README with quick start and feature overview
- [x] Example schedules in examples/ directory
- [x] Inline code documentation and docstrings

### Planned

- [ ] API documentation (Sphinx/mkdocs)
- [ ] Schedule YAML schema documentation with examples
- [ ] CLI command reference
- [ ] Getting started guide (with workflow)
- [ ] Troubleshooting guide (common matching failures)
- [ ] Migration guide (upgrading between versions)
- [ ] Architecture decision records (ADRs)

---

## Future Vision (v2.0.0+)

### Advanced Features

- [ ] Multi-currency support
- [ ] Advanced recurrence rules (nth weekday, complex patterns)
- [ ] Parallel processing for independent schedules (2-3x speedup)
- [ ] Incremental/watch mode for continuous monitoring
- [ ] Split schedules (one schedule → multiple postings based on rules)

### Extensibility

- [ ] Plugin system for custom matchers
- [ ] Custom pattern detection algorithms
- [ ] Integration with other accounting tools

---

## Questions for Users (Post-Release)

1. What's your ledger size? (to prioritize performance work)
2. What matching scenarios fail most often? (to improve fuzzy logic)
3. Would you use bulk export/review features?
4. Interest in dry-run / preview before commit?
5. Multi-currency ledgers? (common request?)
6. How do you currently bootstrap schedules? (manual YAML or would you use `generate`/`detect`?)
