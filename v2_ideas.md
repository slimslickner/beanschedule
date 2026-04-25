# Beanschedule v2: Post-Import Reconciliation

> **Status: Speculative design. Not planned for immediate implementation.**

## Background

Beanschedule currently operates as a beangulp import hook — schedules are matched and metadata applied at import time. This works but has a few friction points:

- Matching is tightly coupled to the import pipeline
- It's not easy to re-run or audit after the fact
- The hook can't match transactions that were imported via other paths

This document describes a proposed v2 major revision, which introduces a post-import reconciliation workflow backed by SQLite state and removes the beangulp hook entirely.

---

## Problem Statement

After importing transactions into a Beancount ledger, the user wants to:

1. Know which imported transactions correspond to known schedules
2. Identify schedules with no matching transaction that are coming up soon
3. Confirm or dismiss suspected matches interactively
4. Do this as a separate step from import — idempotently, re-runnable at any time

---

## Proposed Workflow

```
1. Import transactions normally (via beangulp or any other method)
2. Run: beanschedule reconcile --ledger main.beancount
3. CLI shows suspected matches and upcoming unmatched schedules
4. User confirms, dismisses, or skips each
5. State is persisted to SQLite — re-running skips already-resolved items
```

There is no automated matching. The reconciler is the only way to create match state. All matches are human-confirmed.

---

## Matching Logic

For each defined schedule, the reconciler:

1. Determines the expected date window (±N days of the scheduled date, configurable via `--window`)
2. Queries the ledger for transactions within that window on the relevant account
3. Filters by amount range (as defined in the schedule YAML)
4. Ranks all candidates by date proximity and amount closeness
5. Presents **all candidates** to the user for selection

Already-confirmed or dismissed matches (per SQLite state) are skipped.

Schedules with no candidates that are due within the configured lookahead window are surfaced as **upcoming/pending**. There is no overdue concept — unmatched schedules remain pending until explicitly dismissed or matched.

---

## Amortization

For amortization-type schedules (e.g. mortgage interest/principal splits), the reconciler has one narrow exception to the no-ledger-writes rule: upon confirmation of an amortization match, the CLI rewrites the matched transaction with the correct postings calculated from the amortization schedule.

This is:

- Only triggered for schedules explicitly typed as amortization
- Only happens after explicit human confirmation
- Never silent or automated

This keeps the ledger self-contained and correct without requiring beanschedule to be present at parse time to compute postings.

---

## State: SQLite

Match state is stored in a SQLite database (default: `~/.beanschedule/state.db`, configurable via CLI flag or config file).

The db should be committed to git alongside the ledger. Because SQLite is binary, the recommended approach is to configure a `textconv` filter in `.gitattributes` so that `git diff` produces readable output. The db is considered a permanent component of the ledger — it is never dropped and recreated.

### Transaction Hashing

Use Beancount's built-in entry hashing rather than a custom implementation.

> **Design consideration:** The native hash is content-derived, so editing a matched transaction (fixing a narration, adjusting an amount) will change its hash and orphan the corresponding SQLite row. This is especially relevant for amortization matches, which explicitly rewrite a transaction's postings upon confirmation — breaking the hash immediately after it is recorded.
>
> An alternative is to assign a random UUID to each transaction as metadata (e.g. `id: "550e8400-e29b-41d4-a716-446655440000"`) and use that as `tx_hash`. This requires a one-time backfill script and a load-time validation plugin to ensure all transactions carry an ID, but the reference survives any future edits.
>
> For an initial implementation, native hashing is simpler — no ledger changes required. The `beanschedule reset` command can handle the orphaned-row case when edits happen. Migrating to UUID-based IDs later is straightforward: add the metadata field, backfill the ledger, update the schema to store the UUID instead of the content hash.

### Schema (draft)

```sql
CREATE TABLE matches (
    id INTEGER PRIMARY KEY,
    schedule_id TEXT NOT NULL,         -- matches YAML schedule name/id
    tx_hash TEXT NOT NULL,             -- beancount native entry hash
    tx_date TEXT NOT NULL,
    tx_narration TEXT,
    amount TEXT,
    status TEXT NOT NULL,              -- 'confirmed' | 'dismissed'
    created_at TEXT NOT NULL
);

CREATE TABLE pending (
    id INTEGER PRIMARY KEY,
    schedule_id TEXT NOT NULL,
    expected_date TEXT NOT NULL,
    status TEXT NOT NULL,              -- 'pending' | 'dismissed' | 'resolved'
    created_at TEXT NOT NULL
);
```

---

## Forecasting Plugin

The existing forecasting plugin is updated to query SQLite to determine which schedules have already been matched, rather than scanning the ledger. This avoids double-counting and ensures forecasted transactions only appear for unresolved schedules.

---

## CLI Commands

### `beanschedule reconcile`

Main command. Parses the ledger, runs matching against all schedules, presents results interactively.

```
beanschedule reconcile \
  --ledger main.beancount \
  --schedule schedules/ \
  --db ~/.beanschedule/state.db \
  --window 5
```

Output format (example):

```
Schedule: Mortgage Payment (expected 2024-01-01)

  Candidates:
    1. 2024-01-02  "CHASE MORTGAGE"      Assets:Checking  -2,134.00 USD
    2. 2024-01-03  "CHASE MORTGAGE PMT"  Assets:Checking  -2,134.00 USD

  [1/2] select candidate  [d] dismiss  [s] skip
```

Upcoming schedules with no candidates:

```
Schedule: Electric Bill (expected 2024-01-05) — upcoming, no match yet
  [d] dismiss  [s] skip
```

### `beanschedule status`

Non-interactive summary. Shows matched schedules, upcoming with no match, and dismissed items.

```
beanschedule status --ledger main.beancount [--month 2024-01]
```

### `beanschedule reset`

Clears SQLite state for a specific schedule or date range, for re-reconciling incorrect matches.

```
beanschedule reset --schedule mortgage --since 2024-01-01
```

---

## YAML Schedule Format

No breaking changes to the existing format. Each schedule must have a stable `id` field (or one derived deterministically from the schedule name) to serve as the foreign key in SQLite. If existing schedules lack an explicit `id`, the v2 migration should document the derivation rule clearly.

---

## Removed: Beangulp Hook

The beangulp import hook is removed in v2. All matching is done via the reconciler CLI. This ensures:

- No silent automated writes to SQLite
- Every match has a human confirmation on record
- The reconciler session is the auditable moment of decision

---

## Non-Goals

- Automated matching without human confirmation
- Modifying ledger files except for confirmed amortization matches
- Overdue tracking — pending schedules remain pending until matched or dismissed
