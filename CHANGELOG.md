# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Breaking Changes

- **`narration` field removed from the `Posting` model.** The top-level `narration:` key on posting items in schedule YAML files is no longer supported. Posting metadata (including narration) must now be placed inside a `metadata:` dict on the posting.

- **Skip marker flag `S` removed.** The `S` Beancount flag is reserved by Beancount itself and is no longer recognized as a skip marker. Use the `#skipped` tag or `schedule_skipped` metadata instead.

  **Before:**

  ```yaml
  postings:
    - account: Expenses:Housing:Mortgage-Interest
      amount: 1250.00
      narration: Mortgage Interest
  ```

  **After:**

  ```yaml
  postings:
    - account: Expenses:Housing:Mortgage-Interest
      amount: 1250.00
      metadata:
        narration: Mortgage Interest
  ```

  Posting entries with `narration: null` should simply have that line removed. This change does not affect `transaction.narration` or `missing_transaction.narration_prefix`, which remain unchanged.

### Added

- **Skip markers** — mark scheduled occurrences as intentionally skipped using the `#skipped` tag or `schedule_skipped` metadata. CLI: `beanschedule skip <id> <date>`
- **Configurable forecasting** — `forecast_months`, `min_forecast_date`, and `include_past_dates` settings in global config
- **Pending transactions** — stage one-time transactions in `pending.beancount` that auto-match and enrich on import. CLI: `beanschedule pending`
- **Shadow account forecasting** (plugin) — redirect plugin-generated forecast postings to configurable shadow equity accounts (`shadow_upcoming_account`, `shadow_overdue_account`) so balance assertions on real accounts are never affected
- **`filing_account` metadata** (plugin) — all plugin-generated transactions now carry the original `match.account` value before any shadow redirect, for reliable filtering and reporting
- **`#scheduled` tag** (plugin) — all plugin-generated transactions are tagged `#scheduled` for easy filtering
- **`forecast_flag` directive** (plugin) — customize the Beancount flag on plugin-generated transactions (default `#`)
- **Auto-open shadow accounts** (plugin) — `Open` directives for shadow accounts are generated automatically using the earliest occurrence date
- **`autobean.narration` compatibility** — `filename` and `lineno` metadata are now set on plugin-generated transactions
- **Auto-accounts on pending** — pending transaction matching now auto-creates missing accounts
- Posting-level `metadata` dict now supports arbitrary key/value pairs on schedule postings (not just `narration`).
- Pending transactions now capture all transaction-level and posting-level metadata from `.beancount` files, not just `narration`.

### Fixed

- **Duplicate forecast detection** (plugin) — `filter_occurrences_by_existing_transactions()` now uses date-window matching (same logic as the hook), suppressing forecasts when an actual transaction falls within `date_window_days` of the expected date rather than requiring an exact date match

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
