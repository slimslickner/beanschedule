# Beanschedule

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Ledger-native scheduled transactions for Beancount.**

Beanschedule is a forward-looking tool built on one pure core with thin shells.
Schedules are defined as `custom "schedule"` directives in the ledger, and the
import hook, the Beancount plugin, the CLI and the Fava report all read the same
core, so they cannot disagree.

## The model

The model is iCalendar's, over Beancount directives:

- **Rule** — one immutable `custom "schedule" "new" "<id>"` directive. Its
  recurrence generates the nominal occurrence dates.
- **Posting** — `custom "schedule" "posting" "<id>" "<account>"`, one per
  other-side account, carrying that posting's `amount` plus any further metadata
  (`narration`, `contribution-year`, …). A schedule that omits it keeps whatever
  split the importer produced.
- **Posted occurrence** — a transaction carrying `schedule: "<id>"` metadata.
  Its nominal date is re-derived by the nearest-occurrence rule, so nothing is
  stored on the transaction.
- **Skip** — `custom "schedule" "skip" "<id>"`, dated at the skipped nominal
  date (an EXDATE).
- **Move** — `custom "schedule" "move" "<id>" <new_date>`, dated at the original
  nominal date (a RECURRENCE-ID).
- **`next`** — the first nominal date with no resolved occurrence. Derived, never
  written. A resolved occurrence is one with a posted link, a skip, or a move.

```beancount
2026-01-01 custom "schedule" "new" "paycheck"
  rrule: "FREQ=MONTHLY;BYMONTHDAY=15"
  start: 2026-01-15
  payee: "Acme"
  match-account: "Assets:Bank:Checking"
  match-payee: "Acme"
  match-amount: -3000.00
  amount-mode: "approx"
  amount-tolerance: 7.50

; The split, declared posting by posting. Amounts must sum to -match-amount.
2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Taxes:Federal"
  amount: 600.00
  narration: "Federal withholding"

2026-01-01 custom "schedule" "posting" "paycheck" "Expenses:Savings"
  amount: 2400.00

2026-12-15 custom "schedule" "skip" "paycheck"
2026-12-15 custom "schedule" "move" "paycheck" 2026-12-20
```

The registry validates every posting: one that names an unknown schedule is
orphaned (`E010`), one that posts to the matched account is rejected (`E013`),
the amounts must sum to the negative of `match-amount` (`E011`), at most one
posting may omit its amount (`E014`), and an amortized rule cannot also declare
postings (`E012`).

## Installation

```bash
uv sync
```

Python 3.13 is required. The version comes from the git tag via `hatch-vcs`.

## The two-ledger topology

Schedule directives live in one balance-neutral `Schedules.bean`, included in the
general ledger (`main.bean`) and excluded from the import ledger
(`main_no_plugins.bean`):

- `main.bean` (Fava) includes the journal, `Schedules.bean`, and
  `plugin "beanschedule.plugin"`.
- `main_no_plugins.bean` (import) includes the journal only, so the hook sees
  the tagged transactions it needs but never the plugin's forecast output.
- The hook loads `Schedules.bean` directly by path, from the
  `BEANSCHEDULE_SCHEDULES` environment variable or `Schedules.bean` in the
  working directory.

The split is only *required* when forecast injection is enabled; report-only
forecasting adds nothing to the ledger.

## Command line

```bash
beanschedule check    LEDGER                 # heavy, ledger-wide validation
beanschedule report   LEDGER                 # next, overdue, resolved, upcoming
beanschedule forecast LEDGER                 # print upcoming occurrences
beanschedule list     LEDGER                 # schedules with next and overdue
beanschedule detect   LEDGER                 # propose schedules for recurring payments
beanschedule migrate  schedules/             # convert schedules/*.yaml to directives
beanschedule skip     LEDGER ID DATE   --write [FILE]
beanschedule move     LEDGER ID DATE NEW --write [FILE]
beanschedule create   LEDGER ID --rrule R --start D --account A --posting ACCT AMT --write [FILE]
beanschedule edit     LEDGER ID --amount X --write [FILE]
beanschedule rebuild  LEDGER          --write [FILE]
beanschedule docs [--check]                  # schema.md, errors.md, cli.md
```

The mutating commands write **opt-in only**, through `writer.py`, at one
configured file inside the ledger directory. A cadence change splits the series
(set `end` on the old rule, create a new one); an amount change rewrites the one
directive in place.

## Pending support

Stage one-time payments in `pending.bean`; the hook matches each by account,
amount and date, applies its splits, and removes it from the file. Point it
elsewhere with `BEANSCHEDULE_PENDING`.

## Configuration

The **import hook** and the **Beancount/Fava shells** are configured separately,
because the import ledger (`main_no_plugins.bean`) excludes both `Schedules.bean`
and the plugin — nothing declared on the Fava side can reach the hook.

**Hook (two environment variables).** `beangulp` loads `main_no_plugins.bean`;
the hook finds the schedules and pending files itself:

| Variable | Meaning | Default |
| --- | --- | --- |
| `BEANSCHEDULE_SCHEDULES` | The `Schedules.bean` to match against | `Schedules.bean` in the cwd |
| `BEANSCHEDULE_PENDING` | The one-time pending file | `pending.bean` in the cwd |

**Plugin (a config string on the directive).** The plugin reads the schedule
directives from the ledger it is loaded with, so it needs no path. Its config is
the string after `plugin`, either the bare word `forecast` or a Python-literal
mapping:

```beancount
plugin "beanschedule.plugin" "{'forecast': True, 'months': 3}"
```

| Key | Meaning |
| --- | --- |
| `forecast` | Inject `#`-flagged forecast transactions (requires the two-ledger split) |
| `months` | How many months forward to forecast |

**Fava extension (a config string on the directive).** The report is read-only
unless a `write` path is configured, and that path is the `Schedules.bean` the
hook also reads:

```beancount
2026-01-01 custom "fava-extension" "beanschedule.fava_ext" "{'write': 'Schedules.bean', 'months': 2}"
```

| Key | Meaning |
| --- | --- |
| `write` | The Beancount file to write directives to, relative to the ledger directory; omit for read-only |
| `months` | How many months of future occurrences to show |

## Documentation

- `docs/schema.md` — directive verbs, metadata keys and reserved values.
- `docs/errors.md` — every diagnostic code.
- `docs/cli.md` — the command tree.
- `examples/` — a self-contained ledger.

All three documents are generated from the registries and gated in CI by
`beanschedule docs --check`.

## Architecture

```
src/beanschedule/
  schema.py     registry: verbs/metadata + diagnostic codes -> docs
  core.py       pure: parse rules, derive occurrences, match, link, amortization
  recurrence.py pure RRULE date generation
  actions.py    build custom "schedule" directives (CLI + Fava emit identical text)
  report.py     shared view model (next, overdue, per-schedule ledger)
  config.py     parse the config strings plugins and Fava carry
  writer.py     deterministic opt-in ledger edits
  hook.py       beangulp: match, enrich, tag            [never writes rules]
  plugin.py     beancount: light diagnostics; opt-in forecast injection
  detector.py   ledger -> proposed schedule directives
  migrate.py    legacy schedules/*.yaml -> directives
  cli.py        check / report / forecast / list / detect / migrate / skip / move / create / edit / rebuild
  fava_ext.py   read-only report, opt-in writes         [only module importing Fava]
  templates/    Fava report template
```

## Licence

MIT. See [LICENSE](LICENSE).
