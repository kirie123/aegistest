"""LLM Client — standard-library only, supports DeepSeek (OpenAI-compatible)."""

import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class LLMClient:
    """Base LLM client interface."""

    def complete(self, prompt: str) -> str:
        raise NotImplementedError

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Mock client for testing without API calls."""

    def __init__(self, responses: Optional[List[str]] = None):
        self.responses = responses or []
        self._call_count = 0
        self._calls: List[Dict] = []

    def complete(self, prompt: str) -> str:
        self._calls.append({"type": "complete", "prompt": prompt[:200]})
        resp = self._next_response()
        return resp

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None) -> Dict[str, Any]:
        self._calls.append({"type": "chat", "messages": len(messages), "tools": bool(tools)})
        resp = self._next_response()
        return {"content": resp, "tool_calls": []}

    def _next_response(self) -> str:
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
            self._call_count += 1
            return resp
        return '[]'


class DeepSeekClient(LLMClient):
    """
    DeepSeek API client (OpenAI-compatible).

    Reads config from C:\\Users\\Administrator\\.aiko\\settings.json by default,
    or falls back to environment variables.
    """

    DEFAULT_CONFIG_PATH = r"C:\Users\Administrator\.aiko\settings.json"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        config_path: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self._timeout = timeout
        self._ctx = ssl.create_default_context()

        # Resolve credentials
        cfg = self._load_config(config_path or self.DEFAULT_CONFIG_PATH)

        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or cfg.get("api_key", "")
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL") or cfg.get("base_url", "https://api.deepseek.com")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or cfg.get("model", "deepseek-chat")

        # Ensure base_url has no trailing slash and points to chat completions endpoint
        self.base_url = self.base_url.rstrip("/")
        # DeepSeek's OpenAI-compatible endpoint is /v1; /anthropic is for Claude-format
        # We need OpenAI format for tool_calls, so strip /anthropic and use /v1
        if "/anthropic" in self.base_url:
            self.base_url = self.base_url.replace("/anthropic", "")
        if not self.base_url.endswith("/v1"):
            self._api_base = f"{self.base_url}/v1"
        else:
            self._api_base = self.base_url

    def _load_config(self, path: str) -> Dict[str, str]:
        p = Path(path)
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

        cfg: Dict[str, str] = {}
        if isinstance(data, dict):
            cfg["model"] = data.get("model", "")
            api = data.get("api", {})
            if isinstance(api, dict):
                cfg["base_url"] = api.get("baseUrl", "")
                cfg["api_key"] = api.get("apiKey", "")
        return cfg

    def complete(self, prompt: str) -> str:
        """Single-turn completion via chat API."""
        result = self.chat([{"role": "user", "content": prompt}])
        return result.get("content", "")

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Call chat completions API.

        Returns dict with:
          - content: assistant text content
          - tool_calls: list of {"id", "type", "function": {"name", "arguments"}}
        """
        url = f"{self._api_base}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API error {e.code}: {error_body}") from e
        except Exception as e:
            raise RuntimeError(f"DeepSeek API request failed: {e}") from e

        choice = body.get("choices", [{}])[0]
        message = choice.get("message", {})

        # Extract text content
        content = message.get("content") or ""

        # Extract tool_calls
        raw_tool_calls = message.get("tool_calls", [])
        tool_calls: List[Dict[str, Any]] = []
        for tc in raw_tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", ""),
                },
            })

        return {
            "content": content,
            "tool_calls": tool_calls,
            "model": body.get("model", ""),
            "usage": body.get("usage", {}),
        }
