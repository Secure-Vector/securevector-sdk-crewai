"""Zero-config global install: ``import securevector_sdk_crewai.auto``.

Reads ``SECUREVECTOR_SDK_MODE`` (default ``observe``) from the environment and
monkeypatches CrewAI's BaseTool so every tool call in the process is
instrumented with no per-tool wiring. All other settings come from the same
environment variables documented in :mod:`securevector_sdk_crewai.config`.
"""

import os

from . import install

install(mode=os.environ.get("SECUREVECTOR_SDK_MODE", "observe"), register_global=True)
