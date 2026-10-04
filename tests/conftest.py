"""Never inherit the developer's live extraction selection in automated tests."""

import pytest


@pytest.fixture(autouse=True)
def offline_extraction_environment(monkeypatch):
    monkeypatch.setenv("EXTRACTION_PROVIDER", "fixture")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MAX_RETRIES", raising=False)
    monkeypatch.delenv("DEEPSEEK_TOTAL_TIMEOUT_SECONDS", raising=False)
