"""Catálogo de productos, alias, histórico de precios y comparativas.

§3.14 y §5.12 del contrato. Aquí vive además el **emparejado en cascada** que usa
la pantalla de revisión de facturas (`facturas.py` lo importa de este módulo):

    barcode → grouping_key → alias → pg_trgm + RapidFuzz → sugerencia → nuevo

El reparto de trabajo entre SQL y Python es el de `docs/arquitectura/modelo-datos.md`:
PostgreSQL **preselecciona** con un umbral laxo de trigramas (0,30) y la decisión
la toma `app/services/normalizacion.py` con RapidFuzz y su umbral de 88. Ningún
umbral se duplica y el análisis del historial es siempre
`app/services/precios.py`: aquí no se recalcula ninguna media.
"""

from __future__ import annotations

import uuid as uuidlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import Select, delete, func, inspect, or_, select, text, update

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.core.errors import Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.factura import InvoiceLine
from app.models.fusion import MergeOperation, MergeOperationChange
from app.models.hogar import Household
from app.models.producto import Product, ProductAlias, ProductPrice
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comercio import ComercioRefRespuesta
from app.schemas.comun import Pagina
from app.schemas.informe import CestaComercioFilaRespuesta, CestaInformeRespuesta
from app.schemas.producto import (
    AliasProductoCrear,
    AliasProductoRespuesta,
    ComparativaProductoRespuesta,
    EstadisticasPrecioRespuesta,
    OrigenPrecio,
    PrecioActualizar,
    PrecioComercioRespuesta,
    PrecioCrear,
    PrecioFiltro,
    PrecioRespuesta,
    ProductoActualizar,
    ProductoCrear,
    ProductoFiltro,
    ProductoFusionCrear,
    ProductoFusionRespuesta,
    ProductoFusionResultadoRespuesta,
    ProductoRefRespuesta,
    ProductoRespuesta,
    ProductoSepararCrear,
    ProductoSepararResultadoRespuesta,
    ProductoSugerenciaFiltro,
    ProductoSugerenciaRespuesta,
)
from app.services import precios
from app.services.formato import CENTIMO, CUATRO_DECIMALES, cuantizar
from app.services.normalizacion import (
    UMBRAL_COINCIDENCIA,
    DescripcionNormalizada,
    clave_agrupacion,
    es_mismo_producto,
    mejor_coincidencia,
    normalizar_descripcion,
    similitud,
    sin_acentos,
)
from app.services.precios import PuntoPrecio, Tendencia, analizar_historial

router = APIRouter(dependencies=[Depends(verificar_csrf)])

#: Umbral laxo de la preselección por trigramas. No decide nada: su trabajo es no
#: perder candidatos (modelo-datos §6).
UMBRAL_TRIGRAMA = 0.30

#: Candidatos que se traen a Python para la comparación difusa.
MAXIMO_CANDIDATOS = 20

#: Zona de duda de la cascada: se sugiere, pero no se enlaza solo (RN-60).
UMBRAL_SUGERENCIA = 70.0

#: Una fusión se puede deshacer durante 30 días (RN-65).
DIAS_PARA_DESHACER = 30

#: Una observación con más de estos días ya no sirve para decidir dónde comprar.
DIAS_PRECIO_RANCIO = 90


def ahora() -> datetime:
    return datetime.now(UTC)


async def cargado[T](sesion: Any, objeto: T) -> T:
    """Vuelve a leer las columnas que calcula el servidor tras un `COMMIT`.

    `created_at` y `updated_at` los pone PostgreSQL, así que SQLAlchemy los deja
    expirados después de escribir. En asíncrono una carga diferida explota
    (`MissingGreenlet`): hay que releer a mano y de forma explícita.
    """
    if objeto is not None and inspect(objeto).unloaded:
        await sesion.refresh(objeto)
    return objeto


def _u8(texto: str | None) -> str | None:
    """Recorta a los 8 caracteres de `String(8)` de unidades y tamaños."""
    if texto is None:
        return None
    limpio = texto.strip()
    return limpio[:8] or None


def _tendencia(cambio: Decimal | None) -> Tendencia:
    """Etiqueta la variación con los mismos umbrales del servicio de precios."""
    if cambio is None:
        return Tendencia.SIN_DATOS
    if cambio > precios.UMBRAL_RUIDO:
        return Tendencia.SUBE
    if cambio < -precios.UMBRAL_RUIDO:
        return Tendencia.BAJA
    return Tendencia.ESTABLE


def _pct(proporcion: Decimal | None) -> float | None:
    """Proporción del servicio (0,08) → porcentaje del contrato (8.0)."""
    if proporcion is None:
        return None
    return float((proporcion * 100).quantize(CENTIMO))


# --------------------------------------------------------------------------- #
# Normalización y firma de un producto
# --------------------------------------------------------------------------- #


def normalizada_con_tamanyo(
    texto: str,
    *,
    size_value: Decimal | None = None,
    size_unit: str | None = None,
    barcode: str | None = None,
) -> DescripcionNormalizada:
    """Normaliza una descripción y deja que el tamaño explícito mande.

    Cuando el usuario teclea el tamaño en el formulario, ese dato es mejor que el
    que se adivina de la descripción, y es el que tiene que entrar en la clave de
    agrupación para que el veto de tamaño de `es_mismo_producto()` funcione.
    """
    normalizada = normalizar_descripcion(texto)
    if size_value is not None and size_unit:
        normalizada.tamanyo_valor = size_value
        normalizada.tamanyo_unidad = _u8(size_unit)
    if barcode:
        normalizada.codigo = barcode.strip().lower()
    return normalizada


def firma_de(producto: Product) -> DescripcionNormalizada:
    """La firma normalizada de un producto ya guardado, para compararlo."""
    return DescripcionNormalizada(
        canonica=producto.canonical_name,
        marca_probable=producto.brand,
        tamanyo_valor=producto.size_value,
        tamanyo_unidad=producto.size_unit,
        codigo=producto.barcode.lower() if producto.barcode else None,
    )


def ref_producto(producto: Product) -> ProductoRefRespuesta:
    return ProductoRefRespuesta(
        id=producto.id,
        name=producto.name,
        brand=producto.brand,
        size_text=texto_tamanyo(producto.size_value, producto.size_unit),
    )


def texto_tamanyo(valor: Decimal | None, unidad: str | None) -> str | None:
    if valor is None or not unidad:
        return None
    return f"{format(valor.normalize(), 'f')} {unidad}"


def ref_comercio(comercio: Payee | None) -> ComercioRefRespuesta | None:
    if comercio is None:
        return None
    return ComercioRefRespuesta(id=comercio.id, name=comercio.name)


# --------------------------------------------------------------------------- #
# Emparejado en cascada (modelo-datos §6)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class Emparejamiento:
    """Resultado de la cascada: a qué producto va la línea y por qué."""

    product_id: uuidlib.UUID
    metodo: str
    puntuacion: Decimal | None = None
    alias: str | None = None


async def emparejar(
    sesion: Any,
    household_id: uuidlib.UUID,
    normalizada: DescripcionNormalizada,
    *,
    codigo_barras: str | None = None,
) -> Emparejamiento | None:
    """Niveles 1 a 4 de la cascada. Devuelve None si nada llega al umbral 88."""
    clave = clave_agrupacion(normalizada)
    codigo = (codigo_barras or normalizada.codigo or "").strip() or None

    # Niveles 1 a 3: SQL exacto, una sola consulta ordenada por certeza.
    exacto = await sesion.execute(
        text(
            """
            WITH candidato AS (
                SELECT p.id, 1 AS nivel, 'barcode' AS metodo, 100.0 AS score, NULL::text AS alias
                  FROM products p
                 WHERE p.household_id = CAST(:hh AS uuid)
                   AND CAST(:codigo AS text) IS NOT NULL
                   AND p.barcode = CAST(:codigo AS text)
                   AND p.merged_into_id IS NULL
                UNION ALL
                SELECT p.id, 2, 'grouping_key', 100.0, NULL
                  FROM products p
                 WHERE p.household_id = CAST(:hh AS uuid)
                   AND p.grouping_key = CAST(:clave AS text)
                   AND p.merged_into_id IS NULL
                UNION ALL
                SELECT a.product_id, 3, 'alias', COALESCE(a.match_score, 100.0), a.normalized_text
                  FROM product_aliases a
                 WHERE a.household_id = CAST(:hh AS uuid)
                   AND a.normalized_text = CAST(:canonica AS text)
            )
            SELECT id, metodo, score, alias FROM candidato ORDER BY nivel LIMIT 1
            """
        ),
        {
            "hh": str(household_id),
            "codigo": codigo,
            "clave": clave,
            "canonica": normalizada.canonica,
        },
    )
    fila = exacto.first()
    if fila is not None:
        return Emparejamiento(
            product_id=fila.id,
            metodo=fila.metodo,
            puntuacion=Decimal(str(fila.score)),
            alias=fila.alias,
        )

    # Nivel 4: preselección por trigramas y decisión en Python con RapidFuzz.
    candidatos = await candidatos_trigrama(sesion, household_id, normalizada)
    if not candidatos:
        return None
    elegido = mejor_coincidencia(
        normalizada.canonica, {str(p.id): p.canonical_name for p in candidatos}
    )
    if elegido is None:
        return None
    identificador, puntuacion = elegido
    producto = next(p for p in candidatos if str(p.id) == identificador)
    # Segunda comprobación con la firma completa: aplica el veto de tamaño y la
    # primacía del código de barras, que `mejor_coincidencia()` no ve.
    if not es_mismo_producto(normalizada, firma_de(producto)):
        return None
    return Emparejamiento(
        product_id=producto.id,
        metodo="trigram_fuzzy",
        puntuacion=Decimal(str(round(puntuacion, 2))),
    )


async def candidatos_trigrama(
    sesion: Any,
    household_id: uuidlib.UUID,
    normalizada: DescripcionNormalizada,
    *,
    limite: int = MAXIMO_CANDIDATOS,
) -> list[Product]:
    """Preselecciona con el índice GIN de trigramas, sin decidir nada.

    El veto de tamaño se replica en SQL **solo como prefiltro**: gastar
    comparaciones difusas en productos que `es_mismo_producto()` va a rechazar de
    todas formas es trabajo tirado.
    """
    if not normalizada.canonica:
        return []
    await sesion.execute(text(f"SET LOCAL pg_trgm.similarity_threshold = {UMBRAL_TRIGRAMA}"))
    consulta = (
        select(Product)
        .where(
            Product.household_id == household_id,
            Product.merged_into_id.is_(None),
            Product.archived_at.is_(None),
            Product.canonical_name.op("%")(normalizada.canonica),
        )
        .order_by(func.similarity(Product.canonical_name, normalizada.canonica).desc())
        .limit(limite)
    )
    if normalizada.tamanyo_unidad:
        consulta = consulta.where(
            or_(
                Product.size_unit.is_(None),
                (Product.size_unit == _u8(normalizada.tamanyo_unidad))
                & (Product.size_value == normalizada.tamanyo_valor),
            )
        )
    return list((await sesion.execute(consulta)).scalars().all())


async def sugerencias_para(
    sesion: Any,
    household_id: uuidlib.UUID,
    normalizada: DescripcionNormalizada,
    *,
    limite: int = 5,
    minimo: float = UMBRAL_COINCIDENCIA,
) -> list[tuple[Product, float]]:
    """Candidatos ordenados por parecido, para que el usuario confirme (RN-60)."""
    candidatos = await candidatos_trigrama(sesion, household_id, normalizada, limite=50)
    puntuados = [
        (producto, puntuacion)
        for producto in candidatos
        if (puntuacion := _puntuar(normalizada, producto)) >= minimo
    ]
    puntuados.sort(key=lambda par: par[1], reverse=True)
    return puntuados[:limite]


def _puntuar(normalizada: DescripcionNormalizada, producto: Product) -> float:
    """Parecido difuso, ya con el veto de tamaño y de código de barras aplicado."""
    if not es_mismo_producto(normalizada, firma_de(producto), umbral=UMBRAL_SUGERENCIA):
        return 0.0
    return similitud(normalizada.canonica, producto.canonical_name)


# --------------------------------------------------------------------------- #
# Alta de productos y memoria de alias
# --------------------------------------------------------------------------- #


async def crear_producto(
    alcance: AlcanceHogar,
    datos: ProductoCrear,
    *,
    origen: str = "manual",
) -> Product:
    """Crea un producto con su clave de agrupación. 409 si la clave ya existe."""
    await _tematica_del_hogar(alcance, datos.default_category_id)
    normalizada = normalizada_con_tamanyo(
        datos.name,
        size_value=datos.size_value,
        size_unit=datos.size_unit,
        barcode=datos.barcode,
    )
    clave = clave_agrupacion(normalizada)
    repetido = (
        await alcance.sesion.execute(
            select(Product.id).where(
                Product.household_id == alcance.household_id,
                Product.grouping_key == clave,
                Product.merged_into_id.is_(None),
            )
        )
    ).scalar_one_or_none()
    if repetido is not None:
        raise Conflicto(
            "Ya tienes un producto que se agrupa igual que este.",
            codigo="nombre_duplicado",
            detalles=[{"campo": "name", "mensaje": str(repetido)}],
        )

    producto = Product(
        household_id=alcance.household_id,
        name=datos.name,
        canonical_name=normalizada.canonica,
        grouping_key=clave,
        brand=datos.brand or normalizada.marca_probable,
        size_value=datos.size_value if datos.size_unit else None,
        size_unit=_u8(datos.size_unit) if datos.size_value is not None else None,
        unit=_u8(datos.unit),
        barcode=datos.barcode,
        category_id=datos.default_category_id,
        notes=datos.note,
    )
    alcance.sesion.add(producto)
    await alcance.sesion.flush()
    if origen == "invoice":
        # El alias de la propia descripción se aprende en cuanto nace el producto.
        await aprender_alias(
            alcance,
            producto.id,
            normalizada.canonica,
            bruto=datos.name,
            metodo="manual",
        )
    return producto


async def aprender_alias(
    alcance: AlcanceHogar,
    product_id: uuidlib.UUID,
    normalizado: str,
    *,
    bruto: str | None = None,
    payee_id: uuidlib.UUID | None = None,
    metodo: str = "manual",
    puntuacion: Decimal | None = None,
    confirmado: bool = True,
) -> ProductAlias | None:
    """Memoriza una grafía para que la próxima factura se reconozca sola.

    Es lo que hace que RapidFuzz se ejecute una vez por grafía nueva y no una vez
    por línea de factura.
    """
    if not normalizado:
        return None
    existente = (
        await alcance.sesion.execute(
            select(ProductAlias).where(
                ProductAlias.household_id == alcance.household_id,
                ProductAlias.normalized_text == normalizado,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        existente.times_seen += 1
        existente.last_seen_on = date.today()
        if existente.product_id != product_id and confirmado:
            # Una confirmación humana reasigna el alias mal aprendido.
            existente.product_id = product_id
            existente.match_method = "manual"
            existente.confirmed_at = ahora()
            existente.confirmed_by_id = alcance.usuario.id
        return existente

    alias = ProductAlias(
        household_id=alcance.household_id,
        product_id=product_id,
        normalized_text=normalizado,
        grouping_key=None,
        raw_sample=(bruto or normalizado)[:300],
        payee_id=payee_id,
        match_method=metodo if metodo != "none" else "manual",
        match_score=puntuacion,
        times_seen=1,
        last_seen_on=date.today(),
        confirmed_by_id=alcance.usuario.id if confirmado else None,
        confirmed_at=ahora() if confirmado else None,
    )
    alcance.sesion.add(alias)
    await alcance.sesion.flush()
    return alias


# --------------------------------------------------------------------------- #
# Historial de precios
# --------------------------------------------------------------------------- #


async def puntos_por_producto(
    sesion: Any,
    household_id: uuidlib.UUID,
    product_ids: list[uuidlib.UUID],
    *,
    desde: date | None = None,
    hasta: date | None = None,
    payee_ids: list[uuidlib.UUID] | None = None,
    incluir_promociones: bool = True,
) -> dict[uuidlib.UUID, list[PuntoPrecio]]:
    """Historial en la forma que espera `app/services/precios.py`."""
    if not product_ids:
        return {}
    consulta = (
        select(
            ProductPrice.product_id,
            ProductPrice.priced_on,
            ProductPrice.unit_price,
            ProductPrice.quantity,
            ProductPrice.payee_id,
            Payee.name.label("payee_name"),
            InvoiceLine.invoice_id,
        )
        .join(Payee, Payee.id == ProductPrice.payee_id, isouter=True)
        .join(InvoiceLine, InvoiceLine.id == ProductPrice.invoice_line_id, isouter=True)
        .where(
            ProductPrice.household_id == household_id,
            ProductPrice.product_id.in_(product_ids),
        )
        .order_by(ProductPrice.priced_on)
    )
    if desde is not None:
        consulta = consulta.where(ProductPrice.priced_on >= desde)
    if hasta is not None:
        consulta = consulta.where(ProductPrice.priced_on <= hasta)
    if payee_ids:
        consulta = consulta.where(ProductPrice.payee_id.in_(payee_ids))
    if not incluir_promociones:
        consulta = consulta.where(ProductPrice.is_promotion.is_(False))

    historial: dict[uuidlib.UUID, list[PuntoPrecio]] = defaultdict(list)
    for fila in (await sesion.execute(consulta)).all():
        historial[fila.product_id].append(
            PuntoPrecio(
                fecha=fila.priced_on,
                precio=fila.unit_price,
                comercio=fila.payee_name,
                factura_id=str(fila.invoice_id) if fila.invoice_id else None,
                cantidad=fila.quantity,
            )
        )
    return dict(historial)


async def ultima_observacion(
    sesion: Any,
    household_id: uuidlib.UUID,
    product_id: uuidlib.UUID,
    *,
    payee_id: uuidlib.UUID | None = None,
    antes_de: date | None = None,
    excluir: uuidlib.UUID | None = None,
) -> ProductPrice | None:
    """La observación anterior contra la que se calcula la variación (RN-63)."""
    consulta = (
        select(ProductPrice)
        .where(
            ProductPrice.household_id == household_id,
            ProductPrice.product_id == product_id,
        )
        .order_by(ProductPrice.priced_on.desc(), ProductPrice.created_at.desc())
        .limit(1)
    )
    if payee_id is not None:
        consulta = consulta.where(ProductPrice.payee_id == payee_id)
    if antes_de is not None:
        consulta = consulta.where(ProductPrice.priced_on <= antes_de)
    if excluir is not None:
        consulta = consulta.where(ProductPrice.id != excluir)
    return (await sesion.execute(consulta)).scalar_one_or_none()


@dataclass(slots=True)
class Variacion:
    """Variación calculada y contra qué se ha comparado."""

    anterior: ProductPrice | None
    porcentaje: float | None
    base: str | None


async def calcular_variacion(
    sesion: Any,
    household_id: uuidlib.UUID,
    product_id: uuidlib.UUID,
    *,
    precio: Decimal,
    unidad: str | None,
    payee_id: uuidlib.UUID | None,
    fecha: date,
    excluir: uuidlib.UUID | None = None,
) -> Variacion:
    """RN-63: contra el mismo comercio; si no hay, contra la última global.

    Comparar entre unidades distintas (€/kg contra €/ud) está prohibido: si la
    unidad no coincide no hay variación.
    """
    base = "same_payee"
    anterior = None
    if payee_id is not None:
        anterior = await ultima_observacion(
            sesion,
            household_id,
            product_id,
            payee_id=payee_id,
            antes_de=fecha,
            excluir=excluir,
        )
    if anterior is None:
        base = "global"
        anterior = await ultima_observacion(
            sesion, household_id, product_id, antes_de=fecha, excluir=excluir
        )
    if anterior is None:
        return Variacion(anterior=None, porcentaje=None, base=None)
    if _u8(anterior.unit) != _u8(unidad):
        return Variacion(anterior=anterior, porcentaje=None, base=base)
    return Variacion(
        anterior=anterior,
        porcentaje=_pct(precios.variacion(anterior.unit_price, precio)),
        base=base,
    )


async def refrescar_producto(sesion: Any, producto: Product) -> None:
    """Recalcula los contadores desnormalizados del producto."""
    fila = (
        await sesion.execute(
            select(
                func.count(ProductPrice.id),
                func.min(ProductPrice.priced_on),
                func.max(ProductPrice.priced_on),
            ).where(
                ProductPrice.household_id == producto.household_id,
                ProductPrice.product_id == producto.id,
            )
        )
    ).one()
    producto.price_observation_count = fila[0] or 0
    producto.first_seen_on = fila[1]
    producto.last_seen_on = fila[2]
    ultimo = await ultima_observacion(sesion, producto.household_id, producto.id)
    producto.last_unit_price = ultimo.unit_price if ultimo else None


async def registrar_observacion(
    alcance: AlcanceHogar,
    *,
    producto: Product,
    fecha: date,
    precio_unitario: Decimal,
    unidad: str | None = None,
    cantidad: Decimal | None = None,
    total: Decimal | None = None,
    payee_id: uuidlib.UUID | None = None,
    invoice_line_id: uuidlib.UUID | None = None,
    origen: str = "invoice",
    moneda: str = "EUR",
) -> tuple[ProductPrice, Variacion]:
    """Añade una observación de precio y devuelve su variación (F-15, RN-62)."""
    variacion = await calcular_variacion(
        alcance.sesion,
        alcance.household_id,
        producto.id,
        precio=precio_unitario,
        unidad=unidad,
        payee_id=payee_id,
        fecha=fecha,
    )
    observacion = ProductPrice(
        household_id=alcance.household_id,
        product_id=producto.id,
        payee_id=payee_id,
        invoice_line_id=invoice_line_id,
        priced_on=fecha,
        unit_price=cuantizar(precio_unitario, CUATRO_DECIMALES),
        unit=_u8(unidad),
        quantity=cantidad,
        line_total=total,
        currency=moneda,
        source=origen,
        change_pct=(
            Decimal(str(variacion.porcentaje)) if variacion.porcentaje is not None else None
        ),
    )
    alcance.sesion.add(observacion)
    await alcance.sesion.flush()
    await refrescar_producto(alcance.sesion, producto)
    return observacion, variacion


# --------------------------------------------------------------------------- #
# Estadísticas y comparativas, siempre a través del servicio de precios
# --------------------------------------------------------------------------- #


def estadisticas_de(
    product_id: uuidlib.UUID,
    puntos: list[PuntoPrecio],
    *,
    desde: date | None = None,
    hasta: date | None = None,
) -> EstadisticasPrecioRespuesta:
    analisis = analizar_historial(puntos)
    mediana = _mediana([p.precio for p in puntos])
    hace_un_anyo = None
    if analisis.precio_actual is not None:
        limite = (analisis.fecha_actual or date.today()) - timedelta(days=365)
        antiguos = [p for p in puntos if p.fecha <= limite]
        if antiguos:
            base = max(antiguos, key=lambda p: p.fecha).precio
            hace_un_anyo = _pct(precios.variacion(base, analisis.precio_actual))
    return EstadisticasPrecioRespuesta(
        product_id=product_id,
        observations=analisis.observaciones,
        period_from=desde or (min(p.fecha for p in puntos) if puntos else None),
        period_to=hasta or (max(p.fecha for p in puntos) if puntos else None),
        min_unit_price=analisis.precio_minimo,
        max_unit_price=analisis.precio_maximo,
        average_unit_price=analisis.precio_medio,
        median_unit_price=mediana,
        last_unit_price=analisis.precio_actual,
        last_observed_at=analisis.fecha_actual,
        change_pct=_pct(analisis.variacion_ultima),
        change_pct_12m=hace_un_anyo,
        trend=analisis.tendencia,
    )


def _mediana(valores: list[Decimal]) -> Decimal | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[mitad]
    return cuantizar((ordenados[mitad - 1] + ordenados[mitad]) / 2, CUATRO_DECIMALES)


def comparativa_por_comercio(
    puntos: list[PuntoPrecio],
    comercios: dict[str, Payee],
) -> list[PrecioComercioRespuesta]:
    """`comparar_comercios()` del servicio, vestido con el contrato (F-38)."""
    comparativas = precios.comparar_comercios(puntos)
    if not comparativas:
        return []
    mas_barato = comparativas[0].precio
    medias: dict[str, list[Decimal]] = defaultdict(list)
    for punto in puntos:
        if punto.comercio:
            medias[punto.comercio].append(punto.precio)

    filas: list[PrecioComercioRespuesta] = []
    for comparativa in comparativas:
        valores = medias[comparativa.comercio]
        media = cuantizar(sum(valores) / len(valores), CUATRO_DECIMALES)
        diferencia = cuantizar(comparativa.precio - mas_barato)
        filas.append(
            PrecioComercioRespuesta(
                payee=ref_comercio(comercios.get(comparativa.comercio)),
                last_unit_price=comparativa.precio,
                last_observed_at=comparativa.fecha,
                observations=comparativa.observaciones,
                average_unit_price=media,
                diff_vs_cheapest=diferencia,
                diff_vs_cheapest_pct=_pct(precios.variacion(mas_barato, comparativa.precio)) or 0.0,
                is_stale=(date.today() - comparativa.fecha).days > DIAS_PRECIO_RANCIO,
            )
        )
    return filas


async def comercios_por_nombre(sesion: Any, household_id: uuidlib.UUID) -> dict[str, Payee]:
    """Los comercios del hogar indexados por nombre, que es la clave del servicio."""
    filas = (
        await sesion.execute(select(Payee).where(Payee.household_id == household_id))
    ).scalars()
    return {comercio.name: comercio for comercio in filas}


async def comparativa_de(
    alcance: AlcanceHogar, producto: Product, *, meses: int = 12
) -> ComparativaProductoRespuesta:
    desde = date.today() - timedelta(days=30 * meses)
    historial = await puntos_por_producto(
        alcance.sesion, alcance.household_id, [producto.id], desde=desde
    )
    puntos = historial.get(producto.id, [])
    comercios = await comercios_por_nombre(alcance.sesion, alcance.household_id)
    filas = comparativa_por_comercio(puntos, comercios)
    reparto = None
    if len(filas) >= 2:
        reparto = _pct(precios.variacion(filas[0].last_unit_price, filas[-1].last_unit_price))
    return ComparativaProductoRespuesta(
        product=ref_producto(producto),
        unit=producto.unit,
        cheapest=filas[0] if filas else None,
        most_expensive=filas[-1] if filas else None,
        spread_pct=reparto,
        by_payee=filas,
    )


async def comparar_cesta_de(
    alcance: AlcanceHogar,
    productos: list[Product],
    *,
    meses: int = 3,
    basket_id: uuidlib.UUID | None = None,
    cantidades: dict[uuidlib.UUID, Decimal] | None = None,
) -> CestaInformeRespuesta:
    """Coste de la misma cesta en cada comercio visto (F-60)."""
    desde = date.today() - timedelta(days=30 * meses)
    historial = await puntos_por_producto(
        alcance.sesion, alcance.household_id, [p.id for p in productos], desde=desde
    )
    comercios = await comercios_por_nombre(alcance.sesion, alcance.household_id)

    lineas: list[precios.LineaCesta] = []
    rancios: dict[str, int] = defaultdict(int)
    for producto in productos:
        puntos = historial.get(producto.id, [])
        ultimos: dict[str, Decimal] = {}
        for comparativa in precios.comparar_comercios(puntos):
            ultimos[comparativa.comercio] = comparativa.precio
            if (date.today() - comparativa.fecha).days > DIAS_PRECIO_RANCIO:
                rancios[comparativa.comercio] += 1
        lineas.append(
            precios.LineaCesta(
                producto_id=str(producto.id),
                nombre=producto.name,
                cantidad=(cantidades or {}).get(producto.id, Decimal(1)),
                precios=ultimos,
            )
        )

    comparativa = precios.comparar_cesta(lineas)
    por_id = {str(p.id): p for p in productos}
    minimo = min(comparativa.totales.values()) if comparativa.totales else Decimal("0.00")

    filas: list[CestaComercioFilaRespuesta] = []
    faltantes: dict[str, list[ProductoRefRespuesta]] = {}
    for comercio, total in sorted(comparativa.totales.items(), key=lambda par: par[1]):
        ausentes = comparativa.incompletos.get(comercio, [])
        cubiertos = len(lineas) - len(ausentes)
        filas.append(
            CestaComercioFilaRespuesta(
                payee=ref_comercio(comercios.get(comercio)),
                total=total,
                covered_items=cubiertos,
                missing_items=len(ausentes),
                coverage_pct=round(100 * cubiertos / len(lineas), 2) if lineas else 0.0,
                diff_vs_cheapest=cuantizar(total - minimo),
                stale_prices=rancios.get(comercio, 0),
                is_comparable=not ausentes,
            )
        )
        if ausentes:
            nombres = {linea.nombre: linea.producto_id for linea in lineas}
            faltantes[comercio] = [
                ref_producto(por_id[nombres[nombre]]) for nombre in ausentes if nombre in nombres
            ]

    comparables = [fila for fila in filas if fila.is_comparable]
    return CestaInformeRespuesta(
        basket_id=basket_id,
        items=len(lineas),
        cheapest=(comparables or filas)[0] if filas else None,
        by_payee=filas,
        missing_by_payee=faltantes,
        max_saving=comparativa.ahorro_maximo,
    )


# --------------------------------------------------------------------------- #
# Construcción de la respuesta del catálogo
# --------------------------------------------------------------------------- #


async def _estadisticas_basicas(
    sesion: Any, household_id: uuidlib.UUID, product_ids: list[uuidlib.UUID]
) -> dict[uuidlib.UUID, dict[str, Any]]:
    """Agregados de precio y de alias de un puñado de productos."""
    if not product_ids:
        return {}
    resumen: dict[uuidlib.UUID, dict[str, Any]] = {
        identificador: {
            "observations": 0,
            "payees": 0,
            "aliases": 0,
            "min": None,
            "max": None,
            "avg": None,
            "last": None,
            "previous": None,
        }
        for identificador in product_ids
    }
    filas = (
        await sesion.execute(
            select(
                ProductPrice.product_id,
                func.count(ProductPrice.id),
                func.min(ProductPrice.unit_price),
                func.max(ProductPrice.unit_price),
                func.avg(ProductPrice.unit_price),
                func.count(func.distinct(ProductPrice.payee_id)),
            )
            .where(
                ProductPrice.household_id == household_id,
                ProductPrice.product_id.in_(product_ids),
            )
            .group_by(ProductPrice.product_id)
        )
    ).all()
    for fila in filas:
        resumen[fila[0]].update(
            observations=fila[1],
            min=fila[2],
            max=fila[3],
            avg=cuantizar(Decimal(fila[4]), CUATRO_DECIMALES) if fila[4] is not None else None,
            payees=fila[5],
        )

    alias = (
        await sesion.execute(
            select(ProductAlias.product_id, func.count(ProductAlias.id))
            .where(
                ProductAlias.household_id == household_id,
                ProductAlias.product_id.in_(product_ids),
            )
            .group_by(ProductAlias.product_id)
        )
    ).all()
    for fila in alias:
        resumen[fila[0]]["aliases"] = fila[1]

    # Las dos últimas observaciones de cada producto: es lo que da `change_pct`.
    ordenadas = (
        select(
            ProductPrice.product_id,
            ProductPrice.unit_price,
            func.row_number()
            .over(
                partition_by=ProductPrice.product_id,
                order_by=(ProductPrice.priced_on.desc(), ProductPrice.created_at.desc()),
            )
            .label("rn"),
        )
        .where(
            ProductPrice.household_id == household_id,
            ProductPrice.product_id.in_(product_ids),
        )
        .subquery()
    )
    for fila in (await sesion.execute(select(ordenadas).where(ordenadas.c.rn <= 2))).all():
        clave = "last" if fila.rn == 1 else "previous"
        resumen[fila.product_id][clave] = fila.unit_price
    return resumen


def respuesta_producto(
    producto: Product,
    resumen: dict[str, Any],
    *,
    categoria: CategoriaRefRespuesta | None = None,
    umbral_subida: Decimal = Decimal("5.00"),
    change_pct_12m: float | None = None,
) -> ProductoRespuesta:
    anterior, ultimo = resumen.get("previous"), resumen.get("last")
    cambio = precios.variacion(anterior, ultimo) if anterior and ultimo else None
    porcentaje = _pct(cambio)
    return ProductoRespuesta(
        id=producto.id,
        created_at=producto.created_at,
        updated_at=producto.updated_at,
        name=producto.name,
        brand=producto.brand,
        canonical_name=producto.canonical_name,
        size_value=producto.size_value,
        size_unit=producto.size_unit,
        size_text=texto_tamanyo(producto.size_value, producto.size_unit),
        unit=producto.unit,
        barcode=producto.barcode,
        default_category=categoria,
        is_archived=producto.archived_at is not None,
        aliases_count=resumen.get("aliases", 0),
        observations_count=resumen.get("observations", 0),
        payees_count=resumen.get("payees", 0),
        first_seen_on=producto.first_seen_on,
        last_seen_on=producto.last_seen_on,
        last_unit_price=producto.last_unit_price,
        min_unit_price=resumen.get("min"),
        max_unit_price=resumen.get("max"),
        average_unit_price=resumen.get("avg"),
        change_pct=porcentaje,
        change_pct_12m=change_pct_12m,
        trend=_tendencia(cambio),
        has_increase=porcentaje is not None and Decimal(str(porcentaje)) >= umbral_subida,
        note=producto.notes,
    )


async def _categorias_ref(
    sesion: Any, household_id: uuidlib.UUID, ids: list[uuidlib.UUID]
) -> dict[uuidlib.UUID, CategoriaRefRespuesta]:
    limpios = [identificador for identificador in ids if identificador]
    if not limpios:
        return {}
    filas = (
        await sesion.execute(
            select(Category).where(Category.household_id == household_id, Category.id.in_(limpios))
        )
    ).scalars()
    return {
        categoria.id: CategoriaRefRespuesta(
            id=categoria.id, name=categoria.name, color=categoria.color_hex
        )
        for categoria in filas
    }


async def _umbral_subida(sesion: Any, household_id: uuidlib.UUID) -> Decimal:
    valor = (
        await sesion.execute(select(Household.price_alert_pct).where(Household.id == household_id))
    ).scalar_one_or_none()
    return valor if valor is not None else Decimal("5.00")


async def _tematica_del_hogar(alcance: AlcanceHogar, categoria_id: uuidlib.UUID | None) -> None:
    """RN-01: una temática de otro hogar no se puede asignar a un producto.

    Sin esta comprobación la única defensa era la clave ajena compuesta
    `(household_id, category_id)`, que salta en el `COMMIT` y el usuario recibe un
    500 en lugar del 404 que manda RN-02.
    """
    if categoria_id is None:
        return
    existe = await alcance.sesion.scalar(
        select(Category.id).where(
            Category.household_id == alcance.household_id, Category.id == categoria_id
        )
    )
    if existe is None:
        raise NoEncontrado("La temática no existe.")


async def _comercio_del_hogar(alcance: AlcanceHogar, comercio_id: uuidlib.UUID | None) -> None:
    """Lo mismo para el comercio de una observación de precio."""
    if comercio_id is None:
        return
    existe = await alcance.sesion.scalar(
        select(Payee.id).where(Payee.household_id == alcance.household_id, Payee.id == comercio_id)
    )
    if existe is None:
        raise NoEncontrado("El comercio no existe.")


async def _producto_o_404(alcance: AlcanceHogar, product_id: uuidlib.UUID) -> Product:
    producto = (
        await alcance.sesion.execute(
            select(Product).where(
                Product.household_id == alcance.household_id, Product.id == product_id
            )
        )
    ).scalar_one_or_none()
    if producto is None:
        raise NoEncontrado("Este producto no existe.")
    return producto


# --------------------------------------------------------------------------- #
# Endpoints del catálogo
# --------------------------------------------------------------------------- #


@router.get("/products/suggestions", tags=["products"], summary="Candidatos por parecido")
async def sugerencias(
    alcance: Alcance,
    filtro: Annotated[ProductoSugerenciaFiltro, Query()],
) -> list[ProductoSugerenciaRespuesta]:
    """Lo que usa la pantalla de revisión para proponer un producto (RN-60)."""
    normalizada = normalizar_descripcion(filtro.description)
    candidatos = await sugerencias_para(
        alcance.sesion,
        alcance.household_id,
        normalizada,
        limite=filtro.limit,
        minimo=filtro.min_score,
    )
    comercios = await comercios_por_nombre(alcance.sesion, alcance.household_id)
    por_nombre = {comercio.id: comercio for comercio in comercios.values()}
    respuestas: list[ProductoSugerenciaRespuesta] = []
    for producto, puntuacion in candidatos:
        ultimo = await ultima_observacion(alcance.sesion, alcance.household_id, producto.id)
        respuestas.append(
            ProductoSugerenciaRespuesta(
                product=ref_producto(producto),
                score=round(puntuacion, 2),
                last_unit_price=ultimo.unit_price if ultimo else None,
                last_payee=(
                    ref_comercio(por_nombre.get(ultimo.payee_id))
                    if ultimo and ultimo.payee_id
                    else None
                ),
            )
        )
    return respuestas


@router.get("/products/merges", tags=["products"], summary="Fusiones recientes")
async def listar_fusiones(
    alcance: Alcance,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Pagina[ProductoFusionRespuesta]:
    consulta = (
        select(MergeOperation)
        .where(
            MergeOperation.household_id == alcance.household_id,
            MergeOperation.entity_type == "product",
            MergeOperation.parent_merge_operation_id.is_(None),
        )
        .order_by(MergeOperation.created_at.desc())
    )
    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    operaciones = list(
        (await alcance.sesion.execute(consulta.offset((page - 1) * size).limit(size))).scalars()
    )
    return Pagina.crear(
        [await _respuesta_fusion(alcance, operacion) for operacion in operaciones],
        page=page,
        size=size,
        total=total,
    )


@router.post(
    "/products/merges/{merge_id}/undo",
    tags=["products"],
    summary="Deshace una fusión completa",
)
async def deshacer_fusion(
    alcance: AlcanceEscritura, merge_id: uuidlib.UUID
) -> ProductoFusionResultadoRespuesta:
    """Devuelve cada observación a su producto de origen (RN-65)."""
    operacion = (
        await alcance.sesion.execute(
            select(MergeOperation).where(
                MergeOperation.household_id == alcance.household_id,
                MergeOperation.id == merge_id,
                MergeOperation.entity_type == "product",
            )
        )
    ).scalar_one_or_none()
    if operacion is None:
        raise NoEncontrado("Esa fusión no existe.")
    if operacion.status != "done":
        raise ReglaDeNegocio(
            "Esta fusión ya se ha deshecho o no llegó a completarse.",
            codigo="producto_no_fusionado",
        )
    if operacion.undo_deadline is not None and operacion.undo_deadline < ahora():
        raise ReglaDeNegocio(
            f"El plazo para deshacer esta fusión era de {DIAS_PARA_DESHACER} días.",
            codigo="producto_no_fusionado",
        )

    hijas = list(
        (
            await alcance.sesion.execute(
                select(MergeOperation).where(
                    MergeOperation.parent_merge_operation_id == operacion.id
                )
            )
        ).scalars()
    )
    for una in [operacion, *hijas]:
        await _revertir_cambios(alcance, una)
        una.status = "reverted"
        una.reverted_at = ahora()
        una.reverted_by_id = alcance.usuario.id
    await alcance.sesion.flush()

    # Las observaciones han vuelto a su producto: hay que recontar los dos lados.
    afectados = {operacion.target_id, *(una.source_id for una in [operacion, *hijas])}
    for product_id in afectados:
        producto = await alcance.sesion.get(Product, product_id)
        if producto is not None:
            await alcance.sesion.refresh(producto)
            await refrescar_producto(alcance.sesion, producto)
    await alcance.sesion.commit()
    return await _resultado_fusion(alcance, operacion, hijas)


@router.post(
    "/products/merge",
    tags=["products"],
    summary="Fusiona productos duplicados",
)
async def fusionar(
    alcance: AlcanceEscritura, datos: ProductoFusionCrear
) -> ProductoFusionResultadoRespuesta:
    """F-39: mueve alias, precios y líneas al destino y archiva los orígenes."""
    destino = await _producto_o_404(alcance, datos.target_id)
    if destino.merged_into_id is not None:
        raise ReglaDeNegocio(
            "El producto destino ya está fusionado en otro.", codigo="fusion_invalida"
        )
    origenes = [await _producto_o_404(alcance, identificador) for identificador in datos.source_ids]
    for origen in origenes:
        if origen.merged_into_id is not None:
            raise ReglaDeNegocio(
                f"«{origen.name}» ya está fusionado en otro producto.",
                codigo="fusion_invalida",
            )

    padre: MergeOperation | None = None
    hijas: list[MergeOperation] = []
    for origen in origenes:
        operacion = MergeOperation(
            household_id=alcance.household_id,
            entity_type="product",
            source_id=origen.id,
            target_id=destino.id,
            source_label=origen.name,
            target_label=destino.name,
            status="running",
            options={"keep_aliases": datos.keep_aliases},
            performed_by_id=alcance.usuario.id,
            started_at=ahora(),
            parent_merge_operation_id=padre.id if padre else None,
        )
        alcance.sesion.add(operacion)
        await alcance.sesion.flush()
        if padre is None:
            padre = operacion
        else:
            hijas.append(operacion)

        movidos = await _mover_a(alcance, operacion, origen, destino, datos.keep_aliases)
        origen.merged_into_id = destino.id
        origen.archived_at = origen.archived_at or ahora()
        await _anotar(alcance, operacion, "products", origen.id, "merged_into_id", None, destino.id)
        operacion.counts = movidos
        operacion.source_snapshot = {
            "name": origen.name,
            "grouping_key": origen.grouping_key,
            "canonical_name": origen.canonical_name,
        }
        operacion.status = "done"
        operacion.finished_at = ahora()
        operacion.undo_deadline = ahora() + timedelta(days=DIAS_PARA_DESHACER)

    assert padre is not None  # noqa: S101 - `source_ids` tiene min_length=1
    await refrescar_producto(alcance.sesion, destino)
    for origen in origenes:
        await refrescar_producto(alcance.sesion, origen)
    await alcance.sesion.commit()
    return await _resultado_fusion(alcance, padre, hijas)


async def _mover_a(
    alcance: AlcanceHogar,
    operacion: MergeOperation,
    origen: Product,
    destino: Product,
    conservar_alias: bool,
) -> dict[str, int]:
    """Reasigna precios, líneas y alias del origen al destino, con diario."""
    contadores = {"prices": 0, "invoice_lines": 0, "aliases": 0}

    for observacion in (
        (
            await alcance.sesion.execute(
                select(ProductPrice).where(
                    ProductPrice.household_id == alcance.household_id,
                    ProductPrice.product_id == origen.id,
                )
            )
        )
        .scalars()
        .all()
    ):
        await _anotar(
            alcance,
            operacion,
            "product_prices",
            observacion.id,
            "product_id",
            origen.id,
            destino.id,
        )
        observacion.product_id = destino.id
        contadores["prices"] += 1

    for linea in (
        (
            await alcance.sesion.execute(
                select(InvoiceLine).where(
                    InvoiceLine.household_id == alcance.household_id,
                    InvoiceLine.product_id == origen.id,
                )
            )
        )
        .scalars()
        .all()
    ):
        await _anotar(
            alcance, operacion, "invoice_lines", linea.id, "product_id", origen.id, destino.id
        )
        linea.product_id = destino.id
        contadores["invoice_lines"] += 1

    alias = list(
        (
            await alcance.sesion.execute(
                select(ProductAlias).where(
                    ProductAlias.household_id == alcance.household_id,
                    ProductAlias.product_id == origen.id,
                )
            )
        ).scalars()
    )
    for uno in alias:
        if conservar_alias:
            await _anotar(
                alcance,
                operacion,
                "product_aliases",
                uno.id,
                "product_id",
                origen.id,
                destino.id,
            )
            uno.product_id = destino.id
        else:
            alcance.sesion.add(
                MergeOperationChange(
                    household_id=alcance.household_id,
                    merge_operation_id=operacion.id,
                    table_name="product_aliases",
                    row_pk=uno.id,
                    change_type="delete",
                    old_row={
                        "product_id": str(uno.product_id),
                        "normalized_text": uno.normalized_text,
                        "match_method": uno.match_method,
                    },
                )
            )
            await alcance.sesion.delete(uno)
        contadores["aliases"] += 1
    await alcance.sesion.flush()
    return contadores


async def _anotar(
    alcance: AlcanceHogar,
    operacion: MergeOperation,
    tabla: str,
    fila: uuidlib.UUID,
    columna: str,
    antes: Any,
    despues: Any,
) -> None:
    """Una línea del diario de deshacer por cada valor que cambia."""
    alcance.sesion.add(
        MergeOperationChange(
            household_id=alcance.household_id,
            merge_operation_id=operacion.id,
            table_name=tabla,
            row_pk=fila,
            change_type="update",
            column_name=columna,
            old_value=str(antes) if antes is not None else None,
            new_value=str(despues) if despues is not None else None,
        )
    )


_TABLAS_DESHACER = {
    "product_prices": ProductPrice,
    "invoice_lines": InvoiceLine,
    "product_aliases": ProductAlias,
    "products": Product,
}


async def _revertir_cambios(alcance: AlcanceHogar, operacion: MergeOperation) -> None:
    """Recorre el diario al revés y devuelve cada valor a su sitio."""
    cambios = list(
        (
            await alcance.sesion.execute(
                select(MergeOperationChange)
                .where(MergeOperationChange.merge_operation_id == operacion.id)
                .order_by(MergeOperationChange.seq.desc())
            )
        ).scalars()
    )
    for cambio in cambios:
        modelo = _TABLAS_DESHACER.get(cambio.table_name)
        if modelo is None:
            continue
        if cambio.change_type == "update" and cambio.column_name:
            valor = uuidlib.UUID(cambio.old_value) if cambio.old_value else None
            await alcance.sesion.execute(
                update(modelo).where(modelo.id == cambio.row_pk).values({cambio.column_name: valor})
            )
        elif cambio.change_type == "delete" and cambio.old_row:
            alcance.sesion.add(
                ProductAlias(
                    id=cambio.row_pk,
                    household_id=alcance.household_id,
                    product_id=uuidlib.UUID(cambio.old_row["product_id"]),
                    normalized_text=cambio.old_row["normalized_text"],
                    match_method=cambio.old_row["match_method"],
                )
            )
    # El origen vuelve a estar vivo: la lápida de fusión se retira.
    await alcance.sesion.execute(
        update(Product)
        .where(Product.id == operacion.source_id)
        .values(merged_into_id=None, archived_at=None)
    )
    await alcance.sesion.flush()


async def _respuesta_fusion(
    alcance: AlcanceHogar, operacion: MergeOperation
) -> ProductoFusionRespuesta:
    await cargado(alcance.sesion, operacion)
    hijas = list(
        (
            await alcance.sesion.execute(
                select(MergeOperation).where(
                    MergeOperation.parent_merge_operation_id == operacion.id
                )
            )
        ).scalars()
    )
    origenes = [operacion.source_id, *[hija.source_id for hija in hijas]]
    productos = {
        producto.id: producto
        for producto in (
            await alcance.sesion.execute(
                select(Product).where(Product.id.in_([*origenes, operacion.target_id]))
            )
        ).scalars()
    }
    destino = productos.get(operacion.target_id)
    plazo = operacion.undo_deadline or (operacion.created_at + timedelta(days=DIAS_PARA_DESHACER))
    return ProductoFusionRespuesta(
        id=operacion.id,
        target=ref_producto(destino) if destino else None,
        sources=[ref_producto(productos[o]) for o in origenes if o in productos],
        prices_moved=int(operacion.counts.get("prices", 0)),
        performed_at=operacion.finished_at or operacion.created_at,
        undo_available_until=plazo,
        undone_at=operacion.reverted_at,
        can_undo=operacion.status == "done" and plazo > ahora(),
    )


async def _resultado_fusion(
    alcance: AlcanceHogar, padre: MergeOperation, hijas: list[MergeOperation]
) -> ProductoFusionResultadoRespuesta:
    todas = [padre, *hijas]
    for operacion in todas:
        await cargado(alcance.sesion, operacion)
    origenes = [operacion.source_id for operacion in todas]
    productos = {
        producto.id: producto
        for producto in (
            await alcance.sesion.execute(
                select(Product).where(Product.id.in_([*origenes, padre.target_id]))
            )
        ).scalars()
    }
    plazo = padre.undo_deadline or (padre.created_at + timedelta(days=DIAS_PARA_DESHACER))
    return ProductoFusionResultadoRespuesta(
        merge_id=padre.id,
        target=ref_producto(productos[padre.target_id]),
        sources=[ref_producto(productos[o]) for o in origenes if o in productos],
        prices_moved=sum(int(o.counts.get("prices", 0)) for o in todas),
        invoice_lines_moved=sum(int(o.counts.get("invoice_lines", 0)) for o in todas),
        aliases_moved=sum(int(o.counts.get("aliases", 0)) for o in todas),
        performed_at=padre.finished_at or padre.created_at,
        undo_available_until=plazo,
    )


@router.get("/products", tags=["products"], summary="Catálogo de productos")
async def listar_productos(
    alcance: Alcance,
    filtro: Annotated[ProductoFiltro, Query()],
) -> Pagina[ProductoRespuesta]:
    consulta: Select = select(Product).where(Product.household_id == alcance.household_id)
    if filtro.q:
        patron = f"%{sin_acentos(filtro.q).lower()}%"
        consulta = consulta.where(
            or_(Product.canonical_name.ilike(patron), Product.name.ilike(patron))
        )
    if filtro.category_id:
        consulta = consulta.where(Product.category_id == filtro.category_id)
    if filtro.is_archived is not None:
        consulta = consulta.where(
            Product.archived_at.is_not(None)
            if filtro.is_archived
            else Product.archived_at.is_(None)
        )
    else:
        consulta = consulta.where(Product.merged_into_id.is_(None))
    if filtro.payee_id:
        vistos = select(ProductPrice.product_id).where(
            ProductPrice.household_id == alcance.household_id,
            ProductPrice.payee_id == filtro.payee_id,
        )
        consulta = consulta.where(Product.id.in_(vistos))

    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()

    columnas = {
        "name": Product.name,
        "last_price": Product.last_unit_price,
        "observations": Product.price_observation_count,
        "last_seen_on": Product.last_seen_on,
        "created_at": Product.created_at,
        # `change_pct` no es una columna: se ordena por el último precio y la
        # variación exacta se calcula abajo, con el servicio de precios.
        "change_pct": Product.last_unit_price,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    consulta = consulta.order_by(Product.id)

    productos = list(
        (
            await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size))
        ).scalars()
    )
    resumen = await _estadisticas_basicas(
        alcance.sesion, alcance.household_id, [p.id for p in productos]
    )
    categorias = await _categorias_ref(
        alcance.sesion, alcance.household_id, [p.category_id for p in productos]
    )
    umbral = await _umbral_subida(alcance.sesion, alcance.household_id)
    filas = [
        respuesta_producto(
            producto,
            resumen.get(producto.id, {}),
            categoria=categorias.get(producto.category_id),
            umbral_subida=umbral,
        )
        for producto in productos
    ]
    if filtro.has_increase is not None:
        filas = [fila for fila in filas if fila.has_increase is filtro.has_increase]
    return Pagina.crear(filas, page=filtro.page, size=filtro.size, total=total)


@router.post(
    "/products",
    tags=["products"],
    status_code=status.HTTP_201_CREATED,
    summary="Crea un producto",
)
async def crear(alcance: AlcanceEscritura, datos: ProductoCrear) -> ProductoRespuesta:
    producto = await crear_producto(alcance, datos)
    await alcance.sesion.commit()
    await cargado(alcance.sesion, producto)
    categorias = await _categorias_ref(alcance.sesion, alcance.household_id, [producto.category_id])
    return respuesta_producto(producto, {}, categoria=categorias.get(producto.category_id))


@router.get("/products/{product_id}", tags=["products"], summary="Detalle del producto")
async def detalle_producto(alcance: Alcance, product_id: uuidlib.UUID) -> ProductoRespuesta:
    producto = await _producto_o_404(alcance, product_id)
    resumen = await _estadisticas_basicas(alcance.sesion, alcance.household_id, [producto.id])
    historial = await puntos_por_producto(alcance.sesion, alcance.household_id, [producto.id])
    estadisticas = estadisticas_de(producto.id, historial.get(producto.id, []))
    categorias = await _categorias_ref(alcance.sesion, alcance.household_id, [producto.category_id])
    return respuesta_producto(
        producto,
        resumen.get(producto.id, {}),
        categoria=categorias.get(producto.category_id),
        umbral_subida=await _umbral_subida(alcance.sesion, alcance.household_id),
        change_pct_12m=estadisticas.change_pct_12m,
    )


@router.patch("/products/{product_id}", tags=["products"], summary="Corrige el producto")
async def actualizar_producto(
    alcance: AlcanceEscritura, product_id: uuidlib.UUID, datos: ProductoActualizar
) -> ProductoRespuesta:
    producto = await _producto_o_404(alcance, product_id)
    campos = datos.model_dump(exclude_unset=True)

    if "is_archived" in campos:
        producto.archived_at = ahora() if campos.pop("is_archived") else None
    if "default_category_id" in campos:
        nueva = campos.pop("default_category_id")
        await _tematica_del_hogar(alcance, nueva)
        producto.category_id = nueva
    if "note" in campos:
        producto.notes = campos.pop("note")
    for campo in ("name", "brand", "barcode"):
        if campo in campos:
            setattr(producto, campo, campos.pop(campo))
    for campo in ("unit", "size_unit"):
        if campo in campos:
            setattr(producto, campo, _u8(campos.pop(campo)))
    if "size_value" in campos:
        producto.size_value = campos.pop("size_value")
    if (producto.size_value is None) != (producto.size_unit is None):
        raise ReglaDeNegocio("Indica el tamaño y su unidad, o ninguno de los dos.")

    # Renombrar o cambiar el tamaño cambia la identidad de agrupación.
    normalizada = normalizada_con_tamanyo(
        producto.name,
        size_value=producto.size_value,
        size_unit=producto.size_unit,
        barcode=producto.barcode,
    )
    producto.canonical_name = normalizada.canonica
    producto.grouping_key = clave_agrupacion(normalizada)
    await alcance.sesion.commit()
    return await detalle_producto(alcance, product_id)


@router.delete(
    "/products/{product_id}",
    tags=["products"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra el producto",
)
async def borrar_producto(
    alcance: AlcanceEscritura,
    product_id: uuidlib.UUID,
    reassign_to: uuidlib.UUID | None = None,
    force: bool = False,
) -> Response:
    producto = await _producto_o_404(alcance, product_id)
    observaciones = (
        await alcance.sesion.execute(
            select(func.count(ProductPrice.id)).where(
                ProductPrice.household_id == alcance.household_id,
                ProductPrice.product_id == producto.id,
            )
        )
    ).scalar_one()
    if observaciones and not (reassign_to or force):
        raise Conflicto(
            f"Este producto tiene {observaciones} precios en el histórico. "
            "Indica a qué producto reasignarlos o confirma el borrado con force.",
            codigo="conflicto",
        )
    if reassign_to:
        destino = await _producto_o_404(alcance, reassign_to)
        await alcance.sesion.execute(
            update(ProductPrice)
            .where(
                ProductPrice.household_id == alcance.household_id,
                ProductPrice.product_id == producto.id,
            )
            .values(product_id=destino.id)
        )
        await refrescar_producto(alcance.sesion, destino)
    elif force:
        await alcance.sesion.execute(
            delete(ProductPrice).where(
                ProductPrice.household_id == alcance.household_id,
                ProductPrice.product_id == producto.id,
            )
        )
    await alcance.sesion.execute(
        update(InvoiceLine)
        .where(
            InvoiceLine.household_id == alcance.household_id,
            InvoiceLine.product_id == producto.id,
        )
        .values(product_id=None, match_method="none", match_score=None)
    )
    await alcance.sesion.delete(producto)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/products/{product_id}/split",
    tags=["products"],
    summary="Separa un producto mal fusionado",
)
async def separar_producto(
    alcance: AlcanceEscritura, product_id: uuidlib.UUID, datos: ProductoSepararCrear
) -> ProductoSepararResultadoRespuesta:
    """RN-65: mueve observaciones, líneas y alias al destino y recalcula ambos."""
    origen = await _producto_o_404(alcance, product_id)
    if datos.target_product_id:
        destino = await _producto_o_404(alcance, datos.target_product_id)
        if destino.id == origen.id:
            raise ReglaDeNegocio("El destino tiene que ser un producto distinto.")
    else:
        assert datos.new_product is not None  # noqa: S101 - lo garantiza el esquema
        destino = await crear_producto(alcance, datos.new_product)

    observaciones = select(ProductPrice).where(
        ProductPrice.household_id == alcance.household_id,
        ProductPrice.product_id == origen.id,
    )
    condiciones = []
    if datos.price_ids:
        condiciones.append(ProductPrice.id.in_(datos.price_ids))
    if datos.payee_id:
        condiciones.append(ProductPrice.payee_id == datos.payee_id)
    alias_movibles: list[ProductAlias] = []
    if datos.alias_ids:
        alias_movibles = list(
            (
                await alcance.sesion.execute(
                    select(ProductAlias).where(
                        ProductAlias.household_id == alcance.household_id,
                        ProductAlias.product_id == origen.id,
                        ProductAlias.id.in_(datos.alias_ids),
                    )
                )
            ).scalars()
        )
        textos = [alias.normalized_text for alias in alias_movibles]
        if textos:
            lineas = select(InvoiceLine.id).where(
                InvoiceLine.household_id == alcance.household_id,
                InvoiceLine.normalized_description.in_(textos),
            )
            condiciones.append(ProductPrice.invoice_line_id.in_(lineas))
    if condiciones:
        observaciones = observaciones.where(or_(*condiciones))

    movidas = list((await alcance.sesion.execute(observaciones)).scalars())
    lineas_movidas = 0
    for observacion in movidas:
        observacion.product_id = destino.id
        if observacion.invoice_line_id:
            resultado = await alcance.sesion.execute(
                update(InvoiceLine)
                .where(
                    InvoiceLine.id == observacion.invoice_line_id,
                    InvoiceLine.product_id == origen.id,
                )
                .values(product_id=destino.id, match_method="manual")
            )
            lineas_movidas += resultado.rowcount or 0
    for alias in alias_movibles:
        alias.product_id = destino.id
        alias.match_method = "manual"
        alias.confirmed_at = ahora()

    await alcance.sesion.flush()
    await refrescar_producto(alcance.sesion, origen)
    await refrescar_producto(alcance.sesion, destino)
    await alcance.sesion.commit()
    return ProductoSepararResultadoRespuesta(
        source=ref_producto(origen),
        target=ref_producto(destino),
        prices_moved=len(movidas),
        invoice_lines_moved=lineas_movidas,
        aliases_moved=len(alias_movibles),
    )


# --------------------------------------------------------------------------- #
# Alias
# --------------------------------------------------------------------------- #


def _respuesta_alias(alias: ProductAlias, comercio: Payee | None = None) -> AliasProductoRespuesta:
    return AliasProductoRespuesta(
        id=alias.id,
        product_id=alias.product_id,
        raw_description=alias.raw_sample or alias.normalized_text,
        normalized=alias.normalized_text,
        payee=ref_comercio(comercio),
        times_seen=alias.times_seen,
        source="manual" if alias.match_method == "manual" else "invoice",
        created_at=alias.created_at,
    )


@router.get("/products/{product_id}/aliases", tags=["products"], summary="Grafías reconocidas")
async def listar_alias(alcance: Alcance, product_id: uuidlib.UUID) -> list[AliasProductoRespuesta]:
    await _producto_o_404(alcance, product_id)
    filas = (
        await alcance.sesion.execute(
            select(ProductAlias)
            .where(
                ProductAlias.household_id == alcance.household_id,
                ProductAlias.product_id == product_id,
            )
            .order_by(ProductAlias.times_seen.desc())
        )
    ).scalars()
    return [_respuesta_alias(alias) for alias in filas]


@router.post(
    "/products/{product_id}/aliases",
    tags=["products"],
    status_code=status.HTTP_201_CREATED,
    summary="Añade un alias a mano",
)
async def crear_alias(
    alcance: AlcanceEscritura, product_id: uuidlib.UUID, datos: AliasProductoCrear
) -> AliasProductoRespuesta:
    await _producto_o_404(alcance, product_id)
    normalizada = normalizar_descripcion(datos.raw_description)
    existente = (
        await alcance.sesion.execute(
            select(ProductAlias).where(
                ProductAlias.household_id == alcance.household_id,
                ProductAlias.normalized_text == normalizada.canonica,
                ProductAlias.product_id != product_id,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        raise Conflicto("Esa descripción ya está aprendida para otro producto.", codigo="conflicto")
    alias = await aprender_alias(
        alcance, product_id, normalizada.canonica, bruto=datos.raw_description
    )
    await alcance.sesion.commit()
    assert alias is not None  # noqa: S101 - la descripción tiene min_length=2
    await cargado(alcance.sesion, alias)
    return _respuesta_alias(alias)


@router.delete(
    "/products/{product_id}/aliases/{alias_id}",
    tags=["products"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quita un alias mal aprendido",
)
async def borrar_alias(
    alcance: AlcanceEscritura, product_id: uuidlib.UUID, alias_id: uuidlib.UUID
) -> Response:
    alias = (
        await alcance.sesion.execute(
            select(ProductAlias).where(
                ProductAlias.household_id == alcance.household_id,
                ProductAlias.product_id == product_id,
                ProductAlias.id == alias_id,
            )
        )
    ).scalar_one_or_none()
    if alias is None:
        raise NoEncontrado("Ese alias no existe.")
    await alcance.sesion.delete(alias)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Precios
# --------------------------------------------------------------------------- #


async def respuesta_precio(
    alcance: AlcanceHogar,
    observacion: ProductPrice,
    *,
    productos: dict[uuidlib.UUID, Product] | None = None,
    comercios: dict[uuidlib.UUID, Payee] | None = None,
    invoice_id: uuidlib.UUID | None = None,
) -> PrecioRespuesta:
    await cargado(alcance.sesion, observacion)
    producto = (productos or {}).get(observacion.product_id)
    if producto is None:
        producto = await _producto_o_404(alcance, observacion.product_id)
    comercio = (comercios or {}).get(observacion.payee_id) if observacion.payee_id else None
    cambio = float(observacion.change_pct) if observacion.change_pct is not None else None
    return PrecioRespuesta(
        id=observacion.id,
        product_id=observacion.product_id,
        product=ref_producto(producto),
        payee=ref_comercio(comercio),
        observed_at=observacion.priced_on,
        unit_price=observacion.unit_price,
        unit=observacion.unit,
        quantity=observacion.quantity,
        total=observacion.line_total,
        currency=observacion.currency,
        source=OrigenPrecio(observacion.source),
        invoice_id=invoice_id,
        invoice_line_id=observacion.invoice_line_id,
        change_pct=cambio,
        change_basis="same_payee" if observacion.payee_id else "global",
        is_increase=cambio is not None and cambio > 0,
        created_at=observacion.created_at,
    )


@router.get("/products/{product_id}/prices", tags=["prices"], summary="Historial de precios")
async def historial_de_producto(
    alcance: Alcance,
    product_id: uuidlib.UUID,
    filtro: Annotated[PrecioFiltro, Query()],
) -> Pagina[PrecioRespuesta]:
    """F-15: fecha, comercio, precio unitario, unidad, cantidad y factura."""
    await _producto_o_404(alcance, product_id)
    return await _pagina_de_precios(alcance, filtro, product_id=product_id)


@router.get("/prices", tags=["prices"], summary="Observaciones de precio")
async def listar_precios(
    alcance: Alcance, filtro: Annotated[PrecioFiltro, Query()]
) -> Pagina[PrecioRespuesta]:
    return await _pagina_de_precios(alcance, filtro, product_id=filtro.product_id)


async def _pagina_de_precios(
    alcance: AlcanceHogar,
    filtro: PrecioFiltro,
    *,
    product_id: uuidlib.UUID | None,
) -> Pagina[PrecioRespuesta]:
    consulta = select(ProductPrice).where(ProductPrice.household_id == alcance.household_id)
    if product_id:
        consulta = consulta.where(ProductPrice.product_id == product_id)
    if filtro.payee_id:
        consulta = consulta.where(ProductPrice.payee_id == filtro.payee_id)
    if filtro.date_from:
        consulta = consulta.where(ProductPrice.priced_on >= filtro.date_from)
    if filtro.date_to:
        consulta = consulta.where(ProductPrice.priced_on <= filtro.date_to)
    if filtro.source:
        consulta = consulta.where(ProductPrice.source == filtro.source.value)
    if filtro.invoice_id:
        lineas = select(InvoiceLine.id).where(
            InvoiceLine.household_id == alcance.household_id,
            InvoiceLine.invoice_id == filtro.invoice_id,
        )
        consulta = consulta.where(ProductPrice.invoice_line_id.in_(lineas))

    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    columnas = {
        "observed_at": ProductPrice.priced_on,
        "unit_price": ProductPrice.unit_price,
        "created_at": ProductPrice.created_at,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    observaciones = list(
        (
            await alcance.sesion.execute(
                consulta.order_by(ProductPrice.id).offset(filtro.desplazamiento).limit(filtro.size)
            )
        ).scalars()
    )

    productos = {
        producto.id: producto
        for producto in (
            await alcance.sesion.execute(
                select(Product).where(
                    Product.id.in_([o.product_id for o in observaciones] or [uuidlib.uuid4()])
                )
            )
        ).scalars()
    }
    comercios = {
        comercio.id: comercio
        for comercio in (
            await alcance.sesion.execute(
                select(Payee).where(Payee.household_id == alcance.household_id)
            )
        ).scalars()
    }
    facturas = dict(
        (
            await alcance.sesion.execute(
                select(InvoiceLine.id, InvoiceLine.invoice_id).where(
                    InvoiceLine.id.in_(
                        [o.invoice_line_id for o in observaciones if o.invoice_line_id]
                        or [uuidlib.uuid4()]
                    )
                )
            )
        ).all()
    )
    filas = [
        await respuesta_precio(
            alcance,
            observacion,
            productos=productos,
            comercios=comercios,
            invoice_id=facturas.get(observacion.invoice_line_id),
        )
        for observacion in observaciones
    ]
    return Pagina.crear(filas, page=filtro.page, size=filtro.size, total=total)


@router.post(
    "/prices",
    tags=["prices"],
    status_code=status.HTTP_201_CREATED,
    summary="Registra un precio visto",
)
async def crear_precio(alcance: AlcanceEscritura, datos: PrecioCrear) -> PrecioRespuesta:
    """Un escaparate, una etiqueta del súper: precio sin factura detrás."""
    producto = await _producto_o_404(alcance, datos.product_id)
    await _comercio_del_hogar(alcance, datos.payee_id)
    repetido = (
        await alcance.sesion.execute(
            select(ProductPrice.id).where(
                ProductPrice.household_id == alcance.household_id,
                ProductPrice.product_id == producto.id,
                ProductPrice.payee_id == datos.payee_id,
                ProductPrice.priced_on == datos.observed_at,
                ProductPrice.unit_price == datos.unit_price,
            )
        )
    ).scalar_one_or_none()
    if repetido is not None:
        raise Conflicto("Ya has registrado ese mismo precio para ese día y comercio.")
    observacion, _ = await registrar_observacion(
        alcance,
        producto=producto,
        fecha=datos.observed_at,
        precio_unitario=datos.unit_price,
        unidad=datos.unit,
        cantidad=datos.quantity,
        total=datos.total,
        payee_id=datos.payee_id,
        origen="manual",
        moneda=datos.currency,
    )
    await alcance.sesion.commit()
    return await respuesta_precio(alcance, observacion)


@router.patch("/prices/{price_id}", tags=["prices"], summary="Corrige una observación")
async def actualizar_precio(
    alcance: AlcanceEscritura, price_id: uuidlib.UUID, datos: PrecioActualizar
) -> PrecioRespuesta:
    observacion = (
        await alcance.sesion.execute(
            select(ProductPrice).where(
                ProductPrice.household_id == alcance.household_id, ProductPrice.id == price_id
            )
        )
    ).scalar_one_or_none()
    if observacion is None:
        raise NoEncontrado("Esa observación de precio no existe.")
    campos = datos.model_dump(exclude_unset=True)
    if "observed_at" in campos:
        observacion.priced_on = campos.pop("observed_at")
    if "unit_price" in campos:
        observacion.unit_price = campos.pop("unit_price")
    if "unit" in campos:
        observacion.unit = _u8(campos.pop("unit"))
    if "quantity" in campos:
        observacion.quantity = campos.pop("quantity")
    if "total" in campos:
        observacion.line_total = campos.pop("total")
    if "payee_id" in campos:
        nuevo = campos.pop("payee_id")
        await _comercio_del_hogar(alcance, nuevo)
        observacion.payee_id = nuevo

    variacion = await calcular_variacion(
        alcance.sesion,
        alcance.household_id,
        observacion.product_id,
        precio=observacion.unit_price,
        unidad=observacion.unit,
        payee_id=observacion.payee_id,
        fecha=observacion.priced_on,
        excluir=observacion.id,
    )
    observacion.change_pct = (
        Decimal(str(variacion.porcentaje)) if variacion.porcentaje is not None else None
    )
    producto = await _producto_o_404(alcance, observacion.product_id)
    await refrescar_producto(alcance.sesion, producto)
    await alcance.sesion.commit()
    return await respuesta_precio(alcance, observacion)


@router.delete(
    "/prices/{price_id}",
    tags=["prices"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borra una observación",
)
async def borrar_precio(alcance: AlcanceEscritura, price_id: uuidlib.UUID) -> Response:
    observacion = (
        await alcance.sesion.execute(
            select(ProductPrice).where(
                ProductPrice.household_id == alcance.household_id, ProductPrice.id == price_id
            )
        )
    ).scalar_one_or_none()
    if observacion is None:
        raise NoEncontrado("Esa observación de precio no existe.")
    producto = await _producto_o_404(alcance, observacion.product_id)
    await alcance.sesion.delete(observacion)
    await alcance.sesion.flush()
    await refrescar_producto(alcance.sesion, producto)
    await alcance.sesion.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products/{product_id}/price-stats", tags=["prices"], summary="Estadísticas de precio")
async def estadisticas_precio(
    alcance: Alcance,
    product_id: uuidlib.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
) -> EstadisticasPrecioRespuesta:
    producto = await _producto_o_404(alcance, product_id)
    historial = await puntos_por_producto(
        alcance.sesion, alcance.household_id, [producto.id], desde=date_from, hasta=date_to
    )
    puntos = historial.get(producto.id, [])
    estadisticas = estadisticas_de(producto.id, puntos, desde=date_from, hasta=date_to)
    comercios = await comercios_por_nombre(alcance.sesion, alcance.household_id)
    analisis = analizar_historial(puntos)
    if analisis.comercio_mas_barato:
        estadisticas.cheapest_payee = ref_comercio(comercios.get(analisis.comercio_mas_barato))
    return estadisticas


@router.get(
    "/products/{product_id}/comparison",
    tags=["prices"],
    summary="Comparativa entre comercios",
)
async def comparativa_producto(
    alcance: Alcance,
    product_id: uuidlib.UUID,
    months: Annotated[int, Query(ge=1, le=60)] = 12,
) -> ComparativaProductoRespuesta:
    """F-38: dónde sale más barato el mismo producto."""
    producto = await _producto_o_404(alcance, product_id)
    return await comparativa_de(alcance, producto, meses=months)


# --------------------------------------------------------------------------- #
# Cesta de la compra
# --------------------------------------------------------------------------- #


async def productos_de_cesta(
    alcance: AlcanceHogar, product_ids: list[uuidlib.UUID]
) -> list[Product]:
    """Los productos de la cesta: los indicados, o los habituales del hogar (F-60)."""
    consulta = select(Product).where(
        Product.household_id == alcance.household_id, Product.merged_into_id.is_(None)
    )
    if product_ids:
        consulta = consulta.where(Product.id.in_(product_ids))
    else:
        consulta = consulta.where(Product.is_basket_item.is_(True), Product.archived_at.is_(None))
    return list((await alcance.sesion.execute(consulta.order_by(Product.name))).scalars())


@router.get("/baskets/comparison", tags=["baskets"], summary="Comparativa de cesta")
async def comparativa_cesta(
    alcance: Alcance,
    product_id: Annotated[list[uuidlib.UUID], Query()] = [],  # noqa: B006 - FastAPI lo copia
    months: Annotated[int, Query(ge=1, le=60)] = 3,
) -> CestaInformeRespuesta:
    """Cuánto cuesta la misma cesta en cada comercio, con su cobertura."""
    productos = await productos_de_cesta(alcance, list(product_id))
    if not productos:
        raise ReglaDeNegocio(
            "Indica los productos de la cesta o marca alguno como habitual.",
            codigo="datos_invalidos",
        )
    return await comparar_cesta_de(alcance, productos, meses=months)
