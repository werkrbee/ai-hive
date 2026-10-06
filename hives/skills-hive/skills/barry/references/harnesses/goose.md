# Barry on Goose (Block)

**Skills load from:** `~/.config/goose/skills/` (global) or `.goose/skills/`
(project).

**Delegation:** Goose is built around **recipes** (YAML bundling instructions,
required MCP extensions, parameters, and prompt) and MCP servers as tools. Barry's
intake → plan → delegate → synthesize loop still applies; map "delegate" to:

| Barry role | Goose equivalent |
|------------|------------------|
| explore | a read-only recipe / MCP query |
| generalPurpose | a task recipe |
| shell | shell via an MCP extension |
| code-review / security-review | dedicated review recipes |
| best-of-n-runner | parallel recipe runs |

**Models:** Goose is model-agnostic (any LLM). Only pass a model when asked.
