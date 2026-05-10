"""
IP 白名单中间件

允许以下 IP 访问：
- localhost (127.0.0.1)
- 本机其他地址 (::1)
- 100.66.1.0/24 网段

所有其他 IP 返回 403 Forbidden。
"""

import ipaddress
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


ALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("100.66.1.0/24"),
]


class IPSubnetMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = self._get_client_ip(request)

        if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        if not self._is_ip_allowed(client_ip):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": f"Access denied: {client_ip} is not in the allowed network. "
                    f"Allowed networks: 127.0.0.1, ::1, 100.66.1.*"
                },
            )

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            return ip

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"

    def _is_ip_allowed(self, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
            for network in ALLOWED_NETWORKS:
                if ip in network:
                    return True
            return False
        except ValueError:
            return False


def is_request_from_localhost(request: Request) -> bool:
    if not request.client:
        return False
    client_host = request.client.host
    return client_host in ("127.0.0.1", "::1", "localhost")
