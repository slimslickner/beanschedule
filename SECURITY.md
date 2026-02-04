# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in beanschedule, please report it responsibly by emailing **slimslickner@gmail.com** instead of using the public issue tracker.

Please include:
- Description of the vulnerability
- Steps to reproduce (if applicable)
- Potential impact
- Suggested fix (if you have one)

## What We Consider a Vulnerability

Security issues in beanschedule include:

- **Data corruption** - Bugs that could corrupt ledger data or create invalid transactions
- **Unauthorized access** - If beanschedule is used in a shared environment
- **Input injection** - YAML/regex parsing that could execute arbitrary code
- **Dependency vulnerabilities** - Known CVEs in our dependencies

## What We Don't Consider a Vulnerability

- Documentation issues
- Feature requests
- Performance problems
- Style/formatting bugs that don't affect functionality

## Response Timeline

We aim to:
1. Acknowledge your report within 48 hours
2. Provide an initial assessment within 1 week
3. Release a fix within 2 weeks (if confirmed)
4. Credit the reporter (unless you prefer anonymity)

## Supported Versions

Security updates are provided for:
- Latest stable release
- Previous major version (for 6 months)

Earlier versions are not supported. Please upgrade to receive security fixes.

## Security Best Practices

When using beanschedule:

- Keep beanschedule and its dependencies updated
- Validate YAML schedule files from untrusted sources
- Restrict access to your `schedules/` directory
- Use strong permissions on your ledger files
- Review auto-detected schedules before importing them
