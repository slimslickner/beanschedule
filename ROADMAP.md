# Beanschedule Roadmap

Pre-release checklist and performance optimization opportunities before open sourcing.

## Status: Beta → Production Ready

---

## Core Fixes & Stability

### ✅ Fixed

- [x] Hook signature alignment with beangulp (accepting `existing_entries` directly)
- [x] Support for checking schedules against existing ledger entries
- [x] Placeholder generation format (always 4-tuple for beangulp compatibility)
- [x] Lazy matching optimization (80%+ performance improvement verified)

### 🔄 In Progress / Todo

- [ ] Error handling improvements
  - [ ] Graceful handling of invalid schedule YAML syntax
  - [ ] Better error messages for misconfigured matching criteria
  - [ ] Validation of recurrence rules at load time
- [ ] Type hints completion (currently ~90% coverage)
- [ ] Comprehensive docstrings for public API
- [ ] Edge case testing
  - [ ] Leap year handling in recurrence
  - [ ] DST transitions
  - [ ] Schedules with no transactions in ledger

---

## Performance Optimizations

**Current Bottleneck**: Payee pattern compilation and fuzzy matching via `SequenceMatcher`. Current run: **5-10 seconds** (down from 45s with lazy matching).

### ✅ Completed

#### 1. **Lazy Matching Strategy** ⭐⭐⭐⭐⭐

Only match transactions that fall within expected date windows, not all historical transactions.

- **Impact**: 90%+ speedup when ledger has years of data ✅ VERIFIED
- **Effort**: Medium ✅ DONE
- **Implementation**:
  - ✅ Built date→transaction index from ledger once
  - ✅ For each schedule occurrence, only check transactions within schedule's `date_window_days`
  - ✅ Reduced comparisons from 14k*43 to ~300-500*43
  - ✅ Only ledger transactions with explicit `schedule_id` metadata block placeholders (prevents false matches)

### High Priority (Critical - Next)

#### 2. **Payee Pattern Compilation** ⭐⭐⭐⭐

Pre-compile regex patterns and cache fuzzy match results.

- **Impact**: 40-50% speedup
- **Effort**: Low
- **Implementation**:

  ```python
  # In TransactionMatcher.__init__:
  self.compiled_patterns = {}
  for schedule in schedules:
      if self._is_regex_pattern(pattern):
          self.compiled_patterns[schedule.id] = re.compile(pattern, re.IGNORECASE)

  # Cache fuzzy match results (payee rarely changes within a ledger)
  self.fuzzy_cache = {}
  ```

#### 3. **Skip Ledger Matching When No Schedule Has schedule_id** ⭐⭐⭐

- **Impact**: 5-10% speedup
- **Effort**: Trivial
- **Logic**: If no transactions in ledger have `schedule_id` metadata, skip ledger matching entirely

### Medium Priority

#### 4. **Bulk Transaction Filtering**

Only extract and match transactions for accounts that have active schedules.

- **Impact**: 20-30% speedup
- **Effort**: Medium
- **Implementation**:
  - Build set of account→schedules map
  - Filter ledger entries before matching loop
  - Skip accounts with no active schedules

#### 5. **Recurrence Caching**

Cache generated occurrences across multiple hook runs (useful in repl/testing).

- **Impact**: 10-15% speedup on repeated runs
- **Effort**: Low
- **Note**: Need to consider cache invalidation on schedule file changes

#### 6. **Batch Scoring**

Use vectorized operations (numpy) for score calculations instead of per-transaction loops.

- **Impact**: 15-25% speedup
- **Effort**: Medium-High
- **Tradeoff**: Adds numpy dependency

### Low Priority (Nice-to-Have)

#### 7. **Parallel Processing**

- Use multiprocessing for matching independent schedules
- **Impact**: 2-3x speedup on multi-core systems
- **Effort**: High
- **Tradeoff**: Complexity, thread-safety concerns with logging

#### 8. **Incremental Mode**

Track which transactions were already matched, only process new imports.

- **Impact**: Minimal for normal use (most value in development/testing)
- **Effort**: Medium

---

## Feature Completeness

### High Priority (UX - Getting Started)

- [ ] **CLI: Generate schedule template from transaction** ⭐⭐⭐⭐⭐
  - `beanschedule generate --date 2024-01-15 --ledger path/to/ledger.bean`
  - Prompts user to select a transaction from that date
  - Creates a schedule YAML template with that transaction's details (payee, amount, account)
  - User fills in recurrence pattern
  - **Impact**: Drastically reduces friction for new users bootstrapping schedules
  - **Effort**: Medium

- [ ] **CLI: Auto-detect recurring transactions** ⭐⭐⭐⭐
  - `beanschedule detect --ledger path/to/ledger.bean [--confidence 0.8]`
  - Analyzes ledger to find likely recurring transactions
  - Shows user suggestions: "Found monthly mortgage (confidence: 95%)", "Found quarterly utilities (confidence: 78%)"
  - Option to auto-create schedule templates for detected patterns
  - **Impact**: Users can auto-generate 50-80% of schedules instead of manual entry
  - **Effort**: High (requires recurring pattern detection algorithm)
  - **Algorithm Details**:
    - Group transactions by similar payee/amount (fuzzy matching, configurable tolerance)
    - Analyze date gaps between matching transactions in sorted order
    - Detect patterns: monthly (28-31 days), quarterly (~90 days), annual (~365 days), weekly (7 days), bi-weekly (14 days)
    - Handle edge cases: transactions on different days of month (1st vs 15th), leap years
    - Calculate confidence score based on regularity (e.g., 95% if 19/20 months present)
    - Filter out noise: require minimum 3 occurrences before suggesting
    - Output candidates sorted by confidence with user preview

- [ ] **Interactive setup wizard** ⭐⭐⭐⭐
  - `beanschedule init` - guided setup for new users
  - Walk through: where to store schedules, which accounts to monitor, basic schedule creation
  - **Impact**: Excellent first-time user experience
  - **Effort**: Medium

### Medium Priority

- [ ] Dry-run mode (`--dry-run` flag for testing without committing)
- [ ] Export matched transactions to CSV for review
- [ ] Interactive mode for confirming fuzzy matches above threshold
- [ ] Schedule statistics command (coverage report, match rates over time)
- [ ] Schedule summary and next transaction command ⭐⭐⭐
  - `beanschedule show <schedule_id> [--count N]`
  - Shows schedule details: payee, recurrence pattern, match account
  - Displays next N scheduled transaction dates (default: 5)
  - Shows last matched transaction date (if any)
  - **Impact**: Quick way to see when a schedule is due and verify configuration
  - **Effort**: Low
- [ ] Remove account matching limitation ⭐⭐⭐
  - Allow schedules to match from any account (not just the configured one)
  - Add optional `match.account` field (if present, enforce; if absent, match any account)
  - Useful for flexibility when paying bills from different accounts
  - **Impact**: More flexible matching for real-world scenarios where payment source varies
  - **Effort**: Low
- [ ] Zerosum account support for transfers ⭐⭐⭐⭐
  - Single schedule definition for credit card transfers using zerosum plugin
  - Currently requires two separate schedules (one for each half of the transfer)
  - Add support for defining both postings (source account and zerosum account) in one schedule
  - Example: one schedule for "CC payment" generates both the expense side and the transfer
  - **Impact**: Dramatically reduces schedule complexity for transfer-heavy workflows
  - **Effort**: Medium (requires understanding zerosum plugin behavior, multi-posting generation)
  - **Priority**: High - improves user experience for common use case
- [ ] Conditional schedule instances (skip if conditions not met) ⭐⭐
  - Skip generating a scheduled instance if conditions are not met
  - Use cases: skip transfer if credit card balance is zero, skip payment if no budget remaining
  - Could be implemented as: `condition: skip_if_zero_balance`, or more general conditional logic
  - **Impact**: Prevents unnecessary placeholder transactions for optional/conditional payments
  - **Effort**: Medium (requires balance/account state querying)
- [ ] Support for split schedules (one schedule can generate multiple postings based on rules)

---

## CLI Commands

### Current (v1.0.0)

- `beanschedule` (no args) - shows help/version

### Planned (v1.1.0+)

- [ ] `beanschedule generate` - Create schedule template from a transaction
- [ ] `beanschedule detect` - Auto-detect recurring transactions in ledger
- [ ] `beanschedule init` - Interactive setup wizard
- [ ] `beanschedule validate` - Validate schedule YAML files for syntax/logic errors
- [ ] `beanschedule stats` - Show schedule coverage and match statistics
- [ ] `beanschedule export` - Export matched transactions to CSV

---

## Testing & Quality

- [x] Unit tests for core matching logic (22/22 passing)
- [x] Lazy matching tested and verified (80%+ speedup confirmed)
- [x] **Integration tests using examples/** ✅ (11 tests total)
  - [x] Load example.beancount as existing ledger
  - [x] Process against examples/schedules/* (11+ real, realistic schedules)
  - [x] Verify matching behavior against real transaction patterns
  - [x] TestExamplesIntegration class with 9 comprehensive tests
  - [x] **TestPerScheduleIntegration class** - Tests each schedule with synthetic imports + real ledger
  - [x] All 11+ example schedules are now directly tested
- [x] Removed dead code
  - [x] Deleted unused `sample_posting` fixture
  - [x] Deleted unused `custom_global_config` fixture
  - [x] Removed synthetic integration test classes (replaced with real examples)
- [ ] Performance benchmarks (with/without optimizations)
- [ ] Regression testing for schedule formats
- [ ] Tests for recurring pattern detection algorithm
- [ ] CI/CD pipeline (GitHub Actions)
- [x] **Code coverage: 86%** ✅ (target: 85%+ - EXCEEDED!)

---

## Documentation

- [x] README with basic usage
- [ ] API documentation (Sphinx/mkdocs)
- [ ] Schedule YAML schema documentation with examples
- [ ] CLI command reference
- [ ] Getting started guide (with `beanschedule generate` workflow)
- [ ] Troubleshooting guide (common matching failures)
- [ ] Migration guide (upgrading between versions)
- [ ] Architecture decision records (ADRs)

---

## Before Open Source Release

### Required

- [ ] MIT License badge in README
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

## Version Roadmap

### v1.0.0 (Current - Beta) ✅

- [x] Core matching and enrichment
- [x] Placeholder generation
- [x] Basic ledger integration
- [x] Lazy matching optimization (80%+ speedup)

### v1.1.0 (Next - Performance & Setup)

- [ ] Pattern compilation & caching (40% speedup)
- [ ] Skip unnecessary ledger matching (5-10% speedup)
- [ ] Bulk transaction filtering (20-30% speedup)
- [x] **Integration tests using examples/** ✅ - Load example.beancount and real schedules (9 tests)
- [ ] **CLI: `beanschedule generate`** - Create schedule template from a transaction
- [ ] Performance benchmarking

### v1.2.0 (Soon After - Features & Polish)

- [ ] **CLI: `beanschedule detect`** - Auto-detect recurring transactions in ledger
- [ ] **CLI: `beanschedule init`** - Interactive setup wizard
- [ ] **CLI: `beanschedule validate`** - Validate schedule YAML files
- [ ] **CLI: `beanschedule show`** - Display schedule summary and next scheduled transactions
- [ ] **CLI: `beanschedule stats`** - Schedule coverage and match statistics
- [ ] Dry-run mode for hook
- [ ] CSV export for matched transactions

### v1.3.0 (Polish)

- [ ] Interactive mode for confirming fuzzy matches above threshold
- [ ] Better error messages and validation
- [ ] Recurrence caching for performance

### v2.0.0 (Longer term - Advanced Features)

- [ ] Multi-currency support
- [ ] Advanced recurrence rules (nth weekday, complex patterns)
- [ ] Parallel processing
- [ ] Incremental/watch mode
- [ ] Split schedules (one schedule → multiple postings based on rules)

---

## Performance Baseline

*Measured on M2 MacBook Pro with 14,874 ledger entries and 43 schedules*

- **Before lazy matching**: ~45 seconds
- **After lazy matching**: ~5-10 seconds ✅ (80%+ reduction achieved!)
- **Target after remaining optimizations**: ~2-3 seconds

---

## Open Source Considerations

- Repository already on GitHub (private)
- Dependencies: beancount, beangulp, pydantic, pyyaml (all popular/maintained)
- No GPL dependencies (MIT/Apache licensed)
- Python 3.9+ support
- Cross-platform (macOS, Linux, Windows)

---

## Questions for Users (Post-Release)

1. What's your ledger size? (to prioritize performance work)
2. What matching scenarios fail most often? (to improve fuzzy logic)
3. Would you use bulk export/review features?
4. Interest in dry-run / preview before commit?
5. Multi-currency ledgers? (common request?)
6. How do you currently bootstrap schedules? (manual YAML or would you use `generate`/`detect`?)
