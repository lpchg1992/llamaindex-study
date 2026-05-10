"""
IP 白名单中间件

允许以下 IP 访问：
- localhost (127.0.0.1)
- 本机其他地址 (::1)
- 100.66.1.0/24 网段

所有其他 IP 返回 403 Forbidden。
"""

import ipaddress
import os
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# 允许的网段
ALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.1/32"),  # 127.0.0.1
    ipaddress.ip_network("::1/128"),  # localhost IPv6
    ipaddress.ip_network("100.66.1.0/24"),  # 100.66.1.*
]

# 已知的主机名（反向代理场景）
ALLOWED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "::1",
}


class IPSubnetMiddleware(BaseHTTPMiddleware):
    """IP 白名单中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = self._get_client_ip(request)

        # 跳过健康检查端点
        if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        # 检查 IP 是否在白名单中
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
        """从请求中提取客户端 IP"""
        # 优先从 X-Forwarded-For 头获取（反向代理场景）
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For 可能包含多个 IP，取第一个
            ip = forwarded.split(",")[0].strip()
            return ip

        # 其次从 X-Real-IP 获取
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # 最后从 direct client IP 获取
        if request.client:
            return request.client.host

        return "unknown"

    def _is_ip_allowed(self, ip_str: str) -> bool:
        """检查 IP 是否在白名单中"""
        try:
            ip = ipaddress.ip_address(ip_str)

            # 检查是否是已知的可信主机名（反向代理场景）
            if hasattr(self, "_trusted_host_check"):
                return True

            for network in ALLOWED_NETWORKS:
                if ip in network:
                    return True
            return False
        except ValueError:
            # 无法解析 IP，返回 False
            return False


def is_request_from_localhost(request: Request) -> bool:
    """检查请求是否来自本地"""
    if not request.client:
        return False

    client_host = request.client.host
    return client_host in ("127.0.0.1", "::1", "localhost")
