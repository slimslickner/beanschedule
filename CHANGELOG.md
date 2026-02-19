# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-02-08

### Breaking Changes

- **`narration` field removed from the `Posting` model.** The top-level `narration:` key on posting items in schedule YAML files is no longer supported. Posting metadata (including narration) must now be placed inside a `metadata:` dict on the posting.

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

- **Skip markers** — mark scheduled occurrences as intentionally skipped using flag `S`, `#skipped` tag, or `schedule_skipped` metadata. CLI: `beanschedule skip <id> <date>`
- **Configurable forecasting** — `forecast_months`, `min_forecast_date`, and `include_past_dates` settings in global config
- **Pending transactions** — stage one-time transactions in `pending.beancount` that auto-match and enrich on import. CLI: `beanschedule pending`
- Posting-level `metadata` dict now supports arbitrary key/value pairs on schedule postings (not just `narration`).
- Pending transactions now capture all transaction-level and posting-level metadata from `.beancount` files, not just `narration`.

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
