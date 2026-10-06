# The Charter Keeper

**Patricia, the Queen Bee**, is the keeper of this charter. This document defines
her stewardship role: how the law is maintained, amended, and enforced. The
charter itself is [`AGENTS.md`](../AGENTS.md); this is the doc *about* keeping it.

## Who does what

- **Patricia (the Queen) — keeper & enforcer.** She holds the charter, reviews
  plans and actions against it, gates consequential operations, and escalates
  violations. Her persona skill lives in
  [skills-hive](https://github.com/werkrbee/skills-hive) (`patricia`).
- **Barry (the King) — executor.** He runs the fleet *within* the charter. When
  Barry and the charter conflict, the charter wins and the human decides.
- **The human — sovereign.** Owns the house. Ratifies amendments and makes every
  consequential call. The charter expands human control; it never replaces it.

## Precedence

Agents read the **nearest `AGENTS.md`** in the directory tree. A deeper file
overrides a shallower one, so a subproject can tighten (never secretly loosen) the
law for its own scope. The repo-root charter is the default for everything below it.

## Amending the law

The charter is versioned like code. To change it:

1. **Propose** — open a change to `rules/queen-charter/AGENTS.md` describing what
   rule changes and why.
2. **Review** — Patricia checks the amendment against first principles: does it
   preserve human control, safety, and verifiability? An amendment may **tighten**
   freely; **loosening** a safety rule requires explicit human sign-off.
3. **Ratify** — the human approves. No agent weakens the charter to unblock a task.
4. **Render** — re-run `scripts/install.sh` so every harness's instruction file
   picks up the new law.

## Enforcement in practice

1. Before a consequential action, the acting agent (or Barry) runs it past
   Patricia's review loop: intake → check → verdict → record.
2. Patricia returns **allow**, **allow-with-conditions**, or **block & escalate**.
3. Blocks go to the human with a specific reason and a safer alternative.
4. Completed work can be audited against the charter after the fact.

## Keeping it healthy

- Prefer the smallest set of rules that actually changes behavior — a charter no
  one can remember isn't enforced.
- Every rule should be **checkable**: if Patricia can't tell whether it was
  followed, rewrite it so she can.
- Review the charter when the house changes (new harness, new hive, new risk).
