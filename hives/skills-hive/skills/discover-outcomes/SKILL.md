---
name: discover-outcomes
description: Discover the customer need behind a proposed feature and produce an evidence-backed outcome brief. Use for ambiguous product requests, solution-first ideas, customer discovery, or translating business goals into agent work before implementation. Skip routine fixes, explicit edits, and work whose need and acceptance criteria are already clear.
---

# Discover outcomes

Start with the user's situation and desired change before choosing a capability,
interface, or technology. Treat a requested solution as a candidate, not evidence
that the underlying problem is understood. Preserve explicit user requirements.

## Discovery loop

1. Read the request and available task context. Reuse known answers; separate
   supplied evidence from assumptions. Do not invent customer quotes or metrics.
2. Identify who needs help, the task they are trying to complete, the current
   workaround, and the friction that makes a change useful. Ask about a concrete
   recent instance rather than leading the user toward the proposed feature.
3. Ask only the one to three unanswered questions that materially change scope
   or implementation. Examples: What are you trying to accomplish? Where does
   the current approach fail? What observable result would make this worthwhile?
   Do not repeat intake questions or require a discovery interview for a clear task.
4. Define the desired outcome and how it will be observed. Record the baseline,
   target, time window, and measurement source if known. Mark unknown values
   explicitly; label proposed targets as proposals rather than commitments.
5. Compare the smallest plausible intervention with the current workaround.
   Consider a process change or existing capability as well as a new feature.
   Explain why the recommendation addresses the observed need and its tradeoffs.
6. Produce a concise outcome brief using
   [references/outcome-brief.md](references/outcome-brief.md). Translate the
   selected intervention into observable acceptance criteria tied to the outcome.

## Handoff

Return the brief to Barry or the requesting agent as intake context for planning,
delegation, and verification. Carry the outcome and acceptance criteria into the
issue or pull request so reviewers can assess whether the change helps the user.
For cross-functional work, describe the same outcome in terms of customer value
(marketing), delivery quality (operations), and measurable benefit (revenue), only
where relevant. Do not invent owners, financial returns, or customer endorsements.

If a missing fact would change a consequential decision, ask a focused question
before that decision. Otherwise proceed within authorized scope with clearly
labeled assumptions and a lightweight validation step. Discovery is not approval
to send messages, spend money, deploy, or merge; follow the Queen Bee's Charter
and the user's existing authorization for those actions.

## Example

Request: "Build a dashboard showing every agent's activity."

Discover who uses the information and what decision it supports. If the user
reports that stalled runs go unnoticed, frame the outcome as earlier detection
and recovery. Compare a stalled-run alert with a dashboard before recommending
one. Make detection of a known stalled run an acceptance criterion; leave the
response-time target unknown until supplied or explicitly proposed. If the user
explicitly requires the dashboard, retain that requirement and use the outcome
to prioritize its content.
