"""Provide audit for all requests."""

import datetime
import time
from collections import namedtuple

from fastapi import Request
from starlette import datastructures as s_datas
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from azul_restapi_server.settings import logging as log_config

UnknownPath = namedtuple("UnknownPath", ["path"])


class AuditMiddleware:
    """Provide audit for all requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Continue processing chain with app until we need to log."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive=receive)
        start_time = time.time()
        await self.app(scope, receive, lambda x: self.sender(request, send, start_time, x))

    async def sender(self, request: Request, send: Send, start_time, message: Message):
        """Perform logging of event."""
        await self.log_event(request, start_time, message)
        return await send(message)

    async def log_event(self, request: Request, start_time, message: Message):
        """Audit the request when a response is generated."""
        if message["type"] != "http.response.start":
            # doesn't contain status code
            # we should have already processed the http.response.start message
            return
        if request.url.path in log_config.audit_path_filter:
            return

        duration_s = time.time() - start_time
        duration_ms = duration_s * 1000
        duration_us = duration_ms * 1000

        # Try to find a security label the application has emitted under the
        # "x-azul-security" header
        security_label = "-"

        for name, value in message["headers"]:
            if name == b"x-azul-security":
                security_label = str(value, "UTF-8")
                break

        username = "-"
        if hasattr(request.state, "user_info"):
            username = request.state.user_info.username
        # add the username to the outgoing response
        message["headers"].append((b"X-Username", username.encode()))

        if request.client:
            req_host: s_datas.Address = request.client
        else:
            req_host: s_datas.Address = s_datas.Address(host="localhost", port=5000)
        # define simple, optional vars for format string
        fmt_vars = dict(
            username=username,
            client_ip=req_host.host,
            client_port=req_host.port,
            connection=request.headers.get("connection", "-"),
            method=request.method,
            path=request.url.path,
            # Generic path that doesn't contain any parameters
            generic_path=request.scope.get("root_path", "") + request.scope.get("route", UnknownPath("")).path,
            status_code=message["status"],
            # allow fall back access to header for custom, 'x-' style values
            headers=request.headers,
            user_agent=request.headers.get("user-agent", "-"),
            referer=request.headers.get("referer", "-"),
            time=datetime.datetime.now(tz=datetime.timezone.utc),
            duration_s=duration_s,
            duration_ms=duration_ms,
            duration_us=duration_us,
            security=security_label,
        )

        request.app.audit_logger.info(log_config.audit_format.format(**fmt_vars))
