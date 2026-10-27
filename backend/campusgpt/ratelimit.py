"""Rate limits for login and chat (NFR-S5), as FastAPI dependencies.

Moving-window counters from the `limits` library, kept in this process's memory: enough for
the single API process this project runs. A rejected request gets 429 with Retry-After.

The client address is request.client.host. Next.js forwards /api requests without adding
X-Forwarded-For (self-hosted, it does not know the client's address) but passes one from the
browser through unchanged, so `make api` trusts no forwarded headers: locally every browser
is 127.0.0.1 and the per-IP limits act as one global limit, which nobody can dodge by
sending their own header. Deployed behind nginx/Caddy, which append the real address, the
API trusts that proxy and the limits apply per client (see the Makefile). The per-account
and per-user limits do not depend on addresses.
"""
import math
import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from campusgpt.auth import CurrentUser, current_user
from campusgpt.config import get_settings

_limiter = MovingWindowRateLimiter(MemoryStorage())


def reset() -> None:
    """Forget every counter (tests)."""
    _limiter.storage.reset()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def too_many(retry_after: int, message: str = "Too many requests") -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                         f"{message}. Try again in {retry_after} s.",
                         headers={"Retry-After": str(retry_after)})


def check(scope: str, setting: str, key: str) -> None:
    """Count one request for `key` against the limit named by `setting` (e.g. "10/minute")."""
    rule = parse(getattr(get_settings(), setting))
    if not _limiter.hit(rule, scope, key):
        reset_at = _limiter.get_window_stats(rule, scope, key).reset_time
        raise too_many(max(1, math.ceil(reset_at - time.time())))


def per_ip(scope: str, setting: str) -> Callable:
    async def dependency(request: Request) -> None:
        check(scope, setting, client_ip(request))
    return dependency


def per_user(scope: str, setting: str) -> Callable:
    async def dependency(user: CurrentUser = Depends(current_user)) -> None:
        check(scope, setting, str(user.id))
    return dependency
