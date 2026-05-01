# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.0]

### Changed

- **Recurrence rules now use RRULE format (RFC 5545)** — The `recurrence` block in schedule YAML files now uses a single `rrule` string instead of discrete `frequency`, `day_of_month`, `day_of_week`, etc. fields. Examples:

  ```yaml
  # Before
  recurrence:
    frequency: MONTHLY
    start_date: 2024-01-15
    day_of_month: 15

  # After
  recurrence:
    rrule: FREQ=MONTHLY;BYMONTHDAY=15
    start_date: 2024-01-15
  ```

  Common patterns:
  - Monthly on day 15: `FREQ=MONTHLY;BYMONTHDAY=15`
  - Biweekly on Friday: `FREQ=WEEKLY;INTERVAL=2;BYDAY=FR`
  - Quarterly on 1st: `FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1`
  - Yearly (Sep 15): `FREQ=YEARLY;BYMONTH=9;BYMONTHDAY=15`
  - Last day of month: `FREQ=MONTHLY;BYMONTHDAY=-1`
  - 2nd Tuesday: `FREQ=MONTHLY;BYDAY=+2TU`
  - Multiple days (5th & 20th): `FREQ=MONTHLY;BYMONTHDAY=5,20`

  **Old format files continue to load without changes** — the loader migrates them transparently at parse time.

### Added

- **`beanschedule migrate [path]`** — Rewrites schedule YAML files from the old `frequency`/`day_of_month` format to `rrule` in-place. Use `--dry-run` to preview changes without writing.

  ```bash
  beanschedule migrate schedules/           # migrate all files
  beanschedule migrate --dry-run schedules/ # preview only
  ```

### Removed

- `RecurrenceRule` fields `frequency`, `day_of_month`, `month`, `day_of_week`, `interval`, `days_of_month`, `interval_months`, `nth_occurrence` replaced by single `rrule` string. The `FrequencyType` and `DayOfWeek` enums are retained for internal detector use.

## [1.5.1]

### Added

- **`beanschedule pending fix` command** — Converts deprecated `;;` posting comments to proper `narration:` metadata. Run this command before importing to fix deprecated comment syntax in `pending.beancount` files:

  ```bash
  # Preview changes
  beanschedule pending fix --dry-run

  # Apply fixes
  beanschedule pending fix
  ```

  Transforms:
  ```beancount
  Expenses:Shopping  50.00 USD  ;; Item description
  ```
  Into:
  ```beancount
  Expenses:Shopping  50.00 USD
    narration: "Item description"
  ```

- **`beanschedule list --format match`** — New output format showing each schedule's ID, match account, and expected amount (exact ± tolerance, range, or `(any)`). Useful for quickly auditing match criteria without the full schedule table.

- **`beanschedule show --postings`** — New flag to display a schedule's transaction postings as a table. Columns: account, amount, currency, role, and one column per unique metadata key (pivoted across all postings).

- Missing scheduled transaction warnings now include the expected amount and account on each line, making it easier to identify which transactions are overdue at a glance.

### Fixed

- **Plugin duplicate forecast when posting date exceeds `date_window_days`** — `filter_occurrences_by_existing_transactions` now reads `schedule_matched_date` metadata (written by the hook at enrich time) as the anchor for the covered-date window, falling back to `txn.date` when absent. Fixes the case where the bank posts outside the schedule's window (e.g., expected 2026-02-28, posted 2026-03-04) and the occurrence was incorrectly treated as uncovered, generating a spurious overdue forecast.

- **`_detect_operating_currency` now uses frequency counting** — Previously returned the currency of the first posting found. Commodity currencies (e.g., `VEHICLE.2014SUBARU`) appearing early in the ledger could shadow the true operating currency (e.g., `USD`). Now counts occurrences across all postings and returns the most frequent.

- **Pending enrichment now preserves tags and links** — Tags and links from `pending.beancount` entries are merged onto the enriched transaction. The `#pending` tag is stripped from the result.

### Performance

- **`filter_occurrences_by_existing_transactions` O(n×m) → O(n+m)** — Replaced nested loops with upfront covered-dates set construction: iterate transactions once to build the set, then filter occurrences with O(1) lookups. Eliminates quadratic behavior for large ledgers with many schedules and a long forecast window.

## [1.5.0]

### Breaking Changes

- **`include_past_dates` now defaults to `true`.** Previously, scheduled transactions with expected dates in the past were silently skipped unless `include_past_dates: true` was set explicitly. The new default surfaces overdue transactions as placeholders and warnings. Users who prefer the old behavior can opt out:

  ```yaml
  # _config.yaml
  include_past_dates: false
  ```

- **`GlobalConfig.default_currency` now defaults to `null` (auto-detected) instead of `"USD"`.** The hook infers the currency from existing ledger entries; the plugin reads it from the ledger's `option "operating_currency"` directive. Set explicitly in `_config.yaml` to override:

  ```yaml
  # _config.yaml
  default_currency: EUR
  ```

### Added

- **Multi-currency postings** — individual postings in a schedule can now specify a `currency` field, allowing mixed-unit transactions such as a paycheck that accrues vacation hours (`VACHR`) and vests shares (`GOOGL`) alongside standard USD postings:

  ```yaml
  postings:
    - account: Assets:Bank:Checking
      amount: null                      # uses imported bank amount (USD)
    - account: Income:Salary
      amount: -4615.38                  # USD (inherits default)
    - account: Assets:Vacation
      amount: 4.00
      currency: VACHR                   # explicit non-default currency
    - account: Assets:Vesting
      amount: 5.00
      currency: GOOGL                   # explicit non-default currency
  ```

- **Auto-detect `operating_currency`** — when `default_currency` is not set in `_config.yaml`, the hook scans existing ledger entries to infer the operating currency, and the forecast plugin reads `option "operating_currency"` from the ledger options map. Falls back to `USD` if neither source is available.

## [1.4.2]

### Changed

- **`#pending` tag is no longer required in `pending.beancount`.** All transactions in the file are treated as pending automatically. The tag is still added by `beanschedule pending create` as a visual marker but is not enforced.
- **`beanschedule pending create` now places `#pending` inline** on the transaction header line (standard beancount tag syntax) rather than as a separate indented line.

## [1.4.1]

### Fixed

- **Ledger matching now uses `schedule_matched_date` for date window comparison.** Previously, when checking existing ledger transactions to avoid false "missing" warnings, the hook compared `entry.date` (the actual bank posting date) against the expected schedule date. If the bank's posting date fell outside `date_window_days` of the scheduled occurrence — which is common — the occurrence was incorrectly flagged as missing again on re-import. The hook now uses `schedule_matched_date` metadata (written at enrich time) as the authoritative comparison date, falling back to `entry.date` when the metadata is absent.

## [1.4.0]

### Breaking Changes

- **`match.amount` is now the authoritative source for amount matching.** Posting amounts are for enrichment only and play no role in matching. Set `match.amount` explicitly to enable amount-based scoring.
- **`match.amount_tolerance` requires `match.amount`.** Previously silently ignored if `amount` was unset; now raises a validation error.
- **`match.amount` and `match.amount_min`/`amount_max` are mutually exclusive.** Setting both raises a validation error. `amount_min`/`amount_max` must also be set together.
- **The `match.account` posting always uses the imported bank amount.** A non-null posting amount on the match account no longer overrides the actual imported value.
- **`narration` field removed from the `Posting` model.** Use `metadata.narration` instead. Does not affect `transaction.narration` or `missing_transaction.narration_prefix`.
- **Skip marker flag `S` removed.** Reserved by Beancount itself; no longer recognized. Use the `#skipped` tag or `schedule_skipped` metadata instead.
- **Schedule loading is directory-only.** File-mode loading removed; schedules must be in a directory.

### Added

- **Skip markers** — mark scheduled occurrences as intentionally skipped using the `#skipped` tag or `schedule_skipped` metadata. CLI: `beanschedule skip <id> <date>`
- **Configurable forecasting** — `forecast_months`, `min_forecast_date`, and `include_past_dates` settings in global config
- **Pending transactions** — stage one-time transactions in `pending.beancount` that auto-match and enrich on import. CLI: `beanschedule pending`
- **Shadow account forecasting** (plugin) — redirect forecast postings to configurable shadow equity accounts (`shadow_upcoming_account`, `shadow_overdue_account`) so balance assertions on real accounts are never affected
- **`filing_account` metadata** (plugin) — all plugin-generated transactions carry the original `match.account` before any shadow redirect
- **`#scheduled` tag** (plugin) — all plugin-generated transactions are tagged `#scheduled`
- **`forecast_flag`** (plugin) — customize the Beancount flag on plugin-generated transactions (default `#`)
- **Auto-open shadow accounts** (plugin) — `Open` directives for shadow accounts are generated automatically
- **`autobean.narration` compatibility** — `filename` and `lineno` metadata now set on plugin-generated transactions
- **Auto-accounts on pending** — pending transaction matching auto-creates missing `Open` directives
- Posting-level `metadata` dict supports arbitrary key/value pairs (not just `narration`)
- Pending transactions capture all transaction-level and posting-level metadata from `.beancount` files

### Fixed

- **Duplicate forecast detection** (plugin) — `filter_occurrences_by_existing_transactions()` now uses date-window matching, suppressing forecasts when an actual transaction falls within `date_window_days` rather than requiring an exact date match
- Skip entries with auto-balancing postings no longer cause errors in amortization

## [1.3.0]

### Added

- Loan amortization with automatic principal/interest splits (`amortization:` config)
- Stateful amortization mode reading live balance from ledger (`balance_from_ledger: true`)
- `beanschedule amortize` CLI command for forecast and schedule inspection

## [1.2.0]

### Added

- `beanschedule detect` command for auto-detecting schedules from existing ledgers
- `beanschedule create` interactive schedule builder

## [1.1.0]

### Added

- Forecast plugin (`beanschedule.plugins.schedules`) for generating future transactions
- `beanschedule generate` CLI command

## [1.0.0]

### Added

- Core matching and enrichment hook (`schedule_hook`)
- YAML schedule definitions with `match`, `recurrence`, and `transaction` sections
- Fuzzy matching with weighted scoring (payee 40%, amount 40%, date 20%)
- Missing transaction placeholders
- `beanschedule validate`, `list`, `init` CLI commands
