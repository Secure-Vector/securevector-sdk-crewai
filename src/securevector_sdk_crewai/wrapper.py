"""CrewAI tool interception.

CrewAI is not built on langchain-core, so there is no shared callback bus to
hook. Instead we wrap the tool's public ``run`` method: before it executes we
run the three controls (and, in enforce mode, raise ``ToolBlocked`` to abort);
after it returns we scan the output. The shared :class:`Interceptor` owns the
policy — this module only adapts CrewAI's tool surface to it.

Two entry points:

* ``secure_tools([...])`` / ``secure_tool(t)`` — explicit, robust per-tool
  wrapping. Recommended: ``agent = Agent(tools=secure_tools(my_tools), ...)``.
* ``install()`` — best-effort global monkeypatch of CrewAI's ``BaseTool.run``
  so every tool is covered without per-tool wiring. Falls back gracefully if
  CrewAI's internals differ from what we expect.
"""

import functools
import json
import logging
import uuid
from typing import Any, Iterable, List, Optional

from .config import Config
from .core import Interceptor
from .tool_id import normalize_tool_id

log = logging.getLogger("securevector_sdk_crewai")

_WRAPPED_FLAG = "_securevector_wrapped"


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


class SecureCrew:
    """Holds the config + shared interceptor and wraps CrewAI tools."""

    def __init__(self, mode: Optional[str] = None, base_url: Optional[str] = None, **kwargs):
        self.cfg = Config.from_env(mode=mode, base_url=base_url, **kwargs)
        self.interceptor = Interceptor(self.cfg)
        self._session = uuid.uuid4().hex[:16]

    def _secure_callable(self, name: str, original):
        @functools.wraps(original)
        def secured(*args, **kwargs):
            tool_id = normalize_tool_id(None, name=name)
            req = uuid.uuid4().hex[:16]
            # guard_input runs the three controls; in enforce mode a denial
            # raises ToolBlocked here, before the underlying tool executes.
            self.interceptor.guard_input(
                tool_id,
                _to_text({"args": args, "kwargs": kwargs}),
                session_id=self._session,
                request_id=req,
            )
            result = original(*args, **kwargs)
            self.interceptor.scan_output(
                tool_id, _to_text(result), session_id=self._session, request_id=req
            )
            return result

        return secured

    def secure_tool(self, tool: Any) -> Any:
        """Wrap a single CrewAI tool in place; returns the same tool."""
        if tool is None or getattr(tool, _WRAPPED_FLAG, False):
            return tool
        name = getattr(tool, "name", None) or tool.__class__.__name__
        original = getattr(tool, "run", None)
        if not callable(original):
            log.warning("tool %r has no callable run(); skipping", name)
            return tool
        secured = self._secure_callable(name, original)
        try:
            # object.__setattr__ bypasses pydantic v2 field validation; the
            # instance attribute shadows the class method on lookup.
            object.__setattr__(tool, "run", secured)
            object.__setattr__(tool, _WRAPPED_FLAG, True)
        except Exception as exc:  # pragma: no cover - depends on CrewAI internals
            log.warning("could not wrap tool %r: %s", name, exc)
        return tool

    def secure_tools(self, tools: Iterable[Any]) -> List[Any]:
        return [self.secure_tool(t) for t in (tools or [])]

    def install_global(self) -> bool:
        """Monkeypatch CrewAI's BaseTool.run so all tools are covered. Returns
        True if the patch was applied."""
        try:
            # Documented public import path.
            from crewai.tools import BaseTool  # type: ignore
        except Exception:
            try:
                from crewai.tools.base_tool import BaseTool  # type: ignore
            except Exception as exc:
                log.warning("CrewAI BaseTool not importable (%s); use secure_tools() instead", exc)
                return False
        if getattr(BaseTool, _WRAPPED_FLAG, False):
            return True
        crew = self

        original_run = BaseTool.run

        @functools.wraps(original_run)
        def patched_run(self, *args, **kwargs):  # noqa: ANN001
            name = getattr(self, "name", None) or self.__class__.__name__
            tool_id = normalize_tool_id(None, name=name)
            req = uuid.uuid4().hex[:16]
            crew.interceptor.guard_input(
                tool_id,
                _to_text({"args": args, "kwargs": kwargs}),
                session_id=crew._session,
                request_id=req,
            )
            result = original_run(self, *args, **kwargs)
            crew.interceptor.scan_output(
                tool_id, _to_text(result), session_id=crew._session, request_id=req
            )
            return result

        try:
            BaseTool.run = patched_run  # type: ignore[method-assign]
            setattr(BaseTool, _WRAPPED_FLAG, True)
            return True
        except Exception as exc:  # pragma: no cover
            log.warning("global CrewAI patch failed: %s", exc)
            return False
