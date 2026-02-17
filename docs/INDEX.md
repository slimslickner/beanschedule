# Beanschedule Documentation Index

Welcome to the beanschedule documentation. Start with the main README, then dive into the specific features you need.

## 📖 Where to Start

**New to beanschedule?** Start here:

1. [Main README.md](../README.md) - Overview and quick start
2. [SCHEDULES.md](SCHEDULES.md) - Define your first recurring transaction

## 🎯 Feature Documentation

### Core Features

| Feature                       | Purpose                                               | Read                         | Time   |
| ----------------------------- | ----------------------------------------------------- | ---------------------------- | ------ |
| **Schedules & Beangulp Hook** | Define recurring transactions and auto-enrich imports | [SCHEDULES.md](SCHEDULES.md) | 15 min |
| **Forecast Plugin**           | Generate future scheduled transactions for budgeting  | [PLUGIN.md](PLUGIN.md)       | 10 min |
| **Pending Transactions**      | Stage one-time items before they post                 | [PENDING.md](PENDING.md)     | 10 min |
| **Command-Line Tools**        | Validate, list, generate, and manage schedules        | [CLI.md](CLI.md)             | 10 min |
| **Advanced Features**         | Amortization, complex matches, auto-detection         | [ADVANCED.md](ADVANCED.md)   | 15 min |

## 🔍 By Use Case

### "I want to match my imported transactions to scheduled payments"

→ [SCHEDULES.md](SCHEDULES.md)

- Define schedules with match rules
- Integration with beangulp
- How matching works

### "I want to see what bills are coming up"

→ [PLUGIN.md](PLUGIN.md)

- Generate forecast transactions
- Configuration options
- Integration with Fava

### "I want to stage a purchase before it posts"

→ [PENDING.md](PENDING.md)

- Create pending transactions
- Auto-matching on import
- CLI and manual methods

### "I want to understand the command-line tools"

→ [CLI.md](CLI.md)

- All available commands
- Tab completion
- Practical examples

### "I want advanced features (amortization, pattern detection)"

→ [ADVANCED.md](ADVANCED.md)

- Loan amortization setup
- Complex posting splits
- Pattern auto-detection

## 📚 Complete Reference

### SCHEDULES.md

- Schedule file format and structure
- Match section (payee patterns, amount, date)
- Recurrence types (MONTHLY, WEEKLY, etc.)
- Transaction enrichment
- Missing transaction placeholders
- Skip markers
- Examples and troubleshooting

### PLUGIN.md

- Plugin installation and configuration
- Configuration parameters (forecast_months, etc.)
- Behavior and example output
- Use cases (budgeting, planning, visualization)
- Fava integration
- Advanced: loan amortization forecasts

### PENDING.md

- Setup and location
- CLI and manual entry
- Matching logic (±4 days)
- Auto-cleanup after matching
- Examples
- Troubleshooting

### CLI.md

- All commands with examples
  - `validate` - Check for errors
  - `list` - Show all schedules
  - `show` - Details about a schedule
  - `generate` - Occurrence dates
  - `init` - Setup new directory
  - `detect` - Auto-find patterns
  - `create` - Interactive schedule creation
  - `pending` - Manage pending transactions
  - `skip` - Mark as skipped
  - `amortize` - Display amortization schedule
- Tab completion setup
- Tips and examples

### ADVANCED.md

- **Loan Amortization**
  - Static mode (for standard loans)
  - Stateful mode (for real-world situations)
  - Compounding modes (DAILY, MONTHLY)
  - Forecast integration
- **Complex Postings**
  - Paychecks with deductions
  - Multi-currency transactions
  - Zerosum credit card payments
- **Pattern Detection**
  - How detection algorithm works
  - Detection options and sensitivity
  - Creating schedules from detected patterns
  - Advanced matching strategies

## 💡 Quick Tips

- Use `beanschedule validate schedules/` to check for errors
- Use `beanschedule list schedules/` to see all your schedules
- Use `beanschedule show schedule-id --count N` to see upcoming dates
- Use `--verbose` flag for more detailed output on any command
- Check `examples/` directory for real-world schedule examples

## 🤝 Contributing

Found a problem or have a suggestion? Open an issue on GitHub.

---

**Main Repository**: [GitHub](https://github.com/slimslickner/beanschedule)
**License**: MIT
