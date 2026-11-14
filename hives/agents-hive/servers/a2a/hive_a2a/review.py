"""Run one contract call per A2A task: check the input, hold its cost against the
ceiling, ask the model, check the output, and record what it cost.

Task states, as A2A defines them:
  rejected   the monthly ceiling, or the caller's allowance under it (limits.py), is
             reached (the status message says so and when it resets); nothing is sent to
             the model
  working    the model is reviewing
  completed  the verdict is the task's artifact, a JSON data part
  failed     the model errored, ran past the contract's time budget, or returned
             something that doesn't match the contract's output
  canceled   CancelTask arrived while the model was reviewing

Input that doesn't match the contract, or that is too large for the contract's budget,
never becomes a task: SendMessage returns InvalidParamsError (-32602) with the reasons.

The same review runs for an MCP tool call (mcp.py): Reviewer.check_value and
Reviewer.review are shared, so both bindings hold the same contract, budget, ledger and
ceiling.
"""
import asyncio
import json
import logging
import math
from dataclasses import dataclass

from google.protobuf.json_format import MessageToDict

from a2a.helpers.proto_helpers import new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskUpdater
from a2a.utils.errors import InvalidParamsError
from a2a.utils.input_mode_validator import validate_input_modes

from . import contract, limits
from .providers import ProviderError

log = logging.getLogger("hive_a2a")

# A conservative characters-per-token figure for sizing a call before it is made; the
# provider's metered counts are what the ledger records.
CHARS_PER_TOKEN = 3
MIN_OUTPUT_TOKENS = 256


@dataclass(frozen=True)
class Plan:
    user_prompt: str
    max_output_tokens: int
    max_usd: float


@dataclass(frozen=True)
class Outcome:
    """How a review ended: rejected (text, and the refusal's JSON as data), failed (text),
    or completed (the verdict)."""
    state: str
    text: str = ""
    data: dict | None = None
    verdict: dict | None = None


def read_input(message):
    """The contract input carried by an A2A message: one JSON data part, or text parts
    taken as the first required field (e.g. governance-review's proposal)."""
    parts = list(message.parts) if message else []
    data = [p for p in parts if p.HasField("data")]
    text = [p.text for p in parts if p.HasField("text")]
    if len(data) == 1 and not text:
        value = MessageToDict(data[0].data)
        return value, None
    if data:
        return None, "send one JSON data part with the contract input, or text only"
    if text and len(text) == len(parts):
        return "\n".join(text), None
    return None, "the message needs a JSON data part with the contract input"


class Reviewer:
    """Everything a call needs that doesn't change between calls.

    The cache stays inside the trust boundary (the Charter's sub-agents and clones). The
    system prompt is built once from the shared prompt files and holds no caller's data,
    and each call sends only its own input after it, with no session, conversation or
    earlier message. So a provider's prompt cache can only ever hold the shared prefix,
    and nothing one caller sent reaches another's call."""

    def __init__(self, config, ledger, provider):
        self.config = config
        self.ledger = ledger
        self.provider = provider
        c = config.contract
        for where in ("inputs", "output"):
            problems = contract.supported(c[where], where)
            if problems:
                raise ValueError(f"contract {config.capability}: " + "; ".join(problems))
        self.system = "\n\n".join(
            f"<!-- {p.name} -->\n{p.read_text(encoding='utf-8')}" for p in config.prompt_files)
        self.first_required = (c["inputs"].get("required") or [None])[0]

    def check(self, message):
        """(input, plan), or raise InvalidParamsError explaining why the input is refused."""
        value, problem = read_input(message)
        if isinstance(value, str):
            value = {self.first_required: value} if self.first_required else None
            problem = problem or (None if value else "this contract takes a JSON data part")
        if problem:
            raise InvalidParamsError(message=problem)
        return self.check_value(value)

    def check_value(self, value):
        """(value, plan) for contract input already parsed, or raise InvalidParamsError."""
        problems = contract.errors(value, self.config.contract["inputs"])
        if problems:
            raise InvalidParamsError(message="the input doesn't match the contract: " + contract.describe(problems),
                                     data={"errors": problems})
        plan = self.plan(value)
        if plan is None:
            raise InvalidParamsError(message="the input is too large for the contract's per-call budget")
        return value, plan

    def plan(self, value):
        c, m = self.config.contract, self.config.model
        user = (
            f"Run the execution contract `{self.config.capability}` on the input below. Reply with "
            "only a JSON object that matches this output schema, and nothing else.\n\n"
            f"Output schema:\n{json.dumps(c['output'], indent=2)}\n\n"
            f"Input:\n{json.dumps(value, indent=2)}"
        )
        budget = c.get("budget", {})
        est_input = math.ceil((len(self.system) + len(user)) / CHARS_PER_TOKEN)
        max_out = m.max_output_tokens
        if "tokens" in budget:
            max_out = min(max_out, budget["tokens"] - est_input)
        if "usd" in budget and m.output_usd_per_mtok > 0:
            left = budget["usd"] * 1e6 - est_input * m.input_usd_per_mtok
            max_out = min(max_out, math.floor(left / m.output_usd_per_mtok))
        if max_out < MIN_OUTPUT_TOKENS or self.config.price(est_input, 0) > budget.get("usd", math.inf):
            return None
        return Plan(user, max_out, self.config.price(est_input, max_out))

    def entry(self, completion, client=None):
        """The ledger entry for a call that reported its usage."""
        tokens = completion.input_tokens + completion.output_tokens
        usd = self.config.price(completion.input_tokens, completion.output_tokens)
        if usd > self.config.contract.get("budget", {}).get("usd", math.inf):
            log.warning("a call cost $%.4f, over the contract's per-call budget", usd)
        return {
            **self._who(client),
            "usd": round(usd, 6), "tokens": tokens,
            "tokenDetail": {"input": completion.input_tokens, "output": completion.output_tokens},
            # usd is computed from configured prices, not billed figures
            "basis": "estimated",
        }

    def unmetered(self, usd, client=None):
        """An entry for a call that may have been billed but reported no usage."""
        return {**self._who(client), "usd": round(usd, 6), "basis": "estimated"}

    def _who(self, client=None):
        """What the ledger says about the call: the capability, the model's publisher (lower
        case, as the ledger recorded it before the API was its own field), the wire API, the
        model, and the client it was made for, which its allowance is counted from."""
        return {"capability": self.config.capability, "provider": self.config.model.publisher.lower(),
                "api": self.provider.name, "model": self.provider.model, **({"client": client} if client else {})}

    def verdict(self, text):
        """(output, None), or (None, why the model's reply doesn't meet the contract)."""
        return contract.parse_output(text, self.config.contract["output"])

    async def review(self, plan, key, started=None, client=None):
        """Hold the plan's cost against the ceiling and client's allowance, ask the model,
        check its reply and record what it cost, under key in the ledger's calls in flight.
        started() is awaited once the call is about to go out. Returns an Outcome."""
        check = limits.allowance(self.config, client) if client else None
        refusal = await self.ledger.reserve(plan.max_usd, client=client, check=check)
        if refusal:
            log.warning("the %s limit is reached; refused %s", refusal.limit, key)
            return Outcome("rejected", refusal.text(), refusal.data())

        # From here the provider may bill us. Until it reports metered usage, the cost is
        # taken to be the whole reservation, so a timeout or cancel still counts toward the
        # ceiling.
        entry = self.unmetered(plan.max_usd, client)
        try:
            await self.ledger.start(key, entry)
            if started:
                await started()
            budget = self.config.contract.get("budget", {})
            try:
                completion = await asyncio.wait_for(
                    self.provider.complete(self.system, plan.user_prompt, plan.max_output_tokens),
                    timeout=budget.get("seconds"))
            except TimeoutError:
                return Outcome("failed", f"The review ran past the contract's {budget['seconds']}-second budget "
                                         "and was stopped.")
            except ProviderError as e:
                entry = self.entry(e.completion, client) if e.completion else entry if e.sent else None
                log.warning("provider error on %s: %s", key, e)
                return Outcome("failed", f"The model provider failed: {e}")
            entry = self.entry(completion, client)
            verdict, problems = self.verdict(completion.text)
            if problems:
                return Outcome("failed", "The model's reply doesn't match the contract's output: " + problems)
            return Outcome("completed", verdict=verdict)
        finally:
            await self.ledger.settle(plan.max_usd, entry, key=key, client=client)


def _message(updater, text, data=None):
    parts = [new_text_part(text)]
    if data is not None:
        parts.append(new_data_part(data, "application/json"))
    return updater.new_agent_message(parts)


class Executor(AgentExecutor):
    def __init__(self, reviewer):
        self.reviewer = reviewer

    async def execute(self, context, event_queue):
        if context.task_id is None or context.context_id is None:
            return
        r = self.reviewer
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if context.current_task is None:
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        try:
            value, plan = r.check(context.message)
        except InvalidParamsError as e:  # the handler checks first; this is a backstop
            await updater.reject(_message(updater, f"Refused: {e.message}"))
            return

        user = context.call_context.user if context.call_context else None
        client = user.user_name if user and user.is_authenticated else None
        outcome = await r.review(plan, context.task_id, started=updater.start_work, client=client)
        if outcome.state == "rejected":
            await updater.reject(_message(updater, outcome.text, outcome.data))
        elif outcome.state == "failed":
            await updater.failed(_message(updater, outcome.text))
        else:
            await updater.add_artifact([new_data_part(outcome.verdict, "application/json")], name="verdict")
            await updater.complete()

    async def cancel(self, context, event_queue):
        if context.task_id is None or context.context_id is None:
            return
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


class Handler(DefaultRequestHandler):
    """Refuses media types the card doesn't declare (ContentTypeNotSupportedError) and input
    that doesn't meet the contract (InvalidParamsError) before any task is created."""

    def __init__(self, reviewer, **kwargs):
        super().__init__(**kwargs)
        self.reviewer = reviewer

    async def on_message_send(self, params, context):
        validate_input_modes(params.message, self._agent_card)
        self.reviewer.check(params.message)
        return await super().on_message_send(params, context)
