# Coding Standards & Patterns

## Code Quality Tools

From `pyproject.toml`:

- **Formatter**: Ruff (100 char line length)
- **Linter**: Ruff strict mode (E,F,I,N,UP,B,A,COM,C4,DTZ,ISC,ICN,G,PIE,T20,Q,RSE,RET,SLF,SIM,TID,ARG,PTH,ERA,PL,RUF)
- **Type Checker**: mypy (not strict, enforces basic types)
- **Tests**: pytest 85%+ coverage target

Run checks:
```bash
uv run ruff check beanschedule/ tests/    # Lint
uv run ruff format beanschedule/ tests/   # Format
uv run mypy beanschedule/                 # Type check
```

## Key Code Patterns

### 1. Pydantic Models (schema.py)

All configuration/data models use Pydantic v2 with validation:

```python
from pydantic import BaseModel, Field, field_validator

class MatchCriteria(BaseModel):
    account: str
    payee_pattern: str
    amount: AmountCriteria
    date_window_days: int = Field(default=3, ge=0)

    @field_validator('payee_pattern')
    @classmethod
    def validate_regex(cls, v: str) -> str:
        re.compile(v)  # Fail fast on invalid regex
        return v
```

**Pattern**: Models validate at construction time. Fail fast if config is invalid.

### 2. Matcher Algorithm (matcher.py)

Weighted scoring with clear logic:

```python
def calculate_match_score(
    self,
    transaction: Transaction,
    schedule: Schedule,
    expected_date: date
) -> float:
    # Account must match (binary)
    if transaction.account != schedule.match_criteria.account:
        return 0.0

    # Weighted scores: payee (40%) + amount (40%) + date (20%)
    payee_score = self._score_payee(...)  # 0.0-1.0
    amount_score = self._score_amount(...)  # 0.0-1.0
    date_score = self._score_date(...)  # 0.0-1.0

    return 0.4 * payee_score + 0.4 * amount_score + 0.2 * date_score
```

**Pattern**: Clear, explicit scoring with no magic numbers. Weights documented.

### 3. Date Generation (recurrence.py)

Separate methods per frequency type:

```python
def _generate_monthly(self, start: date, end: date, rule: RecurrenceRule) -> list[date]:
    """Generate dates on specific day of month."""
    ...

def _generate_bimonthly(self, start: date, end: date, rule: RecurrenceRule) -> list[date]:
    """Every other month on specific day."""
    ...
```

**Pattern**: One function per frequency type. Easy to test, maintain, extend.

### 4. Lazy Date Indexing (hook.py)

Build index once, use for O(1) lookups:

```python
def _build_date_index(transactions: list[Transaction]) -> dict[date, list[Transaction]]:
    """Map date → [transactions on that date]."""
    index = defaultdict(list)
    for txn in transactions:
        index[txn.date].append(txn)
    return index

# Later: transactions_in_window = index.get(expected_date, [])
```

**Pattern**: Pre-compute expensive lookups. One-time O(n), reused many times.

## Logging

Use **deferred formatting** (not f-strings):

```python
# Good ✅
logger.info("Matched transaction %s with confidence %f", payee, confidence)

# Bad ❌
logger.info(f"Matched transaction {payee} with confidence {confidence}")
```

**Why**: Avoids string interpolation when log level is disabled.

## Validation & Error Handling

- **At boundaries**: Validate YAML input at load time (loader.py)
- **In models**: Pydantic validates at construction (schema.py)
- **Trust internal code**: Don't validate outputs from other modules
- **Explicit errors**: Use descriptive exception messages with context

## Type Hints

Required on all public functions:

```python
def calculate_match_score(
    self,
    transaction: Transaction,
    schedule: Schedule,
    expected_date: date
) -> float:
    ...
```

Optional on simple internal functions, required on complex ones.

## No Premature Abstraction

- One-time operations: don't create helpers
- Similar code appearing 2-3 times: it's OK to repeat
- Simple features: no configurability if not needed yet

## Code Reviews

When reviewing, check:
1. ✅ Tests added/updated for the change
2. ✅ No new ruff/mypy violations
3. ✅ Type hints on public functions
4. ✅ Deferred logging (no f-strings in logger calls)
5. ✅ No unnecessary abstraction or error handling

See `.continue/rules/testing-guide.md` for test patterns.
