"""Bounded, read-only IBKR Flex Web Service v3 requests."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

import requests

FLEX_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
MAX_STATEMENT_BYTES = 10 * 1024 * 1024
RETRYABLE_CODES = {"1001", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1018", "1019", "1021"}


class FlexServiceError(RuntimeError):
    """Safe to expose to users: never includes a URL, token, or broker response."""


class FlexClient:
    def __init__(self, token: str, query_id: str, *, session=None, sleep: Callable[[float], None] = time.sleep):
        if not token or not query_id:
            raise FlexServiceError("IBKR Flex token and query ID are not configured.")
        self._token = token
        self._query_id = query_id
        self._session = session or requests.Session()
        self._sleep = sleep

    def _get(self, endpoint: str, query: str) -> bytes:
        try:
            with self._session.get(
                f"{FLEX_URL}/{endpoint}",
                params={"t": self._token, "q": query, "v": "3"},
                headers={"User-Agent": "Talisman-Flex/1.0"},
                timeout=(10, 45),
                stream=True,
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise FlexServiceError(f"IBKR Flex returned HTTP {response.status_code}.")
                parts = []
                size = 0
                for part in response.iter_content(65536):
                    size += len(part)
                    if size > MAX_STATEMENT_BYTES:
                        raise FlexServiceError("IBKR Flex response exceeds 10 MiB.")
                    parts.append(part)
                return b"".join(parts)
        except requests.RequestException:
            raise FlexServiceError("Unable to reach IBKR Flex Web Service.") from None

    def _request(self, endpoint: str, query: str) -> tuple[bytes, ET.Element]:
        for attempt in range(6):
            payload = self._get(endpoint, query)
            if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                raise FlexServiceError("IBKR Flex returned an unsafe XML response.")
            try:
                root = ET.fromstring(payload)
            except ET.ParseError:
                raise FlexServiceError("IBKR Flex returned invalid XML.") from None
            if root.tag == "FlexQueryResponse" or root.findtext("Status") == "Success":
                return payload, root
            code = root.findtext("ErrorCode") or "unknown"
            if code in RETRYABLE_CODES and attempt < 5:
                # Stay below IBKR's 10 requests/minute/token pacing limit.
                self._sleep(10)
                continue
            safe_code = code if code.isdigit() else "unknown"
            raise FlexServiceError(
                f"IBKR Flex request failed (code {safe_code}). Check token, query and statement availability."
            )
        raise FlexServiceError("IBKR Flex statement generation timed out.")

    def fetch_statement(self) -> bytes:
        try:
            _, response = self._request("SendRequest", self._query_id)
            reference = response.findtext("ReferenceCode")
            if not reference or not reference.isdigit():
                raise FlexServiceError("IBKR Flex did not return a valid statement reference.")
            self._sleep(10)
            # The broker-provided URL is deliberately ignored; credentials only go to our fixed IBKR host.
            statement, _ = self._request("GetStatement", reference)
            return statement
        finally:
            self._session.close()
