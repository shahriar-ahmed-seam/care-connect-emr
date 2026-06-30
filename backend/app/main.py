"""Care-Connect-EMR FastAPI application entry point.

Creates the FastAPI app, installs the consistent error-envelope handlers and
CORS, and exposes a ``/health`` liveness endpoint. Domain routers (auth, RBAC,
appointments, EMR, signaling, etc.) are mounted under the versioned API prefix
in later tasks.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.errors import register_error_handlers

def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains; preload"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    register_error_handlers(app)

    from app.api.admin import router as admin_router
    from app.api.appointments import router as appointments_router
    from app.api.auth import router as auth_router
    from app.api.dashboard import router as dashboard_router
    from app.api.doctors import router as doctors_router
    from app.api.emr import router as emr_router
    from app.api.notifications import router as notifications_router
    from app.api.prescriptions import router as prescriptions_router
    from app.api.signaling import router as signaling_router

    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(admin_router, prefix=settings.api_v1_prefix)
    app.include_router(doctors_router, prefix=settings.api_v1_prefix)
    app.include_router(appointments_router, prefix=settings.api_v1_prefix)
    app.include_router(emr_router, prefix=settings.api_v1_prefix)
    app.include_router(prescriptions_router, prefix=settings.api_v1_prefix)
    app.include_router(notifications_router, prefix=settings.api_v1_prefix)
    app.include_router(dashboard_router, prefix=settings.api_v1_prefix)
    app.include_router(signaling_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness probe used by Render and uptime checks."""
        return {"status": "ok", "service": settings.app_name}

    return app

app = create_app()
