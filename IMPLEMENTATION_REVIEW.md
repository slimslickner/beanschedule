# Beanschedule Implementation Review

## 1. YAML vs Forecast Plugin Support

### ✅ YES - Supports Both

**Hook behavior** (`hook.py` lines 66-89):

```python
# Try loading forecast schedules from existing_entries first
schedule_file = load_forecast_schedules(ledger_entries)
if schedule_file:
    logger.info("Loaded schedules from forecast transactions")

# Fall back to YAML schedules if no forecast schedules found
if schedule_file is None:
    schedule_file = load_schedules_file()
    if schedule_file:
        logger.info("Loaded schedules from YAML file")
```

**Priority**: Forecast transactions → YAML files

**Migration path**: Users can gradually migrate from YAML to forecast files using the `migrate` command.

---

## 2. CLI Command Compatibility

### Command Analysis

| Command | YAML Support | Forecast Support | Notes |
|---------|--------------|------------------|-------|
| `validate` | ✅ | ❌ | Validates YAML syntax only |
| `list` | ✅ | ❌ | Lists schedules from YAML only |
| `generate` | ✅ | ❌ | Generates dates from YAML schedules |
| `show` | ✅ | ❌ | Shows YAML schedule details |
| `create` | ✅ | ❌ | Creates YAML schedule from ledger |
| `detect` | ✅ | ❌ | Detects patterns and creates YAML |
| `init` | ✅ | N/A | Initializes example YAML files |
| `migrate` | ✅ Input | ✅ Output | Converts YAML → Forecast |
| `advance-forecasts` | ❌ | ✅ | Updates forecast transactions |

### 🔴 Gap: No forecast-compatible CLI commands for validation/listing

**Recommendation**: Add forecast-compatible versions or make existing commands dual-mode.

**Proposed new commands**:

```bash
# Add --format flag to existing commands
beanschedule validate Forecast.bean --format forecast
beanschedule list Forecast.bean --format forecast
beanschedule generate paycheck 2024-01-01 2024-12-31 --forecast-file Forecast.bean
```

**OR create separate commands**:

```bash
beanschedule validate-forecast Forecast.bean
beanschedule list-forecast Forecast.bean
```

---

## 3. Forecast Plugin Cleanup

### Current Implementation

**Dual parsing** (`plugins/forecast.py` line 345-347):

```python
# Try parsing from metadata first, then narration
pattern = parse_pattern_from_metadata(entry) or parse_pattern_from_narration(
    entry.narration
)
```

**Narration syntax** (legacy beanlabs compatibility):

```beancount
2024-01-01 # "Rent" "Monthly rent [MONTHLY]"
  Expenses:Housing:Rent     1500.00 USD
  Assets:Checking          -1500.00 USD
```

**Metadata syntax** (beanschedule native):

```beancount
2024-01-01 # "Rent" "Monthly rent"
  schedule-id: "rent-monthly"
  schedule-frequency: "MONTHLY"
  schedule-day-of-month: "1"
  Expenses:Housing:Rent     1500.00 USD
  Assets:Checking          -1500.00 USD
```

### ✅ Recommended Cleanup

**Option 1: Remove narration parsing entirely**

- **Pros**: Simpler code, single source of truth, better metadata validation
- **Cons**: Breaks backward compatibility with beanlabs forecast plugin
- **Migration**: Update `migrate` command to ensure all narration patterns → metadata

**Option 2: Deprecate with warning**

- Keep narration parsing but emit deprecation warning
- Plan to remove in next major version
- Gives users time to migrate

**Option 3: Keep both (current state)**

- Maintain backward compatibility
- Metadata-first priority is already correct

**Recommendation**: **Option 2 - Deprecate with warning**

```python
# In parse_pattern_from_narration():
if pattern_match:
    logger.warning(
        "Deprecated: Using [PATTERN] syntax in narration. "
        "Please migrate to schedule-frequency metadata. "
        "See: beanschedule migrate --help"
    )
```

### Specific Cleanups

1. **Remove redundant narration syntax from docstrings**
   - Update plugin docstring to show metadata as primary method
   - Move narration examples to "Legacy Compatibility" section

2. **Simplify pattern parsing**
   - If we remove narration parsing, delete `parse_pattern_from_narration()` entirely
   - Reduces code from ~340 lines → ~200 lines (40% reduction)

3. **Improve error messages**
   - Add validation errors for missing required metadata fields
   - Currently silently falls through if metadata malformed

---

## 4. General Cleanup for Refactor Branch

### Code Organization

#### A. Remove Unused/Deprecated Code

**Check for**:

```bash
# Find TODOs and FIXMEs
grep -rn "TODO\|FIXME" beanschedule/

# Find unused imports
ruff check beanschedule/ --select F401

# Find commented-out code
grep -rn "^#.*def \|^#.*class " beanschedule/
```

#### B. Documentation Updates

**Files to update**:

- [ ] `README.md` - Update to reflect forecast-first approach
- [ ] `ROADMAP.md` - Mark completed items, update priorities
- [ ] `CLAUDE.md` - Update architecture section with forecast workflow
- [ ] Add `MIGRATION.md` - Guide for YAML → forecast transition

**README changes needed**:

1. **Quick Start** should show forecast file example, not YAML
2. **Installation** section looks good
3. **Usage** should highlight `migrate` command prominently
4. Add **"Forecast vs YAML"** comparison section

#### C. Test Coverage Gaps

**Current coverage**: 73% overall

**Low coverage areas**:

- `cli.py`: 51% (lots of untested CLI commands)
- `detector.py`: 90% (good!)
- `forecast_loader.py`: 64%
- `loader.py`: 88% (YAML loader)

**Recommendation**: Add tests for:

1. `validate` command with various error cases
2. `list` command output formats
3. `generate` command edge cases
4. Forecast loader edge cases (malformed metadata)

#### D. Code Quality

**Run formatters/linters**:

```bash
# Format
uv run ruff format beanschedule/ tests/

# Lint
uv run ruff check beanschedule/ tests/ --fix

# Type check
uv run mypy beanschedule/
```

**Known issues from CLAUDE.md**:

- ⚠️ Logging f-strings → deferred formatting (ROADMAP priority)
- ⚠️ Some recurrence tests pending

#### E. Dependency Audit

**Check for unused dependencies**:

```bash
# List all imports
grep -rh "^import \|^from " beanschedule/ | sort -u > /tmp/imports.txt

# Compare with pyproject.toml dependencies
```

#### F. API Consistency

**Naming inconsistencies**:

- Hook uses `schedule_id` (underscore)
- Forecast uses `schedule-id` (hyphen)
- Both are correct for their context (Python vs Beancount)

**Metadata naming**:

- Forecast transactions: `schedule-*` (hyphenated)
- Matched transactions: `schedule_*` (underscored)
- This is intentional - distinguish source vs enrichment

#### G. Performance Optimizations

**From ROADMAP.md**:

1. ✅ **Lazy matching** - DONE (80% speedup)
2. 🔲 **Payee pattern compilation** - Pre-compile regex (40-50% speedup)
3. 🔲 **Fuzzy match caching** - Cache `SequenceMatcher` results (10-20% speedup)
4. 🔲 **Skip ledger checking** - Don't check all entries for schedule_id

### Specific File Reviews

#### `cli.py` (865 lines)

**Issues**:

- Very long file, could split into modules
- Many similar command implementations (DRY violation)
- Low test coverage (51%)

**Recommendations**:

- Extract common loading logic to helper functions
- Create `cli/` directory with command modules:

  ```
  cli/
    __init__.py
    validate.py
    list.py
    generate.py
    migrate.py
    advance.py
    common.py  # shared helpers
  ```

#### `hook.py` (323 lines)

**Issues**:

- Complex function with many steps
- Some helper functions at end of file

**Recommendations**:

- Keep main hook simple, extract helpers to separate module
- Better separation of concerns

#### `forecast_loader.py` (188 lines)

**Issues**:

- Parses metadata manually with lots of conditionals
- Error handling could be better

**Recommendations**:

- Use pydantic for metadata validation (already using for schema.py)
- More specific error messages

#### `plugins/forecast.py` (167 lines)

**Issues**:

- Dual parsing (narration + metadata)
- No deprecation warnings
- Complex regex patterns

**Recommendations**:

- Deprecate narration syntax with warning
- Simplify to metadata-only in v2.0
- Better error messages for malformed patterns

---

## Summary Recommendations

### High Priority (Before merging to main)

1. ✅ **Add deprecation warnings** for narration-based patterns in forecast plugin
2. ✅ **Update README.md** to show forecast-first approach
3. ✅ **Run ruff format + lint** on entire codebase
4. ✅ **Fix logging f-strings** (ROADMAP item)
5. ✅ **Add MIGRATION.md** guide

### Medium Priority (Can do after merge)

1. 🔲 **Add forecast support** to `validate`, `list`, `generate` commands
2. 🔲 **Split cli.py** into modules for better organization
3. 🔲 **Improve test coverage** for CLI commands (51% → 80%+)
4. 🔲 **Performance optimizations** (payee pattern compilation, caching)

### Low Priority (Future enhancements)

1. 🔲 **Remove narration parsing** entirely (v2.0 breaking change)
2. 🔲 **Refactor hook.py** for better separation of concerns
3. 🔲 **Pydantic validation** in forecast_loader.py

---

## Migration Checklist for Main Branch

- [ ] All tests passing (316 tests currently)
- [ ] Documentation updated (README, ROADMAP, new MIGRATION.md)
- [ ] Code formatted and linted (ruff)
- [ ] Type hints checked (mypy)
- [ ] Changelog updated (CHANGELOG.md)
- [ ] Version bumped in pyproject.toml
- [ ] No regressions in YAML workflow
- [ ] Forecast workflow fully tested
- [ ] advance-forecasts integrated in process_imports.py
