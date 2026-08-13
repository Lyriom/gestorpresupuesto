"""Pruebas de la capa de modelos contra PostgreSQL de verdad.

No valen SQLite ni `create_all()`: lo que se comprueba aquí son `CHECK`, índices
parciales, `NULLS NOT DISTINCT`, arrays con GIN, disparadores y claves ajenas
compuestas, y ninguna de esas cosas existe fuera de la migración de Alembic.

El esquema se construye ejecutando `alembic upgrade head` sobre una base de datos
efímera, así que estas pruebas también verifican la migración.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.semillas import PLANTILLAS, copiar_plantillas_a_hogar, sembrar_plantillas
from app.models import (
    Account,
    Attachment,
    BudgetAllocation,
    BudgetPeriod,
    Category,
    CategoryTemplate,
    Household,
    Payee,
    Transaction,
    TransactionSplit,
    User,
)

BACKEND = Path(__file__).resolve().parents[1]

# Base efímera aparte: las pruebas la crean y la destruyen, así que nunca pisan la
# base de desarrollo.
BASE_PRUEBAS = os.environ.get("TEST_DB_NAME", "presupuesto_test")
URL_ADMIN = os.environ.get(
    "TEST_ADMIN_URL", "postgresql+asyncpg://presupuesto:presupuesto@localhost:5432/postgres"
)
URL_PRUEBAS = URL_ADMIN.rsplit("/", 1)[0] + f"/{BASE_PRUEBAS}"

MOTIVO_SIN_POSTGRES = (
    "Hace falta PostgreSQL en marcha: `docker compose up -d db` en la raíz del repositorio."
)


async def _crear_base_vacia() -> None:
    motor = create_async_engine(URL_ADMIN, isolation_level="AUTOCOMMIT")
    try:
        async with motor.connect() as conexion:
            await conexion.execute(text(f'DROP DATABASE IF EXISTS "{BASE_PRUEBAS}" WITH (FORCE)'))
            await conexion.execute(text(f'CREATE DATABASE "{BASE_PRUEBAS}"'))
    finally:
        await motor.dispose()


@pytest.fixture(scope="session")
def esquema() -> str:
    """Base de datos de pruebas con todas las migraciones aplicadas."""
    import asyncio

    try:
        asyncio.run(_crear_base_vacia())
    except Exception as error:  # pragma: no cover - depende del entorno
        pytest.skip(f"{MOTIVO_SIN_POSTGRES} ({error})")

    # En subproceso y no con la API de Alembic porque `alembic/env.py` toma la URL de
    # `settings`, que se lee al importar: la única forma limpia de apuntarlo a otra
    # base es la variable de entorno.
    entorno = {**os.environ, "DATABASE_URL": URL_PRUEBAS}
    proceso = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=entorno,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    return URL_PRUEBAS


@pytest_asyncio.fixture
async def sesion(esquema: str) -> AsyncIterator[AsyncSession]:
    """Sesión sobre la base de pruebas; cada prueba deja su propio hogar."""
    motor = create_async_engine(esquema)
    fabrica = async_sessionmaker(motor, expire_on_commit=False)
    async with fabrica() as sesion:
        yield sesion
        await sesion.rollback()
    await motor.dispose()


@pytest_asyncio.fixture
async def hogar(sesion: AsyncSession) -> Household:
    hogar = Household(name=f"Hogar {uuid.uuid4().hex[:8]}")
    sesion.add(hogar)
    await sesion.commit()
    return hogar


@pytest_asyncio.fixture
async def tematica(sesion: AsyncSession, hogar: Household) -> Category:
    return await _crear_tematica(sesion, hogar, "Alimentación")


async def _crear_tematica(
    sesion: AsyncSession,
    hogar: Household,
    nombre: str,
    madre: Category | None = None,
    **extra: object,
) -> Category:
    """Crea una temática con la caché derivada ya coherente."""
    identificador = uuid.uuid4()
    ruta = [*madre.path_ids, identificador] if madre else [identificador]
    categoria = Category(
        id=identificador,
        household_id=hogar.id,
        parent_id=madre.id if madre else None,
        name=nombre,
        depth=len(ruta) - 1,
        path_ids=ruta,
        sort_key=".".join(f"{i:04d}" for i in range(len(ruta))),
        **extra,
    )
    sesion.add(categoria)
    await sesion.commit()
    return categoria


async def _crear_cuenta(sesion: AsyncSession, hogar: Household, **extra: object) -> Account:
    cuenta = Account(
        household_id=hogar.id,
        name=extra.pop("name", "BBVA Nómina"),  # type: ignore[arg-type]
        type=extra.pop("type", "checking"),  # type: ignore[arg-type]
        account_class=extra.pop("account_class", "asset"),  # type: ignore[arg-type]
        **extra,
    )
    sesion.add(cuenta)
    await sesion.commit()
    return cuenta


async def _crear_transaccion(
    sesion: AsyncSession,
    hogar: Household,
    cuenta: Account,
    categoria: Category | None,
    importe: str = "-25.40",
    **extra: object,
) -> Transaction:
    transaccion = Transaction(
        household_id=hogar.id,
        account_id=cuenta.id,
        category_id=categoria.id if categoria else None,
        kind=extra.pop("kind", "expense"),  # type: ignore[arg-type]
        booked_on=extra.pop("booked_on", date(2026, 8, 1)),  # type: ignore[arg-type]
        amount=Decimal(importe),
        **extra,
    )
    sesion.add(transaccion)
    await sesion.commit()
    return transaccion


# --- CHECK que de verdad pueden romperse -----------------------------------------


async def test_importe_cero_rechazado(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """Una transacción de cero euros es siempre un error de captura."""
    cuenta = await _crear_cuenta(sesion, hogar)
    with pytest.raises(IntegrityError, match="ck_transactions_amount_not_zero"):
        await _crear_transaccion(sesion, hogar, cuenta, tematica, importe="0.00")


async def test_tarjeta_de_credito_no_puede_ser_activo(
    sesion: AsyncSession, hogar: Household
) -> None:
    """`ck_accounts_class_matches_type` es lo que impide un patrimonio neto falso."""
    with pytest.raises(IntegrityError, match="ck_accounts_class_matches_type"):
        await _crear_cuenta(sesion, hogar, type="credit_card", account_class="asset")


async def test_transferencia_sin_grupo_rechazada(sesion: AsyncSession, hogar: Household) -> None:
    cuenta = await _crear_cuenta(sesion, hogar)
    with pytest.raises(IntegrityError, match="ck_transactions_transfer_shape"):
        await _crear_transaccion(sesion, hogar, cuenta, None, kind="transfer")


async def test_transaccion_sin_tematica_ni_splits_rechazada(
    sesion: AsyncSession, hogar: Household
) -> None:
    """El invariante de splits: o hay temática, o hay reparto, o es transferencia."""
    cuenta = await _crear_cuenta(sesion, hogar)
    with pytest.raises(IntegrityError, match="ck_transactions_split_invariant"):
        await _crear_transaccion(sesion, hogar, cuenta, None)


async def test_el_disparador_de_splits_mantiene_el_invariante(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """Al añadir splits, la cabecera pierde su temática y cuadra sola."""
    cuenta = await _crear_cuenta(sesion, hogar)
    hija = await _crear_tematica(sesion, hogar, "Supermercado", tematica)
    transaccion = await _crear_transaccion(sesion, hogar, cuenta, tematica, "-30.00")

    sesion.add_all(
        [
            TransactionSplit(
                household_id=hogar.id,
                transaction_id=transaccion.id,
                category_id=tematica.id,
                amount=Decimal("-20.00"),
                line_number=1,
            ),
            TransactionSplit(
                household_id=hogar.id,
                transaction_id=transaccion.id,
                category_id=hija.id,
                amount=Decimal("-10.00"),
                line_number=2,
            ),
        ]
    )
    await sesion.commit()

    await sesion.refresh(transaccion)
    assert transaccion.split_count == 2
    assert transaccion.split_total == Decimal("-30.00")
    assert transaccion.category_id is None

    # Y si los splits dejan de sumar el importe, el invariante lo impide.
    with pytest.raises(IntegrityError, match="ck_transactions_split_invariant"):
        sesion.add(
            TransactionSplit(
                household_id=hogar.id,
                transaction_id=transaccion.id,
                category_id=hija.id,
                amount=Decimal("-5.00"),
                line_number=3,
            )
        )
        await sesion.commit()
    await sesion.rollback()


async def test_adjunto_necesita_exactamente_un_dueno(
    sesion: AsyncSession, hogar: Household
) -> None:
    adjunto = Attachment(
        household_id=hogar.id,
        file_name="ticket.pdf",
        mime_type="application/pdf",
        byte_size=1024,
        sha256="a" * 64,
        storage_key=f"{hogar.id}/2026/{uuid.uuid4()}.pdf",
    )
    sesion.add(adjunto)
    with pytest.raises(IntegrityError, match="ck_attachments_single_owner"):
        await sesion.commit()
    await sesion.rollback()


async def test_periodo_presupuestario_debe_ser_dia_uno(
    sesion: AsyncSession, hogar: Household
) -> None:
    sesion.add(BudgetPeriod(household_id=hogar.id, period_month=date(2026, 8, 15)))
    with pytest.raises(IntegrityError, match="ck_budget_periods_first_of_month"):
        await sesion.commit()
    await sesion.rollback()


async def test_asignacion_negativa_rechazada(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """Retirar dinero de una temática es bajar su asignación, no ponerla negativa."""
    periodo = BudgetPeriod(household_id=hogar.id, period_month=date(2026, 8, 1))
    sesion.add(periodo)
    await sesion.commit()
    # Se guardan los identificadores: el `rollback` de más abajo caduca los objetos y
    # volver a leer un atributo dispararía IO fuera del contexto asíncrono.
    hogar_id, periodo_id, categoria_id = hogar.id, periodo.id, tematica.id

    sesion.add(
        BudgetAllocation(
            household_id=hogar_id,
            budget_period_id=periodo_id,
            category_id=categoria_id,
            allocated_amount=Decimal("-10.00"),
        )
    )
    with pytest.raises(IntegrityError, match="ck_budget_allocations_allocated_amount"):
        await sesion.commit()
    await sesion.rollback()

    # El arrastre sí puede ser negativo: es el modo `carry_negative`.
    sesion.add(
        BudgetAllocation(
            household_id=hogar_id,
            budget_period_id=periodo_id,
            category_id=categoria_id,
            allocated_amount=Decimal("100.00"),
            carryover_in=Decimal("-15.00"),
            rollover_mode="carry_negative",
        )
    )
    await sesion.commit()


async def test_cache_del_arbol_incoherente_rechazada(
    sesion: AsyncSession, hogar: Household
) -> None:
    """`ck_categories_path_consistent` impide persistir una caché derivada falsa."""
    categoria = Category(
        household_id=hogar.id,
        name="Con ruta mentirosa",
        depth=0,
        path_ids=[uuid.uuid4()],
        sort_key="0001",
    )
    sesion.add(categoria)
    with pytest.raises(IntegrityError, match="ck_categories_path_consistent"):
        await sesion.commit()
    await sesion.rollback()


async def test_lapida_de_fusion_exige_archivado(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    destino = await _crear_tematica(sesion, hogar, "Supermercado")
    tematica.merged_into_id = destino.id
    with pytest.raises(IntegrityError, match="ck_categories_merged_is_archived"):
        await sesion.commit()
    await sesion.rollback()


async def test_factura_confirmada_exige_fecha_y_total(sesion: AsyncSession) -> None:
    """La regla de producto «revisar antes de guardar», traducida a SQL."""
    from app.models import Invoice

    hogar = Household(name="Hogar facturas")
    sesion.add(hogar)
    await sesion.commit()

    factura = Invoice(
        household_id=hogar.id,
        status="confirmed",
        file_name="luz.pdf",
        storage_key=f"{hogar.id}/2026/{uuid.uuid4()}.pdf",
        byte_size=2048,
        content_sha256="b" * 64,
    )
    sesion.add(factura)
    with pytest.raises(IntegrityError, match="ck_invoices_confirmed_needs_data"):
        await sesion.commit()
    await sesion.rollback()


async def test_estados_de_factura_del_contrato(sesion: AsyncSession) -> None:
    """Los cinco estados del contrato de API, `discarded` incluido (RN-46)."""
    from app.models import Invoice

    hogar = Household(name="Hogar estados")
    sesion.add(hogar)
    await sesion.commit()

    for estado in ("processing", "pending_review", "discarded"):
        sesion.add(
            Invoice(
                household_id=hogar.id,
                status=estado,
                file_name=f"{estado}.pdf",
                storage_key=f"{hogar.id}/2026/{uuid.uuid4()}.pdf",
                byte_size=1,
                content_sha256=uuid.uuid4().hex * 2,
            )
        )
    await sesion.commit()

    sesion.add(
        Invoice(
            household_id=hogar.id,
            status="reviewed",  # el estado del borrador, ya inexistente
            file_name="viejo.pdf",
            storage_key=f"{hogar.id}/2026/{uuid.uuid4()}.pdf",
            byte_size=1,
            content_sha256=uuid.uuid4().hex * 2,
        )
    )
    with pytest.raises(IntegrityError, match="ck_invoices_status"):
        await sesion.commit()
    await sesion.rollback()


async def test_estado_needs_mapping_en_lotes_de_importacion(
    sesion: AsyncSession, hogar: Household
) -> None:
    """`needs_mapping` es el estado que hace que la interfaz pida el mapeo (RN-67)."""
    from app.models import ImportBatch

    lote = ImportBatch(
        household_id=hogar.id,
        source_type="csv",
        file_name="extracto.csv",
        file_sha256="c" * 64,
        byte_size=4096,
        status="needs_mapping",
    )
    sesion.add(lote)
    await sesion.commit()
    assert lote.status == "needs_mapping"


# --- Unicidad ---------------------------------------------------------------------


async def test_email_unico_sin_distinguir_mayusculas(sesion: AsyncSession) -> None:
    sufijo = uuid.uuid4().hex[:8]
    sesion.add(
        User(
            email=f"ana.{sufijo}@example.com",
            password_hash="x",
            display_name="Ana",
        )
    )
    await sesion.commit()

    sesion.add(
        User(
            email=f"ANA.{sufijo}@EXAMPLE.COM",
            password_hash="x",
            display_name="Ana otra vez",
        )
    )
    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        await sesion.commit()
    await sesion.rollback()


async def test_dos_raices_no_pueden_llamarse_igual(sesion: AsyncSession, hogar: Household) -> None:
    """Aquí es donde hace falta `NULLS NOT DISTINCT`: `parent_id` es NULL en las dos."""
    await _crear_tematica(sesion, hogar, "Vivienda")
    with pytest.raises(IntegrityError, match="uq_categories_household_id_parent_id_name"):
        await _crear_tematica(sesion, hogar, "VIVIENDA")
    await sesion.rollback()


async def test_el_nombre_se_libera_al_archivar(sesion: AsyncSession, hogar: Household) -> None:
    """El índice único es parcial: una temática archivada deja libre su nombre."""
    original = await _crear_tematica(sesion, hogar, "Ocio")
    original.archived_at = datetime.now(UTC)
    await sesion.commit()
    await _crear_tematica(sesion, hogar, "Ocio")


async def test_una_linea_de_factura_genera_un_solo_split(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """Si no, revisar dos veces la misma factura duplicaría el gasto."""
    from app.models import Invoice, InvoiceLine

    cuenta = await _crear_cuenta(sesion, hogar)
    factura = Invoice(
        household_id=hogar.id,
        file_name="compra.pdf",
        storage_key=f"{hogar.id}/2026/{uuid.uuid4()}.pdf",
        byte_size=10,
        content_sha256=uuid.uuid4().hex * 2,
    )
    sesion.add(factura)
    await sesion.commit()

    linea = InvoiceLine(
        household_id=hogar.id,
        invoice_id=factura.id,
        line_number=1,
        raw_description="LECHE PASCUAL 1L BRIK",
        line_total=Decimal("-6.90"),
    )
    sesion.add(linea)
    await sesion.commit()

    primera = await _crear_transaccion(sesion, hogar, cuenta, tematica, "-6.90")
    sesion.add(
        TransactionSplit(
            household_id=hogar.id,
            transaction_id=primera.id,
            category_id=tematica.id,
            amount=Decimal("-6.90"),
            line_number=1,
            invoice_line_id=linea.id,
        )
    )
    await sesion.commit()

    segunda = await _crear_transaccion(
        sesion, hogar, cuenta, tematica, "-6.90", booked_on=date(2026, 8, 2)
    )
    sesion.add(
        TransactionSplit(
            household_id=hogar.id,
            transaction_id=segunda.id,
            category_id=tematica.id,
            amount=Decimal("-6.90"),
            line_number=1,
            invoice_line_id=linea.id,
        )
    )
    with pytest.raises(IntegrityError, match="uq_transaction_splits_invoice_line_id"):
        await sesion.commit()
    await sesion.rollback()


# --- Tenencia ---------------------------------------------------------------------


async def test_no_se_puede_referenciar_una_tematica_de_otro_hogar(
    sesion: AsyncSession, hogar: Household
) -> None:
    """La FK compuesta convierte la fuga de tenencia en un error de base de datos."""
    otro = Household(name="Hogar vecino")
    sesion.add(otro)
    await sesion.commit()
    ajena = await _crear_tematica(sesion, otro, "Temática ajena")
    cuenta = await _crear_cuenta(sesion, hogar)

    with pytest.raises(IntegrityError, match="fk_transactions_household_id_category_id"):
        await _crear_transaccion(sesion, hogar, cuenta, ajena)
    await sesion.rollback()


async def test_una_madre_de_otro_hogar_es_imposible(sesion: AsyncSession, hogar: Household) -> None:
    otro = Household(name="Hogar vecino 2")
    sesion.add(otro)
    await sesion.commit()
    ajena = await _crear_tematica(sesion, otro, "Raíz ajena")

    with pytest.raises(IntegrityError, match="fk_categories_household_id_parent_id"):
        await _crear_tematica(sesion, hogar, "Hija tránsfuga", ajena)
    await sesion.rollback()


# --- Borrado en cascada y borrado prohibido ---------------------------------------


async def test_borrar_el_hogar_se_lleva_todo(sesion: AsyncSession) -> None:
    """Borrar el hogar es «borrar mi cuenta»: cascada hasta la última fila."""
    hogar = Household(name="Hogar de usar y tirar")
    sesion.add(hogar)
    await sesion.commit()
    tematica = await _crear_tematica(sesion, hogar, "Alimentación")
    cuenta = await _crear_cuenta(sesion, hogar)
    transaccion = await _crear_transaccion(sesion, hogar, cuenta, tematica)
    sesion.add(Payee(household_id=hogar.id, name="Mercadona", normalized_name="mercadona"))
    await sesion.commit()

    await sesion.execute(delete(Household).where(Household.id == hogar.id))
    await sesion.commit()

    for modelo in (Category, Account, Transaction, Payee):
        restantes = await sesion.execute(
            select(modelo).where(modelo.household_id == hogar.id)  # type: ignore[attr-defined]
        )
        assert restantes.first() is None
    assert transaccion.id is not None


async def test_borrar_la_transaccion_se_lleva_sus_splits(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    cuenta = await _crear_cuenta(sesion, hogar)
    transaccion = await _crear_transaccion(sesion, hogar, cuenta, tematica, "-12.00")
    sesion.add(
        TransactionSplit(
            household_id=hogar.id,
            transaction_id=transaccion.id,
            category_id=tematica.id,
            amount=Decimal("-12.00"),
            line_number=1,
        )
    )
    await sesion.commit()

    await sesion.execute(delete(Transaction).where(Transaction.id == transaccion.id))
    await sesion.commit()

    huerfanos = await sesion.execute(
        select(TransactionSplit).where(TransactionSplit.transaction_id == transaccion.id)
    )
    assert huerfanos.first() is None


async def test_una_tematica_con_movimientos_no_se_borra(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """No existe el borrado de temáticas: solo archivar o fusionar."""
    cuenta = await _crear_cuenta(sesion, hogar)
    await _crear_transaccion(sesion, hogar, cuenta, tematica)

    with pytest.raises(IntegrityError, match="RESTRICT|fk_transactions"):
        await sesion.execute(delete(Category).where(Category.id == tematica.id))
        await sesion.commit()
    await sesion.rollback()


async def test_borrar_una_cuenta_con_movimientos_falla(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """Una cuenta con movimientos se archiva: borrarla agujerearía el patrimonio."""
    cuenta = await _crear_cuenta(sesion, hogar)
    await _crear_transaccion(sesion, hogar, cuenta, tematica)

    with pytest.raises(IntegrityError, match="RESTRICT|fk_transactions"):
        await sesion.execute(delete(Account).where(Account.id == cuenta.id))
        await sesion.commit()
    await sesion.rollback()


# --- Jerarquía de temáticas -------------------------------------------------------


async def test_subarbol_y_ancestros(sesion: AsyncSession, hogar: Household) -> None:
    """Se construye un árbol y se consulta con `path_ids`, sin CTE recursiva."""
    vivienda = await _crear_tematica(sesion, hogar, "Vivienda")
    suministros = await _crear_tematica(sesion, hogar, "Suministros", vivienda)
    luz = await _crear_tematica(sesion, hogar, "Luz", suministros)
    gas = await _crear_tematica(sesion, hogar, "Gas", suministros)
    await _crear_tematica(sesion, hogar, "Alimentación")

    assert (luz.depth, gas.depth) == (2, 2)
    assert luz.path_ids == [vivienda.id, suministros.id, luz.id]

    subarbol = (
        (
            await sesion.execute(
                select(Category.name)
                .where(
                    Category.household_id == hogar.id,
                    Category.path_ids.contains([vivienda.id]),
                )
                .order_by(Category.sort_key, Category.name)
            )
        )
        .scalars()
        .all()
    )
    assert set(subarbol) == {"Vivienda", "Suministros", "Luz", "Gas"}

    ancestros = (
        (
            await sesion.execute(
                text(
                    """
                SELECT c.name
                  FROM categories raiz
                  JOIN unnest(raiz.path_ids) WITH ORDINALITY AS p(id, ord) ON true
                  JOIN categories c ON c.id = p.id AND c.household_id = raiz.household_id
                 WHERE raiz.household_id = :hh AND raiz.id = :id
                 ORDER BY p.ord
                """
                ),
                {"hh": hogar.id, "id": luz.id},
            )
        )
        .scalars()
        .all()
    )
    assert ancestros == ["Vivienda", "Suministros", "Luz"]

    # La vista deja la miga de pan lista para los chips de los informes.
    ruta = (
        await sesion.execute(
            text("SELECT full_path FROM vw_category_tree WHERE id = :id"), {"id": luz.id}
        )
    ).scalar_one()
    assert ruta == "Vivienda › Suministros › Luz"


async def test_refresh_category_paths_reconstruye_la_cache(
    sesion: AsyncSession, hogar: Household
) -> None:
    """Mover una rama es un UPDATE de una fila; la caché la rehace la función."""
    vivienda = await _crear_tematica(sesion, hogar, "Vivienda")
    otra = await _crear_tematica(sesion, hogar, "Segunda residencia")
    suministros = await _crear_tematica(sesion, hogar, "Suministros", vivienda)
    luz = await _crear_tematica(sesion, hogar, "Luz", suministros)

    # Se reparenta con SQL crudo, como hace el algoritmo de fusión.
    await sesion.execute(
        text("UPDATE categories SET parent_id = :nueva WHERE id = :id"),
        {"nueva": otra.id, "id": suministros.id},
    )
    tocadas = (
        await sesion.execute(text("SELECT refresh_category_paths(:hh)"), {"hh": hogar.id})
    ).scalar_one()
    await sesion.commit()
    assert tocadas >= 2

    await sesion.refresh(luz)
    assert luz.path_ids == [otra.id, suministros.id, luz.id]
    assert luz.depth == 2

    # Llamarla otra vez no cambia nada: es idempotente.
    repetida = (
        await sesion.execute(text("SELECT refresh_category_paths(:hh)"), {"hh": hogar.id})
    ).scalar_one()
    assert repetida == 0


async def test_un_ciclo_no_puede_persistirse(sesion: AsyncSession, hogar: Household) -> None:
    """`ck_categories_no_cycle` es la red de seguridad de una fusión mal hecha.

    El movimiento que crearía el ciclo se detecta **antes** con la consulta de guarda
    de la sección 3.4; el `CHECK` es la segunda barrera: una rama recalculada en la
    que una temática aparezca entre sus propios ancestros no puede persistirse.
    """
    madre = await _crear_tematica(sesion, hogar, "Madre")
    hija = await _crear_tematica(sesion, hogar, "Hija", madre)

    # Guarda previa: colgar «Madre» de «Hija» crearía un ciclo, porque «Hija» está en
    # el subárbol de «Madre».
    crearia_ciclo = (
        await sesion.execute(
            text(
                "SELECT 1 FROM categories "
                " WHERE household_id = :hh AND id = :nueva_madre "
                "   AND path_ids @> ARRAY[:id]::uuid[]"
            ),
            {"hh": hogar.id, "nueva_madre": hija.id, "id": madre.id},
        )
    ).first()
    assert crearia_ciclo is not None

    with pytest.raises((IntegrityError, DBAPIError), match="ck_categories_no_cycle"):
        await sesion.execute(
            text(
                "UPDATE categories SET parent_id = :hija, path_ids = :ruta, depth = 2 "
                "WHERE id = :madre"
            ),
            {"hija": hija.id, "ruta": [madre.id, hija.id, madre.id], "madre": madre.id},
        )
        await sesion.commit()
    await sesion.rollback()


async def test_profundidad_maxima(sesion: AsyncSession, hogar: Household) -> None:
    """Ocho niveles son un cortafuegos contra un bucle, no un límite funcional."""
    actual = await _crear_tematica(sesion, hogar, "Nivel 0")
    for nivel in range(1, 9):
        actual = await _crear_tematica(sesion, hogar, f"Nivel {nivel}", actual)
    assert actual.depth == 8

    with pytest.raises(IntegrityError, match="ck_categories_depth"):
        await _crear_tematica(sesion, hogar, "Nivel 9", actual)
    await sesion.rollback()


# --- Semillas ---------------------------------------------------------------------


async def test_las_semillas_estan_completas(sesion: AsyncSession) -> None:
    """La migración de semillas ya ha sembrado el catálogo entero."""
    total = (await sesion.execute(select(CategoryTemplate))).scalars().all()
    assert len(total) == len(PLANTILLAS)

    raices = [p for p in total if p.parent_key is None]
    assert len(raices) == 15  # 14 de gasto y 1 de ingreso
    assert {p.color_slot for p in raices} <= set(range(1, 13))
    assert all(p.color_slot is None for p in total if p.parent_key is not None)
    assert all(p.icon for p in total)
    assert max(p.depth for p in total) == 1

    luz = next(p for p in total if p.template_key == "housing.electricity")
    assert (luz.name, luz.icon, luz.parent_key) == ("Luz", "zap", "housing")


async def test_las_semillas_son_idempotentes(sesion: AsyncSession) -> None:
    """Sembrar dos veces no duplica ni cambia el identificador de una plantilla."""
    antes = (
        await sesion.execute(
            select(CategoryTemplate.template_key, CategoryTemplate.id).order_by(
                CategoryTemplate.template_key
            )
        )
    ).all()

    await sembrar_plantillas(sesion)
    await sembrar_plantillas(sesion)
    await sesion.commit()

    despues = (
        await sesion.execute(
            select(CategoryTemplate.template_key, CategoryTemplate.id).order_by(
                CategoryTemplate.template_key
            )
        )
    ).all()
    assert despues == antes


async def test_copiar_las_plantillas_a_un_hogar(sesion: AsyncSession) -> None:
    """El onboarding (F-50) copia el árbol y también es idempotente."""
    hogar = Household(name="Hogar recién registrado")
    sesion.add(hogar)
    await sesion.commit()

    creadas = await copiar_plantillas_a_hogar(sesion, hogar.id)
    await sesion.commit()
    assert creadas == len(PLANTILLAS)

    repetidas = await copiar_plantillas_a_hogar(sesion, hogar.id)
    await sesion.commit()
    assert repetidas == 0

    tematicas = (
        (await sesion.execute(select(Category).where(Category.household_id == hogar.id)))
        .scalars()
        .all()
    )
    assert len(tematicas) == len(PLANTILLAS)

    sin_clasificar = next(t for t in tematicas if t.template_key == "other.unclassified")
    assert sin_clasificar.is_system

    # La caché derivada queda coherente sin llamar a `refresh_category_paths()`.
    pendientes = (
        await sesion.execute(text("SELECT refresh_category_paths(:hh)"), {"hh": hogar.id})
    ).scalar_one()
    assert pendientes == 0

    luz = next(t for t in tematicas if t.template_key == "housing.electricity")
    vivienda = next(t for t in tematicas if t.template_key == "housing")
    assert luz.parent_id == vivienda.id
    assert luz.path_ids == [vivienda.id, luz.id]
    assert luz.color_slot is None and vivienda.color_slot == 1


# --- Marcas de tiempo -------------------------------------------------------------


async def test_el_disparador_actualiza_updated_at_con_sql_crudo(
    sesion: AsyncSession, hogar: Household, tematica: Category
) -> None:
    """`onupdate` es del ORM; el disparador cubre lo que escribe SQL a pelo."""
    anterior = tematica.updated_at
    await sesion.execute(
        text("UPDATE categories SET notes = 'tocado a mano' WHERE id = :id"),
        {"id": tematica.id},
    )
    await sesion.commit()
    await sesion.refresh(tematica)
    assert tematica.updated_at > anterior
    assert tematica.updated_at - tematica.created_at < timedelta(minutes=1)
