"""Importación de extractos: CSV, OFX y QIF. §3.17 y §5.13 del contrato.

El análisis del CSV es `app/services/importacion.py` tal cual: la detección de
codificación, de delimitador, de la fila de cabecera y del mapeo de columnas ya
está resuelta ahí y aquí no se reimplementa nada de eso. OFX y QIF sí se leen en
este módulo, porque el servicio solo cubre CSV.

Nada se crea hasta el `commit` (RN-67): el análisis solo llena `import_rows`,
que es revisable y corregible fila a fila.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid as uuidlib
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import Alcance, AlcanceEscritura, AlcanceHogar, verificar_csrf
from app.api.v1.facturas import _motor, sanear_nombre
from app.api.v1.productos import ahora, cargado, ref_comercio
from app.core.config import settings
from app.core.errors import AppError, Conflicto, NoEncontrado, ReglaDeNegocio
from app.models.categoria import Category
from app.models.comercio import Payee
from app.models.cuenta import Account
from app.models.importacion import ImportBatch, ImportRow
from app.models.transaccion import Transaction
from app.schemas.categoria import CategoriaRefRespuesta
from app.schemas.comun import Pagina
from app.schemas.importacion import (
    EstadoImportacion,
    FilaImportacionActualizar,
    FilaImportacionFiltro,
    FilaImportacionRespuesta,
    FormatoImportacion,
    ImportacionConfirmarCrear,
    ImportacionEstadoRespuesta,
    ImportacionFiltro,
    ImportacionRespuesta,
    ImportacionResultadoRespuesta,
    MapeoImportacionCrear,
)
from app.services.formato import cuantizar
from app.services.importacion import (
    ErrorImportacion,
    EstadoFila,
    MapeoColumnas,
    calcular_huella,
    importar_csv,
    previsualizar,
)
from app.services.normalizacion import sin_acentos
from app.services.numeros import parsear_decimal, parsear_fecha

logger = logging.getLogger("app.importaciones")

router = APIRouter(dependencies=[Depends(verificar_csrf)])

TROZO = 64 * 1024
SEGUNDOS_DE_ESPERA = 2

#: Clave de la temática «Sin clasificar»: ningún movimiento importado se queda sin.
CLAVE_SIN_CLASIFICAR = "other.unclassified"

#: Correspondencia entre el estado del servicio y el de la tabla intermedia.
ESTADO_DE_FILA = {
    EstadoFila.VALIDA: "new",
    EstadoFila.ERROR: "error",
    EstadoFila.DUPLICADA: "duplicate",
}


# --------------------------------------------------------------------------- #
# Formato por contenido (RN-66)
# --------------------------------------------------------------------------- #


def detectar_formato(datos: bytes) -> FormatoImportacion:
    """Mira el contenido, nunca la extensión del nombre."""
    cabeza = datos[:4096].decode("latin-1").upper()
    if "OFXHEADER" in cabeza or "<OFX>" in cabeza or "<STMTTRN>" in cabeza:
        return FormatoImportacion.OFX
    if "!TYPE:" in cabeza:
        return FormatoImportacion.QIF
    return FormatoImportacion.CSV


_ETIQUETA_OFX = re.compile(r"<([A-Z0-9.]+)>([^<\r\n]*)", re.IGNORECASE)


def leer_ofx(datos: bytes) -> list[dict[str, str]]:
    """Extrae los `STMTTRN` de un OFX, tanto en SGML como en XML."""
    texto = datos.decode("latin-1")
    movimientos: list[dict[str, str]] = []
    for bloque in re.split(r"<STMTTRN>", texto, flags=re.IGNORECASE)[1:]:
        cuerpo = re.split(r"</STMTTRN>", bloque, flags=re.IGNORECASE)[0]
        campos: dict[str, str] = {}
        for etiqueta, valor in _ETIQUETA_OFX.findall(cuerpo):
            limpio = valor.strip()
            if limpio:
                campos.setdefault(etiqueta.upper(), limpio)
        if campos:
            movimientos.append(campos)
    return movimientos


def leer_qif(datos: bytes) -> list[dict[str, str]]:
    """Extrae los movimientos de un QIF: `D` fecha, `T` importe, `P` concepto."""
    texto = datos.decode("latin-1")
    movimientos: list[dict[str, str]] = []
    actual: dict[str, str] = {}
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("!"):
            continue
        if limpia == "^":
            if actual:
                movimientos.append(actual)
            actual = {}
            continue
        actual[limpia[0].upper()] = limpia[1:].strip()
    if actual:
        movimientos.append(actual)
    return movimientos


def _fecha_ofx(texto: str) -> date | None:
    """`20260805120000[+1:CET]` → 2026-08-05."""
    digitos = re.sub(r"\D", "", texto)[:8]
    if len(digitos) != 8:
        return parsear_fecha(texto)
    try:
        return date(int(digitos[:4]), int(digitos[4:6]), int(digitos[6:8]))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Subida
# --------------------------------------------------------------------------- #


async def _leer_flujo(fichero: UploadFile) -> tuple[bytes, str]:
    digestor = hashlib.sha256()
    trozos: list[bytes] = []
    leidos = 0
    while trozo := await fichero.read(TROZO):
        leidos += len(trozo)
        if leidos > settings.max_upload_bytes:
            raise AppError(
                f"El fichero pesa más de {settings.max_upload_mb} MB.",
                codigo="fichero_demasiado_grande",
                estado=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        digestor.update(trozo)
        trozos.append(trozo)
    return b"".join(trozos), digestor.hexdigest()


def _ruta(clave: str) -> Path:
    raiz = settings.upload_dir.resolve()
    destino = (raiz / clave).resolve()
    if raiz not in destino.parents:
        raise NoEncontrado("El fichero de esta importación no está disponible.")
    return destino


@router.post(
    "/imports",
    tags=["imports"],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sube un extracto bancario",
)
async def subir(
    alcance: AlcanceEscritura,
    tareas: BackgroundTasks,
    fichero: Annotated[UploadFile, File(alias="fichero")],
    account_id: Annotated[uuidlib.UUID, Form()],
    format: Annotated[FormatoImportacion | None, Form()] = None,
    mapping_id: Annotated[uuidlib.UUID | None, Form()] = None,
) -> ImportacionRespuesta:
    """Detecta el formato por contenido y analiza en segundo plano (RN-66)."""
    cuenta = await alcance.sesion.get(Account, account_id)
    if cuenta is None or cuenta.household_id != alcance.household_id:
        raise NoEncontrado("Esa cuenta no existe.")

    datos, huella = await _leer_flujo(fichero)
    if not datos.strip():
        raise ReglaDeNegocio("El fichero está vacío.", codigo="datos_invalidos")
    formato = detectar_formato(datos)
    if format is not None and format != formato:
        logger.info("El cliente decía %s y el contenido es %s: manda el contenido", format, formato)

    clave = f"{alcance.usuario.id}/importaciones/{uuidlib.uuid4()}.{formato.value}"
    lote = ImportBatch(
        household_id=alcance.household_id,
        account_id=cuenta.id,
        source_type=formato.value,
        file_name=sanear_nombre(fichero.filename).removesuffix(".pdf") or "extracto",
        file_sha256=huella,
        byte_size=len(datos),
        storage_key=clave,
        status=EstadoImportacion.ANALYZING.value,
        created_by_id=alcance.usuario.id,
    )
    alcance.sesion.add(lote)
    await alcance.sesion.flush()

    destino = _ruta(clave)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    await alcance.sesion.commit()

    tareas.add_task(analizar_lote, _motor(alcance.sesion), lote.id, alcance.household_id)
    return await respuesta_lote(alcance, lote)


# --------------------------------------------------------------------------- #
# Análisis en segundo plano
# --------------------------------------------------------------------------- #


async def analizar_lote(
    motor: AsyncEngine,
    batch_id: uuidlib.UUID,
    household_id: uuidlib.UUID,
    *,
    mapeo_manual: MapeoImportacionCrear | None = None,
) -> None:
    """Interpreta el fichero y llena `import_rows`. Nada más (RN-67)."""
    async with AsyncSession(bind=motor, expire_on_commit=False) as sesion:
        await sesion.execute(
            text("SELECT set_config('app.household_id', :valor, true)"),
            {"valor": str(household_id)},
        )
        lote = (
            await sesion.execute(
                select(ImportBatch).where(
                    ImportBatch.household_id == household_id, ImportBatch.id == batch_id
                )
            )
        ).scalar_one_or_none()
        if lote is None:
            return
        try:
            datos = _ruta(lote.storage_key or "").read_bytes()
        except OSError as exc:
            lote.status = EstadoImportacion.FAILED.value
            lote.error_message = str(exc)
            await sesion.commit()
            return

        await sesion.execute(delete(ImportRow).where(ImportRow.import_batch_id == lote.id))
        huellas = await _huellas_existentes(sesion, household_id, lote.account_id)

        try:
            if lote.source_type == FormatoImportacion.CSV.value:
                await _analizar_csv(sesion, lote, datos, huellas, mapeo_manual)
            else:
                await _analizar_estructurado(sesion, lote, datos, huellas)
        except ErrorImportacion as exc:
            # Columnas sin reconocer: no es un fallo, es que hace falta el mapeo.
            lote.status = EstadoImportacion.NEEDS_MAPPING.value
            lote.error_message = str(exc)
            vista = await run_in_threadpool(previsualizar, datos)
            lote.encoding = str(vista["codificacion"])
            lote.delimiter = str(vista["delimitador"])[:1]
            await sesion.commit()
            return
        except Exception as exc:  # noqa: BLE001 - el lote no puede quedar colgado
            logger.exception("Fallo analizando la importación %s", batch_id)
            lote.status = EstadoImportacion.FAILED.value
            lote.error_message = f"No se ha podido leer el fichero: {exc}"
            await sesion.commit()
            return

        await sesion.commit()


async def _huellas_existentes(
    sesion: AsyncSession, household_id: uuidlib.UUID, account_id: uuidlib.UUID | None
) -> set[str]:
    """Huellas de lo ya registrado en la cuenta, para marcar duplicados (RN-68)."""
    consulta = select(Transaction.import_fingerprint).where(
        Transaction.household_id == household_id,
        Transaction.import_fingerprint.is_not(None),
    )
    if account_id is not None:
        consulta = consulta.where(Transaction.account_id == account_id)
    return {fila for fila in (await sesion.execute(consulta)).scalars() if fila}


async def _analizar_csv(
    sesion: AsyncSession,
    lote: ImportBatch,
    datos: bytes,
    huellas: set[str],
    mapeo_manual: MapeoImportacionCrear | None,
) -> None:
    """Delega en `importar_csv()` y guarda sus filas."""
    columnas: MapeoColumnas | None = None
    sin_cabecera = False
    if mapeo_manual is not None:
        vista = await run_in_threadpool(previsualizar, datos)
        cabecera = [str(celda) for celda in (vista["cabecera"] or [])]
        columnas = mapeo_manual.a_mapeo_columnas(cabecera)
        sin_cabecera = not cabecera

    resultado = await run_in_threadpool(
        importar_csv,
        datos,
        mapeo_manual=columnas,
        sin_cabecera=sin_cabecera,
        huellas_existentes=huellas,
    )

    lote.encoding = resultado.codificacion
    lote.delimiter = resultado.delimitador[:1]
    lote.decimal_separator = ","
    lote.column_mapping = (
        mapeo_manual.model_dump(mode="json")
        if mapeo_manual is not None
        else _mapeo_detectado(resultado.cabecera, resultado.mapeo).model_dump(mode="json")
    )

    for fila in resultado.filas:
        sesion.add(
            ImportRow(
                household_id=lote.household_id,
                import_batch_id=lote.id,
                row_number=fila.numero,
                raw={str(indice): valor for indice, valor in enumerate(fila.crudo)},
                parsed_booked_on=fila.fecha,
                parsed_amount=fila.importe,
                parsed_description=fila.concepto or None,
                fingerprint=fila.huella or None,
                status=ESTADO_DE_FILA[fila.estado],
                message=fila.error,
            )
        )
    _recontar(lote, resultado.filas)
    lote.status = EstadoImportacion.READY.value
    lote.error_message = None
    await sesion.flush()


def _mapeo_detectado(cabecera: list[str], mapeo: MapeoColumnas) -> MapeoImportacionCrear:
    """Traduce los índices del servicio a los nombres de columna del contrato."""

    def nombre(indice: int | None) -> str | None:
        if indice is None:
            return None
        if 0 <= indice < len(cabecera) and str(cabecera[indice]).strip():
            return str(cabecera[indice]).strip()[:120]
        return f"col{indice}"

    return MapeoImportacionCrear(
        date_column=nombre(mapeo.fecha) or "fecha",
        amount_column=nombre(mapeo.importe),
        debit_column=nombre(mapeo.cargo),
        credit_column=nombre(mapeo.abono),
        description_column=nombre(mapeo.concepto),
        balance_column=nombre(mapeo.saldo),
        currency_column=nombre(mapeo.divisa),
        category_column=nombre(mapeo.categoria),
    )


async def _analizar_estructurado(
    sesion: AsyncSession, lote: ImportBatch, datos: bytes, huellas: set[str]
) -> None:
    """OFX y QIF: el fichero ya viene con los campos separados."""
    if lote.source_type == FormatoImportacion.OFX.value:
        crudos = await run_in_threadpool(leer_ofx, datos)
        campos = [
            (
                _fecha_ofx(crudo.get("DTPOSTED", "")),
                parsear_decimal(crudo.get("TRNAMT")),
                (crudo.get("NAME") or crudo.get("MEMO") or "").strip(),
                crudo.get("FITID"),
                crudo,
            )
            for crudo in crudos
        ]
    else:
        crudos = await run_in_threadpool(leer_qif, datos)
        campos = [
            (
                parsear_fecha(crudo.get("D", "")),
                parsear_decimal(crudo.get("T") or crudo.get("U")),
                (crudo.get("P") or crudo.get("M") or "").strip(),
                None,
                crudo,
            )
            for crudo in crudos
        ]

    if not campos:
        raise ValueError("El fichero no contiene movimientos.")

    vistas = set(huellas)
    resumen = {"new": 0, "duplicate": 0, "error": 0}
    for numero, (fecha, importe, concepto, externo, crudo) in enumerate(campos, start=1):
        problemas = []
        if fecha is None:
            problemas.append("no se entiende la fecha")
        if importe is None or importe == 0:
            problemas.append("no se entiende el importe")
        if not concepto:
            problemas.append("falta el concepto")

        if problemas:
            estado = "error"
            huella = None
            mensaje = "; ".join(problemas).capitalize() + "."
        else:
            assert importe is not None  # noqa: S101 - lo garantiza la lista de problemas
            importe = cuantizar(importe)
            huella = calcular_huella(fecha, importe, concepto)
            estado = "duplicate" if huella in vistas else "new"
            mensaje = "Este movimiento ya está registrado." if estado == "duplicate" else None
            vistas.add(huella)
        resumen[estado] += 1

        sesion.add(
            ImportRow(
                household_id=lote.household_id,
                import_batch_id=lote.id,
                row_number=numero,
                raw={clave: str(valor) for clave, valor in crudo.items()},
                parsed_booked_on=fecha,
                parsed_amount=importe if not problemas else None,
                parsed_description=concepto or None,
                parsed_external_id=externo,
                fingerprint=huella,
                status=estado,
                message=mensaje,
            )
        )

    lote.row_count = len(campos)
    lote.duplicate_count = resumen["duplicate"]
    lote.error_count = resumen["error"]
    lote.status = EstadoImportacion.READY.value
    lote.error_message = None
    await sesion.flush()


def _recontar(lote: ImportBatch, filas: list[Any]) -> None:
    lote.row_count = len(filas)
    lote.duplicate_count = sum(1 for fila in filas if fila.estado is EstadoFila.DUPLICADA)
    lote.error_count = sum(1 for fila in filas if fila.estado is EstadoFila.ERROR)


# --------------------------------------------------------------------------- #
# Respuestas
# --------------------------------------------------------------------------- #


async def _contar(alcance: AlcanceHogar, lote: ImportBatch) -> dict[str, int]:
    filas = (
        await alcance.sesion.execute(
            select(ImportRow.status, func.count(ImportRow.id))
            .where(ImportRow.import_batch_id == lote.id)
            .group_by(ImportRow.status)
        )
    ).all()
    return {fila[0]: fila[1] for fila in filas}


async def respuesta_lote(alcance: AlcanceHogar, lote: ImportBatch) -> ImportacionRespuesta:
    await cargado(alcance.sesion, lote)
    cuantos = await _contar(alcance, lote)
    rango = (
        await alcance.sesion.execute(
            select(
                func.min(ImportRow.parsed_booked_on), func.max(ImportRow.parsed_booked_on)
            ).where(ImportRow.import_batch_id == lote.id)
        )
    ).one()
    mapeo = (
        MapeoImportacionCrear.model_validate(lote.column_mapping) if lote.column_mapping else None
    )
    return ImportacionRespuesta(
        id=lote.id,
        created_at=lote.created_at,
        updated_at=lote.updated_at,
        status=EstadoImportacion(lote.status),
        format=FormatoImportacion(lote.source_type),
        account_id=lote.account_id or uuidlib.UUID(int=0),
        filename=lote.file_name,
        size_bytes=lote.byte_size,
        checksum=lote.file_sha256,
        detected_columns=list((lote.column_mapping or {}).keys()) if lote.column_mapping else [],
        detected_delimiter=lote.delimiter,
        detected_encoding=lote.encoding,
        mapping=mapeo,
        rows_total=lote.row_count,
        rows_valid=cuantos.get("new", 0) + cuantos.get("imported", 0),
        rows_duplicated=cuantos.get("duplicate", 0),
        rows_skipped=cuantos.get("skipped", 0),
        rows_error=cuantos.get("error", 0),
        date_from=rango[0],
        date_to=rango[1],
        committed_at=lote.applied_at,
        rolled_back_at=lote.reverted_at,
        transactions_created=lote.imported_count,
        warnings=[],
        error=lote.error_message,
    )


def respuesta_fila(
    fila: ImportRow,
    *,
    comercio: Payee | None = None,
    categoria: Category | None = None,
) -> FilaImportacionRespuesta:
    estados = {
        "new": EstadoFila.VALIDA,
        "imported": EstadoFila.VALIDA,
        "skipped": EstadoFila.VALIDA,
        "duplicate": EstadoFila.DUPLICADA,
        "error": EstadoFila.ERROR,
    }
    return FilaImportacionRespuesta(
        id=fila.id,
        row_number=fila.row_number,
        raw={clave: str(valor) for clave, valor in (fila.raw or {}).items()},
        date=fila.parsed_booked_on,
        amount=fila.parsed_amount,
        description=fila.parsed_description,
        balance=None,
        status=estados.get(fila.status, EstadoFila.VALIDA),
        suggested_payee=ref_comercio(comercio),
        suggested_category=(
            CategoriaRefRespuesta(id=categoria.id, name=categoria.name, color=categoria.color_hex)
            if categoria
            else None
        ),
        matched_rule_id=fila.matched_rule_id,
        is_duplicate=fila.status == "duplicate",
        duplicate_of_id=fila.duplicate_of_id,
        is_skipped=fila.status == "skipped",
        error=fila.message,
        fingerprint=fila.fingerprint,
    )


async def _lote_o_404(alcance: AlcanceHogar, batch_id: uuidlib.UUID) -> ImportBatch:
    lote = (
        await alcance.sesion.execute(
            select(ImportBatch).where(
                ImportBatch.household_id == alcance.household_id, ImportBatch.id == batch_id
            )
        )
    ).scalar_one_or_none()
    if lote is None:
        raise NoEncontrado("Esa importación no existe.")
    return lote


# --------------------------------------------------------------------------- #
# Consulta
# --------------------------------------------------------------------------- #


@router.get("/imports", tags=["imports"], summary="Importaciones")
async def listar(
    alcance: Alcance, filtro: Annotated[ImportacionFiltro, Query()]
) -> Pagina[ImportacionRespuesta]:
    consulta = select(ImportBatch).where(ImportBatch.household_id == alcance.household_id)
    if filtro.status:
        consulta = consulta.where(
            ImportBatch.status.in_([estado.value for estado in filtro.status])
        )
    if filtro.account_id:
        consulta = consulta.where(ImportBatch.account_id == filtro.account_id)
    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    columnas = {
        "created_at": ImportBatch.created_at,
        "committed_at": ImportBatch.applied_at,
        "rows_total": ImportBatch.row_count,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    lotes = list(
        (
            await alcance.sesion.execute(
                consulta.order_by(ImportBatch.id).offset(filtro.desplazamiento).limit(filtro.size)
            )
        ).scalars()
    )
    return Pagina.crear(
        [await respuesta_lote(alcance, lote) for lote in lotes],
        page=filtro.page,
        size=filtro.size,
        total=total,
    )


@router.get("/imports/{batch_id}", tags=["imports"], summary="Detalle de la importación")
async def detalle(alcance: Alcance, batch_id: uuidlib.UUID) -> ImportacionRespuesta:
    return await respuesta_lote(alcance, await _lote_o_404(alcance, batch_id))


@router.get(
    "/imports/{batch_id}/status",
    tags=["imports"],
    response_model=ImportacionEstadoRespuesta,
    summary="Sondeo del análisis",
)
async def estado(
    alcance: Alcance,
    batch_id: uuidlib.UUID,
    respuesta: Response,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Any:
    lote = await _lote_o_404(alcance, batch_id)
    sello = f'"{lote.id}-{lote.status}-{int(lote.updated_at.timestamp() * 1_000_000)}"'
    if if_none_match and sello in {valor.strip() for valor in if_none_match.split(",")}:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": sello})

    cuantos = await _contar(alcance, lote)
    analizando = lote.status == EstadoImportacion.ANALYZING.value
    faltan: list[str] = []
    if lote.status == EstadoImportacion.NEEDS_MAPPING.value:
        faltan = re.findall(r"columnas de: ([^.]+)", lote.error_message or "")
        faltan = [campo.strip() for campo in (faltan[0].split(",") if faltan else [])]
    respuesta.headers["ETag"] = sello
    if analizando:
        respuesta.headers["Retry-After"] = str(SEGUNDOS_DE_ESPERA)
    return ImportacionEstadoRespuesta(
        id=lote.id,
        status=EstadoImportacion(lote.status),
        progress=10 if analizando else 100,
        rows_total=lote.row_count,
        rows_valid=cuantos.get("new", 0) + cuantos.get("imported", 0),
        rows_error=cuantos.get("error", 0),
        missing_fields=faltan,
        error=lote.error_message,
        retry_after_seconds=SEGUNDOS_DE_ESPERA if analizando else None,
    )


@router.get("/imports/{batch_id}/preview", tags=["imports"], summary="Filas interpretadas")
async def previsualizacion(
    alcance: Alcance,
    batch_id: uuidlib.UUID,
    filtro: Annotated[FilaImportacionFiltro, Query()],
) -> Pagina[FilaImportacionRespuesta]:
    """Con temática sugerida, comercio normalizado y marca de duplicado (F-34)."""
    lote = await _lote_o_404(alcance, batch_id)
    consulta = select(ImportRow).where(ImportRow.import_batch_id == lote.id)
    if filtro.only_duplicates:
        consulta = consulta.where(ImportRow.status == "duplicate")
    if filtro.only_errors:
        consulta = consulta.where(ImportRow.status == "error")
    total = (
        await alcance.sesion.execute(select(func.count()).select_from(consulta.subquery()))
    ).scalar_one()
    columnas = {
        "row_number": ImportRow.row_number,
        "date": ImportRow.parsed_booked_on,
        "amount": ImportRow.parsed_amount,
    }
    for campo, descendente in filtro.orden:
        columna = columnas.get(campo)
        if columna is not None:
            consulta = consulta.order_by(columna.desc() if descendente else columna.asc())
    filas = list(
        (
            await alcance.sesion.execute(consulta.offset(filtro.desplazamiento).limit(filtro.size))
        ).scalars()
    )

    comercios = await _comercios(alcance)
    respuestas = []
    for fila in filas:
        comercio = _comercio_para(fila.parsed_description, comercios)
        categoria = None
        if comercio is not None and comercio.default_category_id:
            categoria = await alcance.sesion.get(Category, comercio.default_category_id)
        respuestas.append(respuesta_fila(fila, comercio=comercio, categoria=categoria))
    return Pagina.crear(respuestas, page=filtro.page, size=filtro.size, total=total)


async def _comercios(alcance: AlcanceHogar) -> list[Payee]:
    return list(
        (
            await alcance.sesion.execute(
                select(Payee).where(
                    Payee.household_id == alcance.household_id,
                    Payee.merged_into_id.is_(None),
                )
            )
        ).scalars()
    )


def _normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    return re.sub(r"[^a-z0-9 ]", " ", sin_acentos(texto).lower()).strip()


def _comercio_para(descripcion: str | None, comercios: list[Payee]) -> Payee | None:
    """Reconoce el comercio del concepto del extracto por contención de nombre."""
    plano = _normalizar(descripcion)
    if not plano:
        return None
    mejor: Payee | None = None
    for comercio in comercios:
        aguja = comercio.normalized_name
        if aguja and aguja in plano and (mejor is None or len(aguja) > len(mejor.normalized_name)):
            mejor = comercio
    return mejor


# --------------------------------------------------------------------------- #
# Mapeo y corrección
# --------------------------------------------------------------------------- #


@router.put("/imports/{batch_id}/mapping", tags=["imports"], summary="Fija el mapeo de columnas")
async def fijar_mapeo(
    alcance: AlcanceEscritura,
    batch_id: uuidlib.UUID,
    datos: MapeoImportacionCrear,
    tareas: BackgroundTasks,
) -> ImportacionRespuesta:
    """Reanaliza las filas con el mapeo que indica el usuario (RN-67)."""
    lote = await _lote_o_404(alcance, batch_id)
    if lote.status == EstadoImportacion.COMMITTED.value:
        raise Conflicto("Esta importación ya está confirmada.", codigo="importacion_ya_confirmada")
    lote.column_mapping = datos.model_dump(mode="json")
    lote.status = EstadoImportacion.ANALYZING.value
    lote.delimiter = datos.delimiter[:1]
    lote.decimal_separator = datos.decimal_separator
    lote.date_format = datos.date_format
    await alcance.sesion.commit()
    tareas.add_task(
        analizar_lote,
        _motor(alcance.sesion),
        lote.id,
        alcance.household_id,
        mapeo_manual=datos,
    )
    return await respuesta_lote(alcance, lote)


@router.patch("/imports/{batch_id}/rows/{row_id}", tags=["imports"], summary="Corrige una fila")
async def corregir_fila(
    alcance: AlcanceEscritura,
    batch_id: uuidlib.UUID,
    row_id: uuidlib.UUID,
    datos: FilaImportacionActualizar,
) -> FilaImportacionRespuesta:
    lote = await _lote_o_404(alcance, batch_id)
    if lote.status == EstadoImportacion.COMMITTED.value:
        raise Conflicto("Esta importación ya está confirmada.", codigo="importacion_ya_confirmada")
    fila = (
        await alcance.sesion.execute(
            select(ImportRow).where(
                ImportRow.household_id == alcance.household_id,
                ImportRow.import_batch_id == lote.id,
                ImportRow.id == row_id,
            )
        )
    ).scalar_one_or_none()
    if fila is None:
        raise NoEncontrado("Esa fila no existe en esta importación.")

    campos = datos.model_dump(exclude_unset=True)
    if "date" in campos:
        fila.parsed_booked_on = campos["date"]
    if "amount" in campos:
        fila.parsed_amount = campos["amount"]
    if "description" in campos:
        fila.parsed_description = campos["description"]
    if "is_skipped" in campos:
        fila.status = "skipped" if campos["is_skipped"] else "new"
    if "is_duplicate" in campos:
        fila.status = "duplicate" if campos["is_duplicate"] else "new"
    if campos.get("category_id") is not None:
        categoria = await alcance.sesion.get(Category, campos["category_id"])
        if categoria is None or categoria.household_id != alcance.household_id:
            raise NoEncontrado("Esa temática no existe.")
        # Se guarda en el crudo: la fila intermedia no tiene columna propia.
        fila.raw = {**(fila.raw or {}), "__category_id": str(categoria.id)}
    if campos.get("payee_id") is not None:
        fila.raw = {**(fila.raw or {}), "__payee_id": str(campos["payee_id"])}
    if campos.get("note"):
        fila.raw = {**(fila.raw or {}), "__note": campos["note"]}

    if fila.parsed_booked_on and fila.parsed_amount:
        fila.fingerprint = calcular_huella(
            fila.parsed_booked_on, fila.parsed_amount, fila.parsed_description or ""
        )
        if fila.status == "error":
            fila.status = "new"
            fila.message = None
    await alcance.sesion.commit()
    return respuesta_fila(fila)


# --------------------------------------------------------------------------- #
# Confirmación y reversión
# --------------------------------------------------------------------------- #


@router.post("/imports/{batch_id}/commit", tags=["imports"], summary="Crea las transacciones")
async def confirmar(
    alcance: AlcanceEscritura,
    batch_id: uuidlib.UUID,
    datos: ImportacionConfirmarCrear,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImportacionResultadoRespuesta:
    """RN-69: una importación confirmada no se vuelve a confirmar."""
    lote = await _lote_o_404(alcance, batch_id)
    if lote.status == EstadoImportacion.COMMITTED.value:
        if idempotency_key:
            return ImportacionResultadoRespuesta(
                import_id=lote.id, transactions_created=lote.imported_count
            )
        raise Conflicto("Esta importación ya está confirmada.", codigo="importacion_ya_confirmada")
    if lote.status == EstadoImportacion.NEEDS_MAPPING.value:
        raise ReglaDeNegocio(
            "Faltan columnas por mapear: indica al menos la fecha y el importe.",
            codigo="mapeo_incompleto",
        )
    if lote.status != EstadoImportacion.READY.value:
        raise Conflicto("La importación todavía se está analizando.", codigo="conflicto")
    if lote.account_id is None:
        raise ReglaDeNegocio("La importación no tiene cuenta asociada.", codigo="datos_invalidos")

    defecto = datos.default_category_id
    if defecto is not None:
        categoria = await alcance.sesion.get(Category, defecto)
        if categoria is None or categoria.household_id != alcance.household_id:
            raise NoEncontrado("Esa temática no existe.")
    else:
        defecto = (
            await alcance.sesion.execute(
                select(Category.id).where(
                    Category.household_id == alcance.household_id,
                    Category.template_key == CLAVE_SIN_CLASIFICAR,
                )
            )
        ).scalar_one_or_none()
    if defecto is None:
        raise ReglaDeNegocio(
            "Indica la temática por defecto de la importación.", codigo="datos_invalidos"
        )

    filas = list(
        (
            await alcance.sesion.execute(
                select(ImportRow)
                .where(ImportRow.import_batch_id == lote.id)
                .order_by(ImportRow.row_number)
            )
        ).scalars()
    )
    comercios = await _comercios(alcance)
    creadas = 0
    omitidas = 0
    fallidas = 0
    comercios_creados = 0
    avisos: list[str] = []

    for fila in filas:
        if fila.status in {"skipped", "imported"}:
            omitidas += 1
            continue
        if fila.status == "error":
            fallidas += 1
            continue
        if fila.status == "duplicate" and datos.skip_duplicates:
            omitidas += 1
            continue
        if fila.parsed_booked_on is None or not fila.parsed_amount:
            fallidas += 1
            continue

        comercio = _comercio_para(fila.parsed_description, comercios)
        if comercio is None and datos.create_missing_payees and fila.parsed_description:
            comercio = await _crear_comercio(alcance, fila.parsed_description)
            if comercio is not None:
                comercios.append(comercio)
                comercios_creados += 1

        forzada = (fila.raw or {}).get("__category_id")
        category_id = uuidlib.UUID(forzada) if forzada else None
        if category_id is None and comercio is not None and comercio.default_category_id:
            category_id = comercio.default_category_id

        transaccion = Transaction(
            household_id=alcance.household_id,
            account_id=lote.account_id,
            kind="expense" if fila.parsed_amount < 0 else "income",
            booked_on=fila.parsed_booked_on,
            amount=fila.parsed_amount,
            category_id=category_id or defecto,
            payee_id=comercio.id if comercio else None,
            description=(fila.parsed_description or "")[:500],
            notes=(fila.raw or {}).get("__note"),
            import_batch_id=lote.id,
            external_id=fila.parsed_external_id,
            import_fingerprint=fila.fingerprint,
            categorized_by="import",
            created_by_id=alcance.usuario.id,
        )
        alcance.sesion.add(transaccion)
        await alcance.sesion.flush()
        fila.transaction_id = transaccion.id
        fila.status = "imported"
        creadas += 1

    lote.status = EstadoImportacion.COMMITTED.value
    lote.imported_count = creadas
    lote.applied_at = ahora()
    lote.reverted_at = None
    if fallidas:
        avisos.append(f"{fallidas} filas no se han podido importar.")
    await alcance.sesion.commit()
    return ImportacionResultadoRespuesta(
        import_id=lote.id,
        transactions_created=creadas,
        duplicates_skipped=omitidas,
        rows_failed=fallidas,
        rules_applied=0,
        payees_created=comercios_creados,
        warnings=avisos,
    )


async def _crear_comercio(alcance: AlcanceHogar, concepto: str) -> Payee | None:
    """Da de alta el comercio con las primeras palabras significativas del concepto."""
    plano = _normalizar(concepto)
    palabras = [palabra for palabra in plano.split() if len(palabra) > 2][:3]
    if not palabras:
        return None
    normalizado = " ".join(palabras)
    existente = (
        await alcance.sesion.execute(
            select(Payee).where(
                Payee.household_id == alcance.household_id,
                Payee.normalized_name == normalizado,
            )
        )
    ).scalar_one_or_none()
    if existente is not None:
        return existente
    comercio = Payee(
        household_id=alcance.household_id,
        name=" ".join(palabras).title(),
        normalized_name=normalizado,
        kind="merchant",
    )
    alcance.sesion.add(comercio)
    await alcance.sesion.flush()
    return comercio


@router.post("/imports/{batch_id}/rollback", tags=["imports"], summary="Deshace la importación")
async def revertir(
    alcance: AlcanceEscritura, batch_id: uuidlib.UUID
) -> ImportacionResultadoRespuesta:
    """RN-69: borra **exactamente** las transacciones que creó este lote."""
    lote = await _lote_o_404(alcance, batch_id)
    if lote.status != EstadoImportacion.COMMITTED.value or lote.reverted_at is not None:
        raise Conflicto(
            "Esta importación no está confirmada o ya se ha deshecho.", codigo="conflicto"
        )

    transacciones = list(
        (
            await alcance.sesion.execute(
                select(Transaction).where(
                    Transaction.household_id == alcance.household_id,
                    Transaction.import_batch_id == lote.id,
                )
            )
        ).scalars()
    )
    limite = lote.applied_at
    borrables = [
        transaccion.id
        for transaccion in transacciones
        # Una transacción editada a mano después de importarla no se toca (RN-69).
        if limite is None or transaccion.updated_at <= limite
    ]
    conservadas = len(transacciones) - len(borrables)
    ninguna = [uuidlib.uuid4()]

    # Las filas se desenlazan **antes** de borrar el dinero: `import_rows` tiene un
    # CHECK que exige transacción cuando el estado es `imported`, y el SET NULL de
    # la clave ajena lo rompería a mitad del borrado.
    await alcance.sesion.execute(
        update(ImportRow)
        .where(
            ImportRow.import_batch_id == lote.id,
            ImportRow.transaction_id.in_(borrables or ninguna),
        )
        .values(status="new", transaction_id=None)
    )
    await alcance.sesion.flush()
    await alcance.sesion.execute(
        delete(Transaction).where(
            Transaction.household_id == alcance.household_id,
            Transaction.id.in_(borrables or ninguna),
        )
    )
    borradas = len(borrables)
    lote.reverted_at = ahora()
    lote.imported_count = 0
    await alcance.sesion.commit()
    return ImportacionResultadoRespuesta(
        import_id=lote.id,
        transactions_created=0,
        transactions_deleted=borradas,
        warnings=(
            [f"{conservadas} transacciones se han conservado porque se editaron a mano."]
            if conservadas
            else []
        ),
    )


@router.delete(
    "/imports/{batch_id}",
    tags=["imports"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Descarta la importación",
)
async def borrar(alcance: AlcanceEscritura, batch_id: uuidlib.UUID) -> Response:
    lote = await _lote_o_404(alcance, batch_id)
    if lote.status == EstadoImportacion.COMMITTED.value and lote.reverted_at is None:
        raise Conflicto(
            "Deshaz la importación antes de borrarla.", codigo="importacion_ya_confirmada"
        )
    clave = lote.storage_key
    await alcance.sesion.delete(lote)
    await alcance.sesion.commit()
    if clave:
        _ruta(clave).unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
