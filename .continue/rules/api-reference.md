# API Reference

## Core Modules

### schema.py — Data Models

Pydantic v2 models with validation. All use `model_validate()` or constructor.

**GlobalConfig** - Matching thresholds and behavior
```python
class GlobalConfig(BaseModel):
    match_threshold: float = 0.75  # Min score to match
    date_window_days: int = 3
    fuzzy_match_threshold: float = 0.8
```

**MatchCriteria** - What to match against
```python
class MatchCriteria(BaseModel):
    account: str  # e.g., "Assets:Bank:Checking" (required)
    payee_pattern: str  # Regex pattern
    amount: AmountCriteria  # Exact, range, or tolerance
    date_window_days: int = 3
```

**AmountCriteria** - Amount matching rules
```python
class AmountCriteria(BaseModel):
    # One of:
    exact: float | None = None  # Exact amount
    min: float | max: float | None = None  # Range
    tolerance: float | None = None  # ±tolerance with linear decay
```

**RecurrenceRule** - How often the transaction occurs
```python
class RecurrenceRule(BaseModel):
    frequency: FrequencyType  # MONTHLY, WEEKLY, YEARLY, BIMONTHLY, INTERVAL
    day_of_month: int | None = None  # For MONTHLY
    day_of_week: int | None = None  # For WEEKLY (0=Mon, 6=Sun)
    interval: int = 1
    dates: list[date] | None = None  # Specific dates
```

**Schedule** - Complete schedule definition
```python
class Schedule(BaseModel):
    id: str
    match_criteria: MatchCriteria
    recurrence_rule: RecurrenceRule
    postings: list[Posting]  # Template postings to add
    tags: set[str] = set()
    narration_override: str | None = None
```

**ScheduleFile** - Loaded YAML file
```python
class ScheduleFile(BaseModel):
    config: GlobalConfig
    schedules: list[Schedule]
```

---

### matcher.py — Matching Algorithm

**TransactionMatcher** - Main scoring class

```python
class TransactionMatcher:
    def __init__(self, config: GlobalConfig)

    def calculate_match_score(
        self,
        transaction: Transaction,
        schedule: Schedule,
        expected_date: date
    ) -> float:
        """
        Score transaction against schedule.
        Returns 0.0-1.0 (0 if account mismatch).
        Formula: 0.4 * payee + 0.4 * amount + 0.2 * date
        """

    def find_best_match(
        self,
        transaction: Transaction,
        schedules: list[Schedule],
        expected_dates: list[date]
    ) -> tuple[Schedule, date, float] | None:
        """
        Find best matching schedule for transaction.
        Returns (schedule, expected_date, score) or None if no match ≥ threshold.
        """
```

**Scoring Breakdown** (0.0-1.0 per component):
- **Payee** (40%): Exact match > fuzzy match (difflib) > regex match > no match
- **Amount** (40%): Exact match > within tolerance > within range > no match
- **Date** (20%): Exact match > within window > outside window

---

### recurrence.py — Date Generation

**RecurrenceEngine** - Generates expected transaction dates

```python
class RecurrenceEngine:
    def generate(
        self,
        rule: RecurrenceRule,
        start: date,
        end: date
    ) -> list[date]:
        """
        Generate transaction dates for schedule.
        Supports: MONTHLY, WEEKLY, YEARLY, BIMONTHLY, INTERVAL.
        Uses dateutil.rrule for robust date math.
        Returns dates in [start, end] range.
        """
```

**Frequency Types** (from `FrequencyType` enum):
- `MONTHLY` - Day of month (e.g., 15th each month)
- `WEEKLY` - Day of week (e.g., every Tuesday)
- `YEARLY` - Specific date (e.g., Dec 25)
- `BIMONTHLY` - Every other month on specific day
- `INTERVAL` - Custom intervals (uses `dateutil.rrule`)

---

### loader.py — YAML Loading

**File Modes**:
1. Single file: `schedules.yaml`
2. Directory: `schedules/` with `_config.yaml` + `*.yaml` files

**Main Functions**:

```python
def load_schedules_file(path: Path) -> ScheduleFile:
    """Load and validate schedules.yaml or schedules/_config.yaml."""

def load_schedules_from_directory(path: Path) -> ScheduleFile:
    """Load schedules/ directory with _config.yaml."""

def find_schedules_location(
    start_dir: Path | None = None
) -> Path:
    """
    Auto-discover schedules in order:
    1. $BEANSCHEDULE_DIR env var
    2. Current directory (schedules.yaml or schedules/)
    3. Parent of current dir (if looks like importers dir)
    Raises FileNotFoundError if not found.
    """
```

---

### hook.py — Beangulp Integration

**Main Hook Function**:

```python
def schedule_hook(
    account: str,
    directives: list,
    date_range: tuple[date, date],
    progress: Any = None
) -> tuple[str, list, list]:
    """
    Beangulp hook entry point.

    Input:
    - account: Account being imported
    - directives: Extracted transactions
    - date_range: (start, end) date range
    - progress: Progress callback (unused)

    Output:
    - (account, new_directives, placeholders)

    Process:
    1. Load schedules (auto-discovery)
    2. Generate expected dates per schedule
    3. Match transactions using lazy date index
    4. Enrich matched transactions
    5. Create placeholders for missing matches
    """
```

**Internal Functions**:

```python
def _generate_expected_occurrences(
    schedules: ScheduleFile,
    date_range: tuple[date, date]
) -> dict[str, list[date]]:
    """Map schedule.id → [expected dates]."""

def _build_date_index(
    directives: list
) -> dict[date, list]:
    """Map date → [transactions on that date]. O(1) lookup."""

def _enrich_transaction(
    transaction: Transaction,
    schedule: Schedule,
    matched_date: date,
    score: float
) -> Transaction:
    """Add metadata, merge tags, add postings."""

def _create_placeholder(
    schedule: Schedule,
    expected_date: date
) -> Transaction:
    """Create [MISSING] placeholder transaction."""
```

---

### cli.py — Command-Line Interface

**Module**: `beanschedule.cli` (modular package)

```python
from beanschedule.cli import main

# Entry point
def main(ctx: click.Context, debug: bool = False):
    """Beanschedule: Match and enrich scheduled transactions."""
```

**Commands**:

```python
@main.command()
def validate(path: str):
    """Validate schedule YAML file."""

@main.command()
@click.option('--schedule', help='Filter by schedule ID')
@click.option('--limit', type=int, help='Max results')
def list(path: str, schedule: str, limit: int):
    """List schedules with details."""

@main.command()
@click.option('--start', required=True, help='Start date (YYYY-MM-DD)')
@click.option('--end', required=True, help='End date (YYYY-MM-DD)')
def generate(schedule_id: str, start: str, end: str):
    """Generate expected dates for schedule."""

@main.command()
@click.option('--output', default='schedules/', help='Output directory')
def init(output: str):
    """Create example schedules/."""
```

**Testing CLI**: Use Click's `CliRunner` (not manual execution):
```python
from click.testing import CliRunner
from beanschedule.cli import main

def test_validate():
    runner = CliRunner()
    result = runner.invoke(main, ['validate', 'schedules.yaml'])
    assert result.exit_code == 0
```

---

### utils.py — Helper Functions

```python
def slugify(text: str) -> str:
    """Convert text to slug (lowercase, hyphens, alphanumeric)."""
    # Used for schedule IDs and file names
```

---

## Key Patterns

### Creating Models

```python
# From dict (YAML)
schedule = Schedule.model_validate(yaml_dict)

# From constructor
config = GlobalConfig(match_threshold=0.8)

# Validation fails fast
try:
    schedule = Schedule.model_validate(invalid_dict)
except ValidationError as e:
    print(f"Invalid schedule: {e}")
```

### Matching a Transaction

```python
from beanschedule.matcher import TransactionMatcher
from beanschedule.schema import GlobalConfig

matcher = TransactionMatcher(GlobalConfig())

# Single score
score = matcher.calculate_match_score(txn, schedule, expected_date)

# Find best match
result = matcher.find_best_match(txn, schedules, expected_dates)
if result:
    schedule, matched_date, score = result
    print(f"Matched with confidence {score}")
```

### Generating Expected Dates

```python
from beanschedule.recurrence import RecurrenceEngine
from datetime import date

engine = RecurrenceEngine()
dates = engine.generate(
    rule=schedule.recurrence_rule,
    start=date(2024, 1, 1),
    end=date(2024, 12, 31)
)
```

### Loading Schedules

```python
from beanschedule.loader import load_schedules_file, find_schedules_location

# Auto-discover
path = find_schedules_location()
schedule_file = load_schedules_file(path)

# Explicit path
schedule_file = load_schedules_file(Path('schedules.yaml'))

# Access config and schedules
for schedule in schedule_file.schedules:
    print(f"{schedule.id}: {schedule.match_criteria.account}")
```
