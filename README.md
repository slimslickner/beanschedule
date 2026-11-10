# Beanschedule

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Reconciliation-native scheduled transactions for Beancount.**

Beanschedule is built on one pure core with thin shells. A schedule is a real
Beancount transaction carrying an `id` and an `rrule`, so there are no bespoke
directive verbs and no import hook: import runs normally, then reconciliation is
an explicit, re-runnable step that matches imported transactions to schedules,
tags them, and advances each schedule to its next occurrence. The CLI, the
Beancount plugin and the Fava report all read the same core, so they cannot
disagree.

## The model

The model is iCalendar's, over Beancount transactions:

- **Schedule** — a real `Transaction` with an `id`, an `rrule` and its postings.
  Its date is its next occurrence, and it anchors the series. Schedules live in
  one file (`schedules.bean`) that the main ledger does **not** include, so the
  series never inflates balances.
- **Matched occurrence** — an imported transaction that resolves a schedule,
  tagged `schedule: "<id>"`. Its nominal date is re-derived by the
  nearest-occurrence rule, so nothing extra is stored.
- **Pending** — any transaction in `pending.bean`, which the main ledger
  includes. The plugin tags it and flags it, so one-off items are obvious until
  reconciliation consumes them.
- **`next`** — the first nominal date with no matched occurrence, derived and
  never written. A skip or a move is just an edit to the schedule's date.

```beancount
; schedules.bean — a paycheck split across two accounts
2026-02-15 * "Acme" "Paycheck"
  id: "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  match-payee: "Acme"
  amount-tolerance: 7.50
  Assets:Bank:Checking       -3000.00 USD
  Expenses:Taxes:Federal       600.00 USD
    narration: "Federal withholding"
  Expenses:Savings            2400.00 USD
```

The matched account is the first balance-sheet posting (or `match-account`).
Every other posting is the split; its amounts must sum to the negative of the
matched amount (`E011`), and at most one may omit its amount (`E014`).

When a schedule (or a pending transaction) reconciles a match, its **tags**,
**links** (`^`), **transaction metadata** and **posting metadata** are carried
onto the matched transaction — anything the engine does not itself own. So a
schedule can be tagged `#housing`, linked `^mortgage-2026`, or carry
`category: "home"`, and the real transaction inherits all of it.

### Amortization

An amortized schedule marks its posting legs with `schedule-leg`. The leg
amounts are placeholders the engine recomputes per occurrence:

```beancount
2026-01-01 * "Chase" "Mortgage"
  id: "mortgage"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=1"
  method: "static"
  rate: 0.065
  term: 360
  Assets:Bank:Checking             -2134.00 USD
  Liabilities:Mortgage:Principal    900.00 USD
    schedule-leg: "principal"
  Expenses:Interest                 100.00 USD
    schedule-leg: "interest"
```

`method: "balance-from-ledger"` walks forward from the `principal` leg's ledger
balance instead of the static term.

The matched posting is the whole cash payment. When the schedule carries an
`escrow` amount, it is that portion of the payment, so the principal/interest
split is computed from the remainder (the P+I payment) and the escrow is added
back on top; the three legs always sum to the matched amount.

## Installation

```bash
uv sync
```

Python 3.13 is required. The version comes from the git tag via `hatch-vcs`.

## Configuration

**Plugin (a config string on the directive).** The plugin relabels pending
transactions and validates `schedules.bean`, which the ledger does not include,
by path:

```beancount
plugin "beanschedule.plugin" "{'schedules_file': 'schedules.bean', 'pending_file': 'pending.bean', 'pending_tag': 'pending', 'pending_flag': '!'}"
```

| Key | Meaning | Default |
| --- | --- | --- |
| `schedules_file` | The schedules file, relative to the ledger | `schedules.bean` |
| `pending_file` | The pending file, relative to the ledger | `pending.bean` |
| `pending_tag` | The tag added to pending transactions | `pending` |
| `pending_flag` | The flag set on pending transactions | `!` |

A bare `plugin "beanschedule.plugin"` uses the defaults. `bean-check main.bean`
alone does not validate the schedules; `beanschedule check` loads both. The
plugin's config is the **single source of truth** for the paths — the Fava
extension reads it rather than repeating it.

**Fava extension (a config string on the directive).** The report takes its
paths from the plugin; only Fava-specific settings live here:

```beancount
2026-01-01 custom "fava-extension" "beanschedule.fava_ext" "{'write': True, 'months': 2}"
```

| Key | Meaning |
| --- | --- |
| `write` | `True` to make the report writable at the plugin's `schedules_file`, or a string naming a different file; omit for read-only |
| `months` | How many months of future occurrences to show |

## Command line

```bash
beanschedule check     LEDGER                 # validate the schedules
beanschedule report    LEDGER [--json]        # next, overdue, resolved, upcoming
beanschedule list      LEDGER [--json]        # schedules with next and overdue
beanschedule upcoming  LEDGER [--all] [--json]  # one ledger of outstanding occurrences
beanschedule amortize  LEDGER [--id ID] [--json]  # loan amortization to payoff
beanschedule reconcile LEDGER [--write]       # match imported transactions (dry run by default)
beanschedule detect    LEDGER                 # propose schedules for recurring payments
beanschedule migrate   schedules/             # convert schedules/*.yaml to transactions
beanschedule migrate-ledger LEDGER [--write]   # strip v1 tracking metadata (dry run by default)
beanschedule skip      LEDGER ID      --write [FILE]
beanschedule move      LEDGER ID DATE --write [FILE]
beanschedule create    LEDGER ID --rrule R --start D --account A --posting ACCT AMT --write [FILE]
beanschedule edit      LEDGER ID --amount X --write [FILE]
beanschedule docs [--check]                   # schema.md, errors.md, cli.md
```

`reconcile` tags each matched transaction in its own file and advances each
schedule in `schedules.bean`. It is a dry run until `--write` is passed; in Fava
it is the **Reconcile** button. The mutating commands write **opt-in only**,
through `writer.py`, inside the ledger directory.

## The Fava report

The extension renders three tabs:

- **Overview** — every schedule as a row (account, payee, recurrence, next,
  overdue and due counts, amount), with the Reconcile button and a create form.
- **Upcoming** — one date-ordered ledger of every schedule's outstanding
  occurrences, each marked **overdue**, **due** (within the schedule's match
  window), or **upcoming**.
- **Schedule** — a per-schedule drill-down: the rule's details, its
  diagnostics, and, for an amortized loan, the projected amortization schedule
  (remaining payments and principal, interest, escrow and payoff date). With
  `write` configured, the drill-down edits the schedule's own Beancount source
  in place, alongside quick skip / move / delete actions.

Schedules are read from `schedules.bean` **without** Beancount's interpolation
and validation, so an amortized schedule's amount-less leg postings are kept
rather than dropped; the engine reports its own diagnostics for anything wrong.

## The topology

- `main.bean` (Fava) includes the import ledger and `pending.bean`, and loads the
  plugin and the Fava extension.
- `import.bean` (beangulp's target and duplicate-detection source) includes the
  journal **only** — never `pending.bean` or `schedules.bean`.
- `schedules.bean` (recurring) is included by nothing; the plugin and the report
  read it by path.
- `pending.bean` (one-off) is included by `main.bean` **only**, so beangulp never
  mistakes a placeholder for the transaction it is waiting for and skips the
  real import.

## Documentation

- `docs/schema.md` — metadata keys and reserved values.
- `docs/errors.md` — every diagnostic code.
- `docs/cli.md` — the command tree.
- `examples/` — a self-contained ledger.

All three documents are generated from the registries and the command tree, and
gated in CI by `beanschedule docs --check`.

## Architecture

```
src/beanschedule/
  schema.py     registry: metadata keys + diagnostic codes -> docs
  core.py       pure: parse schedules, derive occurrences, match, amortization
  recurrence.py pure RRULE date generation
  reconcile.py  pure: match imported transactions, advance frontiers
  actions.py    build and render schedule transactions (CLI + Fava emit identical text)
  report.py     shared view model (next, overdue, due, upcoming ledger, amortization)
  config.py     parse the config strings plugins and Fava carry
  writer.py     deterministic opt-in ledger edits
  plugin.py     beancount: relabel pending; validate the schedules file
  detector.py   ledger -> proposed schedule transactions
  migrate.py    legacy schedules/*.yaml -> transactions
  migrate_ledger.py  strip v1 tracking metadata and placeholders from a ledger
  cli.py        check / report / list / upcoming / amortize / reconcile / detect / migrate / migrate-ledger / skip / move / create / edit
  fava_ext.py   tabbed report, opt-in reconcile + edits   [only module importing Fava]
  templates/    Fava report template
```

## Licence

MIT. See [LICENSE](LICENSE).
