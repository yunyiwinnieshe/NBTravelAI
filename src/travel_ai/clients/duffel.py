"""Authenticated HTTP client for Duffel's flight offer API."""

import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from travel_ai.schemas.flights import CabinClass


class DuffelError(RuntimeError):
    """Base error for controlled Duffel integration failures."""


class DuffelConfigurationError(DuffelError):
    """Raised when required Duffel configuration is unavailable or invalid."""


class DuffelAuthenticationError(DuffelError):
    """Raised when Duffel rejects the configured access token."""


class DuffelRateLimitError(DuffelError):
    """Raised when Duffel rate-limits a flight search."""


class DuffelApiError(DuffelError):
    """Raised for transport failures and other unsuccessful Duffel responses."""


class DuffelResponseError(DuffelError):
    """Raised when Duffel returns a response that cannot be interpreted."""


@dataclass(frozen=True)
class DuffelSettings:
    """Runtime configuration for the Duffel sandbox client."""

    access_token: str
    base_url: str = "https://api.duffel.com"
    supplier_timeout_ms: int = 10_000
    request_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not self.access_token.strip():
            raise DuffelConfigurationError("DUFFEL_ACCESS_TOKEN is required")
        if not self.access_token.startswith("duffel_test_"):
            raise DuffelConfigurationError(
                "Travel AI accepts only Duffel test-mode access tokens"
            )
        if not 2_000 <= self.supplier_timeout_ms <= 60_000:
            raise DuffelConfigurationError(
                "DUFFEL_SUPPLIER_TIMEOUT_MS must be between 2000 and 60000"
            )
        if self.request_timeout_seconds <= 0:
            raise DuffelConfigurationError("request timeout must be positive")

    @classmethod
    def from_environment(cls) -> "DuffelSettings":
        """Load Duffel settings without placing secrets in application code."""
        raw_supplier_timeout = os.getenv("DUFFEL_SUPPLIER_TIMEOUT_MS", "10000")
        try:
            supplier_timeout_ms = int(raw_supplier_timeout)
        except ValueError as error:
            raise DuffelConfigurationError(
                "DUFFEL_SUPPLIER_TIMEOUT_MS must be an integer"
            ) from error

        return cls(
            access_token=os.getenv("DUFFEL_ACCESS_TOKEN", ""),
            base_url=os.getenv("DUFFEL_BASE_URL", "https://api.duffel.com"),
            supplier_timeout_ms=supplier_timeout_ms,
        )


class DuffelClient:
    """Create Duffel offer requests without exposing authentication to callers."""

    def __init__(
        self,
        settings: DuffelSettings,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        )

    def close(self) -> None:
        """Close the internally created HTTP client, when present."""
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> "DuffelClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def create_offer_request(
        self,
        *,
        origin_airport_code: str,
        destination_airport_code: str,
        departure_date: date,
        return_date: date,
        cabin_class: CabinClass,
    ) -> dict[str, Any]:
        """Search for one adult's round trip between one airport pair."""
        payload = {
            "data": {
                "cabin_class": cabin_class.value,
                "slices": [
                    {
                        "origin": origin_airport_code,
                        "destination": destination_airport_code,
                        "departure_date": departure_date.isoformat(),
                    },
                    {
                        "origin": destination_airport_code,
                        "destination": origin_airport_code,
                        "departure_date": return_date.isoformat(),
                    },
                ],
                "passengers": [{"type": "adult"}],
            }
        }
        headers = {
            "Authorization": f"Bearer {self._settings.access_token}",
            "Duffel-Version": "v2",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json",
        }

        try:
            response = self._http_client.post(
                "/air/offer_requests",
                params={
                    "return_offers": "true",
                    "supplier_timeout": self._settings.supplier_timeout_ms,
                },
                headers=headers,
                json=payload,
            )
        except httpx.TimeoutException as error:
            raise DuffelApiError("Duffel flight search timed out") from error
        except httpx.RequestError as error:
            raise DuffelApiError(
                "Duffel flight search could not be completed"
            ) from error

        request_id = response.headers.get("x-request-id", "unknown")
        if response.status_code in {401, 403}:
            raise DuffelAuthenticationError(
                f"Duffel authentication failed; request_id={request_id}"
            )
        if response.status_code == 429:
            raise DuffelRateLimitError(
                f"Duffel rate limit exceeded; request_id={request_id}"
            )
        if response.is_error:
            raise DuffelApiError(
                f"Duffel returned HTTP {response.status_code}; request_id={request_id}"
            )

        try:
            body = response.json()
        except ValueError as error:
            raise DuffelResponseError("Duffel returned invalid JSON") from error
        if not isinstance(body, dict):
            raise DuffelResponseError("Duffel response must be a JSON object")
        return body
