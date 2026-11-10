# Examples

A small, self-contained ledger demonstrating the reconciliation model and the
file split it needs.

| File | Role |
| --- | --- |
| `main.bean` | The ledger Fava opens: includes `import.bean` and `pending.bean`, and loads the plugin and report. |
| `import.bean` | beangulp's target and duplicate-detection source: includes the journal only. |
| `journal.bean` | Accounts, opening balances and imported transactions (`schedule:`-tagged and untagged). |
| `schedules.bean` | One recurring schedule, as a real transaction. Not included by anything. Carries a `#payroll` tag, an `^acme-2026` link and `category: "income"` to demonstrate carry-over. |
| `pending.bean` | A staged one-time payment. Included by `main.bean` only. |

The split matters: `import.bean` omits `pending.bean` (a placeholder shares the
account, amount and date of the transaction it waits for, so beangulp would skip
the real one) and `schedules.bean` is omitted everywhere (the plugin and the
report read it by path).

There is no import hook. Import runs normally against `import.bean`, then
reconciliation is an explicit step.

Try:

```bash
# Validate the schedules and show the report.
beanschedule check examples/main.bean
beanschedule list examples/main.bean
beanschedule report examples/main.bean --today 2026-02-01

# Match imported transactions to schedules (dry run, then apply).
beanschedule reconcile examples/main.bean --today 2026-02-01
beanschedule reconcile examples/main.bean --today 2026-02-01 --write schedules.bean

# Propose schedules for the ledger's recurring payments.
beanschedule detect examples/main.bean
```

In Fava, load `main.bean`; the **Schedules** tab shows the schedules and, with
`write` configured, offers a **Reconcile** button.

## `legacy/`

Two v1 YAML schedules kept as migration inputs, not as a supported format:

```bash
beanschedule migrate examples/legacy
```

- `paycheck-biweekly.yaml` — a multi-posting, bi-weekly paycheck.
- `mortgage-amortized.yaml` — an amortized mortgage with escrow postings.

The migrator converts what the transaction model can express and prints a
comment for anything it cannot (multi-currency postings, tags,
`missing_transaction`).
