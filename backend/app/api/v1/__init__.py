"""Agregador de los routers de la versión 1 de la API.

Cada módulo declara sus rutas con la ruta completa (`/invoices/{id}/lines`), así
que aquí no se añaden prefijos: hay recursos que no caben bajo uno solo
—`ajustes.py` publica también `/exports`, y `productos.py` publica `/prices` y
`/baskets`— y forzarlos rompería el contrato.

El orden importa en un caso: los routers con rutas estáticas que podrían
confundirse con un parámetro (`/products/suggestions` frente a
`/products/{id}`) las declaran antes dentro de su propio módulo.
"""

from fastapi import APIRouter

from app.api.v1 import (
    ajustes,
    alertas,
    auth,
    categorias,
    comercios,
    cuentas,
    etiquetas,
    facturas,
    importaciones,
    informes,
    objetivos,
    presupuestos,
    productos,
    recurrentes,
    reglas,
    transacciones,
    transferencias,
    usuarios,
)

api_router = APIRouter()

# Identidad y configuración de la cuenta.
api_router.include_router(auth.router)
api_router.include_router(usuarios.router)
api_router.include_router(ajustes.router)

# Estructura del dinero: dónde está y cómo se clasifica.
api_router.include_router(cuentas.router)
api_router.include_router(categorias.router)
api_router.include_router(comercios.router)
api_router.include_router(etiquetas.router)

# Movimientos y presupuesto.
api_router.include_router(transacciones.router)
api_router.include_router(transferencias.router)
api_router.include_router(presupuestos.router)
api_router.include_router(recurrentes.router)
api_router.include_router(objetivos.router)
api_router.include_router(reglas.router)

# Facturas, catálogo de productos y precios: el diferenciador.
api_router.include_router(facturas.router)
api_router.include_router(productos.router)

# Lectura y entrada/salida de datos.
api_router.include_router(informes.router)
api_router.include_router(importaciones.router)
api_router.include_router(alertas.router)

__all__ = ["api_router"]
