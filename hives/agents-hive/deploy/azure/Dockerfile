# hive_a2a for Patricia's governance-review. Build from the repo root:
#   docker build -f hives/agents-hive/deploy/azure/Dockerfile .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HIVE_REPO_ROOT=/app
WORKDIR /app

COPY hives/agents-hive/servers/a2a/requirements.txt hives/agents-hive/servers/a2a/requirements.txt
RUN pip install --no-cache-dir -r hives/agents-hive/servers/a2a/requirements.txt

# Only what the server reads: its code, the card and contract it serves, the renderer
# for the card, and the prompt files.
COPY hives/agents-hive/servers/a2a/hive_a2a hives/agents-hive/servers/a2a/hive_a2a
COPY hives/agents-hive/scripts/agent_card.py hives/agents-hive/scripts/agent_card.py
COPY hives/agents-hive/cards hives/agents-hive/cards
COPY hives/agents-hive/contracts hives/agents-hive/contracts
COPY hives/agents-hive/agents/charter-review hives/agents-hive/agents/charter-review
COPY hives/skills-hive/skills/patricia/SKILL.md hives/skills-hive/skills/patricia/SKILL.md
COPY hives/rules-hive/rules/queen-charter/AGENTS.md hives/rules-hive/rules/queen-charter/AGENTS.md
COPY hives/agents-hive/deploy/azure/render_config.py /usr/local/bin/render_config.py

RUN useradd --uid 1000 --create-home hive && mkdir /data && chown hive /data
USER hive
WORKDIR /app/hives/agents-hive/servers/a2a
EXPOSE 8080

CMD ["sh", "-c", "python /usr/local/bin/render_config.py /tmp/config.toml && exec python -m hive_a2a --config /tmp/config.toml --host 0.0.0.0 --port 8080"]
