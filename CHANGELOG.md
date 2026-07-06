# Changelog

All notable changes to `securevector-sdk-crewai` are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [1.2.0]

### Added
- **LLM cost tracking** (story #185): the SDK now captures crew LLM token usage
  and posts it to the local app's Cost Tracking (`POST /api/costs/track`), so
  CrewAI agents appear in the dollar-based cost dashboard alongside proxy
  agents and respect per-agent budgets.
  - `install()` / `import securevector_sdk_crewai.auto` additionally patch
    `Crew.kickoff` so every run posts its `crew.usage_metrics` delta
    automatically.
  - `track_crew_usage(crew, agent_id=...)` — explicit capture after
    `kickoff()` for tool-only (`secure_tools`) integrations.
  - Provider + model-id normalization mirrors the app's pricing table
    (`provider/model_id` exact match), including litellm-style
    `provider/model` strings and versioned-model aliases, so dollar cost
    resolves instead of landing as `pricing_known=false`.
  - Attribution: records post as `agent_id` `"crewai-agent"` by default;
    override via `track_crew_usage(agent_id=...)` or
    `SECUREVECTOR_SDK_AGENT_ID`.
  - Best-effort like audit forwarding: an unreachable app or unknown model
    never breaks the crew.

## [1.1.0]

### Added
- **Unified engine endpoint** (#190): point the SDK at the local app or a
  self-hosted deployment via `SECUREVECTOR_ENGINE_ENDPOINT`. Legacy
  `SECUREVECTOR_SDK_APP_URL` continues to work as a fallback.

## [1.0.0]

### Added
- Initial CrewAI adapter (Phase 2 of the SecureVector SDK roadmap, story #174).
- A tool wrapper (`secure_tools` / `secure_tool`) and a best-effort global
  monkeypatch (`install`) of CrewAI's `BaseTool.run` (resolved via the
  documented `from crewai.tools import BaseTool` import) that run the three
  controls on every tool call:
  - **(a)** tool-call permission resolution (synced → override → essential → default-allow),
  - **(b)** secret / data-leak detection on tool input and output,
  - **(c)** threat detection on tool input and output.
- `import securevector_sdk_crewai.auto` for zero-config global setup.
- `observe` (fail-open, default) and `enforce` (fail-closed) modes — in enforce
  mode a denied tool raises `ToolBlocked` before it executes.
- Audit forwarding to the local app's tamper-evident chain with
  `runtime_kind="crewai"` attribution.
- CI + Test PyPI (develop) / PyPI (main release) publishing via OIDC trusted
  publishing, mirroring `securevector-guardian-model`.
