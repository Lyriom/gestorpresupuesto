#!/bin/sh
# Aplica las migraciones pendientes y arranca el servidor. Si la base de datos
# todavía no acepta conexiones (arranque simultáneo en EasyPanel), se reintenta.
set -eu

echo "[entrypoint] Esperando a la base de datos..."
intento=1
maximo=30
until alembic upgrade head 2>/tmp/alembic.err; do
    if [ "$intento" -ge "$maximo" ]; then
        echo "[entrypoint] La migración sigue fallando tras $maximo intentos:"
        cat /tmp/alembic.err >&2
        exit 1
    fi
    echo "[entrypoint] Intento $intento/$maximo fallido, reintento en 2s..."
    intento=$((intento + 1))
    sleep 2
done

echo "[entrypoint] Migraciones aplicadas. Arrancando la aplicación."
exec "$@"
