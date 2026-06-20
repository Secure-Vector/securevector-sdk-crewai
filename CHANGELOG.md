# Changelog

All notable changes to `securevector-sdk-crewai` are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

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
