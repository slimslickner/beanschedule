# Changelog

## 2.0.0

Beanschedule is rewritten to be **ledger-native**. Schedules are now
`custom "schedule"` directives in the ledger rather than YAML files, and one pure
core drives the beangulp hook, the Beancount plugin, the CLI and the Fava report.

### Added

- `custom "schedule"` directives: `new` (a rule), `posting` (an other-side
  posting, with its own `amount` and arbitrary metadata such as `narration` or
  `contribution-year`), `skip` (an EXDATE) and `move` (a RECURRENCE-ID), with a
  registry that generates `docs/schema.md` and `docs/errors.md`.
- A pure core (`beanschedule.core`) that parses rules, derives nominal
  occurrences, resolves posted links, skips and moves, and computes
  balance-from-ledger and static amortization splits.
- Greedy chronological matching with the ½-gap consumption rule.
- A shared, read-only report view (`beanschedule.report`) used by both the CLI
  and the Fava report.
- A deterministic, opt-in writer (`beanschedule.writer`) and directive builders
  (`beanschedule.actions`).
- A detector that proposes schedules from a ledger, feeding `create`.
- `migrate`, a YAML reader in its own module (`beanschedule.migrate`) that
  converts `schedules/*.yaml` to directives idempotently, checks the migrated
  postings balance against `match-amount`, and reports the legacy fields the
  directive model cannot express.
- Opt-in forecast injection through the Beancount plugin; both the plugin and
  the Fava extension take a Python-literal config string, e.g.
  `plugin "beanschedule.plugin" "{'forecast': True, 'months': 3}"`.
- `hatch-vcs` versioning, a CI gate, conventional commits and generated release
  notes.

### Changed

- Matching at import stays, but the historical tracking trail is removed: no
  stored actual/nominal dates, no confidence scores, no placeholder
  transactions, no amortization metadata trail.
- Overdue is always a computed view, never a persisted record.
- The command line moves from Click to `argparse` + `argcomplete`.
- Stacks use frozen slotted dataclasses and `Decimal` instead of Pydantic.
- The hook finds its files from `BEANSCHEDULE_SCHEDULES` and
  `BEANSCHEDULE_PENDING`; the pending file is standardised on the `.bean`
  suffix (`pending.bean`).
- `beangulp` and `pyyaml` move to optional extras (`[beangulp]`, `[migrate]`).

### Removed

- YAML schedule files (use `migrate`), Pydantic and Click.
- The v1 `BEANSCHEDULE_DIR` variable and the cwd/parent file hunting; a
  multi-currency or placeholder-only v1 schedule has no directive equivalent and
  is reported by `migrate` rather than silently dropped.

### Performance

- The occurrence horizon is a fixed span from the reference date, never the
  ledger's latest directive. A far-future `open`/`custom` previously expanded
  every rule across millennia (a 43-schedule ledger went from ~4.1M occurrences
  to ~9.7k; the 43-schedule scan dropped from 22.7s to under 0.1s).
- Posted transactions are resolved against each rule's precomputed nominal list
  by bisect, instead of re-expanding the rule around every date; a 2,000-tagged
  ledger dropped from ~0.8s to ~0.05s.
- Static amortization enumerates each series once (no per-date re-derivation),
  and liability balances are gathered for all amortized schedules in one pass.

### Fixed

- The `beanschedule/plugins/schedules.py` header declared GPLv2 under an MIT
  project; the licence is MIT.
- Date arithmetic is clamped to the representable range, so a ledger carrying a
  far-future directive no longer raises `OverflowError` when deriving the
  occurrence window.
- Forecast and enrichment never emit a posting with no amount. The one posting
  allowed to omit its amount is now filled explicitly so the transaction
  balances; a schedule with more than one amount-less posting is reported
  (`E014`) rather than crashing Beancount's balance check.
- The shared-account diagnostic was removed. Several schedules on one account is
  normal, and the engine resolves any real competition deterministically by
  declaration order, so there was nothing actionable to warn about.
