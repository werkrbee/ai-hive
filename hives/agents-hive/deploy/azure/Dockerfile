# hive_a2a for Patricia's governance-review. Build from the repo root:
#   docker build -f hives/agents-hive/deploy/azure/Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HIVE_REPO_ROOT=/app
WORKDIR /app

COPY hives/agents-hive/servers/a2a/requirements.txt hives/agents-hive/servers/a2a/requirements.txt
RUN pip install --no-cache-dir -r hives/agents-hive/servers/a2a/requirements.txt

# Only what the server reads: its code, the card, contract and passport it serves, the
# renderer for the card, and the prompt files.
COPY hives/agents-hive/servers/a2a/hive_a2a hives/agents-hive/servers/a2a/hive_a2a
COPY hives/agents-hive/scripts/agent_card.py hives/agents-hive/scripts/agent_card.py
COPY hives/agents-hive/cards hives/agents-hive/cards
COPY hives/agents-hive/contracts hives/agents-hive/contracts
COPY hives/agents-hive/passports hives/agents-hive/passports
COPY hives/agents-hive/agents/charter-review hives/agents-hive/agents/charter-review
COPY hives/skills-hive/skills/patricia/SKILL.md hives/skills-hive/skills/patricia/SKILL.md
COPY hives/rules-hive/rules/queen-charter/AGENTS.md hives/rules-hive/rules/queen-charter/AGENTS.md
COPY hives/agents-hive/deploy/azure/render_config.py /usr/local/bin/render_config.py

# And what the weekly trust evaluation reads (eval/weekly.sh): the runner and its suite,
# the results her baseline is in, the scripts that check her passport and pins and record
# the evaluation, the policy and schemas they read, and the audit log's blob copier.
COPY hives/agents-hive/schema hives/agents-hive/schema
COPY hives/agents-hive/scripts/trust_eval.py hives/agents-hive/scripts/trust_eval.py
COPY hives/agents-hive/scripts/validate_passports.py hives/agents-hive/scripts/validate_passports.py
COPY hives/agents-hive/deploy/azure/eval/run.py hives/agents-hive/deploy/azure/eval/run.py
COPY hives/agents-hive/deploy/azure/eval/cases.json hives/agents-hive/deploy/azure/eval/cases.json
COPY hives/agents-hive/deploy/azure/eval/results.jsonl hives/agents-hive/deploy/azure/eval/results.jsonl
COPY hives/agents-hive/deploy/azure/eval/weekly.sh hives/agents-hive/deploy/azure/eval/weekly.sh
COPY hives/agents-hive/deploy/azure/audit_blob.py hives/agents-hive/deploy/azure/audit_blob.py
COPY hives/workflows-hive/scripts/run.py hives/workflows-hive/scripts/run.py
COPY hives/knowledge-hive/scripts/check_audit.py hives/knowledge-hive/scripts/check_audit.py
COPY hives/rules-hive/scripts/check_policy.py hives/rules-hive/scripts/check_policy.py
COPY hives/rules-hive/schema hives/rules-hive/schema
COPY hives/rules-hive/rules/queen-charter/policy.json hives/rules-hive/rules/queen-charter/policy.json

RUN useradd --uid 1000 --create-home hive && mkdir /data && chown hive /data
USER hive
WORKDIR /app/hives/agents-hive/servers/a2a
EXPOSE 8080

CMD ["sh", "-c", "python /usr/local/bin/render_config.py /tmp/config.toml && exec python -m hive_a2a --config /tmp/config.toml --host 0.0.0.0 --port 8080"]
