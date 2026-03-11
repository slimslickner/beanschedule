# Roadmap

Improvement areas identified from a full repository review.

## Top Priority

- [x] **Multi-currency postings in schedule YAML** — allow individual postings to specify a currency other than the default (e.g., vacation days accrued as `VACDAY`, RSU grants as `STOCK`). A posting with a non-default currency would include an explicit `currency` key alongside its `amount`. This enables paycheck schedules with mixed-unit postings like salary (USD), vacation accrual (VACDAY), and vested shares (TSLA) in a single schedule entry.

- [x] **Read `operating_currency` from ledger options** — `GlobalConfig.default_currency` currently defaults to `"USD"` and is never read from the ledger's `option "operating_currency"` directive. When no explicit `default_currency` is set in `beanschedule.yaml`, the hook should fall back to the ledger's `operating_currency`.

## Quick Wins (< 1 day)

- [ ] **Add GitHub Actions CI workflow** — `.github/workflows/` exists but is empty; add test + lint + type-check pipeline
- [ ] **Replace `assert` with `raise ValueError`** in `cli/commands.py` (~3 places) — `assert` is stripped by `python -O`
- [ ] **Log warning on metadata parse failure** in `hook.py` — `schedule_matched_date` parse errors silently fall back to `entry.date`

## High Value (1-2 days)

- [ ] **Fix summary log counts** in `hook.py:_log_summary()` — shows "matched/matched" instead of "matched/expected"
- [ ] **Add schema validation for frequency-specific fields** — e.g., MONTHLY with no `day_of_month` silently generates zero dates instead of failing at load time
- [ ] **Add dependency upper bounds** in `pyproject.toml` — e.g., `beancount>=3.2.0,<4.0.0` to prevent breakage on major upgrades
- [ ] **Fix date range buffer with `min_forecast_date`** in `hook.py` — buffer is applied then overridden by `min()`, losing the buffer

## Medium Term (1 week)

- [ ] **Improve test coverage to 85%** — main gaps in hook.py error paths, plugin, and amortization
- [ ] **Use `freezegun` for date-sensitive tests** — several tests use hardcoded absolute dates that will age poorly
- [ ] **Fix amortization rounding** — static mode uses raw division while stateful mode uses `quantize()`; intermediate balances aren't quantized
- [ ] **Strengthen matcher test assertions** — e.g., `0.7 < score < 1.0` is too loose to catch regressions
- [ ] **Add error path tests** — most tests are happy-path; few test malformed input, corrupted metadata, or I/O failures

## Nice to Have (ongoing)

- [ ] **Add pre-commit hooks** (`.pre-commit-config.yaml`) — automate ruff/ty checks before commits
- [ ] **Publish to PyPI** — project is at v1.4.1 and production-ready; README says "not yet published"
- [ ] **Add performance/regression tests** — no tests for lazy matching optimization or large dataset behavior
- [ ] **Fix silent error swallowing in `recurrence.py`** — catches all exceptions and returns `[]`, masking real bugs
- [ ] **Fix silent config parse errors in `plugins/schedules.py`** — malformed JSON config falls back to file path with no warning
- [ ] **Optimize `utils.py` date window check** — `filter_occurrences_by_existing_transactions` is O(n^2), could be O(n) with a date set
- [ ] **Combine duplicate ID detection in `loader.py`** — iterates schedule list twice; easily merged into one pass
