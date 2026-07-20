from __future__ import annotations

import asyncio
import unittest

from starlette.requests import Request
from starlette.responses import Response

from backend.main import cache_headers


def request_for(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
        }
    )


class HttpMiddlewareTests(unittest.TestCase):
    def test_hashed_static_assets_receive_immutable_cache_header(self) -> None:
        async def next_response(_request: Request) -> Response:
            return Response(b"asset", status_code=200)

        response = asyncio.run(cache_headers(request_for("/assets/app-abc123.js"), next_response))
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")

    def test_api_responses_are_not_cached(self) -> None:
        async def next_response(_request: Request) -> Response:
            return Response(b"{}", status_code=200, media_type="application/json")

        response = asyncio.run(cache_headers(request_for("/api/health"), next_response))
        self.assertEqual(response.headers["cache-control"], "no-store")


if __name__ == "__main__":
    unittest.main()
