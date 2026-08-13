#!/usr/bin/env bash
#
# Copia de seguridad completa: base de datos y facturas subidas.
#
# Una copia de la base de datos sin los PDF originales deja las facturas sin
# documento, y una copia de los PDF sin la base de datos los deja sin contexto.
# Este script se lleva las dos cosas o falla; no deja una copia a medias.
#
# Uso:
#   scripts/copia-seguridad.sh [directorio-destino]
#
# Variables de entorno (se leen de .env si existe):
#   DATABASE_URL   conexión a PostgreSQL
#   UPLOAD_DIR     directorio de las facturas subidas (por defecto ./uploads)
#   RETENCION      cuántas copias conservar (por defecto 14)
#
# En EasyPanel, ejecútalo desde la consola del servicio de la aplicación, o
# prográmalo con cron en el servidor apuntando al volumen de datos.

set -euo pipefail

DESTINO="${1:-copias}"
RETENCION="${RETENCION:-14}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Carga del .env, sin pisar lo que ya venga del entorno. Se hace leyendo línea a
# línea en vez de con `source`: así una contraseña con comillas o con espacios no
# se interpreta como código, y las variables quedan exportadas de verdad.
cargar_env() {
    local fichero="$1"
    [[ -f "$fichero" ]] || return 0
    local linea clave valor
    while IFS= read -r linea || [[ -n "$linea" ]]; do
        linea="${linea%$'\r'}"
        [[ "$linea" =~ ^[[:space:]]*# ]] && continue
        [[ "$linea" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
        clave="${linea%%=*}"
        valor="${linea#*=}"
        # Quita un par de comillas envolventes, si las hay.
        if [[ "$valor" == \"*\" || "$valor" == \'*\' ]]; then
            valor="${valor:1:${#valor}-2}"
        fi
        # Lo que ya está en el entorno gana.
        [[ -n "${!clave-}" ]] && continue
        export "$clave=$valor"
    done < "$fichero"
}

cargar_env "$RAIZ/.env"

: "${DATABASE_URL:?Falta DATABASE_URL: defínela o pon un .env en la raíz}"
UPLOAD_DIR="${UPLOAD_DIR:-$RAIZ/uploads}"

marca="$(date +%Y%m%d-%H%M%S)"
trabajo="$(mktemp -d)"
trap 'rm -rf "$trabajo"' EXIT

mkdir -p "$DESTINO"

echo "==> Copia de seguridad $marca"

# psql y pg_dump no entienden el driver de SQLAlchemy que lleva la URL.
url_psql="${DATABASE_URL/+asyncpg/}"
url_psql="${url_psql/+psycopg2/}"

echo "--> Volcando la base de datos"
# El formato personalizado (-Fc) permite restaurar tablas por separado y ya
# viene comprimido.
opciones_volcado=(--format=custom --no-owner --no-privileges)

if command -v pg_dump >/dev/null 2>&1; then
    pg_dump "${opciones_volcado[@]}" --file="$trabajo/base-datos.dump" "$url_psql"
else
    # En un portátil rara vez está el cliente de PostgreSQL instalado, pero sí
    # Docker con el contenedor de la base de datos: se usa el pg_dump de dentro,
    # que además coincide en versión con el servidor.
    contenedor="${PG_CONTENEDOR:-$(docker ps --filter "ancestor=postgres:16-alpine" \
        --format '{{.Names}}' 2>/dev/null | head -1)}"
    if [[ -z "$contenedor" ]]; then
        echo "ERROR: no se encuentra pg_dump ni un contenedor de PostgreSQL en marcha." >&2
        echo "       Instala el cliente de PostgreSQL, arranca la base de datos con" >&2
        echo "       'docker compose up -d db', o define PG_CONTENEDOR con su nombre." >&2
        exit 1
    fi
    echo "    (usando el pg_dump del contenedor $contenedor)"
    # La URL vista desde dentro del contenedor apunta a su propio localhost.
    url_interna="$(echo "$url_psql" | sed -E 's#@[^:/]+:[0-9]+/#@localhost:5432/#')"
    docker exec "$contenedor" pg_dump "${opciones_volcado[@]}" "$url_interna" \
        > "$trabajo/base-datos.dump"
fi
echo "    $(du -h "$trabajo/base-datos.dump" | cut -f1)"

echo "--> Copiando las facturas subidas"
if [[ -d "$UPLOAD_DIR" ]]; then
    tar -czf "$trabajo/facturas.tar.gz" -C "$(dirname "$UPLOAD_DIR")" "$(basename "$UPLOAD_DIR")"
    echo "    $(du -h "$trabajo/facturas.tar.gz" | cut -f1)"
else
    echo "    AVISO: no existe $UPLOAD_DIR; no hay facturas que copiar."
    tar -czf "$trabajo/facturas.tar.gz" --files-from=/dev/null
fi

# Un manifiesto para saber qué hay dentro sin descomprimir nada.
cat > "$trabajo/manifiesto.txt" <<FIN
Gestor de Presupuesto — copia de seguridad
Fecha            : $(date -Iseconds)
Servidor         : $(hostname)
Base de datos    : $(echo "$url_psql" | sed -E 's#://[^@]+@#://***@#')
Directorio de PDF: $UPLOAD_DIR
Revisión aplicada: $(cd "$RAIZ/backend" 2>/dev/null && (./.venv/bin/alembic current 2>/dev/null | tail -1 || echo "desconocida") || echo "desconocida")

Para restaurar, ver scripts/restaurar-copia.sh
FIN

archivo="$DESTINO/presupuesto-$marca.tar"
tar -cf "$archivo" -C "$trabajo" base-datos.dump facturas.tar.gz manifiesto.txt
echo "==> Copia creada: $archivo ($(du -h "$archivo" | cut -f1))"

# Rotación: se conservan las N más recientes.
sobrantes=$(find "$DESTINO" -maxdepth 1 -name 'presupuesto-*.tar' -type f | sort -r | tail -n "+$((RETENCION + 1))")
if [[ -n "$sobrantes" ]]; then
    echo "--> Retirando copias antiguas (se conservan $RETENCION):"
    while IFS= read -r viejo; do
        echo "    $(basename "$viejo")"
        rm -f "$viejo"
    done <<< "$sobrantes"
fi

echo "==> Listo."
