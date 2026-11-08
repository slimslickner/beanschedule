# Examples

A small, self-contained ledger demonstrating the two-ledger topology.

| File | Role |
| --- | --- |
| `main.bean` | The Fava ledger: includes the journal, the schedules and the plugin. |
| `main_no_plugins.bean` | The import ledger: includes the journal only. beangulp loads this one. |
| `journal.bean` | Accounts, opening balances and an imported paycheck tagged `schedule: "paycheck"`. |
| `Schedules.bean` | The `custom "schedule"` directives: one rule, its postings, and a skip. |
| `pending.bean` | A staged one-time payment the hook matches and removes. |

Try:

```bash
# Point the hook at the schedules, then import (beangulp) against main_no_plugins.bean.
export BEANSCHEDULE_SCHEDULES=examples/Schedules.bean

# Validate, list and report the schedules.
beanschedule check examples/main.bean
beanschedule list examples/main.bean
beanschedule report examples/main.bean --today 2026-02-01

# Propose schedules for the ledger's recurring payments.
beanschedule detect examples/main.bean
```

With `plugin "beanschedule.plugin" "forecast"` in `main.bean`, Fava projects the
upcoming occurrences as `#`-flagged transactions.

## `legacy/`

Two v1 YAML schedules kept as migration inputs, not as a supported format:

```bash
beanschedule migrate examples/legacy
```

- `paycheck-biweekly.yaml` — a multi-posting, bi-weekly paycheck.
- `mortgage-amortized.yaml` — an amortized mortgage with escrow postings.

The migrator converts what the directive model can express and prints a comment
for anything it cannot (multi-currency postings, tags, `missing_transaction`).
