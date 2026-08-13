"""Formato de error uniforme para toda la API.

Todas las respuestas de error tienen la misma forma, de modo que el frontend
tiene un único camino de interpretación:

    {"error": {"codigo": "saldo_insuficiente",
               "mensaje": "...",
               "detalles": [{"campo": "importe", "mensaje": "..."}]}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Error de negocio con código estable y estado HTTP asociado."""

    estado: int = status.HTTP_400_BAD_REQUEST
    codigo: str = "error_solicitud"
    mensaje: str = "No se ha podido completar la operación."

    def __init__(
        self,
        mensaje: str | None = None,
        *,
        codigo: str | None = None,
        estado: int | None = None,
        detalles: list[dict[str, str]] | None = None,
    ) -> None:
        self.mensaje = mensaje or self.mensaje
        self.codigo = codigo or self.codigo
        self.estado = estado or self.estado
        self.detalles = detalles or []
        super().__init__(self.mensaje)


class NoEncontrado(AppError):
    estado = status.HTTP_404_NOT_FOUND
    codigo = "no_encontrado"
    mensaje = "El recurso no existe."


class NoAutenticado(AppError):
    estado = status.HTTP_401_UNAUTHORIZED
    codigo = "no_autenticado"
    mensaje = "Necesitas iniciar sesión."


class SinPermiso(AppError):
    estado = status.HTTP_403_FORBIDDEN
    codigo = "sin_permiso"
    mensaje = "No tienes permiso para hacer esto."


class Conflicto(AppError):
    estado = status.HTTP_409_CONFLICT
    codigo = "conflicto"
    mensaje = "La operación entra en conflicto con el estado actual."


class ReglaDeNegocio(AppError):
    estado = status.HTTP_422_UNPROCESSABLE_ENTITY
    codigo = "regla_de_negocio"
    mensaje = "La operación incumple una regla de negocio."


class DemasiadasPeticiones(AppError):
    estado = status.HTTP_429_TOO_MANY_REQUESTS
    codigo = "demasiadas_peticiones"
    mensaje = "Demasiados intentos. Espera un momento."


def _respuesta(
    estado: int, codigo: str, mensaje: str, detalles: list[dict[str, Any]] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=estado,
        content={"error": {"codigo": codigo, "mensaje": mensaje, "detalles": detalles or []}},
    )


# Mensajes en español para los errores de validación más comunes de Pydantic.
_MENSAJES_VALIDACION = {
    "missing": "Este campo es obligatorio.",
    "string_too_short": "El valor es demasiado corto.",
    "string_too_long": "El valor es demasiado largo.",
    "value_error": "El valor no es válido.",
    "greater_than": "El valor debe ser mayor.",
    "greater_than_equal": "El valor es demasiado pequeño.",
    "less_than": "El valor debe ser menor.",
    "less_than_equal": "El valor es demasiado grande.",
    # Sin concretar el número: hay campos de dos decimales (importes) y de
    # cuatro (precios unitarios de luz y gas).
    "decimal_max_places": "Tiene demasiados decimales.",
    "int_parsing": "Debe ser un número entero.",
    "decimal_parsing": "Debe ser un número.",
    "float_parsing": "Debe ser un número.",
    "date_from_datetime_parsing": "La fecha no es válida.",
    "enum": "El valor no está entre las opciones permitidas.",
}


def registrar_manejadores(app: FastAPI) -> None:
    """Engancha los manejadores de excepciones a la aplicación."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _respuesta(exc.estado, exc.codigo, exc.mensaje, exc.detalles)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalles = []
        for error in exc.errors():
            # Se salta "body"/"query" del principio de la ruta del campo.
            partes = [str(p) for p in error["loc"] if p not in ("body", "query", "path")]
            detalles.append(
                {
                    "campo": ".".join(partes) or "cuerpo",
                    "mensaje": _MENSAJES_VALIDACION.get(error["type"], error["msg"]),
                }
            )
        return _respuesta(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "datos_invalidos",
            "Revisa los datos del formulario.",
            detalles,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigos = {
            401: "no_autenticado",
            403: "sin_permiso",
            404: "no_encontrado",
            405: "metodo_no_permitido",
            409: "conflicto",
            413: "fichero_demasiado_grande",
            415: "tipo_no_soportado",
            429: "demasiadas_peticiones",
        }
        detalle = exc.detail if isinstance(exc.detail, str) else "Error en la solicitud."
        return _respuesta(exc.status_code, codigos.get(exc.status_code, "error_http"), detalle)

    @app.exception_handler(Exception)
    async def _inesperado(peticion: Request, exc: Exception) -> JSONResponse:
        # Se registra la traza completa en el servidor pero nunca se expone al
        # cliente: podría filtrar rutas, consultas o datos de otros usuarios.
        logger.exception(
            "Error no controlado en %s %s", peticion.method, peticion.url.path, exc_info=exc
        )
        return _respuesta(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "error_interno",
            "Se ha producido un error inesperado. Vuelve a intentarlo.",
        )
