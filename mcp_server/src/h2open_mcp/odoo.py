"""Minimal client for Odoo's JSON-2 external API (``POST /json/2/<model>/<method>``).

Every call runs as the user who owns the API key, so Odoo applies that user's
access rights and the h2o_* business rules exactly as in the web client.
"""

import os
from dataclasses import dataclass
from typing import Any

import httpx


class OdooError(Exception):
    """An error Odoo returned (access refused, wrong state, bad input, ...)."""


@dataclass
class OdooConfig:
    url: str
    database: str
    api_key: str
    timezone: str = "Europe/Istanbul"
    timeout: float = 60.0

    @classmethod
    def from_env(cls):
        missing = [name for name in ("H2OPEN_URL", "H2OPEN_DB", "H2OPEN_API_KEY") if not os.environ.get(name)]
        if missing:
            raise SystemExit(
                f"Set {', '.join(missing)}: the Odoo URL (e.g. http://localhost:8069), the database name "
                "and an API key (Odoo > Preferences > Account Security > New API Key)."
            )
        return cls(
            url=os.environ["H2OPEN_URL"].rstrip("/"),
            database=os.environ["H2OPEN_DB"],
            api_key=os.environ["H2OPEN_API_KEY"],
            timezone=os.environ.get("H2OPEN_TZ") or cls.timezone,
        )


class Odoo:
    def __init__(self, config: OdooConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self._http = httpx.Client(
            base_url=config.url,
            timeout=config.timeout,
            transport=transport,
            headers={
                "Authorization": f"bearer {config.api_key}",
                "X-Odoo-Database": config.database,
            },
        )

    def call(self, model: str, method: str, ids: list[int] | None = None, **kwargs) -> Any:
        """Call a public model method. ``kwargs`` are its keyword arguments."""
        body = dict(kwargs)
        if ids:
            body["ids"] = list(ids)
        try:
            response = self._http.post(f"/json/2/{model}/{method}", json=body)
        except httpx.HTTPError as exc:
            raise OdooError(f"Cannot reach Odoo at {self.config.url}: {exc}") from exc
        if response.status_code == 200:
            return response.json()
        try:
            error = response.json()
            message = error.get("message") or error.get("name") or response.text
        except ValueError:
            message = response.text.strip() or response.reason_phrase
        if response.status_code == 401:
            message = f"Odoo refused the API key ({message}). Check H2OPEN_API_KEY and H2OPEN_DB."
        raise OdooError(message)

    def search_read(self, model, domain, fields, order=None, limit=None, offset=0):
        kwargs = {"domain": domain, "fields": fields}
        if order:
            kwargs["order"] = order
        if limit:
            kwargs["limit"] = limit
        if offset:
            kwargs["offset"] = offset
        return self.call(model, "search_read", **kwargs)

    def read(self, model, ids, fields):
        if not ids:
            return []
        return self.call(model, "read", ids=ids, fields=fields)

    def search_count(self, model, domain):
        return self.call(model, "search_count", domain=domain)
