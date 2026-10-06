# Security policy

## Reporting a vulnerability

Please report security issues privately — do **not** open a public issue. Use GitHub's
**private vulnerability reporting** (Security tab → "Report a vulnerability") on this repo, or
email the maintainers listed in `.github/CODEOWNERS`.

Include what you found, how to reproduce it, and the potential impact. We'll acknowledge
receipt, investigate, and coordinate a fix and disclosure timeline with you.

## Scope notes

ai-hive ships *artifacts* (instructions, configs, personas), not a running service. The most
likely security-relevant issues are: secrets accidentally committed, MCP server configs that
over-grant permissions, or rules/prompts that weaken human-in-the-loop controls. Flag those
here too.
