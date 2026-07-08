"""Canonical tool-id normalization — the ONLY framework-specific mapping.

The whole SecureVector fleet keys permissions and audit on a single canonical
``tool_id``. CrewAI surfaces a tool's name as ``BaseTool.name`` (passed here as
the flat ``name`` argument). Normalizing it here is the one piece of
CrewAI-specific code; every downstream step (permission resolution, analysis,
audit) is shared engine behaviour, so a policy authored once — "allow
web_search, block shell" — applies identically across LangChain / LangGraph /
CrewAI.

Casing is preserved: the local app matches tool ids case-insensitively, so a
rule authored ``tool_id="Bash"`` still governs a CrewAI tool named ``bash``.

MCP tools commonly surface with a sanitized flat name (``mcp_<server>_<tool>``,
hyphens/dots collapsed to underscores). The sanitization is lossy, so a single
function name cannot be split back into ``server``/``tool`` unambiguously.
``candidate_tool_ids`` therefore emits every plausible ``<server>:<tool>``
split (most-specific first) so rules authored against the cloud
``<server>:<tool>`` form, the bare tool name, or the raw function name all
match — identical behaviour across the sibling SDKs.
"""

from typing import Any, List, Optional

# The audit/Bill-of-Tools/OCSF pipeline groups by this attribution tag.
RUNTIME_KIND = "crewai"

_MCP_PREFIX = "mcp_"


def normalize_tool_id(serialized: Any, name: Optional[str] = None) -> str:
    """Resolve a canonical tool id.

    Accepts a flat ``name`` (CrewAI ``BaseTool.name``) and/or a ``serialized``
    dict (``{"name": ...}`` or a dotted ``{"id": [...]}`` path) for symmetry
    with the other SDKs. Falls back to ``"unknown"`` so a missing name never
    crashes the agent.
    """
    raw: Optional[str] = None
    if isinstance(serialized, dict):
        raw = serialized.get("name")
        if not raw:
            ident = serialized.get("id")
            if isinstance(ident, (list, tuple)) and ident:
                raw = str(ident[-1])
    if not raw:
        raw = name
    if not raw:
        return "unknown"
    return str(raw).strip() or "unknown"


def candidate_tool_ids(tool_id: str) -> List[str]:
    """Expand one tool name into every rule key it should match.

    Ordered most-specific first (the caller resolves tier-first, then takes
    the first candidate that matches within a tier):

    * the raw tool name itself (``mcp_my_api_list_items`` or ``terminal``);
    * for MCP names, every ``<server>:<tool>`` split of the sanitized
      remainder — the cloud policy form. The split point is ambiguous after
      sanitization, so all splits are emitted; the app also aliases the bare
      tool suffix of each ``<server>:<tool>`` key server-side.
    """
    # The caller passes an already-normalized name (normalize_tool_id here
    # takes the framework payload, not a bare string — unlike the hermes SDK).
    tid = str(tool_id or "").strip() or "unknown"
    candidates = [tid]
    if tid.lower().startswith(_MCP_PREFIX):
        rest = tid[len(_MCP_PREFIX):]
        parts = rest.split("_")
        for i in range(1, len(parts)):
            server = "_".join(parts[:i])
            tool = "_".join(parts[i:])
            if server and tool:
                candidates.append(f"{server}:{tool}")
    return candidates
