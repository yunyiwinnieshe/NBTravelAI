"""Keep automated tests offline regardless of developer provider settings."""

import pytest


@pytest.fixture(autouse=True)
def offline_extraction_environment(monkeypatch):
    monkeypatch.setenv("EXTRACTION_PROVIDER", "fixture")
    monkeypatch.setenv("FLIGHT_PROVIDER", "fixture")
    monkeypatch.setenv("ORIGIN_RESOLUTION_PROVIDER", "fixture")
    monkeypatch.setenv("ALLOW_EXAMPLE_FLIGHT_RESULTS", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MAX_RETRIES", raising=False)
    monkeypatch.delenv("DEEPSEEK_TOTAL_TIMEOUT_SECONDS", raising=False)
