# Changelog

## 2.0.0

Beanschedule is rewritten to be **reconciliation-native**. A schedule is a real
Beancount transaction carrying an `id` and an `rrule`; there is no beangulp
import hook and no `custom "schedule"` directive vocabulary. Import runs
normally, then reconciliation — `beanschedule reconcile` or the Fava report —
matches imported transactions to schedules, tags them, and advances each
schedule to its next occurrence. One pure core drives the CLI, the Beancount
plugin and the Fava report.

### Added

- Reconciliation (`beanschedule.reconcile`): a pure plan that links imported
  transactions to a schedule's outstanding occurrences (greedily and
  chronologically, with the ½-gap consumption rule), enriches them with the
  schedule's postings, and advances each schedule's frontier. Applied
  opt-in only, and idempotent.
- Schedules as transactions: a real `Transaction` with `id`, `rrule`, optional
  matching hints and its split as postings. The first balance-sheet posting (or
  `match-account`) is the matched account.
- Amortization via posting legs (`schedule-leg: "principal" | "interest" |
  "escrow"`), whose amounts the engine recomputes; `static` (from `rate`/`term`)
  or `balance-from-ledger`.
- A schedule or pending transaction's tags, links and user metadata — on the
  transaction and on its postings — are carried onto the transaction it
  reconciles, and survive a frontier advance.
- A Fava **Reconcile** action alongside create / skip / move / edit / delete.
- The Beancount plugin relabels pending transactions (tag + flag, config-driven)
  and validates the schedules file by path, reporting the engine's diagnostics
  as ordinary Beancount errors.
- `beanschedule migrate-ledger` rewrites a v1 ledger for the new model: rename
  `schedule_id` to `schedule`, remove the v1 tracking metadata, and delete
  placeholder transactions, in place and dry-run by default.
- The Fava extension reads `schedules_file`/`pending_file` from the plugin's
  config; its own config is reduced to a `write` opt-in (`true`, or a path) and
  `months`.

### Changed

- Matching moves from import time to a post-import reconciliation step; the two
  ledger topology (`main.bean` vs `main_no_plugins.bean`) is gone, and schedules
  are simply a file the ledger does not include.
- A schedule's date **is** its next occurrence; `skip` and `move` are date edits.
- The Fava extension loads the schedules file by path and grows a reconcile
  action.

### Removed

- The beangulp import hook (`hook.py`) and the plugin's forecast injection.
- The `custom "schedule"` verbs (`new`, `posting`, `skip`, `move`) and the
  verb registry; the schema is now a metadata-key registry.
- `BEANSCHEDULE_SCHEDULES` / `BEANSCHEDULE_PENDING`; the plugin config string is
  the single source of truth.

### Performance

- The occurrence horizon is a fixed span from the reference date, never the
  ledger's latest directive, so a far-future directive cannot expand a series
  across millennia.
- Posted transactions are resolved against a rule's precomputed nominal list by
  bisect, and amortization enumerates each series once.

### Fixed

- Date arithmetic is clamped to the representable range.
- Forecast and enrichment never emit a posting with no amount.
