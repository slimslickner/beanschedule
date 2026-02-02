# Stateful Amortization - Current Limitations and Solutions

## The Problem

**Current Implementation (Stateless)**

The current amortization is "stateless" - it calculates based solely on original loan parameters:

```yaml
amortization:
  principal: 320000.00  # Original amount
  annual_rate: 0.07
  term_months: 360
  start_date: 2024-01-01
  extra_principal: 100.00  # Fixed extra amount
```

**Limitations:**

1. ❌ **Can't start extra payments mid-loan**
   - Example: "I want to start paying $200 extra starting in year 5"
   - Current: `extra_principal` applies from day 1

2. ❌ **Doesn't reflect actual balance**
   - If you've made lump sum payments, forecasts still use theoretical balance
   - Current: Always calculates from original principal

3. ❌ **No accounting for missed/late payments**
   - If actual payments differ from schedule, forecasts are wrong
   - Current: Assumes perfect payment history

4. ❌ **Can't model refinancing/modifications**
   - Example: "I refinanced at year 10 with new rate"
   - Current: No way to adjust mid-loan

## Real-World Scenario

**You want to do this:**

```
Year 1-5:  Pay normal P&I only (no extra)
Year 6+:   Pay P&I + $500 extra principal
```

**Current amortization can't model this!**

## Proposed Solutions

### Solution 1: Multiple Schedules (Current Workaround)

Create separate schedules for different periods:

```yaml
# Years 1-5: Normal payments
- id: mortgage-2024-2029
  enabled: false  # Disable after year 5
  recurrence:
    start_date: 2024-01-01
    end_date: 2029-12-31
  amortization:
    principal: 320000.00
    annual_rate: 0.07
    term_months: 360
    start_date: 2024-01-01
    # No extra principal

# Years 6+: With extra payments
- id: mortgage-2030-onwards
  enabled: true
  recurrence:
    start_date: 2030-01-01
  amortization:
    principal: 285432.18  # Calculated balance at end of year 5
    annual_rate: 0.07
    term_months: 300  # 25 years remaining
    start_date: 2030-01-01
    extra_principal: 500.00  # New extra amount
```

**Pros:**
- ✅ Works with current implementation
- ✅ Can model different periods

**Cons:**
- ❌ Manual calculation of remaining balance
- ❌ Requires creating new schedule each time
- ❌ Not dynamic - doesn't adapt to actual payments

### Solution 2: Ledger-Based Balance (Proposed Enhancement)

**Add optional ledger query to amortization:**

```yaml
amortization:
  # Option A: Static (current behavior)
  principal: 320000.00
  start_date: 2024-01-01

  # Option B: Ledger-based (NEW!)
  balance_account: Liabilities:Mortgage:Principal
  balance_as_of: today  # or specific date

  annual_rate: 0.07
  remaining_months: auto  # Calculate from balance and payment

  # Extra principal schedule (NEW!)
  extra_principal_schedule:
    - start_date: 2024-01-01
      amount: 0.00
    - start_date: 2029-01-01
      amount: 500.00
```

**Implementation:**

```python
# In schedules.py plugin
if schedule.amortization.balance_account:
    # Query ledger for current balance
    from beancount.query import query

    balance = get_account_balance(
        ledger_entries,
        schedule.amortization.balance_account,
        schedule.amortization.balance_as_of
    )

    # Use current balance as "principal" for future forecasts
    amort = AmortizationSchedule(
        principal=balance,  # Current balance, not original
        annual_rate=schedule.amortization.annual_rate,
        term_months=calculate_remaining_months(balance, payment, rate),
        start_date=date.today(),  # From today, not original start
    )
```

**Pros:**
- ✅ Adapts to actual payments
- ✅ Reflects reality, not theory
- ✅ Handles lump sum payments automatically
- ✅ Single schedule for entire loan

**Cons:**
- ❌ Complex implementation
- ❌ Requires ledger query capability
- ❌ May be slow with large ledgers

### Solution 3: Amortization Overrides (Simpler Enhancement)

**Add date-based overrides:**

```yaml
amortization:
  principal: 320000.00
  annual_rate: 0.07
  term_months: 360
  start_date: 2024-01-01

  # Override starting from specific dates (NEW!)
  overrides:
    - effective_date: 2029-01-01
      principal: 285432.18  # Manually calculated balance
      extra_principal: 500.00

    - effective_date: 2034-01-01
      principal: 198234.56  # Updated balance
      extra_principal: 1000.00  # Increase extra payment
```

**Implementation:**

```python
def get_active_override(schedule, occurrence_date):
    """Find the most recent override before occurrence_date."""
    if not schedule.amortization.overrides:
        return None

    active = None
    for override in sorted(schedule.amortization.overrides,
                          key=lambda x: x.effective_date):
        if override.effective_date <= occurrence_date:
            active = override
    return active

# In forecast generation
override = get_active_override(schedule, occurrence_date)
if override:
    # Use override values
    amort = AmortizationSchedule(
        principal=override.principal,
        extra_principal=override.extra_principal or 0,
        ...
    )
```

**Pros:**
- ✅ Moderate complexity
- ✅ No ledger queries needed
- ✅ Explicit and clear
- ✅ Handles planned changes

**Cons:**
- ❌ Still manual balance calculation
- ❌ Doesn't adapt to unexpected payments
- ❌ Requires YAML updates

## Recommended Approach

**Phase 1: Amortization Overrides (Immediate)**

Implement Solution 3 for planned scenarios:

```yaml
# Example: Plan to increase extra payments in year 6
amortization:
  principal: 320000.00
  annual_rate: 0.07
  term_months: 360
  start_date: 2024-01-01

  # Use CLI to calculate balance at year 5:
  # $ beanschedule amortize mortgage --format json | jq '.payments[59].balance'

  overrides:
    - effective_date: 2029-01-01
      principal: 285432.18  # From CLI output
      extra_principal: 500.00
```

**Phase 2: Ledger-Based Balance (Future)**

Add ledger query support for true stateful amortization:

```yaml
amortization:
  balance_account: Liabilities:Mortgage:Principal
  balance_as_of: today
  annual_rate: 0.07
  remaining_months: auto
```

## Current Workarounds

### 1. Use CLI to Calculate Future Balance

```bash
# See balance after payment #60 (5 years)
beanschedule amortize mortgage-payment --format json | \
  jq '.payments[59] | {payment: .payment_number, balance: .balance}'
```

Output:
```json
{
  "payment": 60,
  "balance": "285432.18"
}
```

### 2. Create Schedule for Each Phase

```yaml
# mortgage-2024-2028.yaml (Years 1-4, enabled)
# mortgage-2029-onwards.yaml (Years 5+, enabled)
```

### 3. Manual Annual Adjustments

Once a year:
1. Check actual balance: `bean-query ledger.bean "SELECT sum(position) WHERE account ~ 'Mortgage'"`
2. Update schedule with current balance
3. Recalculate term

## Feature Request Tracking

**Immediate Needs:**
- [ ] Amortization overrides (Solution 3)
- [ ] CLI command to calculate balance at specific payment #
- [ ] Helper to generate override YAML from current schedule

**Future Enhancements:**
- [ ] Ledger-based balance queries (Solution 2)
- [ ] Auto-calculate remaining term
- [ ] Variable extra principal schedule
- [ ] Refinancing support

## Impact on Current Implementation

**No breaking changes needed:**
- Current stateless amortization remains default
- New features are opt-in
- Backward compatible

**Minimal changes:**
- Add `overrides` field to `AmortizationConfig` (optional)
- Update `AmortizationSchedule` to accept override parameters
- Modify plugin to check for overrides before generating forecasts

## Example Usage (After Implementation)

```yaml
id: mortgage-with-planned-extra
enabled: true

match:
  account: Assets:Checking
  payee_pattern: "MORTGAGE"

recurrence:
  frequency: MONTHLY
  start_date: 2024-01-01
  day_of_month: 1

amortization:
  principal: 320000.00
  annual_rate: 0.07
  term_months: 360
  start_date: 2024-01-01

  # Plan to increase payments over time
  overrides:
    # Year 6: Start $200 extra
    - effective_date: 2029-01-01
      principal: 285432.18  # Calculate via CLI or spreadsheet
      extra_principal: 200.00

    # Year 11: Increase to $500 extra
    - effective_date: 2034-01-01
      principal: 198234.56
      extra_principal: 500.00

transaction:
  payee: "Mortgage Company"
  metadata:
    schedule_id: mortgage-with-planned-extra
  postings:
    - account: Assets:Checking
      amount: null
    - account: Expenses:Mortgage-Interest
      amount: null
    - account: Liabilities:Mortgage
      amount: null
```

## Conclusion

**Current State:**
- ✅ Works for "happy path" loans
- ❌ Limited flexibility for real-world scenarios

**Recommended:**
1. **Short-term**: Use multiple schedules workaround
2. **Medium-term**: Implement amortization overrides
3. **Long-term**: Add ledger-based balance queries

This provides a migration path from stateless to stateful amortization without breaking existing functionality.

---

**Status**: Analysis Complete
**Priority**: High (common use case)
**Complexity**: Medium (overrides), High (ledger integration)
