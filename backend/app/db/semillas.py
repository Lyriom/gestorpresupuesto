"""Datos semilla: el árbol de temáticas por defecto en español de España.

Las semillas se escriben en `category_templates`, que es **global y sin hogar**: una
migración de datos no puede sembrar filas para usuarios que aún no existen. Con
plantillas, el mismo árbol sirve para el onboarding (F-50), para «restaurar
temáticas por defecto» y para proponer las temáticas nuevas que añada una versión
posterior de la aplicación.

Todo lo de aquí es **idempotente**: se puede ejecutar dos veces sin duplicar nada.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.categoria import Category, CategoryTemplate

# Versión del catálogo. El `downgrade` de la migración de semillas borra por esta
# columna, así que nunca se lleva por delante plantillas de otra versión.
VERSION_CATALOGO = 1

# Clave de la temática de sistema: destino por omisión de las importaciones sin
# regla. No se puede archivar, ni fusionar como origen, ni renombrar.
CLAVE_SIN_CLASIFICAR = "other.unclassified"


class PlantillaTematica(NamedTuple):
    """Una fila del catálogo de plantillas.

    `parent_key` y `depth` no se declaran: se derivan de `template_key`, que ya es
    la ruta (`'housing.electricity'`). Así es imposible que la clave y la jerarquía
    se contradigan.
    """

    template_key: str
    name: str
    icon: str
    kind: str = "expense"
    color_slot: int | None = None

    @property
    def parent_key(self) -> str | None:
        madre, _, hoja = self.template_key.rpartition(".")
        return madre or None

    @property
    def depth(self) -> int:
        return self.template_key.count(".")


# Iconos de Lucide (https://lucide.dev) en kebab-case. Las raíces reciben ranura de
# color 1..12; las subtemáticas **no**, porque heredan el hue de su madre y se
# distinguen por luminosidad. `savings` recicla la ranura 1 y `other` la 5, y las
# temáticas de ingreso comparten la 5 porque el sistema de diseño reserva el verde
# para lo que entra.
PLANTILLAS: tuple[PlantillaTematica, ...] = (
    PlantillaTematica("housing", "Vivienda", "house", color_slot=1),
    PlantillaTematica("housing.rent_mortgage", "Alquiler o hipoteca", "home"),
    PlantillaTematica("housing.community_fees", "Comunidad de propietarios", "building-2"),
    PlantillaTematica("housing.electricity", "Luz", "zap"),
    PlantillaTematica("housing.gas", "Gas", "flame"),
    PlantillaTematica("housing.water", "Agua", "droplets"),
    PlantillaTematica("housing.internet_phone", "Internet y teléfono fijo", "wifi"),
    PlantillaTematica("housing.home_insurance", "Seguro del hogar", "shield-check"),
    PlantillaTematica("housing.maintenance", "Reparaciones y mantenimiento", "wrench"),
    PlantillaTematica("housing.furnishings", "Muebles y menaje", "lamp"),
    PlantillaTematica("housing.cleaning", "Limpieza y droguería", "spray-can"),
    PlantillaTematica("groceries", "Alimentación", "shopping-cart", color_slot=2),
    PlantillaTematica("groceries.supermarket", "Supermercado", "shopping-basket"),
    PlantillaTematica("groceries.bakery", "Panadería y pastelería", "croissant"),
    PlantillaTematica("groceries.butcher_fish", "Carnicería y pescadería", "beef"),
    PlantillaTematica("groceries.greengrocer", "Fruta y verdura", "apple"),
    PlantillaTematica("groceries.drinks", "Bebidas", "cup-soda"),
    PlantillaTematica("groceries.takeaway", "Comida para llevar", "sandwich"),
    PlantillaTematica("transport", "Transporte", "car", color_slot=3),
    PlantillaTematica("transport.fuel", "Combustible", "fuel"),
    PlantillaTematica("transport.public_transport", "Transporte público", "bus"),
    PlantillaTematica("transport.taxi", "Taxi y VTC", "car-taxi-front"),
    PlantillaTematica("transport.car_insurance", "Seguro del coche", "shield-check"),
    PlantillaTematica("transport.car_maintenance", "Taller e ITV", "wrench"),
    PlantillaTematica("transport.parking_tolls", "Parking y peajes", "circle-parking"),
    PlantillaTematica("transport.fines", "Multas", "triangle-alert"),
    PlantillaTematica("transport.bike", "Bicicleta y patinete", "bike"),
    PlantillaTematica("leisure", "Ocio", "party-popper", color_slot=4),
    PlantillaTematica("leisure.restaurants", "Restaurantes", "utensils"),
    PlantillaTematica("leisure.bars_cafes", "Bares y cafeterías", "coffee"),
    PlantillaTematica("leisure.cinema_shows", "Cine, teatro y conciertos", "clapperboard"),
    PlantillaTematica("leisure.books", "Libros y cómics", "book-open"),
    PlantillaTematica("leisure.games", "Videojuegos y juegos de mesa", "gamepad-2"),
    PlantillaTematica("leisure.sports", "Deporte y gimnasio", "dumbbell"),
    PlantillaTematica("leisure.travel", "Viajes y vacaciones", "plane"),
    PlantillaTematica("leisure.hotels", "Alojamiento", "bed-double"),
    PlantillaTematica("leisure.hobbies", "Aficiones", "palette"),
    PlantillaTematica("health", "Salud", "heart-pulse", color_slot=5),
    PlantillaTematica("health.pharmacy", "Farmacia", "pill"),
    PlantillaTematica("health.doctor", "Médico y especialistas", "stethoscope"),
    PlantillaTematica("health.dentist", "Dentista", "smile"),
    PlantillaTematica("health.optician", "Óptica", "glasses"),
    PlantillaTematica("health.health_insurance", "Seguro médico", "shield-plus"),
    PlantillaTematica("health.physio", "Fisioterapia", "activity"),
    PlantillaTematica("health.therapy", "Psicología y terapia", "brain"),
    PlantillaTematica("subscriptions", "Suscripciones", "repeat", color_slot=6),
    PlantillaTematica("subscriptions.video", "Streaming de vídeo", "monitor-play"),
    PlantillaTematica("subscriptions.music", "Música y pódcast", "music"),
    PlantillaTematica("subscriptions.software", "Software y nube", "cloud"),
    PlantillaTematica("subscriptions.press", "Prensa y revistas", "newspaper"),
    PlantillaTematica("subscriptions.mobile", "Móvil", "smartphone"),
    PlantillaTematica("subscriptions.memberships", "Cuotas y asociaciones", "id-card"),
    PlantillaTematica("clothing", "Ropa y calzado", "shirt", color_slot=7),
    PlantillaTematica("clothing.clothes", "Ropa", "shirt"),
    PlantillaTematica("clothing.shoes", "Calzado", "footprints"),
    PlantillaTematica("clothing.accessories", "Complementos", "watch"),
    PlantillaTematica("clothing.alterations", "Arreglos y tintorería", "scissors"),
    PlantillaTematica("education", "Educación", "graduation-cap", color_slot=8),
    PlantillaTematica("education.tuition", "Matrículas y cuotas", "school"),
    PlantillaTematica("education.supplies", "Material escolar", "pencil"),
    PlantillaTematica("education.courses", "Cursos y formación", "book-marked"),
    PlantillaTematica("education.childcare", "Guardería", "baby"),
    PlantillaTematica("education.extracurricular", "Actividades extraescolares", "drama"),
    PlantillaTematica("pets", "Mascotas", "paw-print", color_slot=9),
    PlantillaTematica("pets.food", "Comida", "bone"),
    PlantillaTematica("pets.vet", "Veterinario", "syringe"),
    PlantillaTematica("pets.grooming", "Peluquería y accesorios", "brush"),
    PlantillaTematica("pets.insurance", "Seguro de mascota", "shield-check"),
    PlantillaTematica("gifts", "Regalos y donaciones", "gift", color_slot=10),
    PlantillaTematica("gifts.presents", "Regalos", "gift"),
    PlantillaTematica("gifts.donations", "Donaciones y ONG", "heart-handshake"),
    PlantillaTematica("gifts.celebrations", "Celebraciones", "cake"),
    PlantillaTematica("personal_care", "Cuidado personal", "sparkles", color_slot=11),
    PlantillaTematica("personal_care.hairdresser", "Peluquería y barbería", "scissors"),
    PlantillaTematica("personal_care.cosmetics", "Cosmética e higiene", "droplet"),
    PlantillaTematica("personal_care.beauty", "Estética y bienestar", "flower-2"),
    PlantillaTematica("taxes_fees", "Impuestos y comisiones", "landmark", color_slot=12),
    PlantillaTematica("taxes_fees.income_tax", "IRPF y declaraciones", "file-text"),
    PlantillaTematica("taxes_fees.property_tax", "IBI y tasas municipales", "receipt"),
    PlantillaTematica("taxes_fees.vehicle_tax", "Impuesto de circulación", "car"),
    PlantillaTematica("taxes_fees.bank_fees", "Comisiones bancarias", "banknote"),
    PlantillaTematica("taxes_fees.loan_interest", "Intereses de préstamos", "percent"),
    PlantillaTematica("savings", "Ahorro e inversión", "piggy-bank", color_slot=1),
    PlantillaTematica("savings.emergency_fund", "Fondo de emergencia", "shield"),
    PlantillaTematica("savings.investment", "Aportación a inversión", "trending-up"),
    PlantillaTematica("savings.pension", "Plan de pensiones", "hourglass"),
    PlantillaTematica("savings.goals", "Objetivos de ahorro", "target"),
    PlantillaTematica("other", "Otros gastos", "circle-ellipsis", color_slot=5),
    PlantillaTematica("other.unclassified", "Sin clasificar", "circle-help"),
    PlantillaTematica("other.cash_withdrawal", "Retirada de efectivo", "banknote-arrow-down"),
    PlantillaTematica("other.fees_misc", "Gastos varios", "more-horizontal"),
    PlantillaTematica("income", "Ingresos", "wallet", kind="income", color_slot=5),
    PlantillaTematica("income.salary", "Nómina", "badge-euro", kind="income"),
    PlantillaTematica("income.bonus", "Pagas extra y bonus", "plus-circle", kind="income"),
    PlantillaTematica(
        "income.freelance", "Facturación por cuenta propia", "file-signature", kind="income"
    ),
    PlantillaTematica("income.rental", "Alquileres", "key", kind="income"),
    PlantillaTematica(
        "income.interest_dividends", "Intereses y dividendos", "trending-up", kind="income"
    ),
    PlantillaTematica("income.refunds", "Devoluciones y reembolsos", "undo-2", kind="income"),
    PlantillaTematica("income.second_hand", "Venta de segunda mano", "tag", kind="income"),
    PlantillaTematica("income.benefits", "Prestaciones y ayudas", "hand-coins", kind="income"),
    PlantillaTematica("income.gifts_received", "Regalos recibidos", "gift", kind="income"),
    PlantillaTematica("income.other", "Otros ingresos", "circle-ellipsis", kind="income"),
)


def _orden(plantilla: PlantillaTematica) -> int:
    """Posición de la plantilla entre sus hermanas, en múltiplos de diez.

    Se deja hueco entre valores para poder intercalar una temática nueva en una
    versión posterior sin reordenar el catálogo entero.
    """
    hermanas = [p for p in PLANTILLAS if p.parent_key == plantilla.parent_key]
    return (hermanas.index(plantilla) + 1) * 10


def filas_de_plantillas() -> list[dict]:
    """El catálogo como filas listas para insertar en `category_templates`."""
    return [
        {
            "id": uuid.uuid4(),
            "template_key": p.template_key,
            "parent_key": p.parent_key,
            "name": p.name,
            "kind": p.kind,
            "icon": p.icon,
            "color_slot": p.color_slot,
            "sort_order": _orden(p),
            "depth": p.depth,
            "is_default": True,
            "version": VERSION_CATALOGO,
        }
        for p in PLANTILLAS
    ]


async def sembrar_plantillas(sesion: AsyncSession) -> int:
    """Inserta o actualiza el árbol de plantillas. Devuelve las filas escritas.

    `ON CONFLICT ... DO UPDATE` en lugar de `DO NOTHING` para que una versión futura
    pueda corregir un icono o un nombre sin crear plantillas duplicadas. El `id` no
    se toca en el conflicto: si cambiara, las temáticas ya copiadas a un hogar
    perderían su origen.

    Las raíces se insertan antes que las hijas porque `parent_key` es una clave ajena
    a `template_key` con `RESTRICT`.
    """
    filas = filas_de_plantillas()
    escritas = 0
    for profundidad in sorted({fila["depth"] for fila in filas}):
        nivel = [fila for fila in filas if fila["depth"] == profundidad]
        sentencia = insert(CategoryTemplate).values(nivel)
        sentencia = sentencia.on_conflict_do_update(
            index_elements=["template_key"],
            set_={
                "parent_key": sentencia.excluded.parent_key,
                "name": sentencia.excluded.name,
                "kind": sentencia.excluded.kind,
                "icon": sentencia.excluded.icon,
                "color_slot": sentencia.excluded.color_slot,
                "sort_order": sentencia.excluded.sort_order,
                "depth": sentencia.excluded.depth,
                "updated_at": func.now(),
            },
        )
        resultado = await sesion.execute(sentencia)
        escritas += resultado.rowcount or 0
    return escritas


async def copiar_plantillas_a_hogar(sesion: AsyncSession, household_id: uuid.UUID) -> int:
    """Copia el árbol por defecto a un hogar nuevo (onboarding, F-50).

    Devuelve las temáticas creadas. Es idempotente: las plantillas que el hogar ya
    tiene (por `template_key`) se dejan como están, así que volver a llamar tras
    añadir plantillas nuevas solo crea las que faltan.

    `depth`, `path_ids` y `sort_key` se calculan aquí en lugar de dejarlos vacíos y
    llamar después a `refresh_category_paths()`: `ck_categories_path_consistent` no
    es diferible, así que el `INSERT` ya tiene que cumplirlo, y el UUID se genera en
    Python, de modo que se conoce antes de insertar.
    """
    plantillas = (
        await sesion.execute(
            select(CategoryTemplate)
            .where(CategoryTemplate.is_default)
            .order_by(CategoryTemplate.depth, CategoryTemplate.sort_order)
        )
    ).scalars()

    existentes = set(
        (
            await sesion.execute(
                select(Category.template_key).where(
                    Category.household_id == household_id,
                    Category.template_key.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    # `template_key` → (id, path_ids, sort_key) de lo ya insertado en esta pasada,
    # para poder colgar cada hija de su madre sin volver a consultar.
    creadas: dict[str, tuple[uuid.UUID, list[uuid.UUID], str]] = {}
    filas: list[dict] = []

    for plantilla in plantillas:
        if plantilla.template_key in existentes:
            continue
        madre = creadas.get(plantilla.parent_key) if plantilla.parent_key else None
        if plantilla.parent_key and madre is None:
            # La madre ya existía en el hogar o no es `is_default`: sin ella no se
            # puede calcular la ruta, así que se deja para una pasada posterior.
            continue

        identificador = uuid.uuid4()
        tramo = f"{plantilla.sort_order:04d}"
        if madre is None:
            ruta = [identificador]
            clave_orden = tramo
        else:
            ruta = [*madre[1], identificador]
            clave_orden = f"{madre[2]}.{tramo}"

        creadas[plantilla.template_key] = (identificador, ruta, clave_orden)
        filas.append(
            {
                "id": identificador,
                "household_id": household_id,
                "parent_id": madre[0] if madre else None,
                "name": plantilla.name,
                "kind": plantilla.kind,
                "color_slot": plantilla.color_slot,
                "icon": plantilla.icon,
                "sort_order": plantilla.sort_order,
                "depth": len(ruta) - 1,
                "path_ids": ruta,
                "sort_key": clave_orden,
                # «Sin clasificar» es la garantía de que ninguna transacción se queda
                # sin temática: ni se archiva ni se fusiona como origen.
                "is_system": plantilla.template_key == CLAVE_SIN_CLASIFICAR,
                "template_key": plantilla.template_key,
            }
        )

    if not filas:
        return 0
    await sesion.execute(insert(Category).values(filas))
    return len(filas)


async def sembrar(sesion: AsyncSession) -> int:
    """Punto de entrada de las semillas de la instalación."""
    return await sembrar_plantillas(sesion)
