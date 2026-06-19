"""The CrewAI wrapper must run the controls around a tool's run() and respect
observe/enforce — without needing CrewAI installed (we fake a tool)."""

import pytest

from securevector_sdk_crewai.client import AnalysisVerdict, Verdict
from securevector_sdk_crewai.config import Config
from securevector_sdk_crewai.errors import ToolBlocked
from securevector_sdk_crewai.wrapper import SecureCrew


class FakeClient:
    def __init__(self, verdict=None, analysis=None):
        self._verdict = verdict or Verdict("allow", "unknown", "default", False, "t")
        self._analysis = analysis or AnalysisVerdict(False, 0, "clean")
        self.audits = []

    def resolve_permission(self, tool_id):
        return self._verdict

    def analyze(self, text, direction):
        return self._analysis

    def record_audit(self, **kw):
        self.audits.append(kw)


class FakeTool:
    """Stand-in for a CrewAI BaseTool: a name + a run()."""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return "tool-output"


def _crew(mode, client):
    crew = SecureCrew(mode=mode)
    crew.interceptor.client = client
    return crew


def test_allow_runs_tool_and_audits():
    c = FakeClient(verdict=Verdict("allow", "low", "ok", False, "search"))
    crew = _crew("observe", c)
    tool = crew.secure_tool(FakeTool("search"))
    assert tool.run(query="hello") == "tool-output"
    assert tool.calls  # original executed
    actions = [a["action"] for a in c.audits]
    assert "allow" in actions


def test_enforce_block_prevents_tool_execution():
    c = FakeClient(verdict=Verdict("block", "high", "shell", True, "Bash"))
    crew = _crew("enforce", c)
    tool = crew.secure_tool(FakeTool("Bash"))
    with pytest.raises(ToolBlocked):
        tool.run(cmd="rm -rf /")
    assert tool.calls == []  # original NEVER ran
    assert c.audits[-1]["action"] == "block"


def test_observe_block_logs_but_runs():
    c = FakeClient(verdict=Verdict("block", "high", "shell", True, "Bash"))
    crew = _crew("observe", c)
    tool = crew.secure_tool(FakeTool("Bash"))
    assert tool.run(cmd="ls") == "tool-output"  # still runs in observe
    assert c.audits[-1]["action"] == "block"


def test_double_wrap_is_idempotent():
    c = FakeClient()
    crew = _crew("observe", c)
    t = FakeTool("x")
    once = crew.secure_tool(t)
    twice = crew.secure_tool(once)
    assert once is twice
    twice.run()
    # one audit per call, not doubled
    assert len([a for a in c.audits]) == 1
