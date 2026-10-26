# Native platform product group design consistency

Governance owner: **Patricia — Queen Bee**. Standard version: **1**.
Task: establish and enforce a shared product design and experience standard
across native platforms for products built with ai-hive.

## Requirement

Every product within a product group MUST provide the same core design,
terminology, navigation, capabilities, workflows, and outcomes across all
supported platforms, including macOS, Windows, iOS, Android, Linux, and web
where applicable. Each product specification MUST name its supported platforms;
this rule does not imply that every product supports every listed platform.

Users and agents MUST be able to transfer their understanding of a product
between platforms without relearning its core behavior. Platform adaptations
for screen size, input methods, accessibility, or operating-system requirements
MUST preserve the shared product experience.

The motivating user observation is that old and new Microsoft Outlook experiences
vary across platforms. The lesson for an Outlook-style product is to provide
consistent concepts, actions, and workflow outcomes across supported desktop,
mobile, and web clients. Platform-specific presentation MUST NOT create
conflicting behavior or unnecessary feature gaps. This observation is a design
lesson, not a verified audit of Microsoft's current products.

## Patricia's governance task

Patricia MUST maintain this canonical, versioned standard in rules-hive and
require product specifications and agent development tasks to inherit it.
Specifications MUST record the standard version and the shared product design,
terminology, navigation, capabilities, and critical workflows.

Patricia MUST maintain a platform parity matrix covering core capabilities,
workflows, terminology, accessibility, and agent interfaces. Agent-facing
actions, permissions, data meanings, and error behavior MUST remain consistent.
The matrix MUST link validation evidence for every supported platform and
identify design drift, remediation owners, and approved exceptions.

Patricia MUST identify drift and route remediation through Barry's execution
workflow. Barry assigns and executes the work; Patricia reviews compliance.
Exceptions MUST have documented justification, explicit human approval, an
owner, and a review date. Expired exceptions MUST be reviewed again before
they can satisfy the release requirement.

Compliance MUST be a release requirement for new products and material product
changes. Patricia MUST block release recommendations for unresolved deviations
unless a current, approved exception covers them. Humans retain release control.
This is a governance review requirement; automated enforcement is not supplied
by this ruleset.

## Acceptance criteria

- A versioned standard defines the shared design and core user experience.
- Every supported platform is assessed against the same parity matrix.
- Equivalent user actions produce equivalent outcomes across platforms.
- Agent-facing actions, permissions, data meanings, and error behavior remain consistent.
- Cross-platform validation covers the product's critical workflows.
- Unresolved deviations block release unless covered by an approved exception.

## Review record

Use the [platform parity matrix template](https://github.com/werkrbee/ai-hive/blob/main/hives/rules-hive/rules/native-platform-product-group-design-consistency/references/platform-parity-matrix.md)
in the source repository. Store the completed matrix and evidence in the product
repository, where its specifications and agent tasks can reference them. Rendered
instruction files are standalone; this link locates supporting material without
requiring the rules-hive directory to be installed alongside them.

Record the product, release, standard version, supported platforms, evidence,
deviations, exceptions, remediation tasks, and Patricia's verdict. Missing
evidence is unverified and MUST NOT be recorded as a pass.

## Intended outcome

Reduce platform fragmentation, simplify user onboarding and support, and enable
reusable agent development that scales across the entire product group.
