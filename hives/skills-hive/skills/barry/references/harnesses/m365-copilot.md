# Barry on Microsoft 365 Copilot (Autopilot)

What is known about running the House in Microsoft 365 Copilot, and Autopilot inside it.
Checked against Microsoft Learn's Autopilot (Frontier) overview and its "Customize and
extend what Autopilot can do" page, and Microsoft's Ignite post of 2026-11-17, on
2026-11-21. It is on the low-code watch list in `harnesses.json`, which has no install
paths for it.

Microsoft 365 Copilot is one harness in the Copilot app, on the web and desktop, with
separate concerns: Home, where chat and cowork meet; Autopilot; and Code, for building
small apps from a description, which is separate from the pro-code GitHub Copilot harness.
Autopilot is a persistent agent with its own Microsoft Entra Agent ID, mailbox, calendar,
memory and cloud workspace. Microsoft says it was previously called Scout, but it isn't
like for like: Scout read skills from a folder on your machine. It runs
scheduled and event-driven routines while your device is off, and you reach it in the
Copilot app or @mention it in Teams. It began rolling out to Frontier customers at Ignite
and is in preview. Neither it nor Code is a sub-harness of GitHub Copilot, which stays the developers'
coding agent.

**Skills.** Autopilot can't read local folders, so there is nothing to install into, and
the old `~/.scout/skills` folder and `loadCopilotCliSkills` setting no longer apply. A
skill reaches it three ways: uploaded on **Plugins**, under **Add** > **Upload skill**, as
a folder or ZIP holding a `SKILL.md` and any supporting files; drafted in a conversation
and approved; or inside a plugin from the Microsoft 365 plugin marketplace, which an
admin can also deploy for everyone. So Barry's skill folder uploads as it is. A saved
skill runs when you type `/` and pick it, or when Autopilot judges it relevant, and can
be shared with named coworkers.

**Behavior.** Autopilot plans and acts without asking at each step. Before it sends,
shares, deletes or changes something, an automated review compares the action with your
request; what matches runs, and the rest waits for your approval. That is close to
Barry's approval list, but Microsoft hasn't published whether Autopilot delegates to
subagents, so run Barry there as one agent that plans and reports, and treat his
delegation steps as a checklist rather than calls.

**Reaching the House.** As a low-code harness it would reach the House over a plugin's
connector, which is how Patricia would be called from it. That hasn't been tried; a
plugin's tools and their limits are in Microsoft's plugin documentation.
