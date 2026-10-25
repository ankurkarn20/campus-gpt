"""Chat model providers (Adapter + Strategy patterns).

The orchestrator talks to a Provider and never to a vendor API directly. OpenAICompatible
covers every hosted model we use (Groq, Gemini's OpenAI endpoint, a local Ollama server);
ScriptedProvider replays canned responses for tests and offline demos.
"""
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import httpx


class ProviderUnavailable(Exception):
    """The model could not be reached or returned an error."""


@dataclass
class TextChunk:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""            # JSON text, exactly as the model produced it


Event = TextChunk | ToolCall


class Provider(Protocol):
    def stream(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[Event]:
        """Yield answer text as it arrives, then any complete tool calls."""
        ...


class OpenAICompatible:
    """Streams /chat/completions from any OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 60):
        self.model = model
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {})

    async def aclose(self):
        await self.client.aclose()

    async def stream(self, messages, tools):
        body = {"model": self.model, "messages": messages, "stream": True, "temperature": 0.2}
        if tools:
            body["tools"] = tools
        calls: dict[int, ToolCall] = {}
        try:
            async with self.client.stream("POST", "/chat/completions", json=body) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode(errors="replace")[:300]
                    raise ProviderUnavailable(f"HTTP {r.status_code}: {detail}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    choices = json.loads(data).get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        yield TextChunk(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        call = calls.setdefault(tc.get("index", 0), ToolCall("", ""))
                        call.id = tc.get("id") or call.id
                        fn = tc.get("function") or {}
                        call.name += fn.get("name") or ""
                        call.arguments += fn.get("arguments") or ""
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"{type(e).__name__}: {e}") from e
        for i, call in sorted(calls.items()):
            call.id = call.id or f"call_{i}"
            yield call


@dataclass
class ScriptedProvider:
    """Replays one scripted reply per model round. Each reply is a list of events; text is
    streamed word by word. Records the messages it was sent, for assertions."""

    replies: Sequence[list[Event]]
    seen: list[list[dict]] = field(default_factory=list)
    offered: list[list[str]] = field(default_factory=list)

    async def stream(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        self.offered.append([t["function"]["name"] for t in tools])
        reply = self.replies[min(len(self.seen), len(self.replies)) - 1]
        for event in reply:
            if isinstance(event, TextChunk):
                for word in event.text.split(" "):
                    yield TextChunk(word + " ")
            else:
                yield event


def make_provider(settings) -> Provider:
    return OpenAICompatible(settings.llm_base_url, settings.llm_api_key, settings.llm_model,
                            settings.llm_timeout_seconds)
