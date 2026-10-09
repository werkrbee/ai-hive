"""Model providers behind one interface: given a system prompt, a user prompt and an
output-token cap, return text and the tokens the provider metered.

  stub       no network; a fixed verdict, for tests and conformance runs
  anthropic  the Messages API (Claude), e.g. Microsoft Foundry's /anthropic endpoint
  openai     the Chat Completions API, e.g. Microsoft Foundry's OpenAI v1 endpoint

Which one, which model and where it is served are configuration. With model.auth =
"entra" the provider authenticates with a Microsoft Entra token from the environment's
managed identity; otherwise with an API key read from the named environment variable.
"""
import json
import os
from dataclasses import dataclass

import httpx

ENTRA_SCOPE = "https://cognitiveservices.azure.com/.default"


class ProviderError(Exception):
    def __init__(self, message, completion=None):
        super().__init__(message)
        self.completion = completion


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


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
            raise ProviderError(f"the environment variable {self.api_key_env} holds no API key")
        return key

    async def _post(self, path, headers, body):
        try:
            r = await self.client.post(self.base_url + path, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} request failed: {type(e).__name__}")
        if r.status_code != 200:
            raise ProviderError(f"{self.name} returned HTTP {r.status_code}")
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


class Anthropic(_HTTP):
    name = "anthropic"

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
            raise ProviderError("anthropic response has no token usage")
        text = "".join(b.get("text", "") for b in data.get("content") or [] if isinstance(b, dict) and b.get("type") == "text")
        return Completion(text, i, o)


class OpenAI(_HTTP):
    name = "openai"

    async def complete(self, system, user, max_tokens):
        token = await self._token()
        data = await self._post("/chat/completions", {"authorization": f"Bearer {token}"}, {
            "model": self.model, "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        })
        usage = data.get("usage") or {}
        i, o = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
        if i is None or o is None:
            raise ProviderError("openai response has no token usage")
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("openai response has no message", Completion("", i, o))
        return Completion(text, i, o)


def create(model, transport=None):
    if model.provider == "stub":
        return Stub(model)
    return {"anthropic": Anthropic, "openai": OpenAI}[model.provider](model, transport)
