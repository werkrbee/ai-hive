# A2A TCK run

Run on 2026-10-09. The setup:
- **TCK:** [a2a-tck](https://github.com/a2aproject/a2a-tck) at commit `263b9cf`.
- **Server:** `hive_a2a` with the stub model, a2a-sdk 1.2.2 and Python 3.13.
- **Transport:** JSON-RPC, the only binding the card declares.
- **Command:** `python conformance/run.py --tck <checkout> --tck-python <tck venv python>`.

The full report is [`compatibility.json`](compatibility.json).

| Level | Pass | Fail | Skipped or not tested |
|-------|-----:|-----:|----------------------:|
| MUST | 50 | 3 | 61 |
| SHOULD | 3 | 0 | 8 |
| MAY | 2 | 1 | 1 |

## Skipped

The skipped requirements are for capabilities the card doesn't declare: streaming, push
notifications, extensions, and the gRPC and HTTP+JSON bindings. The TCK skips a
requirement for an undeclared capability. "Not tested" covers what the TCK can't automate,
such as TLS checks.

## Failures

Two of the three MUST failures come from scenarios that only the TCK's own scripted test
agent can play.
The TCK drives that agent by messageId prefixes, such as "return a text artifact" or "reply
with a Message instead of a Task". A real reviewer returns a verdict artifact on a task, so
it can't play them.
- **DM-ART-001 (MUST):** expects text, file and URL artifacts.
- **DM-MSG-001 (MUST):** expects a bare Message response.
- **CORE-CANCEL-001 and CORE-HIST-002:** need a task held in `input-required`, so they are
  skipped for the same reason. `tests/test_server.py` covers cancel against a working task.

**CORE-SEND-003 (MUST), the third, is a TCK defect.** The requirement says a media type the agent
doesn't support "MUST result in ContentTypeNotSupportedError". The server returns exactly
that: -32005, "Media type application/x-unsupported-tck-type is not supported". But this TCK
version sets no expected error on the requirement, so it counts any error as a failure.
Its own generated Python test agent passes only because it leaves the SDK's input-mode
check off and accepts the part. The server follows the spec.

**CARD-CACHE-003 (MAY):** the card has no `Last-Modified` header. The SDK's card route
sends `ETag` and the `Cache-Control` the server sets, and neither is required.

## Auth during the run

The TCK can't send credentials, so `run.py` puts a local proxy in front of the server. The
proxy adds a token signed by a throwaway key that the run's config trusts. The server's
auth stays on for every request.
