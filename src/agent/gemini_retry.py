"""Shared retry/backoff for Gemini API calls -- used by both the chat
provider (GeminiProvider) and vision extraction, so the lesson learned the
hard way (a daily-quota 429 can suggest a retryDelay of HOURS; blindly
sleeping through it hangs the process instead of failing fast) lives in
one place, not two that could drift apart.
"""

import time
from typing import Optional

MAX_ATTEMPTS = 6
MAX_SLEEP_S = 60


def call_with_retry(call_fn, label: str = "gemini"):
    """call_fn: zero-arg callable that makes one real API call and returns
    the response, or raises. Retries transient failures (network stalls,
    5xx, per-minute 429 throttling) with exponential backoff; raises
    RuntimeError fast -- does not sleep -- when a 429's suggested delay
    exceeds MAX_SLEEP_S, since that signals the free tier's per-day cap,
    not something an interactive retry loop should ever wait out.
    """
    import httpx
    from google.genai import errors

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call_fn()
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt == MAX_ATTEMPTS:
                raise
            wait_s = min(2 ** attempt, 20)
            print(f"  [{label}] network error ({e}), retrying in {wait_s}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait_s)
        except errors.ServerError as e:
            if attempt == MAX_ATTEMPTS:
                raise
            wait_s = min(2 ** attempt, 20)
            print(f"  [{label}] ServerError ({e}), retrying in {wait_s}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait_s)
        except errors.ClientError as e:
            if getattr(e, "code", None) != 429 or attempt == MAX_ATTEMPTS:
                raise
            wait_s = _parse_retry_delay(e) or min(2 ** attempt, 20)
            if wait_s > MAX_SLEEP_S:
                raise RuntimeError(
                    f"{label} quota exhausted with a {wait_s:.0f}s suggested "
                    f"retry delay (> {MAX_SLEEP_S}s ceiling) — this is the "
                    f"free tier's per-day cap, not per-minute throttling. "
                    f"Not sleeping through it. Original error: {e}"
                ) from e
            print(f"  [{label}] 429 RESOURCE_EXHAUSTED, retrying in {wait_s:.1f}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait_s)


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
