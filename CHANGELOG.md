# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.4.0] - 2026-02-08

### Added
- Configurable forecast settings to control forecasting behavior
  - `forecast_months`: extend end_date by N months (default 3)
  - `min_forecast_date`: override start date for forecasting
  - `include_past_dates`: generate placeholders for historical missing dates
- Support for Beancount plugin parameters (dict and JSON syntax) for forecast configuration
- Hook and plugin now respect the same forecast configuration settings
- Official support for marking scheduled transactions as intentionally skipped
  - Skip marker detection (flag 'S', #skipped tag, schedule_skipped metadata)
  - `beanschedule skip` CLI command to generate skip markers
  - Skip markers prevent duplicate placeholder generation
- Pending transactions feature for staging one-time transactions awaiting posting
  - `beanschedule pending create` - Interactive CLI for creating pending transactions
  - `beanschedule pending list` - List all pending transactions with dates and amounts
  - `beanschedule pending clean` - Clean up empty pending file
  - Automatic matching on account + amount + date (±4 days)
  - Auto-removal from staging file after successful match
  - Comprehensive logging with real-time match updates and unmatched summary
  - Simplified format using just `#pending` tag (no metadata required)

### Fixed
- Plugin parameter handling for Beancount config dict/JSON syntax
- Test fixture isolation with forecast_months=0 by default

## [1.2.0] - 2026-01-15

### Added
- Stateful amortization with `balance_from_ledger` mode for dynamic loan balance computation
- Compounding support (MONTHLY and DAILY) for accurate interest calculations
- `beanschedule amortize` command for standalone amortization schedule generation
- Cleared + pending transaction balance computation for accurate starting balance

### Fixed
- Amortization calendar printing with proper formatting
- Amount-tolerance matcher tests for edge cases
- `make_schedule` fixture kwargs handling

### Changed
- Improved amortization accuracy with ledger-driven balance tracking

## [1.1.0] - 2025-12-20

### Added
- `beanschedule detect` - Auto-detect recurring transaction patterns from ledger
- `beanschedule create` - Interactive schedule creation from ledger transactions
- `beanschedule show` - Display detailed schedule information
- `beanschedule list` - List all schedules with filtering
- `beanschedule generate` - Generate expected dates for a schedule
- `beanschedule init` - Initialize example schedules directory
- Static amortization schedules using PMT formula
- Explicit `role` fields for posting categorization (payment, principal, interest)
- Pattern discovery algorithm with confidence scoring
- Integration tests with realistic examples

### Fixed
- Pattern detection accuracy improvements
- CLI output formatting enhancements

## [1.0.0] - 2025-11-10

### Added
- Core transaction matching with weighted scoring algorithm
- Payee matching with regex patterns and fuzzy matching
- Amount matching (exact, tolerance, range-based)
- Date matching with configurable windows
- Transaction enrichment with metadata, tags, and postings
- Placeholder transaction generation for missing expected payments
- Flexible recurrence patterns: MONTHLY, WEEKLY, YEARLY, INTERVAL, BIMONTHLY
- Beangulp hook integration for import workflow
- Lazy matching optimization for performance (80%+ speedup)
- Regex pattern caching and compilation
- Fuzzy match result caching
- YAML schedule configuration with validation
- CLI tools: `validate`, `list`, `show`, `generate`, `create`, `init`
- Unit tests with 86% coverage
- Support for complex posting splits and templates
- Loan amortization with static mode

### Features
- Pattern Discovery - Auto-detect recurring transaction patterns
- Automatic Matching - Fuzzy matching with weighted scoring
- Transaction Enrichment - Add metadata, tags, and complete posting splits
- Missing Transaction Detection - Create placeholders for expected payments
- Flexible Recurrence - Multiple frequency types with customization
- Loan Amortization - Principal/interest splits with configurable modes
- Smart Amount Matching - Fixed, tolerance, or range-based matching
- Beangulp Integration - Drop-in hook for import workflows
- CLI Tools - Validate, test, debug, and discover schedules
- ML Compatibility - Preserves smart_importer training data

---

## Unreleased

### Planned
- Dry-run mode for preview before commit
- ONCE frequency for ad-hoc transactions
- Quick schedule creation wizard
- CSV export for matched transactions
- Optional account matching
- Conditional schedule instances
- Schedule statistics and coverage reports
- Multi-currency support
- Parallel processing for independent schedules
- Plugin system for custom matchers
