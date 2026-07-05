"""LLM cost tracking — post crew token usage to the local app.

The tool interception secures tool calls but never sees the model call, so
CrewAI agents were invisible to the app's Cost Tracking. CrewAI aggregates a
run's LLM usage on ``crew.usage_metrics`` (prompt / completion / cached prompt
tokens); this module reads it after ``kickoff()`` and POSTs it to the app's
``POST /api/costs/track``, which looks up pricing by exact
``"{provider}/{model_id}"`` and computes dollars. Crews run on the user's own
API keys (like the proxy), so the dollar cost is real.

Two capture paths:

* automatic — ``install()`` (and ``import securevector_sdk_crewai.auto``)
  patches ``Crew.kickoff`` so every run posts its usage delta;
* explicit — call :func:`track_crew_usage` yourself after ``kickoff()``.

Everything here is best-effort: an unreachable app, an unknown model, or a
CrewAI internals change never breaks the crew (mirrors the audit fail-soft).
"""

import functools
import logging
import re
from typing import Any, Dict, Optional, Tuple

from .client import LocalAppClient
from .config import Config
from .tool_id import RUNTIME_KIND

log = logging.getLogger("securevector_sdk_crewai")

_KICKOFF_FLAG = "_securevector_cost_wrapped"

# Map versioned model ids to the canonical pricing keys the app's pricing
# table uses. Mirrors the app-side CostRecorder aliases: /api/costs/track
# itself does an EXACT "provider/model_id" match with no normalization, so
# the SDK must normalize client-side or records land as pricing_known=false.
MODEL_ID_ALIASES: Dict[str, str] = {
    # OpenAI versioned → canonical
    "gpt-4o-2024-11-20": "gpt-4o",
    "gpt-4o-2024-08-06": "gpt-4o",
    "gpt-4o-2024-05-13": "gpt-4o",
    "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
    "gpt-4-turbo-2024-04-09": "gpt-4-turbo",
    "gpt-4-turbo-preview": "gpt-4-turbo",
    "gpt-3.5-turbo-0125": "gpt-3.5-turbo",
    "gpt-3.5-turbo-1106": "gpt-3.5-turbo",
    "o1-2024-12-17": "o1",
    "o1-mini-2024-09-12": "o1-mini",
    "o3-mini-2025-01-31": "o3-mini",
    # Gemini variants → canonical
    "gemini-2.0-flash-001": "gemini-2.0-flash",
    "gemini-2.0-flash-exp": "gemini-2.0-flash",
    "gemini-1.5-pro-001": "gemini-1.5-pro",
    "gemini-1.5-pro-002": "gemini-1.5-pro",
    "gemini-1.5-flash-001": "gemini-1.5-flash",
    "gemini-1.5-flash-002": "gemini-1.5-flash",
    # Mistral versioned
    "mistral-large-2402": "mistral-large-latest",
    "mistral-large-2407": "mistral-large-latest",
    "mistral-large-2411": "mistral-large-latest",
    "mistral-small-2402": "mistral-small-latest",
    "mistral-small-2409": "mistral-small-latest",
    # Cohere versioned
    "command-r-plus": "command-r-plus-08-2024",
    "command-r": "command-r-08-2024",
}

# Provider slugs the pricing table keys on: openai / anthropic / gemini /
# ollama / groq / mistral / cohere. CrewAI model strings are usually
# litellm-style ("openai/gpt-4o", "anthropic/claude-...") or bare ids.
_PROVIDER_CANON: Dict[str, str] = {
    "openai": "openai",
    "azure_openai": "openai",
    "azure": "openai",
    "anthropic": "anthropic",
    "google_genai": "gemini",
    "google_vertexai": "gemini",
    "google": "gemini",
    "gemini": "gemini",
    "vertexai": "gemini",
    "vertex_ai": "gemini",
    "ollama": "ollama",
    "ollama_chat": "ollama",
    "groq": "groq",
    "mistralai": "mistral",
    "mistral": "mistral",
    "cohere": "cohere",
}

# Last-resort heuristics on the model id itself.
_MODEL_PREFIX_PROVIDERS: Tuple[Tuple[str, str], ...] = (
    ("gpt-", "openai"),
    ("chatgpt", "openai"),
    ("claude", "anthropic"),
    ("gemini", "gemini"),
    ("mistral", "mistral"),
    ("ministral", "mistral"),
    ("codestral", "mistral"),
    ("command", "cohere"),
)
_OPENAI_O_SERIES = re.compile(r"^o\d(-|$)")


def split_model_id(raw: Any) -> Tuple[Optional[str], str]:
    """Split a possibly provider-prefixed model id (``"openai/gpt-4o"``,
    litellm-style) into ``(provider_hint, bare_model_id)`` and apply the
    canonical-pricing aliases."""
    mid = str(raw or "").strip()
    hint: Optional[str] = None
    if "/" in mid:
        prefix, rest = mid.split("/", 1)
        canon = _PROVIDER_CANON.get(prefix.strip().lower())
        if canon:
            hint, mid = canon, rest.strip()
    return hint, MODEL_ID_ALIASES.get(mid, mid)


def infer_provider(model_id: str = "") -> str:
    """Best-effort provider slug for the pricing lookup ('' when unknown)."""
    mid = str(model_id or "").strip().lower()
    if _OPENAI_O_SERIES.match(mid):
        return "openai"
    for prefix, provider in _MODEL_PREFIX_PROVIDERS:
        if mid.startswith(prefix):
            return provider
    return ""


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def usage_totals(metrics: Any) -> Dict[str, int]:
    """Read ``{prompt, completion, cached}`` token totals off a CrewAI
    ``UsageMetrics`` object (or dict). Zeros when absent."""
    if metrics is None:
        return {"prompt": 0, "completion": 0, "cached": 0}
    return {
        "prompt": int(_field(metrics, "prompt_tokens") or 0),
        "completion": int(_field(metrics, "completion_tokens") or 0),
        "cached": int(_field(metrics, "cached_prompt_tokens") or 0),
    }


def usage_delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    """Tokens attributable to the run bounded by the two snapshots.

    ``usage_metrics`` accumulates on some CrewAI versions and is rebuilt per
    run on others; a shrinking counter means "rebuilt", so the after-snapshot
    IS the run's usage.
    """
    if any(after[k] < before[k] for k in after):
        return dict(after)
    return {k: after[k] - before[k] for k in after}


def crew_model_id(crew: Any) -> str:
    """Best-effort model id for a crew: the first agent's LLM model string.

    ``usage_metrics`` is aggregated per crew, so a mixed-model crew is
    attributed to its first agent's model — a deliberate approximation.
    """
    for agent in getattr(crew, "agents", None) or []:
        llm = getattr(agent, "llm", None)
        if isinstance(llm, str) and llm.strip():
            return llm
        for attr in ("model", "model_name"):
            value = getattr(llm, attr, None)
            if isinstance(value, str) and value.strip():
                return value
    return ""


class CostTracker:
    """Posts token usage, tagged by runtime.

    ``agent_id`` groups records in the app's Cost Tracking dashboard; the
    default is a stable per-runtime id so all crews roll up together unless
    the user names theirs.
    """

    def __init__(
        self,
        cfg: Config,
        client: Optional[LocalAppClient] = None,
        agent_id: Optional[str] = None,
    ):
        self.cfg = cfg
        self.client = client or LocalAppClient(cfg)
        self.agent_id = agent_id or cfg.agent_id or f"{RUNTIME_KIND}-agent"

    def record_crew(self, crew: Any, before: Optional[Dict[str, int]] = None) -> bool:
        """Record a crew's usage (optionally the delta since ``before``).
        Returns True when a record was posted. Never raises."""
        if not self.cfg.enabled:
            return False
        try:
            after = usage_totals(getattr(crew, "usage_metrics", None))
            usage = usage_delta(before, after) if before is not None else after
            if usage["prompt"] <= 0 and usage["completion"] <= 0:
                return False
            hint, model_id = split_model_id(crew_model_id(crew))
            if not model_id:
                return False
            provider = infer_provider(model_id) or hint or "unknown"
            return bool(self.client.record_cost(
                agent_id=self.agent_id,
                provider=provider,
                model_id=model_id,
                input_tokens=usage["prompt"],
                output_tokens=usage["completion"],
                input_cached_tokens=usage["cached"],
            ))
        except Exception as exc:  # never let cost tracking break the crew
            log.debug("cost tracking failed: %s", exc)
            return False


def track_crew_usage(
    crew: Any,
    agent_id: Optional[str] = None,
    base_url: Optional[str] = None,
    client: Optional[LocalAppClient] = None,
    **kwargs,
) -> bool:
    """Explicitly post ``crew.usage_metrics`` to the app's Cost Tracking.

    Call after ``crew.kickoff()``::

        result = crew.kickoff()
        track_crew_usage(crew, agent_id="research-crew")

    Returns True when a record was posted. Never raises.
    """
    cfg = Config.from_env(base_url=base_url, **kwargs)
    return CostTracker(cfg, client=client, agent_id=agent_id).record_crew(crew)


def install_kickoff_tracking(tracker: CostTracker) -> bool:
    """Monkeypatch ``Crew.kickoff`` so every run posts its usage delta.
    Returns True if the patch was applied (idempotent)."""
    try:
        from crewai import Crew  # type: ignore
    except Exception as exc:
        log.debug("CrewAI Crew not importable (%s); use track_crew_usage()", exc)
        return False
    if getattr(Crew, _KICKOFF_FLAG, False):
        return True

    original_kickoff = Crew.kickoff

    @functools.wraps(original_kickoff)
    def patched_kickoff(self, *args, **kwargs):  # noqa: ANN001
        before = usage_totals(getattr(self, "usage_metrics", None))
        result = original_kickoff(self, *args, **kwargs)
        tracker.record_crew(self, before=before)
        return result

    try:
        Crew.kickoff = patched_kickoff  # type: ignore[method-assign]
        setattr(Crew, _KICKOFF_FLAG, True)
        return True
    except Exception as exc:  # pragma: no cover
        log.debug("Crew.kickoff cost patch failed: %s", exc)
        return False
