"""SecureVector SDK for CrewAI.

Usage — wrap your tools (recommended)::

    from securevector_sdk_crewai import secure_tools
    agent = Agent(tools=secure_tools(my_tools), ...)

Or install globally (best-effort monkeypatch of CrewAI's BaseTool)::

    from securevector_sdk_crewai import install
    install(mode="observe")

Or fully zero-config::

    import securevector_sdk_crewai.auto   # reads env, installs globally

Either way, every CrewAI tool call runs the local SecureVector app's three
controls — tool-call permissions, secret/data-leak detection, threat detection
— and each decision is written to the app's tamper-evident audit chain with
``runtime_kind="crewai"``. Requires the SecureVector app running locally
(installed automatically as the ``securevector-ai-monitor`` dependency).

``install()`` / ``.auto`` also patch ``Crew.kickoff`` so every run's LLM token
usage posts to the app's Cost Tracking (dollar cost via the app's pricing
table). Without the global install, call :func:`track_crew_usage` after
``kickoff()``::

    result = crew.kickoff()
    track_crew_usage(crew, agent_id="research-crew")
"""

import logging
from typing import Any, List, Optional

from ._version import __version__
from .config import Config
from .costs import CostTracker, install_kickoff_tracking, track_crew_usage
from .errors import AppUnreachable, SecureVectorError, ToolBlocked
from .wrapper import SecureCrew

log = logging.getLogger("securevector_sdk_crewai")

__all__ = [
    "__version__",
    "install",
    "secure_tool",
    "secure_tools",
    "track_crew_usage",
    "SecureCrew",
    "Config",
    "SecureVectorError",
    "ToolBlocked",
    "AppUnreachable",
]

# Process-wide default crew, created lazily so wrapping shares one interceptor.
_default: Optional[SecureCrew] = None


def _get_default(mode: str = "observe", base_url: Optional[str] = None, **kwargs) -> SecureCrew:
    global _default
    if _default is None:
        _default = SecureCrew(mode=mode, base_url=base_url, **kwargs)
    return _default


def install(
    mode: str = "observe",
    base_url: Optional[str] = None,
    *,
    register_global: bool = True,
    **kwargs,
) -> SecureCrew:
    """Create the default crew and (by default) monkeypatch CrewAI's BaseTool so
    every tool call is instrumented. Returns the :class:`SecureCrew`.

    ``mode``: ``"observe"`` (fail-open, default) or ``"enforce"`` (fail-closed).
    If the global patch can't be applied, wrap tools explicitly with
    :func:`secure_tools`.
    """
    crew = _get_default(mode=mode, base_url=base_url, **kwargs)
    if register_global and not crew.install_global():
        log.warning(
            "Global CrewAI instrumentation unavailable; wrap tools with "
            "secure_tools([...]) instead."
        )
    if register_global and not install_kickoff_tracking(
        CostTracker(crew.cfg, client=crew.interceptor.client)
    ):
        log.debug(
            "Automatic cost tracking unavailable; call track_crew_usage(crew) "
            "after kickoff() instead."
        )
    return crew


def secure_tool(tool: Any, **kwargs) -> Any:
    """Wrap a single CrewAI tool with SecureVector controls."""
    return _get_default(**kwargs).secure_tool(tool)


def secure_tools(tools, **kwargs) -> List[Any]:
    """Wrap a list of CrewAI tools with SecureVector controls."""
    return _get_default(**kwargs).secure_tools(tools)
