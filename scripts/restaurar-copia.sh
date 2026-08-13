#!/usr/bin/env bash
#
# Restaura una copia creada por scripts/copia-seguridad.sh.
#
# ATENCIÓN: sobrescribe los datos actuales. Pide confirmación escrita antes de
# tocar nada, porque restaurar por error una copia de hace dos semanas se parece
# mucho a perder dos semanas de datos.
#
# Uso:
#   scripts/restaurar-copia.sh copias/presupuesto-20260813-142530.tar

set -euo pipefail

ARCHIVO="${1:-}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "$ARCHIVO" ]]; then
    echo "Uso: $0 <fichero.tar>" >&2
    echo >&2
    echo "Copias disponibles:" >&2
    find "$RAIZ/copias" -maxdepth 1 -name 'presupuesto-*.tar' -type f 2>/dev/null |
        sort -r | head -20 | sed 's/^/  /' >&2 || echo "  (ninguna)" >&2
    exit 1
fi

[[ -f "$ARCHIVO" ]] || { echo "No existe: $ARCHIVO" >&2; exit 1; }

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

trabajo="$(mktemp -d)"
trap 'rm -rf "$trabajo"' EXIT
tar -xf "$ARCHIVO" -C "$trabajo"

echo "=== Contenido de la copia ==="
cat "$trabajo/manifiesto.txt"
echo
echo "=== Se va a sobrescribir ==="
url_psql="${DATABASE_URL/+asyncpg/}"
url_psql="${url_psql/+psycopg2/}"
echo "  Base de datos    : $(echo "$url_psql" | sed -E 's#://[^@]+@#://***@#')"
echo "  Directorio de PDF: $UPLOAD_DIR"
echo
echo "Esto BORRA los datos actuales y los reemplaza por los de la copia."
read -r -p "Escribe RESTAURAR para continuar: " confirmacion
[[ "$confirmacion" == "RESTAURAR" ]] || { echo "Cancelado."; exit 1; }

echo "--> Restaurando la base de datos"
# --clean elimina los objetos antes de recrearlos; --if-exists evita el ruido de
# los que no existan todavía.
pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname="$url_psql" "$trabajo/base-datos.dump"

echo "--> Restaurando las facturas"
mkdir -p "$(dirname "$UPLOAD_DIR")"
rm -rf "$UPLOAD_DIR"
tar -xzf "$trabajo/facturas.tar.gz" -C "$(dirname "$UPLOAD_DIR")"

echo "--> Comprobando que el esquema está al día"
if [[ -x "$RAIZ/backend/.venv/bin/alembic" ]]; then
    (cd "$RAIZ/backend" && ./.venv/bin/alembic upgrade head)
else
    echo "    AVISO: no se encuentra alembic. Aplica las migraciones a mano:"
    echo "           cd backend && alembic upgrade head"
fi

echo "==> Restauración terminada. Reinicia la aplicación."
