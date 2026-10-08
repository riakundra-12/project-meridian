"""Provider abstraction for the chat agent. Every provider implements the
same (history, tool-calling) surface regardless of backend — this is what
`AGENT_PROVIDER=gemini|groq|hf|mock` switches between. Only `gemini` and
`mock` are real in B0; `groq`/`hf` are registered stubs (fallback testing
is explicitly out of B0's scope — see the plan).

`history` is opaque outside a Provider's own methods — the runner never
inspects its internals, only passes it back through these methods.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCallRequest:
    name: str
    args: dict
    id: Optional[str] = None  # OpenAI/Groq-style tool_call_id — unused by Gemini, required by Groq's protocol to match a tool result back to its call


@dataclass
class ProviderTurn:
    tool_calls: list = field(default_factory=list)  # list[ToolCallRequest]
    text: Optional[str] = None  # only set if the provider broke the "always call a function" contract


class Provider:
    model_id = "unknown"

    def new_history(self, system_prompt: str, tool_schemas: list):
        raise NotImplementedError

    def add_user_message(self, history, text: str):
        raise NotImplementedError

    def generate(self, history) -> ProviderTurn:
        raise NotImplementedError

    def add_model_turn(self, history, turn: ProviderTurn):
        raise NotImplementedError

    def add_tool_result(self, history, tool_call: ToolCallRequest, result: dict):
        raise NotImplementedError


class GeminiProvider(Provider):
    def __init__(self, api_key: Optional[str] = None, model_id: str = "gemini-3.8-flash"):
        from google import genai
        from google.genai import types

        self._types = types
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set (checked constructor arg and "
                "environment). Copy .env.example to .env and fill it in."
            )
        # Explicit per-request timeout — without this, a stalled connection
        # hangs indefinitely instead of raising something _call_model's
        # retry loop can act on. Observed directly: a run hung for several
        # minutes with zero CPU progress before this was added.
        self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))
        self.model_id = model_id
        self._last_model_content = None

    def new_history(self, system_prompt: str, tool_schemas: list):
        types = self._types
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters_json_schema=t["parameters"],
                    )
                    for t in tool_schemas
                ]
            )
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY,
                )
            ),
        )
        return {"contents": [], "config": config}

    def add_user_message(self, history, text: str):
        types = self._types
        history["contents"].append(types.Content(role="user", parts=[types.Part(text=text)]))
        return history

    def _call_model(self, history):
        from src.agent.gemini_retry import call_with_retry

        return call_with_retry(
            lambda: self._client.models.generate_content(
                model=self.model_id,
                contents=history["contents"],
                config=history["config"],
            ),
            label="gemini-chat",
        )

    def generate(self, history) -> ProviderTurn:
        response = self._call_model(history)
        candidate = response.candidates[0]
        tool_calls = []
        text_parts = []
        for part in candidate.content.parts:
            if part.function_call is not None:
                tool_calls.append(
                    ToolCallRequest(name=part.function_call.name, args=dict(part.function_call.args or {}))
                )
            elif part.text:
                text_parts.append(part.text)
        self._last_model_content = candidate.content
        return ProviderTurn(tool_calls=tool_calls, text=("\n".join(text_parts) or None))

    def add_model_turn(self, history, turn: ProviderTurn):
        history["contents"].append(self._last_model_content)
        return history

    def add_tool_result(self, history, tool_call: ToolCallRequest, result: dict):
        types = self._types
        history["contents"].append(
            types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(name=tool_call.name, response=result))],
            )
        )
        return history


# Scripted, deterministic responses — proves the harness/dispatch/transcript
# plumbing with zero network calls and zero API key. Does NOT exercise the
# model's actual tool-chaining judgment; that's what AGENT_PROVIDER=gemini
# is for. Used later (B2) for citation-validator tests too.
MOCK_SCRIPTS = {
    "primary": [
        {"name": "get_interfaces", "args": {"part_name": "Front Door"}},
        {"name": "get_part", "args": {"part_name": "Front Side Box"}},
        {
            "name": "submit_final_answer",
            "args": {
                "claims": [
                    {
                        "statement": "Front Door interfaces with Front Side Box.",
                        "entity_id": "Front Door",
                        "field": "interfaces",
                        "value": [{"target": "Front Side Box", "resolved": True}],
                        "source_ref": "BOM row 9",
                        "confidence": 1.0,
                    },
                    {
                        "statement": "Front Side Box belongs to the Box subsystem.",
                        "entity_id": "Front Side Box",
                        "field": "subsystem",
                        "value": "Box",
                        "source_ref": "BOM row 13",
                        "confidence": 1.0,
                    },
                ],
                "abstain": False,
            },
        },
    ],
    "sanity1": [
        {"name": "get_part", "args": {"part_name": "Front Door"}},
        {
            "name": "submit_final_answer",
            "args": {
                "claims": [
                    {
                        "statement": "Front Door is made of Aluminium.",
                        "entity_id": "Front Door",
                        "field": "material",
                        "value": "Aluminium",
                        "source_ref": "BOM row 9",
                        "confidence": 1.0,
                    }
                ],
                "abstain": False,
            },
        },
    ],
    "sanity2": [
        {"name": "get_drawing", "args": {"drawing_id": "D-001"}},
        {"name": "submit_final_answer", "args": {"claims": [], "abstain": True}},
    ],
    "interface_network": [
        {"name": "get_interface_network", "args": {"part_name": "Left Side Box", "max_depth": 2}},
        {
            "name": "submit_final_answer",
            "args": {
                "claims": [
                    {
                        "statement": "Left Side Box interfaces with Back Box.",
                        "entity_id": "Left Side Box",
                        "field": "interfaces",
                        "value": [
                            {"target": "Print Platform", "resolved": True},
                            {"target": "Top Side", "resolved": True},
                            {"target": "Front Side Box", "resolved": True},
                            {"target": "Back Box", "resolved": True},
                        ],
                        "source_ref": "BOM row 8",
                        "confidence": 1.0,
                    },
                    {
                        "statement": "Back Box interfaces back with Left Side Box, confirming the cycle.",
                        "entity_id": "Back Box",
                        "field": "interfaces",
                        "value": [
                            {"target": "Left Side Box", "resolved": True},
                            {"target": "Print Platform", "resolved": True},
                            {"target": "Top Side", "resolved": True},
                        ],
                        "source_ref": "BOM row 10",
                        "confidence": 1.0,
                    },
                ],
                "abstain": False,
            },
        },
    ],
    "aggregation": [
        {"name": "search_parts", "args": {"query": "Aluminium"}},
        {
            "name": "submit_final_answer",
            "args": {
                "claims": [
                    {
                        "statement": "Front Door uses Aluminium.",
                        "entity_id": "Front Door",
                        "field": "material",
                        "value": "Aluminium",
                        "source_ref": "BOM row 9",
                        "confidence": 1.0,
                    },
                    {
                        "statement": "Print Platform uses Aluminium.",
                        "entity_id": "Print Platform",
                        "field": "material",
                        "value": "Aluminium",
                        "source_ref": "BOM row 11",
                        "confidence": 1.0,
                    },
                ],
                "abstain": False,
            },
        },
    ],
}


class MockProvider(Provider):
    model_id = "mock"

    def __init__(self, scenario: Optional[str] = None):
        if scenario not in MOCK_SCRIPTS:
            raise ValueError(
                f"mock provider requires a known scenario, got {scenario!r} "
                f"(have: {list(MOCK_SCRIPTS)})"
            )
        self._queue = list(MOCK_SCRIPTS[scenario])

    def new_history(self, system_prompt: str, tool_schemas: list):
        return {"log": []}

    def add_user_message(self, history, text: str):
        history["log"].append({"role": "user", "text": text})
        return history

    def generate(self, history) -> ProviderTurn:
        if not self._queue:
            return ProviderTurn(tool_calls=[], text="(mock script exhausted)")
        step = self._queue.pop(0)
        return ProviderTurn(tool_calls=[ToolCallRequest(name=step["name"], args=step["args"])])

    def add_model_turn(self, history, turn: ProviderTurn):
        history["log"].append({"role": "model", "tool_calls": [(tc.name, tc.args) for tc in turn.tool_calls]})
        return history

    def add_tool_result(self, history, tool_call: ToolCallRequest, result: dict):
        history["log"].append({"role": "tool", "name": tool_call.name, "result": result})
        return history


class GroqProvider(Provider):
    def __init__(self, api_key: Optional[str] = None, model_id: str = "openai/gpt-oss-120b"):
        import json as _json
        from groq import Groq

        self._json = _json
        key = api_key or os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set (checked constructor arg and "
                "environment). Copy .env.example to .env and fill it in."
            )
        self._client = Groq(api_key=key, timeout=30.0)
        self.model_id = model_id
        self._last_message = None

    def new_history(self, system_prompt: str, tool_schemas: list):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tool_schemas
        ]
        return {"messages": [{"role": "system", "content": system_prompt}], "tools": tools}

    def add_user_message(self, history, text: str):
        history["messages"].append({"role": "user", "content": text})
        return history

    def _call_model(self, history):
        import groq

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            try:
                return self._client.chat.completions.create(
                    model=self.model_id,
                    messages=history["messages"],
                    tools=history["tools"],
                    tool_choice="required",
                )
            except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as e:
                # Transient (network stall or Groq's own 5xx).
                if attempt == max_attempts:
                    raise
                wait_s = min(2 ** attempt, 20)
                print(f"  [groq] transient error ({e}), retrying in {wait_s}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait_s)
            except groq.BadRequestError as e:
                # Observed live, ~1-in-3 runs: gpt-oss-120b sometimes emits
                # a tool call named "commentary" (leaking its internal
                # channel-naming convention) with otherwise well-formed
                # submit_final_answer-shaped args. Groq's strict tool-name
                # validation correctly rejects it -- this is the model's
                # sampling noise, not a real malformed request, so a bare
                # retry (not backoff -- it's not rate/server related) is
                # the right fix rather than failing the whole turn on a
                # 1-in-3 coin flip.
                is_channel_quirk = "tool call validation failed" in str(e) and "which was not in request.tools" in str(e)
                if not is_channel_quirk or attempt == max_attempts:
                    raise
                print(f"  [groq] gpt-oss channel-naming quirk, retrying (attempt {attempt}/{max_attempts})")
            except groq.RateLimitError as e:
                # Same lesson as Gemini's 429 handling (provider.py history,
                # see GeminiProvider._call_model): don't blindly sleep
                # through a server-suggested delay that might be hours, not
                # seconds — a daily-quota 429 and a per-minute 429 both
                # raise this same exception type.
                MAX_SLEEP_S = 60
                if attempt == max_attempts:
                    raise
                retry_after = e.response.headers.get("retry-after")
                wait_s = float(retry_after) + 1.0 if retry_after else min(2 ** attempt, 20)
                if wait_s > MAX_SLEEP_S:
                    raise RuntimeError(
                        f"Groq rate limited with a {wait_s:.0f}s suggested "
                        f"retry delay (> {MAX_SLEEP_S}s ceiling) — not "
                        f"sleeping through it. Original error: {e}"
                    ) from e
                print(f"  [groq] 429 rate limited, retrying in {wait_s:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait_s)

    def generate(self, history) -> ProviderTurn:
        response = self._call_model(history)
        message = response.choices[0].message
        self._last_message = message

        tool_calls = []
        for tc in message.tool_calls or []:
            args = self._json.loads(tc.function.arguments)
            tool_calls.append(ToolCallRequest(name=tc.function.name, args=args, id=tc.id))

        return ProviderTurn(tool_calls=tool_calls, text=message.content)

    def add_model_turn(self, history, turn: ProviderTurn):
        msg = {"role": "assistant", "content": self._last_message.content}
        if self._last_message.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self._last_message.tool_calls
            ]
        history["messages"].append(msg)
        return history

    def add_tool_result(self, history, tool_call: ToolCallRequest, result: dict):
        history["messages"].append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": self._json.dumps(result),
            }
        )
        return history


class HFProvider(Provider):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("hf provider not yet implemented; use AGENT_PROVIDER=gemini or mock")


def build_provider(provider_name: str, scenario: Optional[str] = None) -> Provider:
    if provider_name == "gemini":
        return GeminiProvider()
    if provider_name == "mock":
        return MockProvider(scenario=scenario)
    if provider_name == "groq":
        return GroqProvider()
    if provider_name == "hf":
        return HFProvider()
    raise ValueError(f"Unknown AGENT_PROVIDER: {provider_name!r} (expected gemini|groq|hf|mock)")
