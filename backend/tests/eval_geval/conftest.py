"""Overrides for the G-Eval regression suite.

Unlike the rest of the test suite (see tests/conftest.py), these tests
exercise the real evaluator LLM call end-to-end and score its output with a
real judge LLM, so the parent directory's autouse evaluator stub is disabled
here and real credentials are required.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def stub_evaluator() -> None:
    """No-op override of tests/conftest.py's autouse stub_evaluator fixture."""


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")
