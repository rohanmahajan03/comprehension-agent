"""Overrides for the question_generator regression suite.

Unlike the rest of the test suite (see tests/conftest.py), these tests exercise the
real question_generator LLM call end-to-end (no judge model needed — see support.py
docstring for why), so the parent directory's autouse question_generator stub is
disabled here and real credentials are required.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def stub_question_generator() -> None:
    """No-op override of tests/conftest.py's autouse stub_question_generator fixture."""


@pytest.fixture(autouse=True)
def _require_llm_credentials() -> None:
    if not get_settings().llm_api_key:
        pytest.skip("LLM_API_KEY not set — this suite makes real Anthropic API calls")
