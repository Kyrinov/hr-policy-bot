from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

ORCHESTRATOR_UPSTREAM = os.environ.get(
    "ORCHESTRATOR_OLLAMA_UPSTREAM", "http://127.0.0.1:11436"
).rstrip("/")
SPECIALIST_UPSTREAM = os.environ.get(
    "SPECIALIST_OLLAMA_UPSTREAM", "http://127.0.0.1:11435"
).rstrip("/")

UPSTREAMS = {
    "orchestrator": ORCHESTRATOR_UPSTREAM,
    "specialist": SPECIALIST_UPSTREAM,
}

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
}

app = FastAPI(title="AGX Ollama ngrok Proxy")
client = httpx.AsyncClient(timeout=None, follow_redirects=True)


def _filtered_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _upstream_url(role: str, path: str, query: str) -> str:
    upstream = UPSTREAMS.get(role)
    if upstream is None:
        raise HTTPException(status_code=404, detail=f"Unknown Ollama role: {role}")

    url = f"{upstream}/{path.lstrip('/')}" if path else upstream
    if query:
        url = f"{url}?{query}"
    return url


async def _proxy(role: str, path: str, request: Request) -> StreamingResponse:
    url = _upstream_url(role, path, request.url.query)
    upstream_request = client.build_request(
        request.method,
        url,
        headers=_filtered_headers(request.headers),
        content=request.stream(),
    )
    upstream_response = await client.send(upstream_request, stream=True)
    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=_filtered_headers(upstream_response.headers),
        background=BackgroundTask(upstream_response.aclose),
    )


@app.get("/health")
async def health() -> dict[str, object]:
    results: dict[str, object] = {}
    for role, upstream in UPSTREAMS.items():
        try:
            response = await client.get(f"{upstream}/api/tags", timeout=10.0)
            results[role] = {
                "status": "ok" if response.status_code == 200 else "error",
                "upstream": upstream,
                "status_code": response.status_code,
            }
        except httpx.HTTPError as exc:
            results[role] = {
                "status": "error",
                "upstream": upstream,
                "error": str(exc),
            }

    status = "ok" if all(r.get("status") == "ok" for r in results.values()) else "error"
    return {"status": status, "upstreams": results}


@app.api_route(
    "/{role}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_role_root(role: str, request: Request) -> StreamingResponse:
    return await _proxy(role, "", request)


@app.api_route(
    "/{role}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_role_path(role: str, path: str, request: Request) -> StreamingResponse:
    return await _proxy(role, path, request)


@app.on_event("shutdown")
async def shutdown() -> None:
    await client.aclose()
