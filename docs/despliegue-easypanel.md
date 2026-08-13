# Despliegue en EasyPanel

La aplicación es un monolito: una sola imagen Docker sirve la API y el frontend.
Necesitas dos servicios en EasyPanel: **PostgreSQL** y **App**.

## 1. Crear el proyecto

En EasyPanel, `+ Project` → nombre `gestor-presupuesto`.

## 2. Servicio de base de datos

Dentro del proyecto, `+ Service` → **Postgres**.

| Campo | Valor |
| --- | --- |
| Service Name | `db` |
| Image | `postgres:16` |
| Database | `presupuesto` |
| User | `presupuesto` |
| Password | genera una larga y guárdala |

Despliega el servicio. EasyPanel lo expone dentro de la red del proyecto con el
host `$(PROJECT_NAME)_db`, es decir `gestor-presupuesto_db`. **No** publiques el
puerto 5432 hacia fuera: la app se conecta por la red interna.

## 3. Servicio de aplicación

`+ Service` → **App**.

**Source**: GitHub, repositorio `Lyriom/gestorpresupuesto`, rama `main`.
Si el repositorio es privado, conecta antes tu cuenta de GitHub en los ajustes
de EasyPanel.

**Build**: método `Dockerfile`, ruta `Dockerfile` (está en la raíz del repo).

**Environment**: pega estas variables y ajusta los valores marcados.

```env
APP_ENV=production
SECRET_KEY=<genera una clave, ver más abajo>
DATABASE_URL=postgresql+asyncpg://presupuesto:<CONTRASEÑA>@gestor-presupuesto_db:5432/presupuesto
CORS_ORIGINS=
COOKIE_SECURE=true
TRUSTED_PROXIES=*
UPLOAD_DIR=/data/uploads
STATIC_DIR=/app/static
ALLOW_REGISTRATION=true
OCR_ENABLED=true
OCR_LANGUAGES=spa+eng
MAX_UPLOAD_MB=20
DEFAULT_CURRENCY=EUR
DEFAULT_LOCALE=es-ES
DEFAULT_TIMEZONE=Europe/Madrid
```

**`TRUSTED_PROXIES` no es un detalle.** La aplicación cuenta los intentos de
acceso por dirección IP, y detrás de un proxy la IP real solo llega en la
cabecera `X-Forwarded-For`. Esa cabecera la puede escribir cualquiera, así que la
aplicación únicamente la cree si la conexión viene de un proxy declarado aquí:

- Si la dejas **vacía**, el límite de intentos contará todas las peticiones como
  si vinieran de la misma IP (la del proxy de EasyPanel), y un solo visitante
  podría agotar el cupo de los demás.
- Si pones `*`, se acepta la cabecera de cualquier par. Es lo correcto en
  EasyPanel **siempre que el contenedor no publique el puerto 8000 hacia
  internet** y solo se llegue a él a través del proxy. No publiques ese puerto.
- Si prefieres ser estricto, pon la dirección del contenedor del proxy en la red
  interna del proyecto en lugar de `*`.

Genera la clave de firma con:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

`CORS_ORIGINS` va vacío a propósito: el frontend se sirve desde el mismo
dominio, así que no hay petición cruzada. `COOKIE_SECURE=true` es obligatorio en
producción, porque las cookies de sesión no deben viajar por HTTP.

**Ten en cuenta**: cuando termines de crear tu usuario, pon
`ALLOW_REGISTRATION=false` y redespliega. Si no, cualquiera que encuentre la URL
puede registrarse.

## 4. Volumen para las facturas

Pestaña **Mounts** → `+ Volume`:

| Campo | Valor |
| --- | --- |
| Type | Volume |
| Name | `datos` |
| Mount Path | `/data` |

Sin este volumen, las facturas subidas desaparecen en cada despliegue.

## 5. Dominio y HTTPS

Pestaña **Domains** → añade tu dominio (por ejemplo `presupuesto.gozsyl.cloud`),
`Port` **8000**, y activa **HTTPS** con Let's Encrypt. EasyPanel gestiona el
certificado y termina el TLS en su proxy; la aplicación arranca con
`--proxy-headers` para leer bien la IP y el esquema originales.

## 6. Desplegar

Pulsa **Deploy**. En el primer arranque el contenedor:

1. Espera a que PostgreSQL acepte conexiones (reintenta 30 veces cada 2 s).
2. Aplica las migraciones de Alembic (`alembic upgrade head`).
3. Arranca Uvicorn en el puerto 8000.

Comprueba que responde:

```bash
curl -fsS https://presupuesto.gozsyl.cloud/api/health
# {"estado":"ok","app":"Gestor de Presupuesto","entorno":"production"}
```

Después entra por el navegador y crea tu cuenta.

## 7. Despliegues siguientes

Con el repositorio conectado, cada `git push` a `main` puede disparar el build
si activas **Auto Deploy** (o configuras el webhook que te da EasyPanel en la
pestaña de despliegue). Las migraciones se aplican solas en cada arranque.

## Copias de seguridad

El servicio de Postgres de EasyPanel tiene backups programados en su propia
pestaña; actívalos. Pero **un backup de la base de datos sin los PDF deja las
facturas sin documento original**, así que el repositorio incluye un script que
se lleva las dos cosas o falla:

```bash
scripts/copia-seguridad.sh /ruta/donde/guardar     # base de datos + facturas
scripts/restaurar-copia.sh copias/presupuesto-....tar
```

Genera un `.tar` con el volcado de PostgreSQL en formato personalizado, las
facturas comprimidas y un manifiesto que dice qué revisión de esquema tenía la
copia. Conserva las 14 últimas (ajustable con `RETENCION`). Si no encuentra
`pg_dump` en el sistema, usa el del contenedor de la base de datos.

La restauración pide confirmación escrita antes de tocar nada, porque restaurar
por error una copia de hace dos semanas se parece mucho a perder dos semanas de
datos.

Para programarlo en el servidor, un cron diario:

```
0 4 * * * cd /ruta/al/proyecto && RETENCION=30 scripts/copia-seguridad.sh /copias >> /var/log/presupuesto-copias.log 2>&1
```

Además, la propia aplicación permite exportar todos tus datos en JSON desde
**Ajustes → Datos → Exportar**, que sirve como copia independiente del motor.

## Solución de problemas

| Síntoma | Causa probable |
| --- | --- |
| El contenedor reinicia en bucle y los logs muestran fallos de migración | `DATABASE_URL` mal formada o el servicio `db` todavía no está listo. Revisa el host: es `<proyecto>_db`, no `localhost` |
| Entras, recargas y te echa fuera | Falta `COOKIE_SECURE=true` con HTTPS, o `SECRET_KEY` cambia entre despliegues (defínela como variable fija, no generada) |
| Las facturas escaneadas no extraen nada | `OCR_ENABLED=false`, o el PDF es una imagen de baja resolución. Tesseract y el diccionario español ya vienen en la imagen |
| Error 413 al subir una factura | Supera `MAX_UPLOAD_MB`; súbelo y redespliega |
| Las facturas desaparecen tras desplegar | Falta el volumen montado en `/data` |
| La web carga pero la API da 404 | El build no copió los estáticos: revisa que el build use el `Dockerfile` de la raíz |

## Consumo aproximado

Con un usuario y unos cientos de transacciones al mes, la aplicación va sobrada
con 512 MB de RAM y 0,5 vCPU. El pico de memoria es la extracción de un PDF
grande con OCR, que puede llegar a ~400 MB puntuales; si subes facturas
escaneadas de muchas páginas, asigna 1 GB.
