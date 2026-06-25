# SecureVector SDK for CrewAI

[![PyPI](https://img.shields.io/pypi/v/securevector-sdk-crewai)](https://pypi.org/project/securevector-sdk-crewai/)
[![Downloads](https://img.shields.io/pypi/dm/securevector-sdk-crewai)](https://pypistats.org/packages/securevector-sdk-crewai)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://pypi.org/project/securevector-sdk-crewai/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

> Bring the SecureVector local threat monitor's three controls — **tool-call
> permissions**, **secret / data-leak detection**, and **threat detection** —
> to every CrewAI tool call, with tamper-evident audit logging.

```bash
pip install securevector-sdk-crewai
```

> 📦 **One install — batteries included.** `pip install securevector-sdk-crewai`
> **also installs the local SecureVector app** (`securevector-ai-monitor`): the
> adapter **and** the detection engine + tamper-evident audit chain arrive in a
> single `pip install`. The SDK is a thin interception layer — **the app must be
> running locally** (`securevector-app --web`) for it to do anything.

> 🌐 **Pointing at your own cloud? Use the lightweight install.** If you've deployed
> SecureVector to your own cloud, you don't need the bundled
> local app. Install **only the adapter** on the machine where your agents run, and
> point it at your deployment:
>
> ```bash
> # lightweight — adapter only, no local app (your env already has crewai)
> pip install securevector-sdk-crewai --no-deps
>
> # point at your SecureVector endpoint
> export SECUREVECTOR_SDK_APP_URL=https://<your-securevector-endpoint>
> export SECUREVECTOR_API_KEY=<token>
> ```
> The adapter then forwards every tool call to your remote deployment instead of a
> local app. The default `pip install securevector-sdk-crewai` (no `--no-deps`)
> still bundles the app for local use.

## Quick start

Wrap your tools (recommended — robust across CrewAI versions):

```python
from securevector_sdk_crewai import secure_tools

agent = Agent(tools=secure_tools(my_tools), ...)
```

or install globally (best-effort monkeypatch of CrewAI's `BaseTool`):

```python
from securevector_sdk_crewai import install

install(mode="observe")
```

or fully zero-config:

```python
import securevector_sdk_crewai.auto   # reads env, installs globally
```

## What happens on every tool call

Before a tool runs, the SDK:

1. **(a) Permissions** — resolves an allow/block verdict for the tool, using the
   app's own precedence: cloud-pushed **synced** policy → local **override** →
   **essential** registry → default-allow.
2. **(b)+(c) Secret & threat scan** — sends the serialized tool input through the
   app's `/analyze` pipeline.

After the tool returns, the result is scanned the same way to catch secrets /
exfiltration in tool output. Every decision is written to the app's audit chain
tagged `runtime_kind="crewai"`.

## observe vs enforce

| | local app reachable | local app unreachable |
|---|---|---|
| **observe** (default) | log + advisory verdict; tool always runs | tool runs (fail-open) |
| **enforce** (opt-in) | tool runs only if the verdict ≠ block | **tool denied** (fail-closed) |

```python
install(mode="enforce")   # blocks denied tools and fails closed if the app is down
```

In enforce mode a denied tool raises `ToolBlocked` before it executes; enforce
also prints a one-time disclosure to stderr.

## Configuration

All optional, via env or kwargs:

| Env var | Default | Meaning |
|---|---|---|
| `SECUREVECTOR_SDK_APP_URL` | `http://127.0.0.1:8741` | local app base URL |
| `SECUREVECTOR_SDK_MODE` | `observe` | `observe` or `enforce` |
| `SECUREVECTOR_SDK_TIMEOUT_MS` | `3000` | per-call verdict timeout |
| `SECUREVECTOR_SDK_RISK_THRESHOLD` | `70` | risk score that blocks in enforce mode |
| `SECUREVECTOR_SDK_DISABLED` | _(unset)_ | set truthy to no-op |

## Compliance

The tool-call-level, attributed, tamper-evident audit trail this produces is
exactly the **action-layer logging** auditors ask for under **EU AI Act
Art. 12 / 15**. This SDK produces the local evidence; the cloud governance
surface turns it into an auditor-ready pack.

## Trademarks

**SecureVector** is the product name of this SDK. **CrewAI** is a trademark of
CrewAI, Inc. This is an independent, community SDK that *integrates with*
CrewAI via its public tool API. It is **not affiliated with, sponsored by, or
endorsed by CrewAI, Inc.** The name uses "crewai" only descriptively, to
identify the framework this package works with (nominative fair use).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
