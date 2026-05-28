"""LLM Clients — standard-library only, supports OpenAI and Anthropic protocols.

Usage:
    # OpenAI-compatible (DeepSeek, OpenAI, vLLM, etc.)
    client = OpenAIClient(api_key="sk-xxx", base_url="https://api.deepseek.com", model="deepseek-chat")

    # Anthropic (Claude)
    client = AnthropicClient(api_key="sk-ant-xxx", model="claude-3-sonnet")

    # Mock (testing)
    client = MockLLMClient(responses=['{"action":"skill_create",...}'])
"""

import json
import os
import ssl
import urllib.request
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


class OpenAIClient(LLMClient):
    """
    Generic OpenAI-compatible API client.

    Works with any provider that speaks the OpenAI chat.completions protocol:
    OpenAI, DeepSeek, Azure OpenAI, vLLM, Ollama (with /v1), etc.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com",
        model: str = "gpt-4",
        timeout: float = 120.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self._timeout = timeout
        self._ctx = ssl.create_default_context()

        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            self._api_base = f"{base_url}/v1"
        else:
            self._api_base = base_url

    def complete(self, prompt: str) -> str:
        result = self.chat([{"role": "user", "content": prompt}])
        return result.get("content", "")

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
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

        return self._call_api(url, payload)

    def _call_api(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
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
            raise RuntimeError(f"OpenAI API error {e.code}: {error_body}") from e
        except Exception as e:
            raise RuntimeError(f"OpenAI API request failed: {e}") from e

        choice = body.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content") or ""

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


class AnthropicClient(LLMClient):
    """
    Anthropic Claude API client.

    Uses the Messages API (not the legacy Text Completions API).
    Tool use is supported via the native Anthropic tool schema.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model: str = "claude-3-sonnet-20240229",
        timeout: float = 120.0,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.model = model
        self._timeout = timeout
        self._ctx = ssl.create_default_context()

        base_url = base_url.rstrip("/")
        self._api_base = base_url

    def complete(self, prompt: str) -> str:
        result = self.chat([{"role": "user", "content": prompt}])
        return result.get("content", "")

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        url = f"{self._api_base}/v1/messages"

        # Anthropic uses a different messages format
        anthropic_messages = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "system":
                # Anthropic puts system prompt in a top-level field
                continue
            anthropic_messages.append({"role": role, "content": content})

        # Extract system prompt from messages
        system_prompt = ""
        for m in messages:
            if m.get("role") == "system":
                system_prompt = m.get("content", "")
                break

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        if tools:
            # Convert OpenAI tool format to Anthropic format
            anthropic_tools = []
            for t in tools:
                if not isinstance(t, dict):
                    continue
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })
            payload["tools"] = anthropic_tools

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=self._ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API error {e.code}: {error_body}") from e
        except Exception as e:
            raise RuntimeError(f"Anthropic API request failed: {e}") from e

        # Parse Anthropic response format
        content_blocks = body.get("content", [])
        text_content = ""
        tool_calls: List[Dict[str, Any]] = []

        for block in content_blocks:
            btype = block.get("type", "")
            if btype == "text":
                text_content += block.get("text", "")
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        return {
            "content": text_content,
            "tool_calls": tool_calls,
            "model": body.get("model", ""),
            "usage": body.get("usage", {}),
        }
