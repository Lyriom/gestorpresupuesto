"""Punto de entrada del monolito: la API y el frontend compilado en un proceso."""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
from app.services import formato

logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("app")

# La tabla de tipos MIME de Python no conoce `.webmanifest`, así que el manifiesto
# de la PWA saldría como `text/plain` y el navegador no lo aceptaría para instalar
# la aplicación. Se registra aquí, antes de montar los estáticos.
mimetypes.add_type("application/manifest+json", ".webmanifest")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Arranque y apagado ordenado del proceso."""
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    # Los textos que redacta el servidor (avisos del presupuesto, alertas de
    # precio) llevan el símbolo de la moneda. `services/` no importa la
    # configuración por norma, así que se le pasa aquí, una vez.
    formato.fijar_moneda(settings.default_currency)
    logger.info(
        "%s arrancando en modo %s (%s, %s)",
        settings.app_name,
        settings.app_env,
        settings.default_currency,
        settings.default_locale,
    )
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


# Política de contenido. El frontend se sirve del mismo origen y no carga nada de
# fuera, así que todo puede quedarse en `self`. Se permite `data:` en imágenes por
# los iconos incrustados, y `unsafe-inline` en estilos porque Vue aplica estilos
# calculados en línea; los scripts NO lo llevan, que es lo que de verdad frena un
# XSS. `frame-ancestors 'none'` es la versión moderna de X-Frame-Options.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# La documentación interactiva de la API carga Swagger UI de un CDN, así que con
# la política general no funcionaría. Se le da la suya, más laxa pero acotada a
# esas dos rutas, en lugar de abrir la de toda la aplicación.
CSP_DOCUMENTACION = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "worker-src 'self' blob:"
)

RUTAS_DE_DOCUMENTACION = frozenset({"/api/docs", "/api/openapi.json"})

# Vite pone el hash del contenido en el nombre de cada asset, así que un fichero de
# `/assets/` nunca cambia: cachearlo un año ahorra la mitad de las peticiones de una
# recarga. Los demás estáticos (`index.html`, `sw.js`, el manifiesto, los iconos)
# conservan su nombre entre despliegues, y ahí una caché larga es justo lo contrario
# de lo que se quiere: dejaría al usuario con la versión anterior sin saberlo.
CACHE_INMUTABLE = "public, max-age=31536000, immutable"
CACHE_REVALIDAR = "no-cache"


@app.middleware("http")
async def cabeceras_de_seguridad(peticion: Request, siguiente) -> Response:  # noqa: ANN001
    """Cabeceras de endurecimiento en todas las respuestas."""
    respuesta = await siguiente(peticion)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "same-origin"
    respuesta.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    respuesta.headers["Content-Security-Policy"] = (
        CSP_DOCUMENTACION if peticion.url.path in RUTAS_DE_DOCUMENTACION else CSP
    )
    if settings.is_production:
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if peticion.url.path.startswith("/assets/"):
        respuesta.headers["Cache-Control"] = CACHE_INMUTABLE
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

    # HEAD además de GET: los monitores de disponibilidad piden la portada con
    # HEAD para no descargarla entera, y un 405 les parece que el sitio está caído.
    @app.api_route("/{ruta_completa:path}", methods=["GET", "HEAD"], include_in_schema=False)
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
            # Estos ficheros mantienen el nombre entre despliegues, así que se
            # revalidan siempre. Importa sobre todo en `sw.js`: un service worker
            # servido de la caché deja al usuario en la versión vieja de la
            # aplicación hasta que le caduque, y eso puede ser un día entero.
            return FileResponse(candidato, headers={"Cache-Control": CACHE_REVALIDAR})
        return FileResponse(indice, headers={"Cache-Control": CACHE_REVALIDAR})
else:
    logger.warning(
        "No existe el directorio de estáticos (%s): solo se sirve la API. "
        "En desarrollo esto es normal.",
        settings.static_dir,
    )
