# Beanschedule YAML-Only Architecture - Action Plan

## Executive Summary

**Decision**: Pivot from dual-format (YAML + Forecast.bean) to **YAML-only** architecture.

**Goal**: Single source of truth in `schedules.yaml`, with plugin generating forecast transactions dynamically.

**Status**: Feature branch `first-big-update` to be abandoned. New implementation on `main` branch.

**Impact**: The latest commit added 4,260 lines of forecast-transaction code. Much of this work can be salvaged and adapted, but the core approach (transaction-based schedules) will be replaced with YAML-based schedules.

### Why This Pivot Makes Sense

Despite the significant work invested in the forecast-transaction approach, pivoting to YAML-only is the right call because:

1. **Simpler UX** - One file to edit (schedules.yaml), not two (schedules.yaml + Forecast.bean)
2. **No sync complexity** - Plugin reads YAML dynamically, no separate advancement needed for forecasts
3. **Better foundation** - Clean YAML data structure for future beanforecast tool
4. **Easier adoption** - New users understand YAML, not "forecast transactions with special metadata"
5. **Less maintenance** - Single code path instead of dual (YAML + transaction parsing)

**The work isn't wasted**: Core logic (recurrence patterns, matching, CLI UX) will be reused, just with YAML as the source instead of transactions.

---

## Why This Change?

### Problems with Current Approach (Forecast.bean)

1. **Dual maintenance burden** - Users must maintain both schedules.yaml AND Forecast.bean
2. **Sync complexity** - advance-forecasts command must keep files in sync
3. **Verbose format** - Beancount transaction metadata is hard to edit
4. **Not database-like** - Can't easily query/filter forecast transactions
5. **Migration confusion** - migrate command adds complexity
6. **Poor UX** - Two ways to do the same thing

### Benefits of YAML-Only

1. **Single source of truth** - Edit only schedules.yaml
2. **Simple, clear structure** - Database-like records
3. **Plugin generates forecasts** - Read YAML, output forecast transactions dynamically
4. **Better for tooling** - Build beanforecast on clean YAML data
5. **Easier to adopt** - One workflow, clearly documented
6. **Future-proof** - Easy to extend, version control, validate

---

## Architecture Comparison

### Current (Dual-Format) ❌

```
schedules.yaml ──┬──> Import Hook (matches transactions)
                 │
Forecast.bean ───┼──> Forecast Plugin (generates projections)
                 │
                 └──> advance-forecasts (syncs Forecast.bean ← matches)
```

**Problem**: Two sources of truth, manual sync required.

### New (YAML-Only) ✅

```
                    ┌─────────────────┐
                    │ schedules.yaml  │ ← Single source of truth
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
      ┌──────────────┐  ┌─────────┐  ┌──────────┐
      │ Import Hook  │  │ Plugin  │  │ CLI      │
      │ (Enrich)     │  │ (→Fcst) │  │ (Manage) │
      └──────┬───────┘  └────┬────┘  └────┬─────┘
             │               │            │
             └───────┬───────┴────────────┘
                     ▼
            ┌────────────────────┐
            │ Beancount Ledger   │
            │ (Real + Forecast)  │
            └────────────────────┘
```

**Solution**: One source (YAML), plugin reads it, generates forecasts dynamically.

---

## What to Keep from Feature Branch

### 📊 Latest Commit Analysis (2032bdd)

The latest commit "more to support a forecast-like syntax" added **4,260 lines**:

- `forecast_loader.py` (438 lines) - Parse forecast transactions
- `forecast_advancement.py` (112 lines) - Advance forecast dates
- `plugins/forecast.py` (375 lines) - Forecast plugin
- `cli.py` (+620 lines) - migrate, advance-forecasts commands
- `recurrence.py` (+128 lines) - Advanced recurrence patterns
- Many test files (2,493 lines total)

**What to salvage from this work**:

### ✅ Keep These Improvements

1. **Advanced recurrence patterns** - MONTHLY_ON_DAYS, NTH_WEEKDAY, LAST_DAY_OF_MONTH
   - **Keep**: Enhanced RecurrenceEngine logic (recurrence.py +128 lines)
   - **Keep**: Tests (test_advanced_recurrence.py - 453 lines)
   - **Why**: These work with YAML schedules, not specific to forecast format

2. **Hook enhancements** - Placeholder filtering, performance improvements
   - **Keep**: Updated hook logic that works with YAML
   - **Discard**: forecast_loader import and fallback logic

3. **Test infrastructure** - Well-written tests with good fixtures
   - **Keep**: Test patterns and fixtures from forecast tests
   - **Adapt**: Reuse for plugin tests (test_schedules_plugin.py)

4. **CLI command structure** - advance command concept
   - **Keep**: Command structure and UX design
   - **Adapt**: Rewrite to work with YAML instead of Forecast.bean

5. **Schema enhancements** - Any new Pydantic models
   - **Keep**: Schema additions that apply to YAML
   - **Review**: types.py additions

6. **Plugin architecture** - forecast.py structure
   - **Keep**: Overall plugin pattern (loading schedules, generating transactions)
   - **Adapt**: Read from YAML instead of parsing transactions
   - **Rename**: forecast.py → schedules.py

### Specific Components to Salvage

#### From `forecast_advancement.py` (112 lines)

**Keep**:

- `calculate_next_occurrence()` function - Works with Schedule objects
- `advance_forecast_transaction()` pattern - Reuse for YAML updates

**Discard**:

- Transaction parsing logic
- Forecast.bean file handling

#### From `plugins/forecast.py` (375 lines)

**Keep**:

- Plugin registration pattern
- Transaction generation logic structure
- Recurrence date generation

**Adapt**:

- Remove narration-based parsing entirely
- Replace transaction-based loading with YAML loading
- Rename to schedules.py

#### From CLI changes (+620 lines)

**Keep concepts**:

- `advance` command UX and workflow
- `migrate` command's schedule conversion logic (adapt to YAML→YAML)

**Rewrite**:

- Change from Forecast.bean manipulation to YAML manipulation
- Use PyYAML for structured updates instead of transaction rewrites

#### From Tests (2,493 lines)

**Keep patterns**:

- Test fixtures for schedules
- Integration test structure
- Mock patterns for CLI testing

**Adapt**:

- Rewrite forecast_loader tests → YAML loading tests
- Rewrite advancement tests → YAML update tests
- Keep advanced_recurrence tests as-is

### ❌ Discard These Components

1. **forecast_loader.py** - Entire module (parses forecast transactions)
2. **advance-forecasts command** - Will be replaced with advance-schedules
3. **migrate command** - No longer needed (YAML → Forecast.bean conversion)
4. **Forecast.bean file format** - Not using transaction-based schedules
5. **Tests for forecast transaction parsing** - test_forecast_advancement.py
6. **CLI changes for --forecast-file flag** - Not needed

---

## Detailed Implementation Plan

## Phase 1: Update the Plugin (schedules.py)

### 1.1 Rename the Plugin

**File**: `beanschedule/plugins/forecast.py` → `beanschedule/plugins/schedules.py`

**Changes**:

```python
# OLD plugin name
__plugins__ = ('forecast',)

# NEW plugin name
__plugins__ = ('schedules',)
```

**Update docstring**:

```python
"""Beanschedule plugin for Beancount - generates forecast transactions from YAML schedules.

This plugin reads schedule definitions from schedules.yaml and generates
forecast transactions for future occurrences.

Usage in ledger:
    plugin "beanschedule.plugins.schedules"

    ; Or specify custom path:
    plugin "beanschedule.plugins.schedules" "path/to/schedules.yaml"

The plugin will:
1. Auto-discover schedules.yaml (or use provided path)
2. Load schedule definitions
3. Generate forecast transactions for enabled schedules
4. Return them as # (forecast) flag transactions

Schedules are defined in YAML format. See schedules.yaml.example.
"""
```

### 1.2 Remove Narration-Based Parsing

**Remove entire function**: `parse_pattern_from_narration()`

**Why**: We're YAML-only now. No need to parse [MONTHLY] from narration.

**Keep**: `parse_pattern_from_metadata()` - Used only for backward compatibility if someone has old forecast transactions in their ledger.

### 1.3 Implement YAML-Based Schedule Loading

**Replace the main forecast() function**:

```python
def schedules(entries, options_map, config_file=None):
    """Generate forecast transactions from YAML schedule definitions.

    Args:
        entries: Existing beancount entries
        options_map: Beancount options
        config_file: Optional path to schedules.yaml (auto-discovers if not provided)

    Returns:
        Tuple of (entries + forecast_entries, errors)

    Example:
        ; Auto-discover schedules.yaml
        plugin "beanschedule.plugins.schedules"

        ; Custom path
        plugin "beanschedule.plugins.schedules" "config/schedules.yaml"
    """
    import logging
    from pathlib import Path
    from datetime import date, timedelta
    from beanschedule.loader import load_schedules_file, find_schedules_location
    from beanschedule.recurrence import RecurrenceEngine

    logger = logging.getLogger(__name__)
    errors = []

    # 1. Load YAML schedules
    try:
        if config_file:
            # Use provided path
            schedule_path = Path(config_file)
            if not schedule_path.is_absolute():
                # Make relative to ledger file location
                ledger_dir = Path(options_map.get('filename', '.')).parent
                schedule_path = ledger_dir / schedule_path

            schedule_file = load_schedules_file(schedule_path)
        else:
            # Auto-discover
            schedule_location = find_schedules_location()
            if schedule_location:
                schedule_file = load_schedules_file(schedule_location)
            else:
                logger.warning("No schedules.yaml found, skipping forecast generation")
                return entries, []

        if not schedule_file:
            logger.warning("Failed to load schedules, skipping forecast generation")
            return entries, []

    except Exception as e:
        error_msg = f"Failed to load schedules: {e}"
        logger.error(error_msg)
        errors.append(error_msg)
        return entries, errors

    # 2. Determine forecast horizon
    # Default: Today + 1 year
    # Can be configured via plugin options in future
    today = date.today()
    forecast_start = today
    forecast_end = today + timedelta(days=365)

    logger.info(
        f"Generating forecasts from {forecast_start} to {forecast_end} "
        f"({len(schedule_file.schedules)} schedule(s))"
    )

    # 3. Generate forecast transactions
    forecast_entries = []
    engine = RecurrenceEngine()

    for schedule in schedule_file.schedules:
        if not schedule.enabled:
            logger.debug(f"Skipping disabled schedule: {schedule.id}")
            continue

        try:
            # Generate occurrence dates
            occurrences = engine.generate(schedule, forecast_start, forecast_end)

            # Create forecast transaction for each occurrence
            for occurrence_date in occurrences:
                forecast_txn = _create_forecast_transaction(
                    schedule,
                    occurrence_date,
                    schedule_file.config
                )
                forecast_entries.append(forecast_txn)

            logger.debug(
                f"Generated {len(occurrences)} forecast(s) for {schedule.id}"
            )

        except Exception as e:
            error_msg = f"Failed to generate forecasts for {schedule.id}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    logger.info(f"Generated {len(forecast_entries)} forecast transaction(s)")

    return entries + forecast_entries, errors


def _create_forecast_transaction(schedule, occurrence_date, global_config):
    """Create a forecast transaction from a schedule.

    Args:
        schedule: Schedule object
        occurrence_date: Date for this forecast occurrence
        global_config: GlobalConfig with defaults

    Returns:
        beancount.core.data.Transaction with forecast flag
    """
    from beancount.core import data, amount
    from decimal import Decimal

    # Build metadata
    meta = {
        'filename': '<schedules.yaml>',
        'lineno': 0,
        'schedule_id': schedule.id,  # For tracking, not matching
    }

    # Add schedule metadata if present
    if schedule.transaction.metadata:
        for key, value in schedule.transaction.metadata.items():
            # Don't duplicate schedule_id
            if key != 'schedule_id':
                meta[key] = value

    # Build postings
    postings = []
    for posting_template in schedule.transaction.postings:
        # Determine amount
        if posting_template.amount is not None:
            posting_amount = amount.Amount(
                Decimal(str(posting_template.amount)),
                posting_template.currency or global_config.default_currency
            )
        else:
            posting_amount = None  # Balancing posting

        # Build posting metadata if any
        posting_meta = {}
        if posting_template.narration:
            posting_meta['narration'] = posting_template.narration

        posting = data.Posting(
            account=posting_template.account,
            units=posting_amount,
            cost=None,
            price=None,
            flag=None,
            meta=posting_meta if posting_meta else None
        )
        postings.append(posting)

    # Create transaction with # flag (forecast)
    txn = data.Transaction(
        meta=meta,
        date=occurrence_date,
        flag='#',  # Forecast flag
        payee=schedule.transaction.payee,
        narration=schedule.transaction.narration,
        tags=frozenset(schedule.transaction.tags or []),
        links=frozenset(schedule.transaction.links or []),
        postings=postings
    )

    return txn
```

### 1.4 Update Plugin Tests

**New test file**: `tests/test_schedules_plugin.py`

```python
"""Tests for schedules plugin."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from beancount.core import amount, data

from beanschedule.plugins.schedules import schedules
from beanschedule.schema import (
    GlobalConfig,
    MatchCriteria,
    RecurrenceRule,
    Schedule,
    ScheduleFile,
    TransactionTemplate,
    Posting,
)
from beanschedule.types import FrequencyType


@pytest.fixture
def sample_schedule_file(tmp_path):
    """Create a sample YAML schedule file."""
    schedule_yaml = tmp_path / "schedules.yaml"
    schedule_yaml.write_text(
        """
version: "1.0"

config:
  default_currency: USD

schedules:
  - id: rent-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*LANDLORD.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent Payment"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-monthly
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
        - account: Assets:Checking
"""
    )
    return schedule_yaml


class TestSchedulesPlugin:
    """Tests for schedules plugin."""

    def test_plugin_generates_forecasts_from_yaml(self, sample_schedule_file):
        """Should generate forecast transactions from YAML schedules."""
        options_map = {'filename': str(sample_schedule_file.parent / 'main.bean')}

        # Run plugin with explicit config file
        result_entries, errors = schedules(
            [],
            options_map,
            config_file=str(sample_schedule_file)
        )

        # Should have generated forecast transactions
        assert len(result_entries) > 0
        assert len(errors) == 0

        # Check first forecast transaction
        forecast_txn = result_entries[0]
        assert isinstance(forecast_txn, data.Transaction)
        assert forecast_txn.flag == '#'
        assert forecast_txn.payee == "Rent Payment"
        assert forecast_txn.narration == "Monthly rent"
        assert forecast_txn.meta['schedule_id'] == 'rent-monthly'

        # Check postings
        assert len(forecast_txn.postings) == 2
        assert forecast_txn.postings[0].account == "Expenses:Housing:Rent"
        assert forecast_txn.postings[0].units == amount.Amount(
            Decimal("1500.00"), "USD"
        )

    def test_plugin_skips_disabled_schedules(self, tmp_path):
        """Should not generate forecasts for disabled schedules."""
        schedule_yaml = tmp_path / "schedules.yaml"
        schedule_yaml.write_text(
            """
version: "1.0"
schedules:
  - id: disabled-schedule
    enabled: false
    match:
      account: Assets:Checking
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Test"
      narration: ""
      metadata:
        schedule_id: disabled-schedule
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
"""
        )

        options_map = {'filename': str(tmp_path / 'main.bean')}
        result_entries, errors = schedules(
            [],
            options_map,
            config_file=str(schedule_yaml)
        )

        # Should not generate any forecasts
        assert len(result_entries) == 0
        assert len(errors) == 0

    def test_plugin_handles_missing_yaml(self, tmp_path):
        """Should handle missing YAML file gracefully."""
        options_map = {'filename': str(tmp_path / 'main.bean')}

        result_entries, errors = schedules(
            [],
            options_map,
            config_file=str(tmp_path / "nonexistent.yaml")
        )

        # Should return original entries unchanged
        assert len(result_entries) == 0
        # Should have error
        assert len(errors) > 0
```

---

## Phase 2: Create advance-schedules Command

### 2.1 Replace advance-forecasts with advance-schedules

**Location**: `beanschedule/cli.py`

**Remove**: `advance_forecasts()` function and all related helpers

**Add new command**:

```python
@main.command(name="advance")
@click.argument("ledger_file", type=click.Path(exists=True))
@click.option(
    "--schedules",
    "-s",
    type=click.Path(exists=True),
    help="Path to schedules.yaml (auto-discovers if not provided)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview changes without writing to schedules.yaml",
)
def advance_schedules(ledger_file: str, schedules: str | None, dry_run: bool):
    """Advance schedule start dates based on matched transactions.

    This command:
    1. Loads your ledger to find matched transactions (those with schedule_id metadata)
    2. For each matched schedule, calculates the next occurrence
    3. Updates the schedule's start_date in schedules.yaml

    This keeps your schedules in sync with reality as you import real transactions.

    Examples:
        beanschedule advance main.bean
        beanschedule advance main.bean --schedules config/schedules.yaml
        beanschedule advance main.bean --dry-run
    """
    import sys
    from collections import defaultdict
    from pathlib import Path
    import yaml

    from beancount import loader
    from beancount.core import data

    from beanschedule.loader import load_schedules_file, find_schedules_location
    from beanschedule.forecast_advancement import calculate_next_occurrence

    click.echo("=" * 70)
    click.echo("Advancing Schedule Start Dates")
    click.echo("=" * 70)

    # 1. Determine schedules file path
    if schedules:
        schedules_path = Path(schedules)
    else:
        schedules_location = find_schedules_location()
        if not schedules_location:
            click.echo("Error: Could not find schedules.yaml", err=True)
            click.echo("Specify path with --schedules flag", err=True)
            sys.exit(1)
        schedules_path = Path(schedules_location)

    if not schedules_path.exists():
        click.echo(f"Error: Schedules file not found: {schedules_path}", err=True)
        sys.exit(1)

    click.echo(f"Schedules file: {schedules_path}")

    # 2. Load ledger to find matched transactions
    click.echo(f"Loading ledger: {ledger_file}")
    entries, errors, options_map = loader.load_file(str(ledger_file))

    if errors:
        # Filter to non-validation errors
        non_validation_errors = [
            e for e in errors
            if not (hasattr(e, '__class__') and 'Validation' in e.__class__.__name__)
        ]
        if non_validation_errors:
            click.echo(f"Warning: {len(non_validation_errors)} error(s) loading ledger", err=True)
            for error in non_validation_errors[:5]:
                click.echo(f"  {error}", err=True)

    # 3. Find matched transactions (schedule_id metadata, not # flag)
    matched_by_schedule = defaultdict(list)
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue

        # Only real transactions (not forecasts)
        if entry.flag == "#":
            continue

        # Has schedule_id metadata (added by hook)
        if "schedule_id" in entry.meta:
            schedule_id = entry.meta["schedule_id"]
            matched_by_schedule[schedule_id].append(entry)

    if not matched_by_schedule:
        click.echo("\nNo matched transactions found in ledger")
        click.echo("Transactions need schedule_id metadata (added by import hook)")
        return

    click.echo(f"\nFound {len(matched_by_schedule)} schedule(s) with matched transactions")

    # 4. Load schedules from YAML
    schedule_file = load_schedules_file(schedules_path)
    if not schedule_file:
        click.echo("Error: Failed to load schedules", err=True)
        sys.exit(1)

    # Build schedule lookup
    schedules_by_id = {s.id: s for s in schedule_file.schedules}

    # 5. Calculate advancements
    click.echo("\nCalculating advancements:")
    click.echo("-" * 70)

    advancements = {}  # schedule_id -> new_start_date

    for schedule_id, matched_txns in matched_by_schedule.items():
        # Find schedule
        schedule = schedules_by_id.get(schedule_id)
        if not schedule:
            click.echo(f"  {schedule_id}: Schedule not found in YAML (skipping)")
            continue

        # Find latest matched transaction
        latest_match = max(matched_txns, key=lambda t: t.date)

        # Check if advancement needed
        # Only advance if schedule start_date is close to latest match
        date_window = schedule.match.date_window_days or 3
        days_diff = (schedule.recurrence.start_date - latest_match.date).days

        # If schedule is already well ahead of matches, don't advance
        if days_diff > 2 * date_window:
            click.echo(
                f"  {schedule_id}: Already ahead "
                f"(start: {schedule.recurrence.start_date}, "
                f"latest match: {latest_match.date}) - skipping"
            )
            continue

        # Calculate next occurrence after latest match
        reference_date = max(schedule.recurrence.start_date, latest_match.date)
        next_date = calculate_next_occurrence(schedule, reference_date)

        if next_date:
            advancements[schedule_id] = next_date
            click.echo(
                f"  {schedule_id}: {schedule.recurrence.start_date} -> {next_date} "
                f"(based on match: {latest_match.date})"
            )
        else:
            click.echo(
                f"  {schedule_id}: No future occurrences "
                f"(schedule may have ended)"
            )

    if not advancements:
        click.echo("\nNo schedules need advancement")
        return

    # 6. Update YAML file (unless dry-run)
    if dry_run:
        click.echo(f"\nDry-run mode: would update {len(advancements)} schedule(s)")
        return

    # Read current YAML
    with open(schedules_path, 'r') as f:
        yaml_data = yaml.safe_load(f)

    # Update start_date for each schedule
    updated_count = 0
    for schedule_dict in yaml_data.get('schedules', []):
        schedule_id = schedule_dict.get('id')
        if schedule_id in advancements:
            new_start_date = advancements[schedule_id]
            schedule_dict['recurrence']['start_date'] = new_start_date
            updated_count += 1

    # Write back to YAML
    with open(schedules_path, 'w') as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    click.echo(f"\n✓ Updated {updated_count} schedule(s) in {schedules_path}")
```

### 2.2 Update process_imports.py Integration

**Location**: `../Beancount/scripts/process_imports.py`

**Replace**:

```python
# OLD (advance forecasts)
result = subprocess.run([
    "uv", "run", "beanschedule", "advance-forecasts",
    str(main_ledger), "--forecast-file", str(forecast_file)
], ...)
```

**With**:

```python
# NEW (advance schedules)
result = subprocess.run([
    "uv", "run", "beanschedule", "advance",
    str(main_ledger), "--schedules", str(schedules_file)
], ...)
```

---

## Phase 3: Clean Up Code

### 3.1 Delete Unused Files

**Remove these files entirely**:

```bash
rm beanschedule/forecast_loader.py
rm tests/test_forecast_advancement.py
```

### 3.2 Update Imports

**Search and remove imports**:

```bash
# Find files importing forecast_loader
grep -r "from.*forecast_loader import" beanschedule/
grep -r "import.*forecast_loader" beanschedule/

# Should only find hook.py - remove the import line
```

**In hook.py**, remove:

```python
from .forecast_loader import load_forecast_schedules
```

**Update hook.py logic** (lines 69-76):

```python
# OLD: Try loading forecast schedules
try:
    schedule_file = load_forecast_schedules(ledger_entries)
    if schedule_file:
        logger.info("Loaded schedules from forecast transactions")
except Exception as e:
    logger.warning("Failed to load forecast schedules: %s", e)

# NEW: Only load from YAML
# (This block removed entirely - always use YAML)
```

### 3.3 Simplify Hook to YAML-Only

**hook.py** (lines 66-89):

**Replace with**:

```python
# Step 1: Load schedules from YAML
try:
    schedule_file = load_schedules_file()
    if schedule_file:
        logger.info("Loaded schedules from YAML file")
    else:
        logger.info("No schedules.yaml found, returning entries unchanged")
        return extracted_entries_list
except Exception as e:
    logger.error("Failed to load YAML schedules: %s", e)
    return extracted_entries_list

enabled_schedules = get_enabled_schedules(schedule_file)
if not enabled_schedules:
    logger.info("No enabled schedules, returning entries unchanged")
    return extracted_entries_list
```

### 3.4 Remove Migrate Command

**cli.py**: Delete the `migrate()` function entirely (lines ~1387-1500)

**Why**: No longer need to convert YAML → Forecast.bean

### 3.5 Update CLI Help Text

**cli.py** main group docstring:

```python
@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def main(verbose: bool):
    """Beanschedule - Smart transaction matching and enrichment for Beancount.

    Beanschedule helps you automatically match and enrich imported bank
    transactions against recurring schedules defined in YAML.

    Quick Start:
        1. Create schedules.yaml with your recurring transactions
        2. Run: beanschedule validate schedules.yaml
        3. Import transactions with the beanschedule hook
        4. Matched transactions are automatically enriched

    Optional: Enable forecast plugin to see future transactions in ledger
        plugin "beanschedule.plugins.schedules"

    Commands:
        validate    - Validate schedules.yaml syntax and schema
        list        - List all schedules
        generate    - Generate occurrence dates for a schedule
        advance     - Update schedule start dates based on matches
        detect      - Detect recurring patterns in ledger
        init        - Initialize example schedules.yaml
    """
```

---

## Phase 4: Update Documentation

### 4.1 Update README.md

**Replace Quick Start section**:

```markdown
## Quick Start

### 1. Install

```bash
pip install beanschedule
```

### 2. Create Schedules

Create `schedules.yaml` in your Beancount directory:

```yaml
version: "1.0"

schedules:
  - id: rent-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*LANDLORD.*"
      amount: -1500.00
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent Payment"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-monthly
        category: housing
      tags: [rent, recurring]
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
        - account: Assets:Checking
```

### 3. Configure Import Hook

In your beangulp importer config:

```python
from beanschedule.hook import schedule_hook

CONFIG = [
    # ... your importers ...
]

def get_hooks():
    return [schedule_hook]
```

### 4. Import Transactions

```bash
bean-extract -e main.bean importers/config.py ~/Downloads
```

Matched transactions are automatically enriched with:

- Complete posting information
- Metadata and tags from schedule
- schedule_id for tracking
- schedule_confidence score

### 5. Optional: Enable Forecast Plugin

To see future scheduled transactions in Fava:

```beancount
; In main.bean
plugin "beanschedule.plugins.schedules"
```

The plugin reads `schedules.yaml` and generates forecast transactions
for the next year. No separate Forecast.bean file needed!

### 6. Keep Schedules Current

After importing, update schedule start dates:

```bash
beanschedule advance main.bean
```

This advances each schedule's start_date based on matched transactions,
keeping your YAML in sync with reality.

```

### 4.2 Update CLAUDE.md

**Architecture section**:
```markdown
## Architecture Overview

Beanschedule is a **beangulp hook** that matches imported transactions against
schedules defined in YAML and enriches them with posting templates.

### High-Level Flow

1. **Schedule Definition** (`schedules.yaml`)
   - User defines recurring transactions in structured YAML
   - Single source of truth for all schedules

2. **Hook Entry** (`hook.py:schedule_hook()`)
   - Called by beangulp during import
   - Loads schedules from YAML
   - Returns enriched transactions

3. **Transaction Matching** (`matcher.py`)
   - Scores imported transactions against schedules
   - Fuzzy matching for payees, amount tolerance, date windows

4. **Transaction Enrichment** (`hook.py`)
   - Adds complete postings from template
   - Adds metadata (schedule_id, confidence, etc.)
   - Merges tags

5. **Optional: Forecast Plugin** (`plugins/schedules.py`)
   - Reads schedules.yaml
   - Generates forecast transactions for Beancount ledger
   - Provides cash flow projection in Fava

6. **Schedule Advancement** (`cli.py:advance_schedules()`)
   - Finds matched transactions in ledger
   - Updates schedule start_date in YAML
   - Keeps schedules current with reality
```

### 4.3 Create Migration Guide

**New file**: `MIGRATION.md`

```markdown
# Migration Guide

## Upgrading to YAML-Only Architecture (v1.0)

Beanschedule v1.0 simplifies to a single YAML-based workflow.

### What Changed?

**Before**: Two formats (YAML + Forecast.bean)
**Now**: YAML only (plugin generates forecasts dynamically)

### If You're Using YAML Schedules

✅ **No changes needed!** Your existing `schedules.yaml` works as-is.

**Optional updates**:
1. Enable the new plugin to see forecasts in ledger:
   ```beancount
   plugin "beanschedule.plugins.schedules"
   ```

1. Use new advance command:

   ```bash
   # Old
   # (No equivalent - manual YAML editing)

   # New
   beanschedule advance main.bean
   ```

### If You're Using Forecast.bean Format

You need to convert to YAML schedules. Two options:

#### Option 1: Manual Conversion (Recommended for small setups)

Create `schedules.yaml` from your forecast transactions:

```yaml
# Example conversion
# FROM: Forecast.bean
# 2024-01-01 # "Rent" "Monthly rent"
#   schedule-id: "rent-monthly"
#   schedule-frequency: "MONTHLY"
#   schedule-day-of-month: "1"
#   Expenses:Housing:Rent  1500.00 USD
#   Assets:Checking       -1500.00 USD

# TO: schedules.yaml
schedules:
  - id: rent-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*RENT.*"  # Adjust pattern
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Rent"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-monthly
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
        - account: Assets:Checking
```

#### Option 2: Use detect Command (For larger setups)

If you have many schedules in Forecast.bean:

1. Extract schedule patterns from your ledger:

   ```bash
   beanschedule detect main.bean --output-dir schedules/
   ```

2. Review and edit generated YAML files

3. Validate:

   ```bash
   beanschedule validate schedules/
   ```

4. Delete Forecast.bean (after backing up)

### Commands That Changed

| Old Command | New Command | Notes |
|-------------|-------------|-------|
| `migrate` | (removed) | No longer needed |
| `advance-forecasts` | `advance` | Updates YAML instead of Forecast.bean |

### Plugin Changes

| Old | New |
|-----|-----|
| `plugin "beancount.plugins.forecast"` | `plugin "beanschedule.plugins.schedules"` |

The new plugin reads `schedules.yaml` directly.

### Need Help?

Open an issue: <https://github.com/yourusername/beanschedule/issues>

```

### 4.4 Update Example Files

**schedules.yaml.example**:
```yaml
version: "1.0"

# Global configuration
config:
  default_currency: USD
  match_threshold: 0.7
  fuzzy_match_threshold: 0.8
  placeholder_flag: "!"

# Schedule definitions
schedules:
  # Monthly rent payment
  - id: rent-monthly
    enabled: true
    description: "Monthly apartment rent"

    match:
      account: Assets:Bank:Checking
      payee_pattern: ".*LANDLORD.*|.*PROPERTY.*"
      amount: -1500.00
      amount_tolerance: 0.00
      date_window_days: 3

    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1

    transaction:
      payee: "Apartment Landlord"
      narration: "Monthly rent"
      metadata:
        schedule_id: rent-monthly
        category: housing
      tags: [rent, recurring, essential]
      postings:
        - account: Expenses:Housing:Rent
          amount: 1500.00
          narration: "123 Main St apt rent"
        - account: Assets:Bank:Checking

    missing_transaction:
      create_placeholder: true
      narration_prefix: "[MISSING RENT]"

  # Biweekly paycheck
  - id: paycheck-employer
    enabled: true
    description: "Biweekly paycheck from employer"

    match:
      account: Assets:Bank:Checking
      payee_pattern: ".*PAYROLL.*|.*EMPLOYER.*"
      amount: 2500.00
      amount_tolerance: 100.00
      date_window_days: 2

    recurrence:
      frequency: BIMONTHLY
      start_date: 2024-01-05
      days_of_month: [5, 20]

    transaction:
      payee: "Employer Inc"
      narration: "Biweekly salary"
      metadata:
        schedule_id: paycheck-employer
        income_type: salary
      tags: [income, salary]
      postings:
        - account: Assets:Bank:Checking
          amount: 2500.00
        - account: Income:Salary:EmployerInc

  # Weekly groceries (variable amount)
  - id: groceries-weekly
    enabled: true
    description: "Weekly grocery shopping"

    match:
      account: Assets:Bank:Checking
      payee_pattern: ".*WHOLE FOODS.*|.*TRADER.*"
      # No amount - varies week to week
      date_window_days: 2

    recurrence:
      frequency: WEEKLY
      start_date: 2024-01-07  # Sunday
      day_of_week: SUN

    transaction:
      payee: "Grocery Store"
      narration: "Weekly groceries"
      metadata:
        schedule_id: groceries-weekly
        category: food
      tags: [groceries, essential]
      postings:
        - account: Expenses:Food:Groceries
          # Amount omitted - will use import amount
        - account: Assets:Bank:Checking

    missing_transaction:
      create_placeholder: false  # Don't nag about variable spending
```

---

## Phase 5: Testing Strategy

### 5.1 Unit Tests to Update

**Keep and update**:

- `test_hook.py` - Update to YAML-only loading
- `test_matcher.py` - No changes needed
- `test_recurrence.py` - No changes needed
- `test_schema.py` - No changes needed
- `test_loader.py` - No changes needed

**Add new**:

- `test_schedules_plugin.py` - Test plugin with YAML

**Remove**:

- `test_forecast_advancement.py` - Delete entirely
- `test_forecast_loader.py` - Delete if exists

### 5.2 Integration Tests

**Create**: `tests/test_integration_yaml_only.py`

```python
"""Integration tests for YAML-only workflow."""

def test_complete_workflow(tmp_path):
    """Test complete workflow: YAML → Hook → Plugin → Advance."""

    # 1. Create schedules.yaml
    schedules_yaml = tmp_path / "schedules.yaml"
    schedules_yaml.write_text("""
version: "1.0"
schedules:
  - id: test-monthly
    enabled: true
    match:
      account: Assets:Checking
      payee_pattern: ".*TEST.*"
    recurrence:
      frequency: MONTHLY
      start_date: 2024-01-01
      day_of_month: 1
    transaction:
      payee: "Test Payee"
      narration: "Test"
      metadata:
        schedule_id: test-monthly
      postings:
        - account: Expenses:Test
          amount: 100.00
        - account: Assets:Checking
""")

    # 2. Test hook enrichment
    from beanschedule.hook import schedule_hook
    from unittest.mock import patch

    # Mock imported transaction
    # ... test hook enriches it correctly

    # 3. Test plugin generates forecasts
    from beanschedule.plugins.schedules import schedules

    # ... test plugin reads YAML and generates forecasts

    # 4. Test advance command
    # ... test advance updates YAML after match
```

### 5.3 Manual Testing Checklist

```markdown
## Manual Test Plan

### Prerequisites
- [ ] Fresh checkout of updated main branch
- [ ] Virtual environment created: `uv venv && source .venv/bin/activate`
- [ ] Package installed: `uv sync --all-extras`

### Test 1: YAML Validation
- [ ] Create schedules.yaml with valid schedule
- [ ] Run: `uv run python -m beanschedule.cli validate schedules.yaml`
- [ ] Should show: "✓ Validation successful!"
- [ ] Add syntax error to YAML
- [ ] Run validate again
- [ ] Should show clear error message

### Test 2: Import Hook
- [ ] Create test importer with schedule_hook
- [ ] Create test CSV with matching transaction
- [ ] Run bean-extract
- [ ] Verify transaction is enriched with postings and metadata

### Test 3: Forecast Plugin
- [ ] Add to test ledger: `plugin "beanschedule.plugins.schedules"`
- [ ] Run: `bean-check main.bean`
- [ ] Should load without errors
- [ ] Open in Fava
- [ ] Should see forecast transactions (# flag)
- [ ] Verify they match schedules.yaml

### Test 4: Advance Command
- [ ] Import transactions that match schedules
- [ ] Note current start_date in schedules.yaml
- [ ] Run: `uv run python -m beanschedule.cli advance main.bean`
- [ ] Check schedules.yaml
- [ ] Verify start_date advanced to next occurrence

### Test 5: Process Imports Integration
- [ ] Update process_imports.py with new advance command
- [ ] Place test files in Downloads
- [ ] Run: `python scripts/process_imports.py`
- [ ] Verify:
  - [ ] Files imported
  - [ ] Transactions enriched
  - [ ] Schedules advanced
  - [ ] Files sorted
```

---

## Phase 6: Rollout Plan

### 6.1 Branch Strategy

```bash
# Current state
git branch
# * first-big-update (abandon this)
# main

# 1. Switch to main
git checkout main

# 2. Create new feature branch
git checkout -b yaml-only-architecture

# 3. Implement changes from this action plan

# 4. Test thoroughly

# 5. Merge to main
git checkout main
git merge yaml-only-architecture

# 6. Tag release
git tag v1.0.0
git push origin v1.0.0
```

### 6.2 Release Checklist

Before releasing v1.0.0:

**Code**:

- [ ] All changes from action plan implemented
- [ ] All tests passing (should be 300+ tests)
- [ ] Code formatted: `uv run ruff format`
- [ ] Linting clean: `uv run ruff check`
- [ ] Type checking clean: `uv run mypy beanschedule/`

**Documentation**:

- [ ] README.md updated
- [ ] CLAUDE.md updated
- [ ] MIGRATION.md created
- [ ] CHANGELOG.md updated with v1.0.0 notes
- [ ] schedules.yaml.example updated
- [ ] Plugin docstrings updated

**Testing**:

- [ ] All unit tests passing
- [ ] Integration tests added and passing
- [ ] Manual test plan completed
- [ ] Tested on clean install

**Packaging**:

- [ ] Version bumped in pyproject.toml
- [ ] Dependencies up to date
- [ ] Build succeeds: `uv build`
- [ ] Can install from built wheel

**Community**:

- [ ] GitHub repo public
- [ ] Contributing guide
- [ ] Issue templates
- [ ] License file (GPLv2 per current codebase)

---

## Summary of File Changes

### Files to Create/Add

```
✨ beanschedule/plugins/schedules.py (renamed from forecast.py)
✨ tests/test_schedules_plugin.py
✨ tests/test_integration_yaml_only.py
✨ MIGRATION.md
```

### Files to Modify

```
📝 beanschedule/cli.py
   - Remove: migrate, advance-forecasts commands
   - Add: advance command
   - Update: docstrings, help text

📝 beanschedule/hook.py
   - Remove: forecast_loader import
   - Simplify: YAML-only loading

📝 README.md
   - Rewrite: Quick start, architecture, examples
   - Focus: YAML workflow

📝 CLAUDE.md
   - Update: Architecture section
   - Remove: Forecast.bean references

📝 pyproject.toml
   - Bump: version to 1.0.0

📝 ../Beancount/scripts/process_imports.py
   - Update: advance-forecasts → advance command
```

### Files to Delete

```
🗑️ beanschedule/forecast_loader.py
🗑️ tests/test_forecast_advancement.py
🗑️ IMPLEMENTATION_REVIEW.md (was temporary analysis)
```

---

## Estimated Effort

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| 1. Update Plugin | Rename, rewrite YAML loading, tests | 4-6 hours |
| 2. advance Command | Implement CLI command, tests | 3-4 hours |
| 3. Code Cleanup | Delete files, update imports | 1-2 hours |
| 4. Documentation | README, CLAUDE.md, MIGRATION.md | 2-3 hours |
| 5. Testing | Unit, integration, manual | 3-4 hours |
| 6. Rollout | Branch management, release | 1-2 hours |
| **Total** | | **14-21 hours** |

Spread over 3-5 work sessions.

---

## Success Criteria

When complete, users should be able to:

1. ✅ Define schedules in one place (schedules.yaml)
2. ✅ Run imports with automatic enrichment (hook)
3. ✅ See forecasts in ledger (optional plugin)
4. ✅ Keep schedules current (advance command)
5. ✅ No manual file syncing required
6. ✅ Clear, simple workflow
7. ✅ Well-documented with examples

**No more**:

- ❌ Maintaining Forecast.bean file
- ❌ Running migrate commands
- ❌ Confusion about which format to use
- ❌ Complex sync logic

---

## Questions & Decisions

### Q: What about existing users with Forecast.bean?

**A**: Provide clear migration guide (MIGRATION.md). Breaking change is justified for v1.0 and simplifies going forward.

### Q: Should we keep backward compatibility?

**A**: No. Clean break is better than maintaining dual code paths. Migration is straightforward.

### Q: What if users don't want forecast plugin?

**A**: Plugin is optional! Core value is hook-based enrichment, which works without plugin.

### Q: Performance impact of plugin reading YAML on every load?

**A**: Minimal. YAML parsing is fast, and happens once per `bean-check`. Can add caching later if needed.

### Q: Can we still support narration-based patterns for beanlabs compatibility?

**A**: No need. Users wanting beanlabs compatibility can use original beanlabs forecast plugin. Beanschedule is YAML-first.

---

## Next Steps

1. **Review this plan** - Make sure approach is sound
2. **Switch to main branch** - Start fresh
3. **Create yaml-only-architecture branch** - Implement changes
4. **Follow phases 1-6** - Systematic implementation
5. **Test thoroughly** - Don't rush
6. **Release v1.0.0** - Major milestone!
7. **Announce to community** - Share the simplified workflow

---

## Contact & Support

After implementation, users can:

- Report issues: GitHub Issues
- Ask questions: GitHub Discussions
- Contribute: See CONTRIBUTING.md

Let's build something simple, powerful, and easy to use! 🚀
