"""Pytest fixtures for the database-blocking-locks test suite.

The ``BlockingLocksHarness`` class lives inside an SSM YAML heredoc at
``database-blocking-locks/database-blocking-locks-automation.yaml``. To exercise
the class from pytest, this conftest extracts the Python source out of the
heredoc, dedents it, stubs the ``boto3`` import (so the harness module loads in
environments without ``boto3`` installed), and execs the source into a fresh
module namespace.

The resulting module is exposed via the ``harness_module`` fixture (session
scoped — extracting and execing the source once per test session is cheap and
keeps individual tests fast).
"""

from __future__ import annotations

import os
import sys
import textwrap
import types
from typing import Iterator

import pytest


_HERE = os.path.dirname(os.path.abspath(__file__))
_AUTOMATION_YAML = os.path.normpath(
    os.path.join(_HERE, os.pardir, "database-blocking-locks-automation.yaml")
)
_HEREDOC_OPEN = "cat > /tmp/blocking_locks_harness.py << 'PYTHON_EOF'"
_HEREDOC_CLOSE = "PYTHON_EOF"


def _extract_harness_source(yaml_path: str) -> str:
    """Read the SSM YAML and return the dedented Python source from the heredoc.

    Looks for the line that opens the heredoc (``cat > ... << 'PYTHON_EOF'``)
    and the matching closing ``PYTHON_EOF`` line, then returns everything in
    between with the YAML's leading indentation stripped.
    """
    with open(yaml_path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    open_idx: int | None = None
    close_idx: int | None = None
    for idx, line in enumerate(lines):
        if open_idx is None and _HEREDOC_OPEN in line:
            open_idx = idx
            continue
        if open_idx is not None and line.strip() == _HEREDOC_CLOSE:
            close_idx = idx
            break

    if open_idx is None or close_idx is None:
        raise RuntimeError(
            "Could not locate the harness heredoc in %s "
            "(open=%r close=%r)" % (yaml_path, open_idx, close_idx)
        )

    body_lines = lines[open_idx + 1:close_idx]
    return textwrap.dedent("".join(body_lines))


def _install_boto3_stub() -> None:
    """Insert a minimal stub ``boto3`` module into ``sys.modules`` if needed.

    The harness imports ``boto3`` at module-load time but only calls
    ``boto3.client('secretsmanager')`` inside its ``_resolve_password`` helper.
    The dispatch tests never reach that helper, so a do-nothing stub is
    sufficient.
    """
    if "boto3" in sys.modules:
        return
    stub = types.ModuleType("boto3")

    def _client(*_args, **_kwargs):  # pragma: no cover - safety net
        raise RuntimeError(
            "boto3 stub: client() called from a test that should not reach "
            "AWS. If you need real boto3 behaviour, install boto3 in the "
            "test environment."
        )

    stub.client = _client  # type: ignore[attr-defined]
    sys.modules["boto3"] = stub


@pytest.fixture(scope="session")
def harness_module() -> Iterator[types.ModuleType]:
    """Return the harness module loaded from the SSM YAML heredoc.

    The module exposes ``BlockingLocksHarness``, ``DEFAULT_SYNTHETIC_TABLE``,
    ``is_real_mode``, and the rest of the harness's public surface.
    """
    _install_boto3_stub()
    source = _extract_harness_source(_AUTOMATION_YAML)
    module = types.ModuleType("blocking_locks_harness")
    module.__file__ = _AUTOMATION_YAML  # for nicer tracebacks
    code = compile(source, _AUTOMATION_YAML, "exec")
    exec(code, module.__dict__)
    sys.modules["blocking_locks_harness"] = module
    try:
        yield module
    finally:
        sys.modules.pop("blocking_locks_harness", None)
