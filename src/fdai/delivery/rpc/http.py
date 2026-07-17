"""Bounded HTTP route and client for the typed RPC registry."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol
from urllib.parse import urlparse

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.rpc import RpcRegistry, RpcRequest, RpcResponse, RpcScope

_DEFAULT_MAX_BODY_BYTES = 256 * 1024
_DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

RpcAuthorization = Callable[[Request], Awaitable[frozenset[RpcScope]]]


class RpcAuthHeaders(Protocol):
    async def headers(self) -> Mapping[str, str]: ...


class RpcHttpClientError(RuntimeError):
    """Typed RPC client rejected transport or protocol output."""


def make_rpc_route(
    *,
    registry: RpcRegistry,
    authorize: RpcAuthorization,
    path: str = "/rpc",
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
) -> Route:
    """Build an opt-in POST route; callers decide which app and identity own it."""
    if max_body_bytes < 1:
        raise ValueError("RPC route body cap MUST be positive")

    async def endpoint(request: Request) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > max_body_bytes:
                    return _transport_error(413, "request_too_large")
            except ValueError:
                return _transport_error(400, "invalid_content_length")
        body = await request.body()
        if len(body) > max_body_bytes:
            return _transport_error(413, "request_too_large")
        try:
            value = json.loads(body)
            rpc_request = _parse_request(value)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return _transport_error(400, "invalid_request")
        scopes = await authorize(request)
        response = await registry.invoke(rpc_request, scopes=scopes)
        return JSONResponse(response.to_dict())

    return Route(path, endpoint, methods=["POST"])


class RpcHttpClient:
    """Small generated-client target with strict endpoint and response correlation."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: httpx.AsyncClient,
        auth: RpcAuthHeaders,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        _validate_endpoint(endpoint)
        if max_response_bytes < 1:
            raise ValueError("RPC client response cap MUST be positive")
        self._endpoint = endpoint
        self._http = http_client
        self._auth = auth
        self._max_response_bytes = max_response_bytes

    async def invoke(self, request: RpcRequest) -> RpcResponse:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(await self._auth.headers())
        payload = {
            "schema_version": request.schema_version,
            "request_id": request.request_id,
            "method": request.method,
            "params": dict(request.params),
            "idempotency_key": request.idempotency_key,
        }
        try:
            response = await self._http.post(
                self._endpoint,
                headers=headers,
                content=json.dumps(payload),
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise RpcHttpClientError("RPC transport failed") from exc
        if not response.is_success:
            raise RpcHttpClientError(f"RPC transport returned HTTP {response.status_code}")
        if len(response.content) > self._max_response_bytes:
            raise RpcHttpClientError("RPC response exceeds the configured cap")
        try:
            body = response.json()
            return _parse_response(body, expected_request_id=request.request_id)
        except (ValueError, TypeError) as exc:
            raise RpcHttpClientError("RPC response failed protocol validation") from exc


def _parse_request(value: object) -> RpcRequest:
    if not isinstance(value, Mapping):
        raise TypeError("request is not an object")
    params = value.get("params", {})
    if not isinstance(params, Mapping):
        raise TypeError("params is not an object")
    request_id = value.get("request_id")
    method = value.get("method")
    schema_version = value.get("schema_version")
    idempotency_key = value.get("idempotency_key")
    if not isinstance(request_id, str) or not isinstance(method, str):
        raise TypeError("request id and method must be strings")
    if not isinstance(schema_version, str):
        raise TypeError("schema version must be a string")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise TypeError("idempotency key must be a string")
    return RpcRequest(
        request_id=request_id,
        method=method,
        params=dict(params),
        idempotency_key=idempotency_key,
        schema_version=schema_version,
    )


def _parse_response(value: object, *, expected_request_id: str) -> RpcResponse:
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.0.0":
        raise ValueError("invalid response envelope")
    if value.get("request_id") != expected_request_id or not isinstance(value.get("ok"), bool):
        raise ValueError("response correlation failed")
    result = value.get("result", {})
    if not isinstance(result, Mapping):
        raise ValueError("response result is not an object")
    error = value.get("error")
    error_code: str | None = None
    error_message: str | None = None
    if error is not None:
        if not isinstance(error, Mapping):
            raise ValueError("response error is not an object")
        error_code = error.get("code") if isinstance(error.get("code"), str) else None
        error_message = error.get("message") if isinstance(error.get("message"), str) else None
        if error_code is None or error_message is None:
            raise ValueError("response error is incomplete")
    return RpcResponse(
        request_id=expected_request_id,
        ok=bool(value["ok"]),
        result=dict(result),
        error_code=error_code,
        error_message=error_message,
    )


def _transport_error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


def _validate_endpoint(value: str) -> None:
    parsed = urlparse(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("RPC endpoint MUST NOT contain credentials, query, or fragment")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("RPC endpoint MUST be an absolute HTTP(S) URL")
    if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("RPC endpoint MUST use HTTPS outside loopback")


__all__ = [
    "RpcAuthorization",
    "RpcAuthHeaders",
    "RpcHttpClient",
    "RpcHttpClientError",
    "make_rpc_route",
]
