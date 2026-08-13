# Gestor de Presupuesto

Aplicación web monolítica para el control del dinero personal: ingresos del mes repartidos
en una barra de presupuesto, gastos desglosables, temáticas (categorías) propias que se
pueden anidar y fusionar, y lectura de facturas en PDF para construir un historial de
precios por producto y detectar subidas.

## Qué hace

- **Presupuesto en barra**: pones los ingresos del mes y reparte el dinero por temáticas;
  la barra se consume a medida que registras gastos y avisa cuando te pasas.
- **Temáticas propias**: categorías jerárquicas creadas por ti, con color e icono, que
  puedes anidar a varios niveles y **fusionar** cuando dos son de lo mismo (el histórico
  se reasigna sin perder datos).
- **Gastos desglosables**: una compra se puede repartir entre varias temáticas (splits),
  con comercio, etiquetas, notas y adjuntos.
- **Cuentas**: corriente, efectivo, ahorro, tarjeta de crédito, inversión y deuda, con
  transferencias entre ellas y patrimonio neto.
- **Facturas en PDF**: subes la factura, se extraen las líneas de producto, las revisas y
  corriges, y cada producto acumula su historial de precios con comparativas de subidas.
- **Informes**: gasto por temática, evolución mes a mes, cash flow, top comercios y
  evolución del precio de un producto.
- **Modo oscuro** como tema principal, en español de España y euros.

## Stack

| Capa | Tecnología |
| --- | --- |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, Python 3.12 |
| Base de datos | PostgreSQL 16 |
| Frontend | Vue 3 + TypeScript, Vite, Pinia, Vue Router, Tailwind CSS, Chart.js |
| Facturas PDF | pdfplumber, PyMuPDF, Tesseract (OCR), RapidFuzz — todo open source |
| Despliegue | Un solo contenedor Docker (FastAPI sirve el build de Vue) en EasyPanel |

Es un **monolito**: un único proceso de FastAPI sirve la API en `/api/v1` y los ficheros
estáticos del frontend compilado. La base de datos es un servicio aparte.

## Estructura del repositorio

```
backend/       API FastAPI, modelos, servicios y migraciones
frontend/      Aplicación Vue 3
docs/          Análisis de competencia, diseño UI/UX y arquitectura
Dockerfile     Build multi-stage (Vue -> estáticos, Python -> runtime)
compose.yaml   Entorno de desarrollo local con Postgres
```

## Desarrollo local

Requisitos: Docker, Python 3.12 y Node 20.

```bash
cp .env.example .env        # revisa las variables antes de arrancar
docker compose up -d db     # levanta solo PostgreSQL
```

Backend:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

El frontend de desarrollo corre en `http://localhost:5173` y redirige `/api` al backend
en `http://localhost:8000`. La documentación interactiva de la API está en `/api/docs`.

## Despliegue

Ver [docs/despliegue-easypanel.md](docs/despliegue-easypanel.md).

## Documentación

- [Análisis de competencia](docs/competencia.md)
- [Sistema de diseño](docs/ux/design-system.md)
- [Flujos y wireframes](docs/ux/flujos-y-wireframes.md)
- [Modelo de datos](docs/arquitectura/modelo-datos.md)
- [Contrato de API](docs/arquitectura/api.md)
