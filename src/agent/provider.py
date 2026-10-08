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
        self._client = genai.Client(api_key=key)
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
        from google.genai import errors

        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            try:
                return self._client.models.generate_content(
                    model=self.model_id,
                    contents=history["contents"],
                    config=history["config"],
                )
            except errors.ServerError as e:
                # Transient (e.g. 503 UNAVAILABLE — model overloaded).
                if attempt == max_attempts:
                    raise
                wait_s = min(2 ** attempt, 20)
                print(f"  [gemini] ServerError ({e}), retrying in {wait_s}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait_s)
            except errors.ClientError as e:
                # 429 RESOURCE_EXHAUSTED (free-tier RPM cap) is transient —
                # the quota resets within seconds. Any other ClientError
                # (bad model/auth/schema) is not transient and propagates
                # immediately instead of wasting more quota retrying it.
                if getattr(e, "code", None) != 429 or attempt == max_attempts:
                    raise
                wait_s = self._parse_retry_delay(e) or min(2 ** attempt, 20)
                print(f"  [gemini] 429 RESOURCE_EXHAUSTED, retrying in {wait_s:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait_s)

    @staticmethod
    def _parse_retry_delay(client_error) -> Optional[float]:
        try:
            details = client_error.details.get("error", {}).get("details", [])
            for d in details:
                if d.get("@type", "").endswith("RetryInfo"):
                    delay = d.get("retryDelay", "")
                    return float(delay.rstrip("s")) + 1.0  # pad by 1s
        except Exception:
            pass
        return None

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
                        "source_ref": "BOM row 9",
                        "confidence": 1.0,
                    },
                    {
                        "statement": "Front Side Box belongs to the Box subsystem.",
                        "entity_id": "Front Side Box",
                        "field": "subsystem",
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
}


class MockProvider(Provider):
    model_id = "mock"

    def __init__(self, scenario: str):
        if scenario not in MOCK_SCRIPTS:
            raise ValueError(f"No mock script for scenario {scenario!r} (have: {list(MOCK_SCRIPTS)})")
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
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("groq provider not yet implemented; use AGENT_PROVIDER=gemini or mock")


class HFProvider(Provider):
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("hf provider not yet implemented; use AGENT_PROVIDER=gemini or mock")


def build_provider(provider_name: str, scenario: str) -> Provider:
    if provider_name == "gemini":
        return GeminiProvider()
    if provider_name == "mock":
        return MockProvider(scenario=scenario)
    if provider_name == "groq":
        return GroqProvider()
    if provider_name == "hf":
        return HFProvider()
    raise ValueError(f"Unknown AGENT_PROVIDER: {provider_name!r} (expected gemini|groq|hf|mock)")
