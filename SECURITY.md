# Security policy

## Reporting a vulnerability

Please report security issues privately — do **not** open a public issue. Use GitHub's
**private vulnerability reporting**: the Security tab → "Report a vulnerability", or go
straight to <https://github.com/werkrbee/ai-hive/security/advisories/new>. Only maintainers
can see the report.

Include what you found, how to reproduce it, and the potential impact. We'll acknowledge
receipt, investigate, and coordinate a fix and disclosure timeline with you.

## Scope notes

ai-hive ships *artifacts* (instructions, configs, personas), not a running service. The most
likely security-relevant issues are: secrets accidentally committed, MCP server configs that
over-grant permissions, or rules/prompts that weaken human-in-the-loop controls. Flag those
here too.
