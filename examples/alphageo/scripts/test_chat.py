"""Convenience shim — delegates to ``python -m agent_sdk test-chat``.

Prefer the SDK command directly:

    python -m agent_sdk test-chat --app src.main:app \
        --catalog urn:alphageo:climate:v1 \
        "What is the climate risk for NYC in 2050?"

This script exists only to keep the example self-contained for contributors
who discover it before reading the SDK docs.
"""

import sys
from pathlib import Path

# Ensure the SDK root is importable when running from the example dir.
_SDK_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

from agent_sdk.__main__ import main  # noqa: E402

# Inject the alphageo-specific defaults so the shim is zero-config.
_argv = sys.argv[1:]
if not any(a.startswith("--app") or a == "--url" for a in _argv):
    _argv = ["--app", "src.main:app"] + _argv
if "--catalog" not in _argv:
    _argv = ["--catalog", "urn:alphageo:climate:v1"] + _argv

sys.exit(main(["test-chat"] + _argv))
