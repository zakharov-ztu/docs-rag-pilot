"""Minimal client for a local Ollama server — nothing leaves the machine."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Iterator

from rag.config import OLLAMA_URL


class OllamaError(Exception):
    """Ollama could not be reached, timed out, or returned an unexpected response."""


def _chat_request(model: str, system: str, user: str, stream: bool) -> urllib.request.Request:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": stream,
    }
    return urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def chat(model: str, system: str, user: str, timeout: float = 180) -> str:
    req = _chat_request(model, system, user, stream=False)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["message"]["content"]
    # OSError covers URLError and a read timeout (TimeoutError).
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise OllamaError(f"{OLLAMA_URL}: {exc}") from exc


def chat_stream(model: str, system: str, user: str, timeout: float = 180) -> Iterator[str]:
    """Yields the answer piece by piece as the model produces it."""
    req = _chat_request(model, system, user, stream=True)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # Ollama streams one JSON object per line.
            for line in resp:
                part = json.loads(line)
                if "error" in part:
                    raise OllamaError(part["error"])
                yield part["message"]["content"]
                if part.get("done"):
                    return
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise OllamaError(f"{OLLAMA_URL}: {exc}") from exc


def list_models(timeout: float = 5) -> list[str]:
    """Names of the models pulled into the local Ollama, sorted."""
    tags_url = OLLAMA_URL.replace("/api/chat", "/api/tags")
    try:
        with urllib.request.urlopen(tags_url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return sorted(m["name"] for m in body["models"])
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise OllamaError(f"{tags_url}: {exc}") from exc
