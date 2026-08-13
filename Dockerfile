# =============================================================================
# Build multi-stage del monolito: el frontend Vue se compila a estáticos y el
# backend FastAPI los sirve junto a la API. Resultado: una sola imagen, un solo
# proceso, listo para EasyPanel.
# =============================================================================

# --- Etapa 1: compilar el frontend ------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /build

# Se copian primero los manifiestos para aprovechar la caché de capas: si no
# cambian las dependencias, no se reinstalan.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Etapa 2: runtime de Python ---------------------------------------------
FROM python:3.12-slim AS runtime

# tesseract-ocr y su diccionario español permiten leer facturas escaneadas.
# libgl1 y libglib2.0-0 son dependencias nativas de PyMuPDF/Pillow.
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-spa \
        libglib2.0-0 \
        libgl1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    UPLOAD_DIR=/data/uploads \
    STATIC_DIR=/app/static

WORKDIR /app

# Igual que arriba: las dependencias en su propia capa.
COPY backend/pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/entrypoint.sh ./entrypoint.sh

# Estáticos del frontend compilado en la etapa anterior.
COPY --from=frontend /build/dist ./static

# Usuario sin privilegios: si alguien escapa de la aplicación, no es root.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /app /data \
    && chmod +x ./entrypoint.sh

USER appuser

# Volumen para las facturas subidas: sin esto se perderían en cada despliegue.
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
