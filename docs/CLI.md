# Command-Line Interface (CLI)

Beanschedule provides tools for validating, testing, generating, and managing schedules.

## General Options

All commands support:

```bash
--help          # Show command help
--verbose, -v   # Verbose output
```

## Schedules Management

### validate

Validate schedule files for syntax and configuration errors:

```bash
beanschedule validate schedules/
beanschedule validate schedules.yaml
beanschedule validate schedules/ --verbose
```

Checks:

- YAML syntax
- Required fields
- Data type validation
- Recurrence pattern validity
- Account specifications

**Exit codes:**

- `0` - All valid
- `1` - Validation errors found

### list

List all schedules with summary information:

```bash
# Table format (default)
beanschedule list schedules/

# JSON format
beanschedule list schedules/ --format json

# Only enabled schedules
beanschedule list schedules/ --enabled-only

# Verbose output with all details
beanschedule list schedules/ --verbose
```

Output example:

```
Schedule               Account                  Payee Pattern              Amount    Frequency
────────────────────────────────────────────────────────────────────────────────────────────
rent-payment          Assets:Bank:Checking     Property Manager|Landlord  -1500.00  Monthly
electric-bill         Assets:Bank:Checking     Electric|Edison            -50/-200  Monthly
paycheck              Assets:Bank:Checking     MY EMPLOYER                3200.00   Biweekly
```

### show

Display detailed information about a schedule:

```bash
beanschedule show rent-payment
beanschedule show rent-payment --count 12  # Show next 12 occurrences
```

Output:

```
Schedule: rent-payment

Match:
  Account: Assets:Bank:Checking
  Payee: Property Manager|Landlord
  Amount: -1500.00 (tolerance: ±0%)
  Date Window: ±2 days

Recurrence: Monthly on day 1
Next occurrences:
  2026-02-01
  2026-03-01
  2026-04-01
  ...

Transaction Template:
  Payee: Property Manager
  Narration: Monthly Rent
  Tags: [housing]
  Metadata: {schedule_id: rent-payment}
  Postings:
    Assets:Bank:Checking    null
    Expenses:Housing:Rent   null

Missing Transaction Handling:
  Create Placeholder: Yes
  Flag: !
  Prefix: [MISSING]
```

### generate

Generate expected occurrence dates for a schedule:

```bash
beanschedule generate rent-payment 2024-01-01 2024-12-31
beanschedule generate paycheck 2026-01-01 2026-03-31
```

Output:

```
rent-payment (2024-01-01 to 2024-12-31):
  2024-01-01
  2024-02-01
  2024-03-01
  ...
  2024-12-01

Total: 12 occurrences
```

### init

Initialize a new schedules directory with example files:

```bash
beanschedule init
beanschedule init my-schedules/
```

Creates:

```
schedules/
  _config.yaml          # Configuration file
  rent.yaml             # Example monthly schedule
  paycheck.yaml         # Example biweekly schedule
  utilities.yaml        # Example with variable amount
  README.md             # Quick reference
```

## Schedule Discovery

### detect

Auto-detect recurring patterns in your ledger:

```bash
# Show detected patterns (table format)
beanschedule detect ledger.beancount

# Higher confidence threshold
beanschedule detect ledger.beancount --confidence 0.80

# JSON output for processing
beanschedule detect ledger.beancount --format json

# Save as YAML schedule files
beanschedule detect ledger.beancount --output-dir detected-schedules/

# Adjust sensitivity
beanschedule detect ledger.beancount \
  --confidence 0.75 \
  --fuzzy-threshold 0.85 \
  --amount-tolerance 0.05 \
  --min-occurrences 3
```

Output:

```
Detected 15 recurring patterns (confidence >= 60%):

Confidence  Frequency  Payee                  Account                 Amount   Count
─────────────────────────────────────────────────────────────────────────────────────
99%         Monthly    BANK FEES              Assets:US:BofA:Checking  4.00     36
99%         Monthly    EDISON POWER           Assets:US:BofA:Checking  65.00    35
98%         Monthly    RiverBank Properties   Assets:US:BofA:Checking  2400.00  35
```

### create

Create a schedule interactively from a ledger transaction:

```bash
# Find a transaction and create schedule from it
beanschedule create --ledger ledger.beancount --date 2024-01-15

# Specify account
beanschedule create --ledger ledger.beancount --date 2024-01-15 --account Assets:Checking
```

Interactive process:

```
Found transaction:
  2024-01-15 "PROPERTY MGR" -1500.00 USD

Create schedule? (y/n): y
Schedule ID: rent-payment
Enabled: true
Frequency: [MONTHLY, WEEKLY, BIWEEKLY, ...]: MONTHLY
Day of month: [1-31]: 1
Payee pattern: Property Manager|Landlord
Amount: -1500.00
Amount tolerance: 0.00
Date window: 2

Schedule created at: schedules/rent-payment.yaml
```

## Pending Transactions

### pending list

List all pending transactions:

```bash
beanschedule pending list
beanschedule pending list --format json
```

Output:

```
PENDING TRANSACTIONS (2)

2026-02-20: Amazon - -89.99 USD (3 postings)
  Wireless headphones (not yet charged)

2026-02-22: Whole Foods - -127.45 USD (2 postings)
  Groceries (not yet charged)
```

### pending create

Create a pending transaction interactively:

```bash
beanschedule pending create \
  --account Assets:Checking \
  --amount -89.99 \
  --date 2026-02-20 \
  --payee "Amazon" \
  --narration "Wireless headphones"
```

Interactive process:

```
Account 1: Assets:Checking (-89.99 USD)
Split name: Electronics
Account 2: Expenses:Electronics:Audio (89.99 USD)
Add another split? (y/n): y
Split name: Shipping
Account 3: Expenses:Shopping:Shipping (0.00 USD)
Amount for Expenses:Shopping:Shipping: 4.99
Add another split? (y/n): n

Created pending transaction for 2026-02-20 (Amazon)
```

### pending clean

Remove the pending file if empty:

```bash
beanschedule pending clean
```

## Skip Markers

### skip

Mark a scheduled transaction as intentionally skipped:

```bash
# Single date
beanschedule skip rent-payment 2026-02-15

# Multiple dates
beanschedule skip gym-membership 2026-02-15 2026-07-15

# With reason
beanschedule skip utility-payment 2026-04-01 --reason "Prepaid for 2 months"

# Append to file instead of printing
beanschedule skip rent-payment 2026-03-01 --output ledger.beancount

# Custom schedule location
beanschedule skip payment-id 2026-02-01 --schedules-path my-schedules/
```

Output:

```beancount
2026-02-15 S "Payee" "[SKIPPED] Prepaid"
  schedule_id: "rent-payment"
  schedule_skipped: "Prepaid"
  Assets:Checking
```

## Loan Amortization

### amortize

Display amortization schedule for a loan:

```bash
# Static amortization (from original terms)
beanschedule amortize mortgage-payment

# Stateful amortization (from ledger balance)
beanschedule amortize student-loan --ledger ledger.beancount

# Show fewer rows
beanschedule amortize mortgage-payment --limit 12

# Summary statistics only
beanschedule amortize mortgage-payment --summary-only

# Different output format
beanschedule amortize mortgage-payment --format csv

# Custom forecast horizon for stateful mode
beanschedule amortize student-loan --ledger ledger.beancount --horizon 24
```

Options:

- `--ledger, -l PATH` - Path to Beancount ledger (required for stateful mode with `balance_from_ledger: true`)
- `--horizon N` - Forecast horizon in months for stateful mode (default: 12)
- `--format` - Output format: `table`, `csv`, or `json` (default: table)
- `--limit N` - Limit number of payment rows to display
- `--summary-only` - Show summary statistics instead of full amortization table
- `--schedules-path PATH` - Path to schedules directory (default: schedules)

## Shell Tab Completion

Enable tab completion for schedule IDs and dates:

### Bash (4.4+)

```bash
eval "$(_BEANSCHEDULE_COMPLETE=bash_source beanschedule)"
# Add to ~/.bashrc for persistence
```

### Zsh

```bash
eval "$(_BEANSCHEDULE_COMPLETE=zsh_source beanschedule)"
# Add to ~/.zshrc for persistence
```

### Fish

```bash
_BEANSCHEDULE_COMPLETE=fish_source beanschedule | source
# Add to ~/.config/fish/completions/ for persistence
```

Usage:

```bash
beanschedule show r<TAB>      # → rent-payment
beanschedule generate m<TAB>  # → mortgage-payment
beanschedule skip g<TAB>      # → gym-membership
```

Tab completion works for schedule IDs in commands like `show`, `generate`, `skip`, and `amortize`. Other arguments (dates, file paths, etc.) are not auto-completed.

## Tips

### Dry Run

Many commands support `--dry-run` to preview changes:

```bash
beanschedule pending create ... --dry-run
beanschedule skip ... --output temp.beancount
# Review temp.beancount
rm temp.beancount
```

### Debugging

Use `--verbose` for detailed output:

```bash
beanschedule validate schedules/ --verbose
beanschedule detect ledger.beancount --verbose
```

### Output Redirection

Save schedule output:

```bash
beanschedule list schedules/ --format json > schedules.json
beanschedule generate rent-payment 2024-01-01 2024-12-31 > dates.txt
```

## Examples

### Daily Workflow

```bash
# Check for errors
beanschedule validate schedules/

# View what's coming up
beanschedule show paycheck --count 3
beanschedule show rent-payment --count 1

# Create pending transactions for planned spending
beanschedule pending create --account Assets:Checking --amount -50 --date 2026-02-25

# List pending
beanschedule pending list
```

### Setup New Schedules

```bash
# Auto-detect patterns
beanschedule detect ledger.beancount --output-dir auto-detected/

# Review
beanschedule list auto-detected/

# Copy good ones
cp auto-detected/rent.yaml schedules/
cp auto-detected/paycheck.yaml schedules/

# Validate all
beanschedule validate schedules/
```

### Maintenance

```bash
# Update config values
nano schedules/_config.yaml

# Validate changes
beanschedule validate schedules/

# Preview impact
beanschedule show rent-payment --count 12
```

## See Also

- [SCHEDULES.md](SCHEDULES.md) - Schedule definitions
- [PENDING.md](PENDING.md) - Pending transactions details
- [ADVANCED.md](ADVANCED.md) - Advanced features
