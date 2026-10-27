"""Model providers behind one interface: given a system prompt, a user prompt and an
output-token cap, return text and the tokens the provider metered. Each is named for the
wire API it speaks, not for a vendor, since one API serves models from many publishers:

  stub              no network; a fixed verdict, for tests and conformance runs
  messages          the Messages API, e.g. Claude on Microsoft Foundry's /anthropic endpoint
  chat-completions  the Chat Completions API, e.g. Microsoft Foundry's OpenAI v1 endpoint,
                    which serves OpenAI's models and the catalog's other publishers'

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
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cut_off: bool = False  # the reply stopped at its output-token limit


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


class Messages(_HTTP):
    name = "messages"

    async def complete(self, system, user, max_tokens):
        token = await self._token()
        headers = {"anthropic-version": "2023-06-01"}
        if self.auth == "entra":
            headers["authorization"] = f"Bearer {token}"
        else:
            headers["x-api-key"] = token
        data = await self._post("/v1/messages", headers, {
            "model": self.model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
        })
        usage = data.get("usage") or {}
        i, o = _count(usage.get("input_tokens")), _count(usage.get("output_tokens"))
        if i is None or o is None:
            raise ProviderError("messages response has no token usage")
        text = "".join(b.get("text", "") for b in data.get("content") or [] if isinstance(b, dict) and b.get("type") == "text")
        return Completion(text, i, o, cut_off=data.get("stop_reason") == "max_tokens")


class ChatCompletions(_HTTP):
    """Streams the response and asks for usage in its last chunk. Some of the catalog's
    publishers, DeepSeek among them, leave usage null on Foundry's OpenAI v1 endpoint unless
    the response is streamed with stream_options.include_usage, and the server can't price a
    call without it."""

    name = "chat-completions"

    async def complete(self, system, user, max_tokens):
        token = await self._token()
        text, usage, finish = await self._stream("/chat/completions", {"authorization": f"Bearer {token}"}, {
            "model": self.model, "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": True, "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        i, o = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
        if i is None or o is None:
            raise ProviderError("chat-completions response has no token usage")
        if not text:
            raise ProviderError("chat-completions response has no message", Completion("", i, o))
        return Completion(text, i, o, cut_off=finish == "length")

    async def _stream(self, path, headers, body):
        """Reads the server-sent events: the text of each chunk's first choice, in order, the
        last usage any chunk carried, and the first choice's finish reason."""
        parts, usage, finish = [], {}, None
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
                    if isinstance(first, dict) and isinstance(first.get("finish_reason"), str):
                        finish = first["finish_reason"]
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} request failed: {type(e).__name__}")
        return "".join(parts), usage, finish


def create(model, transport=None):
    if model.api == "stub":
        return Stub(model)
    return {"messages": Messages, "chat-completions": ChatCompletions}[model.api](model, transport)
