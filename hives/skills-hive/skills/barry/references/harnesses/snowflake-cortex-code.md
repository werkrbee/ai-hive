# Barry on Snowflake Cortex Code

Snowflake Cortex Code is a data / analytics coding agent on the Snowflake platform
that supports the `SKILL.md` standard. Like Databricks Genie Code, it's a
**workspace/platform** harness — skills are provisioned inside the Snowflake
environment rather than a local home directory.

**Skills load from:** the Snowflake workspace / linked repo (e.g. `.agents/skills/`).
*Verify the exact mechanism against current Snowflake docs — publish/workspace-based.*

**Delegation:** Cortex Code is oriented around SQL, data engineering, and
analytics. Map Barry's roles:

| Barry role | Snowflake equivalent |
|------------|----------------------|
| explore | database / schema / object discovery |
| generalPurpose | SQL / pipeline authoring |
| shell | warehouse / task execution |
| code-review | a review skill on the changeset |

**Fit:** Use Barry to coordinate analytics work (models, SQL, pipelines). Keep
skills portable; put Snowflake-specific behavior in `adapters/snowflake/` only if
it must diverge.

**Models:** only when asked; use the models Cortex exposes.
