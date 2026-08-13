"""Punto de entrada del monolito: la API y el frontend compilado en un proceso."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1 import api_router
from app.core.config import settings
from app.core.errors import registrar_manejadores

logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Arranque y apagado ordenado del proceso."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info("%s arrancando en modo %s", settings.app_name, settings.app_env)
    yield
    from app.db.session import dispose_engine

    await dispose_engine()
    logger.info("Conexiones cerradas. Adiós.")


app = FastAPI(
    title=settings.app_name,
    description="API del gestor de presupuesto personal.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

registrar_manejadores(app)

# Comprime las respuestas grandes (informes y listados largos).
app.add_middleware(GZipMiddleware, minimum_size=1000)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # imprescindible: la sesión va en cookies
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "X-CSRF-Token"],
        max_age=600,
    )


@app.middleware("http")
async def cabeceras_de_seguridad(peticion: Request, siguiente) -> Response:  # noqa: ANN001
    """Cabeceras de endurecimiento en todas las respuestas."""
    respuesta = await siguiente(peticion)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    respuesta.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.is_production:
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta


@app.get("/api/health", tags=["sistema"], summary="Comprobación de vida")
async def health() -> dict[str, str]:
    """Usado por el healthcheck de Docker y por EasyPanel."""
    return {"estado": "ok", "app": settings.app_name, "entorno": settings.app_env}


app.include_router(api_router, prefix=settings.api_prefix)


# --- Frontend compilado -----------------------------------------------------
# En producción el mismo proceso sirve la SPA. Los assets con hash se cachean
# de forma agresiva; index.html nunca, para que un despliegue se vea al instante.
if settings.static_dir.is_dir():
    assets = settings.static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    indice = settings.static_dir / "index.html"

    @app.get("/{ruta_completa:path}", include_in_schema=False)
    async def servir_spa(ruta_completa: str) -> Response:
        """Devuelve el fichero pedido si existe; si no, index.html.

        El enrutado de Vue es del lado del cliente: cualquier ruta desconocida
        tiene que llegar a index.html para que el router decida.
        """
        if ruta_completa.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "codigo": "no_encontrado",
                        "mensaje": "Este endpoint no existe.",
                        "detalles": [],
                    }
                },
            )

        candidato = (settings.static_dir / ruta_completa).resolve()
        raiz = settings.static_dir.resolve()
        # Comprobación de traversal: candidato tiene que seguir dentro de la raíz.
        if candidato.is_file() and raiz in candidato.parents:
            return FileResponse(candidato)
        return FileResponse(indice, headers={"Cache-Control": "no-cache"})
else:
    logger.warning(
        "No existe el directorio de estáticos (%s): solo se sirve la API. "
        "En desarrollo esto es normal.",
        settings.static_dir,
    )
