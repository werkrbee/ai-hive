"""Assemble the A2A server: the Agent Card, the JSON-RPC endpoint, auth, a durable task
store and the reviewer."""
import contextlib
import importlib.util
import logging
from urllib.parse import urlparse

from google.protobuf.json_format import ParseDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette

from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import DatabaseTaskStore
from a2a.types import AgentCard, Role, TaskState

from . import providers
from .auth import Authenticator, AuthMiddleware
from .config import REPO_ROOT
from .ledger import Ledger
from .review import Executor, Handler, Reviewer

log = logging.getLogger("hive_a2a")

UNFINISHED = {TaskState.TASK_STATE_SUBMITTED, TaskState.TASK_STATE_WORKING}


def _agent_card_module():
    path = REPO_ROOT / "hives/agents-hive/scripts/agent_card.py"
    spec = importlib.util.spec_from_file_location("agent_card", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def card(config):
    """The persona's card rendered for this endpoint, with its OAuth2 security scheme."""
    agent_card = _agent_card_module()
    rendered = agent_card.render(config.persona, config.public_url, "JSONRPC")
    rendered["skills"] = [s for s in rendered["skills"] if s["id"] == config.capability]
    for s in rendered["skills"]:
        s["inputModes"] = ["application/json", "text/plain"]  # text is taken as the first required field
    rendered["securitySchemes"] = {"oauth2": {"oauth2SecurityScheme": {
        "description": "OAuth2 client credentials. Only allowlisted clients may call this agent.",
        "flows": {"clientCredentials": {
            "tokenUrl": config.auth.token_url,
            "scopes": {config.auth.scope: f"Call {config.persona}'s {config.capability} skill"},
        }},
    }}}
    rendered["securityRequirements"] = [{"schemes": {"oauth2": {"list": [config.auth.scope]}}}]
    problems = agent_card.validate(rendered)
    if problems:
        raise ValueError("the rendered Agent Card is invalid: " + "; ".join(problems))
    return rendered


async def fail_interrupted(store):
    """Tasks a restart cut off can't resume, so mark them failed rather than leave them working."""
    await store.initialize()
    async with store.async_session_maker.begin() as session:
        rows = (await session.execute(select(store.task_model))).scalars().all()
        for row in rows:
            task = store._from_orm(row)
            if task.status.state not in UNFINISHED:
                continue
            task.status.state = TaskState.TASK_STATE_FAILED
            task.status.message.role = Role.ROLE_AGENT
            task.status.message.message_id = f"{task.id}-restart"
            task.status.message.parts.add().text = "The server restarted during this review. Send it again."
            task.status.timestamp.GetCurrentTime()
            await session.merge(store._to_orm(task, row.owner))
            log.warning("marked task %s failed after a restart", task.id)


def create_app(config, provider=None, authenticator=None, ledger_clock=None):
    config.database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{config.database}")
    store = DatabaseTaskStore(engine)
    ledger = Ledger(config.ledger, config.monthly_ceiling_usd, **({"clock": ledger_clock} if ledger_clock else {}))
    provider = provider or providers.create(config.model)
    reviewer = Reviewer(config, ledger, provider)
    agent_card = ParseDict(card(config), AgentCard())
    handler = Handler(reviewer, agent_executor=Executor(reviewer), task_store=store, agent_card=agent_card)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        await fail_interrupted(store)
        try:
            yield
        finally:
            await handler.aclose()
            await provider.aclose()
            await engine.dispose()

    rpc_path = urlparse(config.public_url).path or "/"
    app = Starlette(
        routes=[*create_agent_card_routes(agent_card, cache_control="public, max-age=300"),
                *create_jsonrpc_routes(handler, rpc_path)],
        lifespan=lifespan,
    )
    app.add_middleware(AuthMiddleware, authenticator=authenticator or Authenticator(config.auth))
    return app
