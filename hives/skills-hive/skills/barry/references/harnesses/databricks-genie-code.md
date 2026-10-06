# Barry on Databricks Genie Code

Databricks Genie Code is a data-science / analytics coding agent on the Databricks
platform that supports the `SKILL.md` standard. It's a **workspace/platform**
harness — skills are typically made available inside the Databricks workspace
rather than a local home directory.

**Skills load from:** the Databricks workspace / repo (e.g. `.agents/skills/` in a
linked repo). *Verify the exact mechanism against current Databricks docs — this
is publish/workspace-based, closer to Foundry than to a local junction.*

**Delegation:** Genie Code is oriented around data + analytics tasks. Map Barry's
roles to Databricks-native capabilities:

| Barry role | Databricks equivalent |
|------------|-----------------------|
| explore | catalog / table / notebook discovery |
| generalPurpose | notebook or job authoring |
| shell | cluster / SQL / job execution |
| code-review | a review skill on the changeset |

**Fit:** Barry is most useful here coordinating analytics workflows (pipelines,
notebooks, SQL) rather than general software delegation. Keep skills portable;
only diverge in `adapters/databricks/` if behavior must differ.

**Models:** only when asked; use the models the workspace exposes.
