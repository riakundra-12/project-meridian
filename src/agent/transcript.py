"""Append-only transcript recorder. Each B0 scenario run produces one of
these, saved as JSON under artifacts/b0_transcripts/ — this file IS the
GATE proof (Master Plan's zero-trust rule: raw tool-call transcript, not a
claim it works).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "b0_transcripts"


class Transcript:
    def __init__(self, scenario: str, provider_name: str, model_id: str, system_prompt: str, user_query: str):
        self.scenario = scenario
        self.provider_name = provider_name
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.user_query = user_query
        self.turns = []
        self.final_answer = None
        self._start = datetime.now(timezone.utc)

    def log_tool_call(self, name: str, args: dict, result: dict):
        self.turns.append({"type": "tool_call", "name": name, "args": args, "result": result})

    def log_failure(self, reason: str):
        self.turns.append({"type": "failure", "reason": reason})

    def set_final_answer(self, final_answer: dict):
        self.final_answer = final_answer

    def to_dict(self) -> dict:
        elapsed = (datetime.now(timezone.utc) - self._start).total_seconds()
        return {
            "scenario": self.scenario,
            "provider": self.provider_name,
            "model_id": self.model_id,
            "system_prompt": self.system_prompt,
            "user_query": self.user_query,
            "turns": self.turns,
            "final_answer": self.final_answer,
            "elapsed_seconds": elapsed,
        }

    def save(self) -> Path:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ARTIFACTS_DIR / f"{self.scenario}_{ts}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False, default=str)
        return path
