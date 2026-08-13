#!/bin/sh
# Aplica las migraciones pendientes y arranca el servidor. Si la base de datos
# todavía no acepta conexiones (arranque simultáneo en EasyPanel), se reintenta.
set -eu

echo "[entrypoint] Aplicando las migraciones..."
intento=1
maximo=30
until alembic upgrade head 2>/tmp/alembic.err; do
    if [ "$intento" -ge "$maximo" ]; then
        echo "[entrypoint] La migración sigue fallando tras $maximo intentos:" >&2
        cat /tmp/alembic.err >&2
        exit 1
    fi
    # El motivo se muestra ya en el primer intento: esperar un minuto para
    # enterarse de que la contraseña estaba mal o que la base no existe hace el
    # despliegue mucho más difícil de depurar. Después solo se cuenta, para no
    # llenar el registro con el mismo error treinta veces.
    if [ "$intento" -eq 1 ]; then
        echo "[entrypoint] Todavía no se puede migrar. Motivo:" >&2
        sed 's/^/[entrypoint]   /' /tmp/alembic.err >&2
        echo "[entrypoint] Si es un problema de conexión, se reintenta; si no, revisa DATABASE_URL." >&2
    fi
    echo "[entrypoint] Intento $intento/$maximo fallido, reintento en 2s..."
    intento=$((intento + 1))
    sleep 2
done

echo "[entrypoint] Migraciones aplicadas. Arrancando la aplicación."
exec "$@"
