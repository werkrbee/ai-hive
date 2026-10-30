"""Model providers behind one interface: given a system prompt, a user prompt and an
output-token cap, return text and the tokens the provider metered. Each is named for the
wire API it speaks, not for a vendor, since one API serves models from many publishers:

  stub              no network; a fixed verdict, for tests and conformance runs
  messages          the Messages API, e.g. Claude on Microsoft Foundry's /anthropic endpoint
  chat-completions  the Chat Completions API, e.g. Microsoft Foundry's OpenAI v1 endpoint,
                    which serves OpenAI's models and the catalog's other publishers'

complete() is one prompt and one reply, as a review is. converse() is a turn of an agent
loop: it sends the conversation so far and the tools the model may call, and returns the
reply's text and tool calls in the same shape whichever API is configured. The
conversation is a list of turns: a User prompt, a Completion the model returned, or a
list of the Results of the tool calls that Completion made. Every reply must report its usage, a tool call's as well, or
it is refused, so the ledger can meter each turn.

Which one, which model and where it is served are configuration. With model.auth =
"entra" the provider authenticates with a Microsoft Entra token from the environment's
managed identity; otherwise with an API key read from the named environment variable.

Both are tested against a mock of their API's request and response shapes. Live on
Foundry, both are verified with the managed identity (deploy/azure/README.md).
"""
import json
import os
from dataclasses import dataclass

import httpx

ENTRA_SCOPE = "https://cognitiveservices.azure.com/.default"


class ProviderError(Exception):
    def __init__(self, message, completion=None, sent=True, status=None, retry_after=None):
        super().__init__(message)
        self.completion = completion
        self.sent = sent  # False when the request never left, so nothing can have been billed
        self.status = status  # the HTTP status, when the provider answered with one
        self.retry_after = retry_after  # seconds the provider asked to wait (Retry-After), if any


def _http_error(name, r):
    try:
        wait = float(r.headers.get("retry-after", ""))
    except ValueError:
        wait = None
    return ProviderError(f"{name} returned HTTP {r.status_code}", status=r.status_code,
                         retry_after=wait if wait is not None and wait >= 0 else None)


@dataclass(frozen=True)
class Tool:
    """A tool the model may call: parameters is a JSON Schema object for its arguments."""
    name: str
    description: str
    parameters: dict


@dataclass(frozen=True)
class ToolCall:
    id: str  # the provider's id for the call, which its result must name
    name: str
    arguments: dict


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cut_off: bool = False  # the reply stopped at its output-token limit
    tool_calls: tuple = ()  # ToolCalls, in the order the model made them


@dataclass(frozen=True)
class User:
    """A prompt in a conversation."""
    text: str


@dataclass(frozen=True)
class Result:
    """What a tool call returned, or the error it failed with."""
    call_id: str
    content: str
    error: bool = False


def _calls_error(name, completion):
    return ProviderError(f"{name} response has a tool call without an id, a name or object arguments",
                         completion)


class Stub:
    """Returns a fixed verdict without calling a model. Counts about four characters a token."""

    def __init__(self, model):
        self.name, self.model = "stub", model.name

    async def complete(self, system, user, max_tokens):
        text = json.dumps({
            "verdict": "allow-with-conditions",
            "reason": "Stub provider: no model reviewed this proposal.",
            "conditions": ["Configure a real model provider before relying on this verdict."],
        })
        return Completion(text, (len(system) + len(user)) // 4 + 1, len(text) // 4 + 1)

    async def converse(self, system, history, tools, max_tokens):
        """Never calls a tool: the same fixed reply, counted over the whole conversation."""
        user = "".join(t.text if isinstance(t, (User, Completion)) else "".join(r.content for r in t)
                       for t in history)
        return await self.complete(system, user, max_tokens)

    async def aclose(self):
        pass


class _HTTP:
    def __init__(self, model, transport=None):
        self.model = model.name
        self.base_url = model.base_url.rstrip("/")
        self.auth = model.auth
        self.api_key_env = model.api_key_env
        self.client = httpx.AsyncClient(transport=transport, timeout=None)
        self.credential = None

    async def _token(self):
        if self.auth == "entra":
            if self.credential is None:
                from azure.identity.aio import DefaultAzureCredential
                self.credential = DefaultAzureCredential()
            return (await self.credential.get_token(ENTRA_SCOPE)).token
        key = os.environ.get(self.api_key_env or "")
        if not key:
            raise ProviderError(f"the environment variable {self.api_key_env} holds no API key", sent=False)
        return key

    async def _post(self, path, headers, body):
        try:
            r = await self.client.post(self.base_url + path, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} request failed: {type(e).__name__}")
        if r.status_code != 200:
            raise _http_error(self.name, r)
        try:
            return r.json()
        except ValueError:
            raise ProviderError(f"{self.name} returned a body that isn't JSON")

    async def aclose(self):
        await self.client.aclose()
        if self.credential is not None:
            await self.credential.close()


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _messages_turn(turn):
    """A conversation's turn as the Messages API takes it."""
    if isinstance(turn, User):
        return {"role": "user", "content": turn.text}
    if isinstance(turn, Completion):
        content = [{"type": "text", "text": turn.text}] if turn.text else []
        content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in turn.tool_calls]
        return {"role": "assistant", "content": content}
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, **({"is_error": True} if r.error else {})}
        for r in turn]}


class Messages(_HTTP):
    name = "messages"

    async def complete(self, system, user, max_tokens):
        return await self.converse(system, [User(user)], (), max_tokens)

    async def converse(self, system, history, tools, max_tokens):
        token = await self._token()
        headers = {"anthropic-version": "2023-06-01"}
        if self.auth == "entra":
            headers["authorization"] = f"Bearer {token}"
        else:
            headers["x-api-key"] = token
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [_messages_turn(t) for t in history]}
        if tools:
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in tools]
        data = await self._post("/v1/messages", headers, body)
        usage = data.get("usage") or {}
        i, o = _count(usage.get("input_tokens")), _count(usage.get("output_tokens"))
        if i is None or o is None:
            raise ProviderError("messages response has no token usage")
        blocks = [b for b in data.get("content") or [] if isinstance(b, dict)]
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        reply = Completion(text, i, o, cut_off=data.get("stop_reason") == "max_tokens")
        calls = []
        for b in blocks:
            if b.get("type") != "tool_use":
                continue
            if not (isinstance(b.get("id"), str) and b["id"] and isinstance(b.get("name"), str) and b["name"]
                    and isinstance(b.get("input"), dict)):
                raise _calls_error(self.name, reply)
            calls.append(ToolCall(b["id"], b["name"], b["input"]))
        return Completion(text, i, o, cut_off=reply.cut_off, tool_calls=tuple(calls))


class ChatCompletions(_HTTP):
    """Streams the response and asks for usage in its last chunk. Some of the catalog's
    publishers, DeepSeek among them, leave usage null on Foundry's OpenAI v1 endpoint unless
    the response is streamed with stream_options.include_usage, and the server can't price a
    call without it."""

    name = "chat-completions"

    async def complete(self, system, user, max_tokens):
        """A review's reply is one JSON object, so it asks for JSON mode; a turn doesn't."""
        return await self._converse(system, [User(user)], (), max_tokens, {"type": "json_object"})

    async def converse(self, system, history, tools, max_tokens):
        return await self._converse(system, history, tools, max_tokens, None)

    async def _converse(self, system, history, tools, max_tokens, response_format):
        token = await self._token()
        body = {"model": self.model, "max_completion_tokens": max_tokens}
        if response_format:
            body["response_format"] = response_format
        body |= {"stream": True, "stream_options": {"include_usage": True},
                 "messages": [{"role": "system", "content": system}] + [m for t in history for m in _chat_turn(t)]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                               "parameters": t.parameters}} for t in tools]
        text, usage, finish, pending = await self._stream("/chat/completions", {"authorization": f"Bearer {token}"}, body)
        i, o = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
        if i is None or o is None:
            raise ProviderError("chat-completions response has no token usage")
        reply = Completion(text, i, o, cut_off=finish == "length")
        calls = []
        for _, c in sorted(pending.items()):
            try:
                arguments = json.loads(c["arguments"] or "{}")
            except ValueError:
                arguments = None
            if not (c["id"] and c["name"] and isinstance(arguments, dict)):
                raise _calls_error(self.name, reply)
            calls.append(ToolCall(c["id"], c["name"], arguments))
        if not text and not calls:
            raise ProviderError("chat-completions response has no message", reply)
        return Completion(text, i, o, cut_off=reply.cut_off, tool_calls=tuple(calls))

    async def _stream(self, path, headers, body):
        """Reads the server-sent events: the text of each chunk's first choice, in order, the
        last usage any chunk carried, the first choice's finish reason, and its tool calls,
        each assembled from its fragments by index."""
        parts, usage, finish, calls = [], {}, None, {}
        try:
            async with self.client.stream("POST", self.base_url + path, headers=headers, json=body) as r:
                if r.status_code != 200:
                    raise _http_error(self.name, r)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        raise ProviderError(f"{self.name} streamed an event that isn't JSON")
                    if not isinstance(chunk, dict) or "error" in chunk:
                        raise ProviderError(f"{self.name} streamed an error")
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    choices = chunk.get("choices")
                    first = choices[0] if isinstance(choices, list) and choices else {}  # Azure's first chunk has none
                    delta = first.get("delta") if isinstance(first, dict) else None
                    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                        parts.append(delta["content"])
                    for d in (delta.get("tool_calls") if isinstance(delta, dict) else None) or []:
                        if not isinstance(d, dict) or not isinstance(d.get("index"), int):
                            raise ProviderError(f"{self.name} streamed a tool call without an index")
                        c = calls.setdefault(d["index"], {"id": "", "name": "", "arguments": ""})
                        f = d.get("function") if isinstance(d.get("function"), dict) else {}
                        c["id"] = c["id"] or (d.get("id") if isinstance(d.get("id"), str) else "")
                        c["name"] += f.get("name") if isinstance(f.get("name"), str) else ""
                        c["arguments"] += f.get("arguments") if isinstance(f.get("arguments"), str) else ""
                    if isinstance(first, dict) and isinstance(first.get("finish_reason"), str):
                        finish = first["finish_reason"]
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} request failed: {type(e).__name__}")
        return "".join(parts), usage, finish, calls


def _chat_turn(turn):
    """A conversation's turn as Chat Completions messages. A tool message has no error flag,
    so a failed call's result says so in its content."""
    if isinstance(turn, User):
        return [{"role": "user", "content": turn.text}]
    if isinstance(turn, Completion):
        m = {"role": "assistant", "content": turn.text or None}
        if turn.tool_calls:
            m["tool_calls"] = [{"id": c.id, "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                               for c in turn.tool_calls]
        return [m]
    return [{"role": "tool", "tool_call_id": r.call_id, "content": f"error: {r.content}" if r.error else r.content}
            for r in turn]


def create(model, transport=None):
    if model.api == "stub":
        return Stub(model)
    return {"messages": Messages, "chat-completions": ChatCompletions}[model.api](model, transport)
