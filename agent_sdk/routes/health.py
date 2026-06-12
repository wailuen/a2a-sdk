"""Health endpoints (DESIGN.md §7 Overview row).

Unauthenticated liveness probe: deployment platforms and the console's
Overview screen both read it. Returns identity-free metadata only — never
secrets, never per-key usage (those live behind /admin/api/overview).

``GET /agent/health`` is a compatibility alias kept for the reference
agents' probes (pitchbook/m365 deploy configs point there).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


def _payload(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "version": settings.agent_version,
    }


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness: the process is up and app state is wired."""
    return _payload(request)


@router.get("/agent/health")
async def agent_health(request: Request) -> dict[str, str]:
    """Alias of /health (reference-agent probe parity)."""
    return _payload(request)
