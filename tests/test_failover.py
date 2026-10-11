"""Tests for the SUP-001 Gemini->Groq failover composition
(run_turn_with_failover). Uses a fake primary that deterministically
raises GeminiQuotaExhausted -- no network, no real quota needed -- and the
real MockProvider as fallback, so this exercises the actual run_turn()
path on the fallback side, not a stub.

Run from the repo root: python -m pytest tests/test_failover.py -v
"""

import pytest

from src.agent.chat_agent import run_turn_with_failover
from src.agent.gemini_retry import GeminiQuotaExhausted
from src.agent.provider import build_provider, Provider


class _AlwaysQuotaExhausted(Provider):
    """A fake primary that fails exactly like Gemini does when its real
    20-req/day cap is hit -- the specific signal, not a generic error."""
    model_id = "fake-quota-exhausted"

    def new_history(self, system_prompt, tool_schemas):
        return []

    def add_user_message(self, history, text):
        return history

    def generate(self, history):
        raise GeminiQuotaExhausted("fake-quota-exhausted: simulated daily cap")

    def add_model_turn(self, history, turn):
        return history

    def add_tool_result(self, history, tool_call, result):
        return history


class _AlwaysBroken(Provider):
    """A fake primary that fails with something that is NOT the quota
    signal -- must propagate, never get masked by falling through to
    fallback. That's the whole point of catching GeminiQuotaExhausted
    specifically instead of a bare except."""
    model_id = "fake-real-bug"

    def new_history(self, system_prompt, tool_schemas):
        return []

    def add_user_message(self, history, text):
        return history

    def generate(self, history):
        raise ValueError("a real bug, not a quota problem")

    def add_model_turn(self, history, turn):
        return history

    def add_tool_result(self, history, tool_call, result):
        return history


def test_quota_exhaustion_falls_over_to_fallback():
    primary = _AlwaysQuotaExhausted()
    fallback = build_provider("mock", scenario="sanity1")

    result, switched = run_turn_with_failover(
        primary, fallback, "What material is the Front Door made of?"
    )

    assert switched is True
    assert "Aluminium" in result.rendered_text


def test_non_quota_error_is_not_masked():
    primary = _AlwaysBroken()
    fallback = build_provider("mock", scenario="sanity1")

    with pytest.raises(ValueError, match="a real bug"):
        run_turn_with_failover(primary, fallback, "What material is the Front Door made of?")


def test_already_switched_skips_primary_entirely():
    """Once switched=True is persisted (by the caller, e.g. app.py's
    session_state), later turns must go straight to fallback -- never
    re-attempt a primary that's guaranteed to fail again before its daily
    quota resets."""
    primary = _AlwaysBroken()  # would raise ValueError if ever called
    fallback = build_provider("mock", scenario="sanity1")

    result, switched = run_turn_with_failover(
        primary, fallback, "What material is the Front Door made of?",
        already_switched=True,
    )

    assert switched is True
    assert "Aluminium" in result.rendered_text


def test_no_fallback_configured_raises_clear_error():
    primary = _AlwaysQuotaExhausted()

    with pytest.raises(RuntimeError, match="no fallback is configured"):
        run_turn_with_failover(primary, None, "What material is the Front Door made of?",
                                already_switched=True)
