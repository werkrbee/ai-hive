# Platform parity matrix

Copy this template into the product repository. Add one row per requirement and
supported platform; list unsupported platforms explicitly outside the matrix.

Product group / product:
Release or change:
Standard version:
Supported platforms:
Unsupported platforms:
Canonical product specification:
Reviewer / review date:

| Requirement or critical workflow | Shared expected behavior | Platform | Validation evidence | Status | Remediation task / owner | Exception |
| --- | --- | --- | --- | --- | --- | --- |
| Core design and navigation | | | | Unverified | | |
| Terminology and capabilities | | | | Unverified | | |
| Critical user workflow (repeat for each) | | | | Unverified | | |
| Accessibility and input adaptations | | | | Unverified | | |
| Agent actions and permissions | | | | Unverified | | |
| Data meanings and error behavior | | | | Unverified | | |

Status is **Pass**, **Deviation**, or **Unverified**. Evidence should identify the
tested build, scenario, expected outcome, actual outcome, and result. An approved
exception leaves the deviation visible; it does not turn it into a pass.

## Exceptions

| ID | Affected requirement / platforms | Justification and user / agent impact | Human approver / approval evidence | Owner | Review date |
| --- | --- | --- | --- | --- | --- |

## Patricia's release review

Verdict: compliant / compliant with approved exceptions / blocked.

Reason and outstanding deviations:
Barry remediation tasks:
Human release decision reference:

Recommend release only when all rows pass or each deviation has a current human-
approved exception. Unverified rows block the compliance verdict.
