"""Hosted Barry's executor: run the orchestration contract as an agent loop on the
workflows-hive engine (design/hosted-barry.md).

Each A2A task is an open engine run with the same ID, under Barry's passport and the
caller's approval policy. The model decides what to do next; the engine decides whether it
may. Each model turn is a turn in the run record, and each tool call the model makes
becomes a step appended to the run, whose action the engine decides with the policy before
it runs: an allowed call runs, a gated one pauses the task in input-required, and a denied
one fails the task. The model's arguments are taken as they are, never as references, and
never as facts: a step's facts come from the caller's request and from lookups the server
makes, through the caller's registration (scripts/registrations.py).

Barry's tools are delegation to the A2A agents in his config, starting with Patricia, and
the tools the caller's registration maps on its MCP servers. He has no shell, file system
or fetch. Each MCP call a step makes carries the step's idempotency key in the request's
_meta, under io.werkrbee/idempotency-key, so a call that runs again after a restart can be
acted on once.

Spend. A run's whole budget (the contract's $5) is held against Barry's monthly ceiling
when it starts, and a run the ceiling can't hold is a rejected task. Each turn is charged
to the hold as it is metered, and what is left is released when the run ends, is
cancelled or expires. Before each turn, the worst case of that turn, its estimated input
and the most output it may write, is checked against what the run has left of its usd,
tokens and working seconds; the run fails when the turn wouldn't fit. Working seconds
count the time turns and steps ran, not the time a task waited for a person. A turn cut
off by a restart is recorded in the ledger at its whole worst case and taken again. What a
run has spent is what the ledger charged to its run ID, that turn included, so the run's
budget and its hold after the restart both count it, and the month stays within the
ceiling.

Task states:
  rejected        the ceiling can't hold the run's budget; nothing runs
  working         the loop is running
  input-required  a step waits for a person's approval; it expires after seven days,
                  which fails the task
  completed       the result, a JSON data part, is the task's artifact
  failed          a denial, a budget stop, an error, or an expired approval
  canceled        CancelTask: a paused task at once, a working one before its next step

A working run resumes from its record when the server starts, repeating neither a
completed turn nor a completed step. SendMessage returns as soon as the task is working;
a caller polls GetTask.
"""
import asyncio
import concurrent.futures
import importlib.util
import itertools
import json
import logging
import math
import uuid

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.auth.user import User as A2AUser
from a2a.helpers.proto_helpers import new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskUpdater
from a2a.types import Artifact, Message, Role, Task, TaskState
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from a2a.utils.input_mode_validator import validate_input_modes

from . import contract
from .config import REPO_ROOT, _registrations
from .providers import Completion, ProviderError, Result, Tool, ToolCall, User
from .review import read_input

log = logging.getLogger("hive_a2a")

CHARS_PER_TOKEN = 3  # as review.py: a conservative estimate, for sizing a turn before it is taken
MIN_OUTPUT_TOKENS = 256
CORRECTIONS = 1  # times a final reply that misses the output schema is sent back
IDEMPOTENCY_META = "io.werkrbee/idempotency-key"
MCP_VERSION = "2026-07-28"  # mcp-hive's target; the server may negotiate another
TIMEOUT = httpx.Timeout(180)  # Patricia's review answers within her 120-second budget
STATES = {"working": TaskState.TASK_STATE_WORKING, "input_required": TaskState.TASK_STATE_INPUT_REQUIRED,
          "completed": TaskState.TASK_STATE_COMPLETED, "failed": TaskState.TASK_STATE_FAILED,
          "cancelled": TaskState.TASK_STATE_CANCELED}
ENDED = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED,
         TaskState.TASK_STATE_REJECTED}

HOSTED = """<!-- hosted -->
You are running as hosted Barry, over A2A, for a caller's goal. Your tools are the ones
offered here: delegation to other agents, and the caller's own tools. You have no shell,
file system or web fetch. Each tool call is decided by the caller's approval policy before
it runs: an allowed call runs, a gated one waits for a person, and a denied one ends the
run. A tool's arguments say what to do; they never prove a fact, so the policy never takes
one from them. When the goal is done, or can't be done with these tools, reply with no
tool call and only a JSON object that matches the output schema."""


def _engine_module():
    path = REPO_ROOT / "hives/workflows-hive/scripts/run.py"
    spec = importlib.util.spec_from_file_location("workflows_hive_run", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_card_module():
    path = REPO_ROOT / "hives/mcp-hive/scripts/server_card.py"
    spec = importlib.util.spec_from_file_location("server_card", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


engine = _engine_module()
registrations = _registrations()


class Shutdown(BaseException):
    """The server is stopping. A BaseException, so the engine records no failure: the turn
    or step it cut off is still working in the record, and runs again on resume."""


class McpError(Exception):
    pass


class _SessionGone(Exception):
    pass


class Caller(A2AUser):
    """The task store's owner, outside a request: the client that started the task."""

    def __init__(self, client):
        self.client = client

    @property
    def is_authenticated(self):
        return True

    @property
    def user_name(self):
        return self.client


def _card_endpoint(mcp):
    """The endpoint an MCP server's Server Card names. Barry sends only his own token, so a
    card that requires other headers can't be used."""
    cards = _server_card_module()
    try:
        source, card = cards.load_card(mcp["discovery"])
        problems = cards.validate(card)
        if problems:
            raise cards.CardError(f"{source}: invalid Server Card: " + "; ".join(problems))
        remote = cards.resolve(mcp["name"], card, mcp.get("variables", {}))
    except cards.CardError as e:
        raise McpError(f"{mcp['name']}: {e}")
    if remote["headers"]:
        raise McpError(f"{mcp['name']}: its Server Card requires headers Barry can't send")
    return remote["url"]


def _sse(text):
    """The JSON-RPC messages in a server-sent event stream."""
    found = []
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                found.append(json.loads(line[5:].strip()))
            except ValueError:
                raise McpError("the server streamed an event that isn't JSON")
    return found


class Network:
    """Barry's calls out: the caller's MCP servers and the A2A agents he delegates to, each
    with a token for his own identity. token(scope) and endpoint(mcp) can be given, for
    tests; otherwise tokens come from the managed identity and endpoints from Server Cards."""

    def __init__(self, transport=None, token=None, endpoint=None):
        self.client = httpx.AsyncClient(transport=transport, timeout=TIMEOUT)
        self._token = token
        self._endpoint = endpoint
        self.credential = None
        self.endpoints, self.sessions, self.listed = {}, {}, {}
        self.ids = itertools.count(1)

    async def token(self, scope):
        if self._token:
            return await self._token(scope)
        if self.credential is None:
            from azure.identity.aio import DefaultAzureCredential
            self.credential = DefaultAzureCredential()
        return (await self.credential.get_token(scope)).token

    async def endpoint(self, mcp):
        if mcp["name"] not in self.endpoints:
            self.endpoints[mcp["name"]] = (self._endpoint(mcp) if self._endpoint
                                           else await asyncio.to_thread(_card_endpoint, mcp))
        return self.endpoints[mcp["name"]]

    async def _post(self, url, server, body, session=None):
        headers = {"authorization": f"Bearer {await self.token(server['token_scope'])}",
                   "accept": "application/json, text/event-stream"}
        if session:
            headers["mcp-protocol-version"] = session["version"]
            if session["id"]:
                headers["mcp-session-id"] = session["id"]
        try:
            r = await self.client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise McpError(f"{server['mcp']['name']}: the request failed: {type(e).__name__}")
        if r.status_code == 404 and session and session["id"]:
            raise _SessionGone()
        if r.status_code not in (200, 202):
            raise McpError(f"{server['mcp']['name']} returned HTTP {r.status_code}")
        if "id" not in body:
            return r, None
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            replies = [m for m in _sse(r.text) if isinstance(m, dict) and m.get("id") == body["id"]]
            reply = replies[-1] if replies else None
        else:
            try:
                reply = r.json()
            except ValueError:
                raise McpError(f"{server['mcp']['name']} returned a body that isn't JSON")
        if not isinstance(reply, dict):
            raise McpError(f"{server['mcp']['name']} sent no reply to {body['method']}")
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise McpError(f"{server['mcp']['name']}: {body['method']} failed: {error.get('message', 'an error')}")
        return r, reply.get("result")

    def _request(self, method, params):
        return {"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params}

    async def _session(self, url, server):
        if url not in self.sessions:
            r, result = await self._post(url, server, self._request("initialize", {
                "protocolVersion": MCP_VERSION, "capabilities": {},
                "clientInfo": {"name": "hive-a2a", "version": "1"}}))
            version = result.get("protocolVersion") if isinstance(result, dict) else None
            session = {"id": r.headers.get("mcp-session-id"), "version": version or MCP_VERSION}
            await self._post(url, server, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
            self.sessions[url] = session
        return self.sessions[url]

    async def mcp(self, server, method, params):
        """A request to one of the caller's MCP servers, in a session started once and again
        if the server ends it."""
        url = await self.endpoint(server["mcp"])
        for _ in range(2):
            session = await self._session(url, server)
            try:
                return (await self._post(url, server, self._request(method, params), session))[1]
            except _SessionGone:
                self.sessions.pop(url, None)
        raise McpError(f"{server['mcp']['name']} ended the session again")

    async def tools(self, server):
        """The server's tools, by name, listed once."""
        name = server["mcp"]["name"]
        if name not in self.listed:
            found, cursor = {}, None
            while True:
                result = await self.mcp(server, "tools/list", {"cursor": cursor} if cursor else {})
                for t in (result or {}).get("tools", []):
                    if isinstance(t, dict) and isinstance(t.get("name"), str):
                        found[t["name"]] = t
                cursor = (result or {}).get("nextCursor")
                if not cursor:
                    break
            self.listed[name] = found
        return self.listed[name]

    async def call(self, server, tool, arguments, key=None):
        params = {"name": tool, "arguments": arguments}
        if key:
            params["_meta"] = {IDEMPOTENCY_META: key}
        result = await self.mcp(server, "tools/call", params)
        if not isinstance(result, dict):
            raise McpError(f"{server['mcp']['name']}: {tool} returned no result")
        return result

    async def delegate(self, d, data, message_id):
        """Send d the contract input data, and wait for its task to end. Returns (content,
        whether it is an error)."""
        body = {"jsonrpc": "2.0", "id": message_id, "method": "SendMessage", "params": {
            "message": {"messageId": message_id, "role": "ROLE_USER", "parts": [{"data": data}]}}}
        headers = {"A2A-Version": "1.0", "authorization": f"Bearer {await self.token(d.token_scope)}"}
        try:
            r = await self.client.post(d.url, json=body, headers=headers)
            reply = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as e:
            raise McpError(f"{d.name}: the request failed: {type(e).__name__}")
        if not isinstance(reply, dict):
            raise McpError(f"{d.name} returned HTTP {r.status_code}")
        if "error" in reply:
            return f"{d.name} refused the request: {(reply['error'] or {}).get('message', 'an error')}", True
        task = (reply.get("result") or {}).get("task") or {}
        state = (task.get("status") or {}).get("state", "")
        if state == "TASK_STATE_COMPLETED":
            values = [p.get("data", p.get("text")) for a in task.get("artifacts", []) for p in a.get("parts", [])]
            return json.dumps(values[0] if len(values) == 1 else values), False
        said = " ".join(p.get("text", "") for p in ((task.get("status") or {}).get("message") or {}).get("parts", []))
        return f"{d.name}'s task ended {state.removeprefix('TASK_STATE_').lower() or 'without a state'}: {said}", True

    async def aclose(self):
        await self.client.aclose()
        if self.credential is not None:
            await self.credential.close()


def _content(result):
    """What an MCP tool result says, for the model."""
    if "structuredContent" in result:
        return json.dumps(result["structuredContent"])
    texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(texts) if texts else json.dumps(result.get("content", []))


def _found(result):
    """A fact-source result as an object, or None."""
    if result.get("isError"):
        return None
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    try:
        value = json.loads(_content(result))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _reply(output):
    return Completion(output["text"], output["inputTokens"], output["outputTokens"], output["cutOff"],
                      tuple(ToolCall(c["id"], c["name"], c["arguments"]) for c in output["toolCalls"]))


def _recorded(reply):
    return {"text": reply.text, "inputTokens": reply.input_tokens, "outputTokens": reply.output_tokens,
            "cutOff": reply.cut_off,
            "toolCalls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls]}


def _chars(history):
    n = 0
    for turn in history:
        if isinstance(turn, User):
            n += len(turn.text)
        elif isinstance(turn, Completion):
            n += len(turn.text) + len(json.dumps(_recorded(turn)["toolCalls"]))
        else:
            n += sum(len(r.content) for r in turn)
    return n


def working_seconds(run):
    """How long the run's turns and steps have run, not counting time spent waiting."""
    total = 0.0
    for state in [*run.get("turns", {}).values(), *run["steps"].values()]:
        if state.get("startedAt") and state.get("endedAt"):
            total += (engine.parse_time(state["endedAt"]) - engine.parse_time(state["startedAt"])).total_seconds()
    return total


class Orchestrator:
    """Everything a run needs that doesn't change between runs, and the runs in progress."""

    def __init__(self, config, ledger, provider, store, network=None, clock=None):
        self.config, self.ledger, self.provider, self.store = config, ledger, provider, store
        self.o = config.orchestration
        c = config.contract
        for where in ("inputs", "output"):
            problems = contract.supported(c[where], where)
            if problems:
                raise ValueError(f"contract {config.capability}: " + "; ".join(problems))
        self.budget = c.get("budget", {})
        if "usd" not in self.budget:
            raise ValueError(f"contract {config.capability} has no usd budget to hold against the ceiling")
        passport, _ = engine.load_passport(self.o.passport)
        unlisted = [d.name for d in self.o.delegates if d.name not in passport["delegates"]]
        if unlisted:
            raise ValueError(f"{self.o.passport}'s passport doesn't list {', '.join(unlisted)} in its delegates")
        self.delegates = {d.name: d for d in self.o.delegates}
        self.by_name = {r["registration"]: r for r in self.o.registrations.values()}
        self.network = network or Network()
        self.engine = engine.Engine(self.o.state_dir, workers={"mcp": self._mcp_step, "a2a": self._a2a_step},
                                    log=log.info, clock=clock)
        self.system = "\n\n".join(
            [f"<!-- {p.name} -->\n{p.read_text(encoding='utf-8')}" for p in config.prompt_files] + [HOSTED])
        self.loop = None
        self.drives = {}
        self.closing = False
        self.sweeper = None
        self.publishing = asyncio.Lock()

    # Requests

    def check(self, message):
        """(input, request), or raise InvalidParamsError explaining why the message is refused.
        request is the caller's trigger and facts, from the message's metadata."""
        value, problem = read_input(message)
        if isinstance(value, str):
            value = {contract_first(self.config.contract): value}
        if problem:
            raise InvalidParamsError(message=problem)
        problems = contract.errors(value, self.config.contract["inputs"])
        if problems:
            raise InvalidParamsError(message="the input doesn't match the contract: " + contract.describe(problems),
                                     data={"errors": problems})
        meta = MessageToDict(message.metadata) if message.HasField("metadata") else {}
        request = {}
        if "trigger" in meta:
            if not isinstance(meta["trigger"], str) or not meta["trigger"]:
                raise InvalidParamsError(message="the metadata's trigger must be a non-empty string")
            request["trigger"] = meta["trigger"]
        if "facts" in meta:
            facts = meta["facts"]
            if not isinstance(facts, dict) or not all(isinstance(v, (str, int, float, bool)) for v in facts.values()):
                raise InvalidParamsError(message="the metadata's facts must be an object of strings, numbers "
                                                 "and booleans")
            request["facts"] = facts
        return value, request

    def policy_for(self, owner):
        reg = self.o.registrations.get(owner)
        return reg["policy"] if reg else engine.CHARTER_POLICY

    async def open(self, task_id, context_id, owner, value, request):
        inputs = {"input": value, "request": request, "owner": owner, "contextId": context_id}
        await asyncio.to_thread(self.engine.open, self.config.capability, inputs, self.policy_for(owner),
                                self.o.passport, task_id)

    # Driving runs

    def spawn(self, run_id, new=False):
        self.drives[run_id] = asyncio.create_task(self.drive(run_id, new))

    async def drive(self, run_id, new):
        try:
            if new:  # until the handler has stored the task as working, a write here could be overwritten
                for _ in range(100):
                    task = await self.store.get(run_id, self.context(await self.owner(run_id)))
                    if task is not None and task.status.state != TaskState.TASK_STATE_SUBMITTED:
                        break
                    await asyncio.sleep(0.05)
            await asyncio.to_thread(self.advance, run_id)
        except (Shutdown, asyncio.CancelledError):
            return
        except Exception as e:  # nothing the loop raises should leave a run working
            log.exception("run %s stopped on an error", run_id)
            await asyncio.to_thread(self._fail, run_id, f"The server failed: {type(e).__name__}: {e}")
        finally:
            self.drives.pop(run_id, None)
        if not self.closing:
            await self.settle(run_id)

    def _fail(self, run_id, message):
        run = self.engine.load(run_id)
        if run["status"] not in engine.TERMINAL:
            self.engine.end(run, "failed", pending=None, error={"step": None, "message": message})

    def _await(self, coro):
        """Run coro on the server's loop from the loop's thread and wait, giving up when the
        server stops."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        while not concurrent.futures.wait([future], timeout=0.1).done:
            if self.closing:
                future.cancel()
                raise Shutdown()
        try:
            return future.result()
        except (concurrent.futures.CancelledError, asyncio.CancelledError):
            raise Shutdown() from None

    def advance(self, run_id):
        """The loop, from the run's record: replay what it recorded, then take turns and run
        the steps they ask for until the run ends or waits."""
        e = self.engine
        run = e.load(run_id)
        if run["status"] != "working":
            return
        reg = self.o.registrations.get(run["inputs"]["owner"])
        tools, offered = self.tools(reg)
        history = [User(self.prompt(run["inputs"]["input"]))]
        corrections = 0
        for n in itertools.count(1):
            tid = f"t{n}"
            plan = None
            if run["turns"].get(tid, {}).get("status") != "completed":
                plan = self.turn_plan(run, history, tools)
                if isinstance(plan, str):
                    e.fail(run, plan)
                    return
            try:
                output = e.turn(run, tid, lambda key: self.take_turn(run_id, key, history, tools, plan))
            except engine.Stopped:
                return
            reply = _reply(output)
            history.append(reply)
            if not reply.tool_calls:
                result, problem = contract.parse_output(reply.text, self.config.contract["output"])
                if problem is None:
                    e.finish(run, result)
                    return
                if corrections == CORRECTIONS:
                    e.fail(run, "The model's final reply doesn't match the contract's output: " + problem)
                    return
                corrections += 1
                history.append(User(f"That reply doesn't match the output schema: {problem}. Reply with only the "
                                    "JSON object, or call a tool."))
                continue
            if e.cancel_requested(run):  # a cancel that landed during the turn stops the lookups too
                return
            results = self.act(run, n, reply.tool_calls, reg, offered)
            if results is None:
                return
            history.append(results)

    def prompt(self, value):
        return (f"Run the execution contract `{self.config.capability}` on the input below. Work toward the "
                "goal with the tools offered. When you are done, reply with only a JSON object that matches "
                "this output schema, and nothing else.\n\n"
                f"Output schema:\n{json.dumps(self.config.contract['output'], indent=2)}\n\n"
                f"Input:\n{json.dumps(value, indent=2)}")

    def tools(self, reg):
        """The tools offered to the model, and what each name stands for: ("a2a", agent) or
        ("mcp", "<server>/<tool>"). Only tools the registration maps to an action are offered."""
        tools, offered = [], {}
        for d in self.o.delegates:
            name = f"delegate__{d.name}"
            tools.append(Tool(name, f"Delegate to {d.name}, an agent that runs the {d.capability} contract: "
                                    f"{d.contract.get('description', '')} Pass only what it needs.",
                              d.contract["inputs"]))
            offered[name] = ("a2a", d.name)
        for server in (reg or {}).get("servers", []):
            sname = server["mcp"]["name"]
            listed = self._await(self.network.tools(server))
            for full, t in reg["tools"].items():
                prefix, _, tool = full.partition("/")
                if prefix != sname or "action" not in t:
                    continue
                if tool not in listed:
                    log.warning("%s doesn't offer %s, which %s's registration maps", sname, tool, reg["registration"])
                    continue
                name = f"{sname}__{tool}"
                tools.append(Tool(name, listed[tool].get("description", ""),
                                  listed[tool].get("inputSchema") or {"type": "object"}))
                offered[name] = ("mcp", full)
        return tools, offered

    def turn_plan(self, run, history, tools):
        """(most output tokens, worst-case usd, seconds left) for the next turn, or why the
        run has no room for it."""
        b, m, spent = self.budget, self.config.model, run["cost"]
        size = len(self.system) + _chars(history) + len(json.dumps([t.__dict__ for t in tools]))
        est_in = math.ceil(size / CHARS_PER_TOKEN)
        max_out = m.max_output_tokens
        if "tokens" in b:
            max_out = min(max_out, b["tokens"] - spent["tokens"] - est_in)
        # The ledger also holds a turn a restart cut off, which the run's own cost never saw.
        left_usd = b["usd"] - max(spent["usd"], self.ledger.run_spent(run["runId"]))
        if m.output_usd_per_mtok > 0:
            max_out = min(max_out, math.floor((left_usd * 1e6 - est_in * m.input_usd_per_mtok) / m.output_usd_per_mtok))
        elif self.config.price(est_in, 0) > left_usd:
            max_out = 0
        if max_out < MIN_OUTPUT_TOKENS:
            return (f"The run's budget has no room for another turn: ${max(left_usd, 0):.4f} and "
                    f"{max(b.get('tokens', 0) - spent['tokens'], 0)} tokens are left of ${b['usd']} and "
                    f"{b.get('tokens', 'no limit on')} tokens.")
        left_seconds = b.get("seconds", math.inf) - working_seconds(run)
        if left_seconds <= 0:
            return f"The run used its {b['seconds']}-second budget of working time."
        return max_out, self.config.price(est_in, max_out), left_seconds

    def take_turn(self, run_id, key, history, tools, plan):
        """One model turn, metered into the ledger and charged to the run's hold. Returns
        (output, cost) for the engine's turn."""
        max_out, max_usd, seconds = plan
        unmetered = {**self.who(run_id), "usd": round(max_usd, 6), "basis": "estimated"}
        self._await(self.ledger.start(key, unmetered))

        async def converse():
            return await asyncio.wait_for(self.provider.converse(self.system, list(history), tools, max_out),
                                          timeout=None if seconds == math.inf else seconds)

        try:
            reply = self._await(converse())
        except TimeoutError:
            self._await(self.ledger.charge(run_id, unmetered, pending=key))
            raise TimeoutError(f"the turn ran past the {seconds:.0f} seconds of working time the run had left")
        except ProviderError as err:
            used = self.entry(run_id, err.completion) if err.completion else unmetered if err.sent else None
            if used:
                self._await(self.ledger.charge(run_id, used, pending=key))
            else:
                self._await(self.ledger.settle(0, key=key))
            raise
        used = self.entry(run_id, reply)
        self._await(self.ledger.charge(run_id, used, pending=key))
        return _recorded(reply), {"usd": used["usd"], "tokens": used["tokens"]}

    def who(self, run_id):
        return {"runId": run_id, "capability": self.config.capability,
                "provider": self.config.model.publisher.lower(), "api": self.provider.name,
                "model": self.provider.model}

    def entry(self, run_id, completion):
        tokens = completion.input_tokens + completion.output_tokens
        return {**self.who(run_id), "usd": round(self.config.price(completion.input_tokens, completion.output_tokens), 6),
                "tokens": tokens, "tokenDetail": {"input": completion.input_tokens, "output": completion.output_tokens},
                "basis": "estimated"}  # usd is computed from configured prices, not billed figures

    def act(self, run, n, calls, reg, offered):
        """Append a step for each tool call that names an offered tool and run them. Returns
        their results, or None when the run ended or waits for a person."""
        e = self.engine
        planned = []
        for i, call in enumerate(calls, 1):
            sid = f"t{n}-{i}"
            what = offered.get(call.name)
            if what is None:
                planned.append((call, None, f"There is no tool named {call.name}. Use only the tools offered."))
                continue
            if sid not in run["steps"]:
                step = self.step_for(sid, what, call.arguments, reg, run["inputs"]["request"])
                if isinstance(step, str):
                    planned.append((call, None, step))
                    continue
                e.append(run, step)
            planned.append((call, sid, None))
        if any(sid and run["steps"][sid]["status"] != "completed" for _, sid, _ in planned):
            run = e.execute(run)
        if run["status"] != "working":
            return None
        return [Result(call.id, problem, error=True) if sid is None else
                Result(call.id, run["steps"][sid]["output"]["content"], run["steps"][sid]["output"]["error"])
                for call, sid, problem in planned]

    def step_for(self, sid, what, arguments, reg, request):
        """The step a tool call becomes, or why it can't be one. Its input and actions are
        literal: an argument that looks like a reference is just text."""
        kind, target = what
        if kind == "a2a":
            return {"id": sid, "worker": "a2a", "literal": True, "input": {"agent": target, "input": arguments},
                    "actions": [{"action": "agent.delegate", "scope": {"passport": target},
                                 "facts": {"context.whole": False}}]}
        try:
            req, present = registrations.resolve(reg, target, arguments, request,
                                                 lambda tool, given: self.lookup(reg, tool, given))
        except registrations.Unmapped as x:
            return str(x)
        return {"id": sid, "worker": "mcp", "literal": True,
                "input": {"registration": reg["registration"], "tool": target, "arguments": arguments,
                          "present": present},
                "actions": [req]}

    def server(self, reg, full):
        name, _, tool = full.partition("/")
        return next(s for s in reg["servers"] if s["mcp"]["name"] == name), tool

    def lookup(self, reg, full, given):
        """A fact source's result, or None when it fails: a missing fact."""
        server, tool = self.server(reg, full)
        try:
            return _found(self._await(self.network.call(server, tool, given)))
        except McpError as e:
            log.warning("lookup %s failed: %s", full, e)
            return None

    def _mcp_step(self, inp, key, _cap):
        server, tool = self.server(self.by_name[inp["registration"]], inp["tool"])
        result = self._await(self.network.call(server, tool, inp["arguments"], key))
        return {"content": _content(result), "error": bool(result.get("isError"))}, {"usd": 0.0, "tokens": 0}

    def _a2a_step(self, inp, key, _cap):
        content, error = self._await(self.network.delegate(self.delegates[inp["agent"]], inp["input"], key))
        return {"content": content, "error": error}, {"usd": 0.0, "tokens": 0}

    # The task store

    @staticmethod
    def context(owner):
        return ServerCallContext(user=Caller(owner))

    async def owner(self, run_id):
        return (await asyncio.to_thread(self.engine.load, run_id))["inputs"]["owner"]

    def describe(self, run):
        """The task state, status text and artifact for a run."""
        status = run["status"]
        if status == "working":
            return "Working on the goal.", None
        if status == "input_required":
            p = run["pending"]
            step = next(s for s in run["plan"]["steps"] if s["id"] == p["step"])
            tool = step["input"].get("tool") or f"delegate__{step['input'].get('agent')}"
            actions = ", ".join(a["action"] for a in p.get("actions", []))
            rules = f" under {', '.join(p['rules'])}" if p.get("rules") else ""
            return (f"Waiting for a person to approve {tool} ({actions}{rules}). It expires unanswered at "
                    f"{p['expiresAt']}."), None
        if status == "completed":
            return "Done.", run["result"]
        if status == "cancelled":
            return "Cancelled.", None
        return (run.get("error") or {}).get("message") or "The run failed.", None

    async def publish(self, run_id):
        """Write the run's state to its task, unless the task has already ended."""
        run = await asyncio.to_thread(self.engine.load, run_id)
        context = self.context(run["inputs"]["owner"])
        async with self.publishing:
            task = await self.store.get(run_id, context)
            if task is None:
                task = Task(id=run_id, context_id=run["inputs"]["contextId"])
            elif task.status.state in ENDED:
                return
            text, result = self.describe(run)
            task.status.state = STATES[run["status"]]
            task.status.message.CopyFrom(Message(
                message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT, task_id=run_id,
                context_id=task.context_id, parts=[new_text_part(text)]))
            task.status.timestamp.GetCurrentTime()
            if result is not None:
                task.artifacts.append(Artifact(artifact_id=str(uuid.uuid4()), name="result",
                                               parts=[new_data_part(result, "application/json")]))
            await self.store.save(task, context)

    async def settle(self, run_id):
        """After the loop stops: apply a cancel that landed as it paused, publish, and release
        an ended run's hold."""
        def cancelled():
            run = self.engine.load(run_id)
            if run["status"] not in engine.TERMINAL:
                self.engine.cancel_requested(run)
            return run

        run = await asyncio.to_thread(cancelled)
        await self.publish(run_id)
        if run["status"] in engine.TERMINAL:
            await self.ledger.release(run_id)

    # Startup, expiry, cancel and shutdown

    def has_run(self, task_id):
        return self.engine.record_path(task_id).is_file()

    def runs(self):
        found = []
        for path in sorted(self.o.state_dir.glob("*.json")):
            try:
                found.append(json.loads(path.read_text()))
            except ValueError:
                log.warning("can't read the run record %s", path)
        return found

    async def start(self):
        """Hold each unfinished run's remainder again, resume the working ones and expire the
        paused ones that are due."""
        self.loop = asyncio.get_running_loop()
        for run in await asyncio.to_thread(self.runs):
            if not run.get("open") or run["workflow"] != self.config.capability:
                continue
            if run["status"] in engine.TERMINAL:
                await self.publish(run["runId"])  # in case the server stopped before it did
                continue
            spent = max(run["cost"]["usd"], self.ledger.run_spent(run["runId"]))
            await self.ledger.hold(run["runId"], self.budget["usd"] - spent)
            if run["status"] == "working":
                log.info("resuming run %s", run["runId"])
                self.spawn(run["runId"])
        await self.sweep()
        self.sweeper = asyncio.create_task(self._sweep_forever())

    async def _sweep_forever(self):
        while True:
            await asyncio.sleep(self.o.sweep_seconds)
            try:
                await self.sweep()
            except Exception:
                log.exception("the expiry sweep failed")

    async def sweep(self):
        """Fail each paused run whose approval has waited past its expiry."""
        for run in await asyncio.to_thread(self.runs):
            if run.get("open") and run["status"] == "input_required" \
                    and await asyncio.to_thread(self.engine.expire_if_due, run):
                await self.settle(run["runId"])

    async def cancel(self, run_id, by):
        """Cancel the run: a paused one now, a working one before its next turn or step."""
        try:
            run = await asyncio.to_thread(self.engine.cancel, run_id, by)
        except engine.EngineError as e:
            log.info("cancel %s: %s", run_id, e)
            return
        if run["status"] in engine.TERMINAL:
            await self.ledger.release(run_id)

    async def close(self):
        self.closing = True
        if self.sweeper:
            self.sweeper.cancel()
        await asyncio.gather(*self.drives.values(), return_exceptions=True)
        await self.network.aclose()


def contract_first(c):
    return (c["inputs"].get("required") or [None])[0]


def _message(updater, text, data=None):
    parts = [new_text_part(text)]
    if data is not None:
        parts.append(new_data_part(data, "application/json"))
    return updater.new_agent_message(parts)


class Executor(AgentExecutor):
    def __init__(self, orchestrator):
        self.o = orchestrator

    async def execute(self, context, event_queue):
        if context.task_id is None or context.context_id is None:
            return
        o = self.o
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if context.current_task is None:
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        try:
            value, request = o.check(context.message)
        except InvalidParamsError as e:  # the handler checks first; this is a backstop
            await updater.reject(_message(updater, f"Refused: {e.message}"))
            return
        refusal = await o.ledger.reserve(o.budget["usd"], key=context.task_id)
        if refusal:
            log.warning("ceiling can't hold a run; refused task %s", context.task_id)
            await updater.reject(_message(updater, refusal.text("runs"), refusal.data()))
            return
        try:
            await o.open(context.task_id, context.context_id, context.call_context.user.user_name, value, request)
        except Exception as e:
            await o.ledger.release(context.task_id)
            log.exception("couldn't open a run for task %s", context.task_id)
            await updater.failed(_message(updater, f"The run couldn't start: {e}"))
            return
        await updater.start_work(_message(updater, "Working on the goal."))
        o.spawn(context.task_id, new=True)

    async def cancel(self, context, event_queue):
        if context.task_id is None or context.context_id is None:
            return
        await self.o.cancel(context.task_id, context.call_context.user.user_name)
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


class Handler(DefaultRequestHandler):
    """Refuses media types the card doesn't declare, a message on an existing task, and
    input that doesn't meet the contract, before any task is created."""

    def __init__(self, orchestrator, **kwargs):
        super().__init__(**kwargs)
        self.orchestrator = orchestrator

    async def on_message_send(self, params, context):
        validate_input_modes(params.message, self._agent_card)
        if params.message.task_id:
            raise UnsupportedOperationError(message="this server takes no message on an existing task yet")
        self.orchestrator.check(params.message)
        return await super().on_message_send(params, context)
