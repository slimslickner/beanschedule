# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
