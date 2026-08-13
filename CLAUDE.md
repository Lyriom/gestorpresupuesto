# Notas para trabajar en este repositorio

Gestor de presupuesto personal self-hosted. Monolito: un proceso de FastAPI
sirve la API en `/api/v1` y los estáticos del frontend Vue compilado.

## Comandos

Backend (desde `backend/`, el entorno virtual está en `backend/.venv`):

```bash
./.venv/bin/python -m pytest tests -q          # pruebas
./.venv/bin/ruff format app tests              # formato
./.venv/bin/ruff check app tests               # análisis
./.venv/bin/alembic upgrade head               # migraciones
./.venv/bin/uvicorn app.main:app --reload      # servidor de desarrollo
```

Frontend (desde `frontend/`):

```bash
npm run dev              # servidor de desarrollo en :5173, con proxy de /api a :8000
npx vue-tsc -b --force   # comprobación de tipos
npm run build            # compilar a frontend/dist
```

**No uses `vue-tsc --noEmit`**: el `tsconfig.json` de la raíz es de tipo
«solution» (solo referencias a los otros), así que con `--noEmit` la herramienta
acaba en silencio sin revisar ni un fichero y da la falsa sensación de que todo
está bien. Hace falta `-b` para que compile los proyectos referenciados.

Base de datos local: `docker compose up -d db` en la raíz. Hace falta un `.env`
en la raíz (copia de `.env.example`) con `SECRET_KEY` y `DATABASE_URL`.

## Convenciones que ya están establecidas

- **Dinero**: `Numeric(14,2)` en base de datos, `Numeric(14,4)` para precios
  unitarios (las facturas de luz y gas traen cuatro o seis decimales). Nunca
  `float`. En JSON los importes viajan **como cadena decimal**, no como número.
- **Idioma**: código, nombres de tabla, columnas y rutas en inglés; comentarios,
  docstrings, mensajes de error y todo el texto visible al usuario en español de
  España. La interfaz usa `es-ES` y euros.
- **Errores de la API**: siempre con la forma
  `{"error": {"codigo", "mensaje", "detalles": [{"campo", "mensaje"}]}}`.
  Las excepciones de negocio están en `app/core/errors.py`.
- **Sesión**: JWT de acceso y refresco en cookies httpOnly, con CSRF por doble
  envío (cookie `csrf_token` más cabecera `X-CSRF-Token`). No hay tokens en
  `localStorage`.
- **Tema**: el modo oscuro es el principal. `index.html` aplica el tema guardado
  antes de la primera pintura leyendo `localStorage.getItem('tema')`.
- **Commits**: mensajes en español, sin trailer de coautoría.

## Dónde está cada cosa

```
backend/app/core/        configuración, seguridad y errores
backend/app/db/          base declarativa, sesión y datos semilla
backend/app/models/      modelos SQLAlchemy (39 tablas)
backend/app/schemas/     esquemas Pydantic v2
backend/app/services/    lógica de negocio, sin dependencias del ORM
backend/app/api/v1/      routers por recurso
frontend/src/lib/        cliente HTTP y formateo es-ES
frontend/src/components/ui/           componentes base
frontend/src/components/presupuesto/  la barra de presupuesto
frontend/src/components/graficos/     envoltorios de Chart.js
docs/                    competencia, diseño UI/UX, modelo de datos y API
```

La lógica de negocio de `app/services/` está escrita como **funciones puras
sobre estructuras simples**, sin tocar la base de datos, y tiene cobertura de
pruebas propia. Si añades reglas de cálculo, ponlas ahí y no en los endpoints:
así la API y los informes dan siempre el mismo número.

## Especificaciones de referencia

Antes de implementar algo nuevo, mira si ya está especificado:

- `docs/arquitectura/modelo-datos.md` — las 39 tablas, la jerarquía de temáticas
  y el algoritmo de fusión.
- `docs/arquitectura/api.md` — los 222 endpoints y las 78 reglas de negocio
  numeradas.
- `docs/ux/design-system.md` — tokens, componentes y la especificación de la
  barra de presupuesto.
- `docs/ux/flujos-y-wireframes.md` — pantallas, flujos y microcopy.
- `docs/competencia.md` — catálogo de 60 funcionalidades con prioridad (F-01 a
  F-60); útil para saber qué es MVP y qué no.

## Detalles que ya han dado problemas

- En las facturas españolas la **coma siempre es decimal**: `0,004` son cuatro
  milésimas, no cuatro euros. `app/services/numeros.py` lo resuelve; no lo
  reimplementes.
- El **precio unitario no se redondea a céntimos** al leer una factura: se
  perdería el histórico de luz y gas.
- Para detectar el delimitador de un CSV **no uses `csv.Sniffer`**: confunde la
  coma decimal con el separador de campos.
- El umbral de aviso del presupuesto se mide sobre lo asignado **más lo
  arrastrado**, no solo sobre lo asignado.
