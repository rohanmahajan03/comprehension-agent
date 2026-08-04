"""Overrides for the graph_builder G-Eval-style regression suite.

Unlike the rest of the test suite (see tests/conftest.py), these tests exercise the
real graph_builder LLM call end-to-end plus a judge LLM call for concept alignment
(see support.py), so the parent directory's autouse graph_builder stub is disabled
here and real credentials are required.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def stub_graph_builder() -> None:
    """No-op override of tests/conftest.py's autouse stub_graph_builder fixture."""


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")
