# Beanschedule Examples

This directory contains example schedule files and a sample Beancount ledger demonstrating how to use beanschedule.

## Example Schedules

The `schedules/` directory contains 10 example schedule files showing different recurrence patterns and matching strategies:

1. **paycheck-bimonthly.yaml** - Bi-monthly paycheck (5th and 20th) with detailed tax/benefit postings
2. **mortgage-payment.yaml** - Monthly mortgage with interest, escrow, and principal split
3. **rent-payment.yaml** - Simple monthly rent payment
4. **utilities-electric.yaml** - Monthly electric bill with variable amount (range matching)
5. **utilities-water.yaml** - Quarterly water bill (interval-based)
6. **subscription-streaming.yaml** - Monthly streaming subscription ($14.99)
7. **subscription-annual.yaml** - Annual cloud storage subscription
8. **insurance-auto.yaml** - Monthly auto insurance with policy metadata
9. **credit-card-payment.yaml** - Monthly credit card payment (variable amount)
10. **loan-payment-biweekly.yaml** - Bi-weekly student loan payment on Fridays

## Recurrence Types Demonstrated

- **MONTHLY**: Schedules that occur once per month on a specific day
- **BIMONTHLY**: Schedules that occur twice per month (e.g., 5th and 20th)
- **WEEKLY**: Schedules that occur every N weeks on a specific day
- **YEARLY**: Schedules that occur once per year on a specific date
- **INTERVAL**: Schedules that occur every N months

## Amount Matching Strategies

The examples show three ways to match transaction amounts:

1. **Fixed amount with tolerance**: `amount: -1850.00, amount_tolerance: 10.00`
   - Matches amounts between -1860.00 and -1840.00

2. **Range matching**: `amount_min: -200.00, amount_max: -50.00`
   - Matches any amount in the specified range
   - Useful for variable bills like utilities

3. **Null amount**: `amount: null`
   - Uses imported amount without matching
   - Useful when combined with other matching criteria

## Using These Examples

### 1. Try the CLI Tool

Validate the example schedules:
```bash
beanschedule validate examples/schedules/
```

List all schedules:
```bash
beanschedule list examples/schedules/
```

Generate expected dates for a schedule:
```bash
beanschedule generate mortgage-payment 2024-01-01 2024-12-31 --schedules-path examples/schedules/
```

### 2. Customize for Your Use

1. Copy the `schedules/` directory to your project:
   ```bash
   cp -r examples/schedules/ my-project/schedules/
   ```

2. Edit the schedule files to match your actual transactions:
   - Update payee patterns to match your bank's format
   - Adjust amounts and dates
   - Modify account names to match your ledger

3. Update `_config.yaml` if needed:
   - Adjust matching threshold (default: 0.80)
   - Change date window (default: 3 days)
   - Modify placeholder flag (default: '!')

### 3. Integrate with Beangulp

Add to your `importers/config.py`:

```python
from beanschedule import schedule_hook

# ... your importer configuration ...

HOOKS = [schedule_hook]
```

Then run your imports as normal:
```bash
bean-extract importers/config.py documents/ > output.beancount
```

## Tips

- **Start simple**: Begin with 2-3 schedules for your most regular transactions
- **Use metadata**: Add custom metadata fields to track additional information
- **Test patterns**: Use `beanschedule validate` to check your YAML syntax
- **Monitor matches**: Check the `schedule_confidence` metadata to see match scores
- **Adjust thresholds**: Lower the fuzzy_match_threshold if you're getting too many false matches

## Example Beancount Ledger

See `example.beancount` for a sample ledger showing how scheduled transactions appear in your Beancount file after being matched and enriched.

## Questions?

For full documentation, see the main project README and documentation at:
https://github.com/yourusername/beanschedule
