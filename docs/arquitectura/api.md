# Contrato de API

Especificación del contrato HTTP del gestor de presupuesto personal. Es el documento de
referencia para implementar `backend/app/api/v1/*` y para consumir la API desde
`frontend/src`. Todo lo que aquí se describe es **contrato**: cambiarlo obliga a versionar.

**Stack**: FastAPI · Pydantic v2 · SQLAlchemy 2.0 async · PostgreSQL 16 · Python 3.12.

**Qué ya está fijado en el repositorio y aquí no se discute** (solo se respeta):

| Pieza | Fichero | Consecuencia para el contrato |
|---|---|---|
| Formato de error | `backend/app/core/errors.py` | `{"error": {"codigo", "mensaje", "detalles"}}` en **todas** las respuestas de error |
| Sesión y CSRF | `backend/app/core/security.py` | JWT de acceso/refresco en cookies httpOnly + doble envío con `csrf_token` / `X-CSRF-Token` |
| Prefijo y límites | `backend/app/core/config.py` | `/api/v1`, `max_upload_mb`, `max_pdf_pages`, `allow_registration` |
| Extracción de facturas | `backend/app/services/extraccion_pdf.py` | `FacturaExtraida` / `LineaExtraida` con confianza y avisos; **revisión humana obligatoria** |
| Cliente HTTP | `frontend/src/lib/api.ts` | Renovación automática con `POST /auth/refresh` ante 401; subida multipart con el campo `fichero` |
| Catálogo funcional | `docs/competencia.md` | La API cubre **todos los P0 y P1** (F-01…F-50); ver §11 |
| Paginación de la UI | `docs/ux/design-system.md` §5.17 | Paginación numérica con total y tamaños 25/50/100/200 |

**Índice**

1. [Convenciones](#1-convenciones)
2. [Autenticación y sesión](#2-autenticación-y-sesión)
3. [Tabla exhaustiva de endpoints](#3-tabla-exhaustiva-de-endpoints)
4. [Esquemas Pydantic v2](#4-esquemas-pydantic-v2)
5. [Reglas de negocio y validaciones](#5-reglas-de-negocio-y-validaciones)
6. [Estructura de carpetas del backend](#6-estructura-de-carpetas-del-backend)
7. [Rendimiento](#7-rendimiento)
8. [Seguridad](#8-seguridad)
9. [Privacidad: qué se registra y qué no](#9-privacidad-qué-se-registra-y-qué-no)
10. [Procesado en segundo plano](#10-procesado-en-segundo-plano)
11. [Cobertura del catálogo funcional](#11-cobertura-del-catálogo-funcional)
12. [Correspondencia con el modelo de datos](#12-correspondencia-con-el-modelo-de-datos)

---

## 1. Convenciones

### 1.1 Versionado

- Todas las rutas cuelgan de `settings.api_prefix` = **`/api/v1`**. En este documento las rutas
  se escriben **relativas a ese prefijo**: `/transactions` significa `/api/v1/transactions`.
- Fuera del prefijo solo viven tres cosas, ya implementadas en `app/main.py`:
  `GET /api/health` (healthcheck de Docker/EasyPanel), `GET /api/docs` y
  `GET /api/openapi.json`.
- **Cambios compatibles** (no versionan): añadir un endpoint, añadir un campo opcional en una
  petición, añadir un campo en una respuesta, añadir un valor a un enum **de respuesta**,
  añadir un filtro opcional, relajar una validación.
- **Cambios incompatibles** (obligan a `/api/v2`): quitar o renombrar un campo o una ruta,
  cambiar el tipo o la semántica de un campo, hacer obligatorio un campo que no lo era,
  añadir un valor a un enum **de petición** que el cliente antiguo no sepa producir, cambiar
  un código HTTP o un `codigo` de error existente.
- Un endpoint que se retira se marca `deprecated=True` en OpenAPI y responde durante al menos
  una versión con la cabecera `Deprecation: true` y `Sunset: <fecha RFC 7231>`.
- Los `codigo` de error son **parte del contrato**: el frontend ramifica sobre ellos
  (`ApiError.codigo`), nunca sobre el texto de `mensaje`.

### 1.2 Formato de error

Es el que ya impone `app/core/errors.py`. No se inventa ninguna otra forma:

```json
{
  "error": {
    "codigo": "splits_no_cuadran",
    "mensaje": "Los splits deben sumar exactamente el importe de la transacción.",
    "detalles": [
      { "campo": "splits", "mensaje": "Suman 45,00 € y la transacción es de 48,50 €." }
    ]
  }
}
```

- `codigo`: identificador estable en `snake_case`, en español, sin acentos.
- `mensaje`: frase en español de España, mostrable al usuario tal cual, sin jerga técnica y
  sin datos internos (ni rutas, ni SQL, ni identificadores de otros usuarios).
- `detalles`: lista de `{"campo", "mensaje"}`. `campo` usa la ruta con puntos del cuerpo
  (`splits.0.amount`, `lines.3.unit_price`) para que el formulario pinte el error en el
  control correcto. Cuando el error no es de un campo concreto, `detalles` va vacío.

Las excepciones se lanzan con las clases que ya existen — nunca con `HTTPException` a pelo
salvo en middleware:

| Clase | HTTP | `codigo` por defecto | Cuándo |
|---|---|---|---|
| `AppError` | 400 | `error_solicitud` | Petición mal formada que no es de validación de esquema |
| `NoAutenticado` | 401 | `no_autenticado` | Sin cookie de sesión, o token caducado/ inválido |
| `SinPermiso` | 403 | `sin_permiso` | CSRF inválido, registro deshabilitado, operación prohibida |
| `NoEncontrado` | 404 | `no_encontrado` | El recurso no existe **o no es del usuario de la sesión** |
| `Conflicto` | 409 | `conflicto` | Estado incompatible: duplicado, ya confirmado, aún con histórico |
| `ReglaDeNegocio` | 422 | `regla_de_negocio` | Datos válidos por tipo que incumplen una regla de §5 |
| `DemasiadasPeticiones` | 429 | `demasiadas_peticiones` | Límite de tasa o bloqueo temporal de credenciales |

Los errores de validación de Pydantic los transforma ya el manejador de
`RequestValidationError` en `422` con `codigo: "datos_invalidos"` y un `detalles` por campo.

**Catálogo de códigos de error propios** (los que el frontend distingue):

| `codigo` | HTTP | Situación |
|---|---|---|
| `credenciales_invalidas` | 401 | Usuario o contraseña incorrectos en `POST /auth/login` |
| `sesion_expirada` | 401 | Refresco caducado, revocado o reutilizado |
| `csrf_invalido` | 403 | Falta `X-CSRF-Token` o no coincide con la cookie |
| `registro_deshabilitado` | 403 | `allow_registration=false` y ya existe algún usuario |
| `contrasenya_incorrecta` | 401 | Contraseña actual errónea en cambio de contraseña o borrado de cuenta |
| `contrasenya_debil` | 422 | Nueva contraseña por debajo de la política (RN-05) |
| `email_ya_registrado` | 409 | Alta con un correo existente |
| `nombre_duplicado` | 409 | Nombre repetido entre hermanos (temáticas), cuentas, etiquetas o reglas |
| `tematica_con_historico` | 409 | Borrado de temática con transacciones/presupuesto sin `reassign_to` |
| `tematica_con_descendientes` | 409 | Borrado de temática con hijos sin reasignar |
| `fusion_invalida` | 422 | Fusionar consigo misma, con un descendiente o entre tipos distintos |
| `ciclo_en_arbol` | 422 | Mover una temática dentro de su propio subárbol |
| `profundidad_maxima` | 422 | El movimiento superaría los 6 niveles de anidación |
| `splits_no_cuadran` | 422 | La suma de splits no coincide con el importe |
| `transferencia_invalida` | 422 | Misma cuenta origen y destino, o transferencia con temática/splits |
| `presupuesto_negativo` | 422 | Asignación de presupuesto negativa |
| `periodo_invalido` | 422 | Periodo que no cumple `AAAA-MM` |
| `periodo_cerrado` | 409 | Modificar asignaciones de un periodo ya cerrado |
| `saldo_insuficiente` | 422 | Retirada de un fondo objetivo mayor que lo acumulado |
| `factura_ya_confirmada` | 409 | Segundo `POST /invoices/{id}/confirm` |
| `factura_no_revisable` | 409 | Editar líneas de una factura en `processing`, `failed` o `confirmed` |
| `factura_duplicada` | 409 | Emisor + número + fecha + total ya registrados (RN-45) |
| `total_no_cuadra` | 422 | Confirmación con líneas que no suman el total y sin `allow_total_mismatch` |
| `pdf_invalido` | 422 | No es un PDF, está cifrado o está dañado |
| `pdf_demasiadas_paginas` | 422 | Supera `max_pdf_pages` |
| `fichero_demasiado_grande` | 413 | Supera `max_upload_mb` |
| `tipo_no_soportado` | 415 | `multipart` ausente o extensión/firma no admitida |
| `cuota_almacenamiento` | 409 | El usuario supera su cuota de adjuntos |
| `importacion_ya_confirmada` | 409 | Segundo `commit` de la misma importación |
| `mapeo_incompleto` | 422 | `commit` de un CSV sin columnas obligatorias mapeadas |
| `producto_no_fusionado` | 422 | Deshacer una fusión de producto que no existe o ya caducó |
| `idempotencia_conflicto` | 409 | Misma `Idempotency-Key` con cuerpo distinto |
| `precondicion_fallida` | 412 | `If-Match` con `ETag` obsoleto (edición concurrente) |
| `datos_invalidos` | 422 | Validación de esquema (lo genera `errors.py`) |
| `error_interno` | 500 | Excepción no controlada (lo genera `errors.py`) |

### 1.3 Códigos HTTP por situación

| Código | Cuándo se usa exactamente |
|---|---|
| `200 OK` | Lectura correcta; actualización (`PATCH`/`PUT`) que devuelve el recurso; acción que devuelve un resultado calculado (`merge`, `confirm`, `apply`) |
| `201 Created` | Alta de un recurso. Siempre con cabecera `Location` y el recurso completo en el cuerpo |
| `202 Accepted` | Trabajo aceptado y encolado: subida de factura, importación, exportación. El cuerpo trae el recurso con `status` y la ruta de sondeo |
| `204 No Content` | Borrado correcto, `logout`, marcar alertas como leídas, cambio de contraseña. Sin cuerpo |
| `304 Not Modified` | `GET` con `If-None-Match` sobre un informe o un estado de factura que no ha cambiado |
| `400 Bad Request` | Petición mal formada que no llega a validarse: JSON roto, `multipart` sin partes, parámetros incompatibles entre sí |
| `401 Unauthorized` | Sin sesión, sesión caducada o credenciales erróneas. Es el único código que dispara el reintento con `POST /auth/refresh` en el cliente |
| `403 Forbidden` | Sesión válida pero operación prohibida: CSRF inválido, registro deshabilitado |
| `404 Not Found` | El recurso no existe **o pertenece a otro usuario** (RN-02: nunca se distingue, para no filtrar existencia) |
| `405 Method Not Allowed` | Método no soportado en una ruta existente |
| `409 Conflict` | Conflicto con el estado actual: duplicado, ya confirmado, temática con histórico, periodo cerrado |
| `412 Precondition Failed` | `If-Match` no coincide con el `ETag` actual |
| `413 Payload Too Large` | Fichero por encima de `max_upload_mb` o cuerpo JSON por encima de 1 MiB |
| `415 Unsupported Media Type` | `Content-Type` no admitido para el endpoint |
| `422 Unprocessable Entity` | Validación de esquema o **regla de negocio** de §5 |
| `429 Too Many Requests` | Límite de tasa. Siempre con `Retry-After` |
| `500 Internal Server Error` | Fallo no previsto. Traza completa en el log del servidor, nunca en la respuesta |
| `503 Service Unavailable` | Dependencia caída (base de datos) durante el arranque o un fallo de pool |

### 1.4 Paginación: `page`/`size`, no cursor

**Decisión: paginación por número de página con total** (`page`, `size`, `total`, `pages`).

Justificación, en este orden:

1. **La interfaz ya la exige.** `docs/ux/design-system.md` §5.17 especifica «Mostrando 1–50 de
   1.284», selector de tamaño 25/50/100/200, botones numéricos con elisión (`1 … 4 5 6 … 43`),
   página reflejada en la URL y salto a una página arbitraria. Un cursor opaco no puede dar
   ninguna de esas cuatro cosas: no hay total, no hay número de página, no hay salto directo y
   no hay enlace compartible estable.
2. **El volumen lo permite.** Es una app personal self-hosted: el orden de magnitud son
   miles-decenas de miles de transacciones por usuario, no millones. `COUNT(*)` con un índice
   por `(user_id, date DESC, id DESC)` y `OFFSET` de unas pocas páginas es irrelevante frente
   al coste de la propia consulta. El argumento clásico contra el `OFFSET` (degradación en
   tablas gigantes) no se aplica a esta escala.
3. **El coste del total se paga una sola vez.** Se calcula con `COUNT(*) OVER ()` en la misma
   consulta que la página (§7.2), así que no hay una segunda ida a la base de datos.
4. **Estabilidad suficiente.** El orden por defecto siempre incluye un desempate por `id`, con
   lo que el orden es total y determinista; el «salto de filas» al insertar datos mientras se
   pagina es un problema teórico en una app de un solo usuario que además está viendo su
   propio mes.

Donde el cursor **sí** se usa, porque ahí no hay UI que paginar y el volumen no está acotado:

- `GET /exports/{id}/file` y `GET /reports/*?format=csv`: respuesta **en streaming**, sin
  paginación, recorriendo con *keyset* (`WHERE (date, id) < (:last_date, :last_id)`) para no
  cargar nada en memoria.
- `GET /transactions?cursor=…`: modo alternativo **opcional** para el botón «Cargar 50 más»
  del design system y para scripts. Si se envía `cursor`, se ignora `page` y la respuesta
  incluye `next_cursor` y omite `total`. La paginación numérica no desaparece nunca.

**Sobre de respuesta** (idéntico en todos los listados):

```json
{
  "items": [],
  "page": 1,
  "size": 50,
  "total": 1284,
  "pages": 26,
  "next_cursor": null
}
```

Parámetros: `page` ≥ 1 (por defecto 1), `size` entre 1 y **200** (por defecto 50; los valores
que ofrece la UI son 25/50/100/200). `size` mayor que 200 → `422 datos_invalidos`. Una `page`
mayor que `pages` devuelve `200` con `items: []`, nunca `404`.

### 1.5 Filtrado

Convenciones únicas para todos los listados, para que el cliente pueda construir la
*query string* mecánicamente desde los chips de filtro de la UI:

| Patrón | Significado | Ejemplo |
|---|---|---|
| `q` | Búsqueda de texto libre, mínimo 2 caracteres, sin distinguir acentos ni mayúsculas | `q=mercadona` |
| `<campo>_from` / `<campo>_to` | Rango cerrado e inclusivo | `date_from=2026-01-01&date_to=2026-03-31` |
| `min_<campo>` / `max_<campo>` | Rango numérico inclusivo, importes como string decimal | `min_amount=10.00&max_amount=99.99` |
| `<campo>_id` | Igualdad por identificador. Repetible: se interpreta como `IN` | `account_id=…&account_id=…` |
| `<campo>` con enum | Igualdad. Repetible | `type=expense&type=transfer` |
| `has_<algo>` | Booleano de existencia | `has_invoice=true`, `has_attachments=false` |
| `is_<algo>` / `only_<algo>` | Booleano de estado | `is_archived=false`, `only_recurring=true` |
| `include_children` | Incluye el subárbol de la temática filtrada (por defecto `true`) | `category_id=…&include_children=false` |
| `period` | Periodo mensual `AAAA-MM` | `period=2026-08` |
| `include` | Relaciones a expandir, separadas por comas (§7.1) | `include=splits,tags,payee` |

Reglas transversales:

- Los booleanos aceptan `true`/`false` en minúsculas. Un parámetro vacío (`?q=`) se trata como
  ausente — así lo envía ya `construirUrl()` en `api.ts`, que descarta `''`, `null` y
  `undefined`.
- Filtro desconocido → se **ignora** en silencio (evita romper enlaces guardados al retirar un
  filtro). Filtro conocido con valor inválido → `422 datos_invalidos`.
- `date_from > date_to` → `400 error_solicitud`.
- El filtrado por temática es **jerárquico por defecto**: `category_id` de un padre incluye a
  sus descendientes (§7.3, columna `path`).
- Todo listado está implícitamente filtrado por el `user_id` de la sesión (RN-01).

### 1.6 Ordenación

Un único parámetro `sort` con lista separada por comas y `-` para descendente:

```
GET /transactions?sort=-date,-amount
GET /products?sort=name
GET /payees?sort=-total_spent
```

- Solo se admiten los campos declarados por endpoint (whitelist en el esquema de consulta);
  cualquier otro → `422 datos_invalidos` con `campo: "sort"`. Nunca se interpola texto del
  cliente en el `ORDER BY`.
- El backend **siempre** añade `id` como último criterio de desempate, aunque el cliente no lo
  pida, para que la paginación sea determinista.
- Orden por defecto por recurso: transacciones `-date,-created_at`; facturas `-uploaded_at`;
  temáticas `position` dentro de cada padre; productos `name`; alertas `-created_at`;
  precios `-observed_at`.

### 1.7 Importes: string decimal, siempre

**Todo importe monetario viaja en JSON como cadena de texto con punto decimal**, tanto en las
peticiones como en las respuestas. Nunca como número JSON.

```json
{ "amount": "1234.56", "unit_price": "0.1487", "total": "-45.00" }
```

Motivo: un número JSON es un `double` en cualquier cliente JavaScript y `0.1 + 0.2` no es
`0.3`. La base de datos ya usa `Numeric(14, 2)` (`Money` en `app/db/base.py`) precisamente
para no arrastrar errores de redondeo, y el precio unitario de luz, gas o telefonía llega con
cuatro o seis decimales (`app/services/numeros.py` lo respeta explícitamente). Serializar como
número tiraría por tierra las dos cosas. El frontend ya está preparado: `aNumero()` en
`frontend/src/lib/formato.ts` acepta `string | number`.

Reglas concretas:

- **Formato de salida**: punto como separador decimal, sin separador de miles, sin símbolo de
  moneda, signo `-` delante si es negativo. Los importes de dinero se serializan **siempre con
  dos decimales exactos** (`"45.00"`, no `"45"`). Los precios unitarios y las cantidades
  conservan sus decimales significativos hasta 4 (`"0.1487"`, `"1.5"`).
- **Formato de entrada**: se acepta la misma forma (`"45"`, `"45.0"`, `"45.00"` son válidos y
  equivalentes). Se **rechaza** con `422` un número JSON (`45.0` sin comillas), la coma decimal
  (`"45,00"` — eso es cosa de la capa de presentación), el separador de miles, el símbolo de
  moneda y la notación científica. El validador de §4.1 lo impone.
- **Precisión**: dinero, 2 decimales y máximo 14 dígitos (coincide con `Numeric(14,2)`); precio
  unitario y cantidad, 4 decimales y máximo 16 dígitos. Más decimales de los admitidos →
  `422 datos_invalidos` (`decimal_max_places`, ya traducido en `errors.py` a «Como máximo dos
  decimales»).
- **Signo**: en la base de datos los importes son **firmados** (gasto negativo, ingreso
  positivo, transferencia dos filas que suman cero: ver `docs/arquitectura/modelo-datos.md`
  §0.5). En la API, el caso normal se escribe en **positivo** y el `kind` expresa la intención
  (`expense`, `income`), porque es lo que teclea el usuario en el formulario. Se admite
  **negativo con `kind="expense"`** para el único caso en que hace falta: devoluciones,
  reembolsos, abonos de una factura y ajustes de conciliación, que deben **reducir el gastado de
  su temática** en lugar de inflar los ingresos del mes. Lo que no se admite nunca es
  `amount = 0`. En las respuestas viajan los dos valores: `amount` (como se capturó) y
  `signed_amount` (el efecto sobre el saldo, ya firmado), para que ningún cliente tenga que
  deducir el signo.
- La moneda va aparte, en `currency` (ISO 4217, tres letras mayúsculas, `EUR` por defecto según
  `settings.default_currency`), nunca pegada al importe.
- Los porcentajes y ratios (confianza, variación) **sí** son números JSON: no son dinero, no se
  suman y una décima de más no descuadra nada. `confidence` va de 0 a 1 con dos decimales;
  `change_pct` es un número con signo (`8.42` = +8,42 %).

### 1.8 Fechas, periodos y zona horaria

- **Fechas** (`date`, `observed_at` de un precio): `AAAA-MM-DD`, sin hora, sin zona. Son fechas
  civiles: la fecha de una compra no cambia porque el usuario viaje.
- **Instantes** (`created_at`, `updated_at`, `uploaded_at`, `confirmed_at`): ISO 8601 en **UTC**
  con sufijo `Z`. La base de datos usa `DateTime(timezone=True)`.
- **Periodo de presupuesto**: cadena `AAAA-MM`, validada con
  `^\d{4}-(0[1-9]|1[0-2])$` (RN-30). Es el formato que ya producen y consumen `periodoDe()`,
  `etiquetaPeriodo()` y `desplazarPeriodo()` en `formato.ts`.
- La zona horaria del usuario (`settings.default_timezone`, `Europe/Madrid`) solo se usa para
  decidir qué es «hoy» y a qué periodo pertenece una fecha cuando el servidor genera datos
  (recurrentes, alertas, digest). Nunca se convierte un `date` recibido.

### 1.9 Idempotencia

Las operaciones peligrosas de repetir aceptan la cabecera **`Idempotency-Key`** (UUIDv4
generado por el cliente):

| Endpoint | Por qué | Comportamiento sin la cabecera |
|---|---|---|
| `POST /invoices` | Reintento de una subida cortada duplicaría la factura | Se cae al hash SHA-256 del fichero (RN-44): devuelve `200` con la factura existente |
| `POST /invoices/{id}/confirm` | Doble clic crearía dos transacciones | `409 factura_ya_confirmada` (RN-46) |
| `POST /imports/{id}/commit` | Duplicaría cientos de movimientos | `409 importacion_ya_confirmada` |
| `POST /transactions` | Doble clic en «Guardar» con conexión lenta | Se acepta; queda a cargo de `GET /transactions/duplicates` |
| `POST /transfers` | Ídem, con doble efecto en dos cuentas | Ídem |
| `POST /recurring/{id}/post` | Materializar dos veces la misma cuota | Unicidad por `(recurring_id, occurrence_date)`: `409 conflicto` |
| `POST /budgets/{period}/close` | Aplicaría el rollover dos veces | Idempotente por diseño (RN-33): repetir no cambia nada |
| `POST /rules/apply` | Reaplicar reglas sobre el histórico | Idempotente por diseño (la acción es «poner temática X», no «sumar») |
| `POST /exports` | Generaría ficheros gigantes de más | Se acepta; los exports caducan a los 7 días |
| `POST /goals/{id}/contribute` | Duplicaría la aportación | Se acepta |

Semántica: se guarda `(user_id, endpoint, key)` → `(hash del cuerpo, código, respuesta)`
durante **24 h**. Repetir la misma clave con el mismo cuerpo devuelve la **respuesta guardada
tal cual** (mismo código, mismo JSON) y la cabecera `Idempotent-Replay: true`. Repetir la misma
clave con un cuerpo distinto → `409 idempotencia_conflicto`. Una petición en curso con la misma
clave → `409 conflicto` con `Retry-After: 2`.

`PUT` y `DELETE` son idempotentes por definición: `PUT /transactions/{id}/splits` deja siempre
el mismo estado final y `DELETE` sobre algo ya borrado devuelve `204`, no `404`.

### 1.10 Concurrencia optimista

Los recursos que se editan desde varias pestañas o desde una pantalla de revisión larga
devuelven `ETag` (hash débil de `updated_at` + `id`) y aceptan `If-Match` en `PATCH`/`PUT`:

- Aplica a: `PATCH /transactions/{id}`, `PUT /transactions/{id}/splits`,
  `PATCH /invoices/{id}`, `PUT /invoices/{id}/lines`, `PATCH /invoices/{id}/lines/{line_id}`,
  `PUT /budgets/{period}/allocations`, `PATCH /categories/{id}`, `PATCH /products/{id}`.
- `If-Match` obsoleto → `412 precondicion_fallida` con el `ETag` actual en la respuesta, para
  que el cliente recargue y avise («Alguien ha cambiado esto mientras editabas»).
- `If-Match` ausente → se acepta (last-write-wins). No se exige para no complicar el cliente en
  los formularios simples; la revisión de facturas sí lo envía siempre.
- `GET` de informes y de `GET /invoices/{id}/status` admiten `If-None-Match` → `304`.

### 1.11 CSRF en cada petición mutante

Todo `POST`, `PATCH`, `PUT` y `DELETE` exige la cabecera `X-CSRF-Token` con el mismo valor que
la cookie `csrf_token` (`csrf_tokens_match()` compara en tiempo constante). Si falta o no
coincide → `403 csrf_invalido`. `GET`, `HEAD` y `OPTIONS` están exentos — así lo hace ya
`api.ts` con su `METODOS_SIN_CSRF`. Las únicas excepciones son `POST /auth/register`,
`POST /auth/login` y `GET /auth/csrf`, que no pueden exigir una cookie que aún no existe: ahí
se valida en su lugar el `Origin`/`Sec-Fetch-Site` contra los orígenes permitidos.

### 1.12 Límites de tasa

Todas las respuestas de endpoints limitados llevan `RateLimit-Limit`, `RateLimit-Remaining` y
`RateLimit-Reset` (segundos). Un `429` lleva además `Retry-After`. Detalle por endpoint en §2.4
y §8.4.

### 1.13 Cabeceras de correlación

Cada respuesta lleva `X-Request-Id` (UUID). Si la petición ya trae `X-Request-Id`, se respeta.
Es el identificador que aparece en los logs (§9) y el que se pide al usuario cuando reporta un
`500`.

---

## 2. Autenticación y sesión

### 2.1 Las tres cookies

| Cookie | Contenido | `httpOnly` | `Secure` | `SameSite` | `Path` | Vida |
|---|---|---|---|---|---|---|
| `access_token` | JWT `typ=access` firmado HS256 | **Sí** | `settings.cookie_secure` | `Lax` | `/api/v1` | `access_token_minutes` (30 min) |
| `refresh_token` | JWT `typ=refresh` con `jti` registrado | **Sí** | `settings.cookie_secure` | `Lax` | `/api/v1/auth` | `refresh_token_days` (30 días) |
| `csrf_token` | 32 bytes aleatorios (`generate_csrf_token()`) | **No** (debe leerlo el JS) | `settings.cookie_secure` | `Lax` | `/` | Igual que el refresco |

Notas de diseño:

- El `Path` del refresco se restringe a `/api/v1/auth`: así el token de refresco **no se envía
  en las cientos de peticiones normales** de la aplicación. Solo viaja cuando de verdad se va a
  usar. Menos superficie de exposición en logs de proxy y en errores.
- `SameSite=Lax` y no `Strict`: con `Strict`, entrar en la aplicación desde un enlace externo
  (el email del digest de F-45, un marcador compartido) mostraría la pantalla de login pese a
  tener sesión válida, porque el navegador no manda la cookie en la navegación entrante.
  `Lax` sí la manda en navegaciones `GET` de nivel superior y **no** la manda en peticiones
  `POST` cross-site, que es exactamente lo que interesa. La defensa contra CSRF no descansa
  solo en esto: el doble envío la completa.
- `Secure` sale de la configuración porque en desarrollo se sirve por HTTP en `localhost`. En
  producción `COOKIE_SECURE=true` es obligatorio (§8.1).
- `cookie_domain` se deja vacío salvo despliegue multi-subdominio: sin `Domain` la cookie es
  *host-only*, que es más restrictivo.

### 2.2 Ciclo de vida completo

```
1. Arranque de la SPA (sin sesión)
   GET /api/v1/meta                → 200 + Set-Cookie: csrf_token=… (si no la había)
                                     El cliente ya puede enviar X-CSRF-Token.

2. Login
   POST /api/v1/auth/login
     Cuerpo: {"email": …, "password": …}
     Cabecera: X-CSRF-Token (de la cookie del paso 1)
   → 200 {user}
     Set-Cookie: access_token=…   (httpOnly, Lax, Path=/api/v1, 30 min)
     Set-Cookie: refresh_token=…  (httpOnly, Lax, Path=/api/v1/auth, 30 d)
     Set-Cookie: csrf_token=…     (rotada: nuevo valor al iniciar sesión)

3. Uso normal
   GET  /api/v1/transactions      → cookie de acceso automática, sin cabecera de auth
   POST /api/v1/transactions      → + X-CSRF-Token leída de la cookie

4. Caducidad del acceso a los 30 minutos
   GET  /api/v1/transactions      → 401 {"error":{"codigo":"no_autenticado"}}
   El cliente (api.ts) detecta el 401, lanza UNA sola renovación compartida:
   POST /api/v1/auth/refresh      → 200
     Set-Cookie: access_token=…   (nuevo)
     Set-Cookie: refresh_token=…  (ROTADO: el jti anterior queda revocado)
     Set-Cookie: csrf_token=…     (rotada)
   y reintenta la petición original una única vez (sinReintento=true).

5. Refresco inválido, caducado o reutilizado
   POST /api/v1/auth/refresh      → 401 {"codigo":"sesion_expirada"} + borrado de las 3 cookies
   El cliente ejecuta alPerderSesion() y navega al login.

6. Logout
   POST /api/v1/auth/logout       → 204, revoca el jti del refresco y borra las 3 cookies
                                     (Set-Cookie con Max-Age=0 en los mismos Path)
```

**Rotación y detección de reutilización**: cada `refresh` invalida el `jti` consumido y emite
uno nuevo (familia de tokens). Si llega un `jti` ya consumido, se asume robo del token: se
revoca **toda la familia** de esa sesión y se responde `401 sesion_expirada`. Los `jti`
revocados viven en tabla hasta su `exp` natural; una tarea diaria los limpia.

**El cliente no toca nada de esto**: `frontend/src/lib/api.ts` no guarda ni un token. Solo lee
la cookie `csrf_token` (que sí es legible) y sabe reaccionar al `401`. Es el diseño que ya
está implementado.

### 2.3 Por qué cookies httpOnly y no `Bearer` en `localStorage`

| Aspecto | Cookie httpOnly + SameSite + CSRF | `Bearer` en `localStorage` |
|---|---|---|
| **XSS** | Un script inyectado **no puede leer** el token: no existe API de JS que lea una cookie `httpOnly`. Puede hacer peticiones en nombre del usuario mientras la página vive, pero **no puede exfiltrar la credencial** para usarla luego desde otro sitio | `localStorage.getItem('token')` y ya está: el atacante se lleva un token válido durante toda su vigencia y lo usa desde su propia máquina, fuera de toda telemetría |
| **Persistencia del daño** | El daño acaba cuando se cierra la pestaña o se revoca el `jti` | El token robado sigue sirviendo hasta que caduca; si se guardó también el refresco, indefinidamente |
| **CSRF** | Es el riesgo que introduce, y se cierra con dos capas: `SameSite=Lax` (el navegador no manda la cookie en `POST` cross-site) **+** doble envío (`csrf_token` + `X-CSRF-Token`), que un sitio ajeno no puede replicar porque no puede leer la cookie del dominio | No hay CSRF, pero se paga con lo de arriba |
| **Código de cliente** | Cero gestión de credenciales: el navegador adjunta la cookie. `api.ts` solo copia una cookie a una cabecera | Hay que interceptar cada petición, guardar, refrescar, sincronizar entre pestañas y limpiar en logout. Cada uno de esos pasos es una oportunidad de filtración |
| **Revocación** | Inmediata en servidor: se borra el `jti` de la familia | Imposible sin una lista negra que, de todos modos, ya obliga a estado en servidor |
| **Encaje con este proyecto** | El despliegue es un **monolito**: FastAPI sirve la SPA y la API en el mismo origen (`app/main.py`). Las cookies son *same-origin*, sin CORS con credenciales, sin preflight extra | Ninguna ventaja aquí: el argumento habitual del `Bearer` (API consumida desde otro dominio o desde móvil nativo) no aplica |
| **Fugas accidentales** | La cookie no aparece en el `Authorization` de una traza copiada, ni en un `console.log`, ni en un informe de error del navegador | Los tokens acaban en logs, capturas y errores de terceros con una facilidad notable |

Resumen: `localStorage` cambia un riesgo que se puede mitigar por completo (CSRF, con dos
mecanismos independientes y verificables) por uno que no se puede mitigar (exfiltración de la
credencial vía XSS). Para una aplicación que administra el dinero de una persona, ese cambio no
compensa. Como refuerzo, `app/main.py` ya envía `X-Content-Type-Options`, `X-Frame-Options:
DENY`, `Referrer-Policy: same-origin` y HSTS en producción; se añade CSP (§8.2).

### 2.4 Límites de tasa en autenticación

Cubo con fichas (*token bucket*) en memoria del proceso — coherente con el despliegue de un
solo contenedor — más bloqueo por credencial persistido en base de datos, para que un reinicio
no borre el bloqueo:

| Endpoint | Límite por IP | Límite por identidad | Al superarlo |
|---|---|---|---|
| `POST /auth/login` | 10 / minuto, 60 / hora | 5 intentos fallidos consecutivos por email | Bloqueo del email con espera exponencial: 1, 2, 4, 8, 15 min (tope 15). `429 demasiadas_peticiones` + `Retry-After`. Un login correcto reinicia el contador |
| `POST /auth/register` | 5 / hora | — | `429` |
| `POST /auth/refresh` | 60 / hora | 30 / hora por familia de sesión | `429`; un exceso desmedido revoca la familia |
| `POST /auth/change-password` | 10 / hora | 5 fallos de contraseña actual / hora | `429` + revocación de todas las demás sesiones |
| `DELETE /users/me` | 3 / hora | — | `429` |
| `GET /auth/csrf`, `GET /meta` | 120 / minuto | — | `429` |

Detalles que importan:

- **Respuesta uniforme y tiempo constante**: usuario inexistente y contraseña incorrecta
  devuelven exactamente `401 credenciales_invalidas` con el mismo mensaje. Si el email no
  existe se verifica igualmente un hash bcrypt señuelo, para no filtrar por tiempo de respuesta
  qué correos están registrados.
- El mensaje de bloqueo **no** dice si el email existe: «Demasiados intentos. Espera un
  momento.» (el `mensaje` por defecto de `DemasiadasPeticiones`).
- La IP se toma del `X-Forwarded-For` **solo** si la petición llega de un proxy de confianza
  configurado (EasyPanel/Traefik). Sin esa comprobación el límite es trivial de esquivar
  falsificando la cabecera.
- El limitador nunca es un punto de fallo: si el almacén de contadores falla, se registra un
  `WARNING` y se **permite** la petición (el resto de defensas siguen en pie).

### 2.5 Endpoints de autenticación y usuario

Ver la tabla completa en §3.1 y §3.2.

---

## 3. Tabla exhaustiva de endpoints

**Cómo leer las tablas**

- Las rutas son relativas a `/api/v1`.
- **Auth**: `—` pública · `S` requiere cookie de sesión válida. **Todo método distinto de `GET`
  exige además `X-CSRF-Token`** (§1.11) y responde `403 csrf_invalido` si falta; no se repite en
  cada fila.
- **Request**: `Q:` parámetros de consulta · `B:` esquema del cuerpo JSON · `M:` multipart ·
  `H:` cabeceras relevantes. Todos los listados aceptan además `page`, `size`, `sort` (§1.4,
  §1.6).
- **Códigos**: se omiten los universales `401` (sin sesión), `403` (CSRF), `422`
  (`datos_invalidos`), `429` y `500`, presentes en todas las rutas que correspondan.
- Los `{id}` son UUID v4. Un UUID mal formado da `422`; uno bien formado que no existe o es de
  otro usuario da `404` (RN-02).

### 3.1 `auth` — sesión

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/auth/csrf` | Emite la cookie `csrf_token` si no existe. Lo llama la SPA al arrancar antes del login | — | — | `{"csrf_token": "…"}` | 200 |
| POST | `/auth/register` | Alta del usuario. Solo si `allow_registration` o si no hay ningún usuario todavía (primer arranque) | — | `B: RegisterIn` | `UserOut` + 3 cookies | 201, 403 `registro_deshabilitado`, 409 `email_ya_registrado`, 422 `contrasenya_debil` |
| POST | `/auth/login` | Inicia sesión y emite acceso + refresco + CSRF | — | `B: LoginIn` | `UserOut` + 3 cookies | 200, 401 `credenciales_invalidas`, 429 |
| POST | `/auth/refresh` | Renueva el acceso rotando el refresco. Es el endpoint al que `api.ts` reintenta ante un 401 | Cookie de refresco | — | `{"expires_at": "…"}` + cookies | 200, 401 `sesion_expirada` |
| POST | `/auth/logout` | Revoca el `jti` actual y borra las tres cookies | S | — | — | 204 |
| POST | `/auth/logout-all` | Revoca **todas** las sesiones del usuario, incluida la actual | S | — | — | 204 |
| POST | `/auth/change-password` | Cambia la contraseña, revoca las demás sesiones y reemite la actual | S | `B: ChangePasswordIn` | — + cookies nuevas | 204, 401 `contrasenya_incorrecta`, 422 `contrasenya_debil` |
| GET | `/auth/me` | «Yo»: usuario de la sesión con sus preferencias y contadores de arranque | S | `Q: include=stats` | `MeOut` | 200 |
| GET | `/auth/sessions` | Sesiones activas (familias de refresco) con dispositivo aproximado y última actividad | S | — | `Page[SessionOut]` | 200 |
| DELETE | `/auth/sessions/{id}` | Revoca una sesión concreta («cerrar sesión en el otro dispositivo») | S | — | — | 204, 404 |

### 3.2 `users` — perfil

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/users/me` | Alias de `/auth/me`, por coherencia REST | S | — | `MeOut` | 200 |
| PATCH | `/users/me` | Cambia nombre, correo, idioma, zona horaria y moneda de visualización | S | `B: UserUpdateIn` | `UserOut` | 200, 409 `email_ya_registrado` |
| DELETE | `/users/me` | Borra la cuenta y **todos** sus datos y ficheros. Exige la contraseña | S | `B: {"password": "…"}` | — | 204, 401 `contrasenya_incorrecta` |
| GET | `/meta` | Metadatos públicos para pintar el login: nombre de la app, `allow_registration`, `first_run`, `max_upload_mb`, `max_pdf_pages`, moneda e idioma por defecto | — | — | `MetaOut` | 200 |
| GET | `/onboarding/status` | Estado del asistente inicial: qué pasos faltan (F-50) | S | — | `OnboardingOut` | 200 |
| POST | `/onboarding/seed` | Crea el juego inicial de temáticas y cuentas a partir de un preset | S | `B: {"preset": "es_basico", "accounts": […]}` | `OnboardingOut` | 200, 409 `conflicto` (ya sembrado) |
| POST | `/onboarding/complete` | Marca el asistente como terminado | S | — | `OnboardingOut` | 200 |

### 3.3 `accounts` — cuentas y patrimonio

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/accounts` | Lista de cuentas con saldo actual calculado | S | `Q: type, is_archived, q, include=balance` | `Page[AccountOut]` | 200 |
| POST | `/accounts` | Crea una cuenta de un tipo (`checking`, `savings`, `cash`, `credit_card`, `investment`, `debt`) con saldo inicial | S | `B: AccountIn` | `AccountOut` | 201, 409 `nombre_duplicado` |
| GET | `/accounts/summary` | Totales por tipo, activos, pasivos y patrimonio neto actual (F-11) | S | `Q: as_of` | `AccountsSummaryOut` | 200 |
| GET | `/accounts/{id}` | Detalle de una cuenta | S | — | `AccountOut` | 200, 404 |
| PATCH | `/accounts/{id}` | Renombra, cambia color/icono, ajusta datos de deuda (cuota, interés, fin) | S | `B: AccountUpdateIn` | `AccountOut` | 200, 404, 409 |
| DELETE | `/accounts/{id}` | Borra la cuenta. Solo si no tiene movimientos | S | — | — | 204, 404, 409 `conflicto` (usar archivado) |
| POST | `/accounts/{id}/archive` | Archiva la cuenta: desaparece de los selectores, conserva el histórico | S | — | `AccountOut` | 200, 404 |
| POST | `/accounts/{id}/unarchive` | Desarchiva | S | — | `AccountOut` | 200, 404 |
| GET | `/accounts/{id}/balance` | Saldo a una fecha, con desglose de pendientes y no conciliados | S | `Q: as_of` | `AccountBalanceOut` | 200, 404 |
| POST | `/accounts/{id}/reconcile` | Conciliación (F-32): compara el saldo real con el registrado y crea el ajuste | S | `B: ReconcileIn` | `ReconcileOut` | 200, 404, 422 |
| GET | `/accounts/{id}/reconciliations` | Historial de conciliaciones | S | — | `Page[ReconciliationOut]` | 200, 404 |
| GET | `/accounts/{id}/amortization` | Calendario de amortización de una cuenta de deuda (F-41) | S | `Q: months` | `AmortizationOut` | 200, 404, 422 (no es de tipo deuda) |

### 3.4 `categories` — temáticas jerárquicas

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/categories` | Lista plana con `path`, `depth` y contadores de uso | S | `Q: q, parent_id, max_depth, is_archived, kind, include=stats` | `Page[CategoryOut]` | 200 |
| GET | `/categories/tree` | Árbol completo anidado, ya ordenado por `position`. Es lo que carga la SPA una vez y cachea | S | `Q: is_archived, kind, period` (para traer asignado/gastado) | `list[CategoryNode]` | 200 |
| POST | `/categories` | Crea una temática, opcionalmente hija de otra | S | `B: CategoryIn` | `CategoryOut` | 201, 404 (padre), 409 `nombre_duplicado`, 422 `profundidad_maxima` |
| GET | `/categories/{id}` | Detalle con antepasados (miga de pan) y número de descendientes | S | — | `CategoryOut` | 200, 404 |
| PATCH | `/categories/{id}` | **Renombra** o cambia color, icono, `rollover_enabled`, `is_locked`, temática por defecto. No rompe el histórico (F-05) | S | `B: CategoryUpdateIn`, `H: If-Match` | `CategoryOut` | 200, 404, 409, 412 |
| DELETE | `/categories/{id}` | Borra. Exige `reassign_to` si tiene histórico, presupuesto o hijos (RN-14) | S | `Q: reassign_to` | — | 204, 404, 409 `tematica_con_historico` / `tematica_con_descendientes` |
| POST | `/categories/{id}/archive` | **Archiva** en vez de borrar (F-06): sale de los selectores, sigue en los informes | S | `Q: cascade=true` | `CategoryOut` | 200, 404 |
| POST | `/categories/{id}/unarchive` | Desarchiva, reactivando también a los antepasados archivados | S | — | `CategoryOut` | 200, 404 |
| POST | `/categories/{id}/move` | **Mueve y reordena en el árbol**: nuevo padre y/o nueva posición entre hermanos | S | `B: CategoryMoveIn` | `CategoryOut` | 200, 404, 422 `ciclo_en_arbol` / `profundidad_maxima` |
| POST | `/categories/reorder` | Reordena varios hermanos de golpe (arrastrar y soltar en la lista) | S | `B: CategoryReorderIn` | `list[CategoryOut]` | 200, 404, 422 |
| POST | `/categories/merge/preview` | **Simula la fusión**: cuántas transacciones, splits, líneas de factura, reglas, recurrentes, presupuestos y fondos se reasignarían, y qué queda tras fusionar | S | `B: CategoryMergeIn` | `CategoryMergePreviewOut` | 200, 404, 422 `fusion_invalida` |
| POST | `/categories/merge` | **Fusiona temáticas reasignando todo el histórico** (F-04): mueve transacciones, splits, líneas, reglas, recurrentes, presupuestos por periodo (sumando asignaciones) y fondos; los hijos de las origen pasan a la destino; las origen se borran | S | `B: CategoryMergeIn`, `H: Idempotency-Key` | `CategoryMergeResultOut` | 200, 404, 409 `periodo_cerrado`, 422 `fusion_invalida` |
| GET | `/categories/merges` | Fusiones recientes, deshacibles durante 30 días | S | — | `Page[CategoryMergeOut]` | 200 |
| POST | `/categories/merges/{id}/undo` | **Deshace una fusión** recreando las temáticas origen y devolviendo cada registro a la suya (usa el registro de reasignación) | S | — | `CategoryMergeResultOut` | 200, 404, 409 `conflicto` (caducada o ya deshecha) |
| GET | `/categories/{id}/usage` | Dónde se usa: transacciones, reglas, recurrentes, fondos, líneas de factura. Es lo que se muestra antes de borrar o fusionar | S | — | `CategoryUsageOut` | 200, 404 |

### 3.5 `transactions` — transacciones, splits y adjuntos

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/transactions` | Listado con **todos los filtros combinables** (F-42) | S | `Q: q, date_from, date_to, account_id*, category_id*, include_children, kind*, min_amount, max_amount, tag_id*, payee_id*, has_invoice, has_attachments, only_recurring, only_uncategorized, only_anomalies, status*, invoice_id, recurring_id, cursor, include=splits,tags,payee,attachments` | `Page[TransactionOut]` | 200, 400 (rango invertido) |
| POST | `/transactions` | Alta rápida de gasto o ingreso (F-07); admite `splits`, `tags`, `payee`, `note` de una vez. Aplica las reglas de auto-categorización si no se da temática | S | `B: TransactionIn`, `H: Idempotency-Key` | `TransactionOut` | 201, 404, 422 `splits_no_cuadran` |
| GET | `/transactions/{id}` | Detalle completo con splits, etiquetas, comercio, adjuntos y factura vinculada | S | `Q: include` | `TransactionOut` | 200, 404 |
| PATCH | `/transactions/{id}` | Edición parcial. Cambiar el importe con splits obliga a reenviarlos (RN-16) | S | `B: TransactionUpdateIn`, `H: If-Match` | `TransactionOut` | 200, 404, 412, 422 |
| DELETE | `/transactions/{id}` | Borra la transacción y sus splits. Si es una pata de transferencia, borra las dos (RN-24) | S | — | — | 204, 404, 409 (procede de factura confirmada: usar `?force=true`) |
| GET | `/transactions/{id}/splits` | Splits de una transacción | S | — | `list[SplitOut]` | 200, 404 |
| PUT | `/transactions/{id}/splits` | **Sustituye el conjunto completo de splits.** Idempotente. La suma debe cuadrar (RN-15) | S | `B: SplitsReplaceIn`, `H: If-Match` | `TransactionOut` | 200, 404, 412, 422 `splits_no_cuadran` |
| DELETE | `/transactions/{id}/splits` | Deshace el desglose y devuelve la transacción a una sola temática | S | `Q: category_id` | `TransactionOut` | 200, 404, 422 |
| POST | `/transactions/bulk-categorize` | Asigna una temática a muchas transacciones seleccionadas | S | `B: {"ids": […], "category_id": …}` | `BulkResultOut` | 200, 404, 422 |
| POST | `/transactions/bulk-tag` | Añade o quita etiquetas en bloque | S | `B: {"ids": […], "add": […], "remove": […]}` | `BulkResultOut` | 200, 404 |
| POST | `/transactions/bulk-delete` | Borra en bloque (máximo 500 por llamada) | S | `B: {"ids": […]}` | `BulkResultOut` | 200, 404, 422 |
| GET | `/transactions/duplicates` | Candidatos a duplicado por importe + fecha ±N días + comercio (F-34) | S | `Q: days=3, account_id, date_from, date_to` | `Page[DuplicateGroupOut]` | 200 |
| POST | `/transactions/{id}/merge` | Fusiona un duplicado en esta transacción: conserva la mejor información de cada una y borra la otra | S | `B: {"duplicate_id": …, "keep": {…}}` | `TransactionOut` | 200, 404, 422 |
| GET | `/transactions/{id}/attachments` | Adjuntos de la transacción (F-21) | S | — | `list[AttachmentOut]` | 200, 404 |
| POST | `/transactions/{id}/attachments` | Sube un adjunto (PDF o imagen) con el campo de formulario **`fichero`** | S | `M: fichero` | `AttachmentOut` | 201, 404, 413, 415, 409 `cuota_almacenamiento` |
| GET | `/attachments/{id}` | Metadatos del adjunto | S | — | `AttachmentOut` | 200, 404 |
| GET | `/attachments/{id}/content` | Descarga el fichero original (`Content-Disposition` saneado, §8.3) | S | `Q: disposition=inline\|attachment` | binario | 200, 404 |
| DELETE | `/attachments/{id}` | Borra el adjunto y su fichero del disco | S | — | — | 204, 404 |

### 3.6 `transfers` — transferencias entre cuentas

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/transfers` | Transferencias como un solo objeto de dos patas (F-09). Equivale a `/transactions?kind=transfer` pero agrupado | S | `Q: date_from, date_to, account_id*` | `Page[TransferOut]` | 200 |
| POST | `/transfers` | Crea la transferencia: dos patas enlazadas por `transfer_group_id`, **sin temática y sin contar como gasto ni ingreso** (RN-21) | S | `B: TransferIn`, `H: Idempotency-Key` | `TransferOut` | 201, 404, 422 `transferencia_invalida` |
| GET | `/transfers/{group_id}` | Detalle de la transferencia con sus dos patas | S | — | `TransferOut` | 200, 404 |
| PATCH | `/transfers/{group_id}` | Cambia importe, fecha, cuentas o nota; actualiza las dos patas en la misma transacción de base de datos | S | `B: TransferUpdateIn` | `TransferOut` | 200, 404, 422 |
| DELETE | `/transfers/{group_id}` | Borra las dos patas | S | — | — | 204, 404 |

### 3.7 `budgets` — presupuesto mensual, rollover e ingresos

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/budgets` | Periodos con presupuesto, con totales por periodo (para el selector de mes) | S | `Q: period_from, period_to` | `Page[BudgetSummaryOut]` | 200 |
| GET | `/budgets/{period}` | **El payload del `BudgetBar`**: ingresos, asignado, gastado, rollover entrante y disponible por temática, más los derivados globales. `period` = `AAAA-MM` | S | `Q: include_archived, depth` | `BudgetOut` | 200, 422 `periodo_invalido` |
| PUT | `/budgets/{period}` | Ajustes del periodo: ingreso previsto (F-01), rollover por defecto, notas | S | `B: BudgetSettingsIn` | `BudgetOut` | 200, 409 `periodo_cerrado`, 422 |
| GET | `/budgets/{period}/allocations` | Asignaciones por temática del periodo | S | — | `list[AllocationOut]` | 200, 422 |
| PUT | `/budgets/{period}/allocations` | **Sustituye el reparto completo** del periodo. Idempotente. Ninguna asignación negativa (RN-28) | S | `B: AllocationsReplaceIn`, `H: If-Match` | `BudgetOut` | 200, 409 `periodo_cerrado`, 412, 422 `presupuesto_negativo` |
| PATCH | `/budgets/{period}/allocations/{category_id}` | Cambia la asignación de **una** temática (edición del campo en la tabla) | S | `B: {"amount": "250.00", "rollover_enabled": true}` | `AllocationOut` | 200, 404, 409, 422 |
| POST | `/budgets/{period}/reassign` | **Reasigna presupuesto entre dos temáticas** sin tocar el total: resta a una y suma a otra. Es el arrastre en la `BudgetBar` | S | `B: BudgetReassignIn` | `BudgetOut` | 200, 404, 409 `periodo_cerrado`, 422 `presupuesto_negativo` / `regla_de_negocio` (temática bloqueada) |
| POST | `/budgets/{period}/copy-from` | Copia el reparto de otro periodo (`source_period`), con estrategia `absolute` o `proportional` al nuevo ingreso | S | `B: BudgetCopyIn` | `BudgetOut` | 200, 404, 409, 422 |
| POST | `/budgets/{period}/distribute` | Reparte lo no asignado entre temáticas según una estrategia (`equal`, `last_period_share`, `average_3m`) | S | `B: BudgetDistributeIn` | `BudgetOut` | 200, 409, 422 |
| GET | `/budgets/{period}/rollover` | Rollover entrante calculado por temática y de dónde viene (F-26) | S | — | `list[RolloverOut]` | 200, 422 |
| POST | `/budgets/{period}/close` | Cierra el periodo y consolida el rollover en el siguiente. **Idempotente** (RN-33) | S | `H: Idempotency-Key` | `BudgetOut` | 200, 422 (periodo futuro) |
| POST | `/budgets/{period}/reopen` | Reabre un periodo cerrado y recalcula el rollover en cascada | S | — | `BudgetOut` | 200, 404 |
| GET | `/budgets/{period}/incomes` | Ingresos registrados del mes que alimentan la barra (F-01) | S | — | `Page[TransactionOut]` | 200, 422 |

### 3.8 `recurring` — recurrentes y suscripciones

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/recurring` | Recurrentes y suscripciones con su próxima fecha e importe esperado (F-28) | S | `Q: kind, is_active, is_subscription, category_id, account_id, q` | `Page[RecurringOut]` | 200 |
| POST | `/recurring` | Crea un recurrente con regla de repetición (`monthly`, `weekly`, `yearly`, `every_n_days`, `last_weekday_of_month`) | S | `B: RecurringIn` | `RecurringOut` | 201, 404, 422 |
| GET | `/recurring/{id}` | Detalle con las últimas ocurrencias materializadas | S | — | `RecurringOut` | 200, 404 |
| PATCH | `/recurring/{id}` | Edita importe, fecha, regla, cuenta, temática o marca de suscripción | S | `B: RecurringUpdateIn` | `RecurringOut` | 200, 404, 422 |
| DELETE | `/recurring/{id}` | Borra la plantilla. Las transacciones ya generadas se conservan | S | — | — | 204, 404 |
| POST | `/recurring/{id}/pause` | Pausa la generación | S | — | `RecurringOut` | 200, 404 |
| POST | `/recurring/{id}/resume` | Reanuda la generación | S | — | `RecurringOut` | 200, 404 |
| POST | `/recurring/{id}/skip` | Salta una ocurrencia concreta (el mes que no se cobró) | S | `B: {"occurrence_date": "2026-09-01"}` | `RecurringOut` | 200, 404, 409 (ya materializada) |
| POST | `/recurring/{id}/post` | Materializa ya una ocurrencia como transacción real, con importe corregible | S | `B: RecurringPostIn`, `H: Idempotency-Key` | `TransactionOut` | 201, 404, 409 `conflicto` |
| GET | `/recurring/upcoming` | Próximos vencimientos en una ventana de días, para el recordatorio (F-49) y el saldo proyectado (F-47) | S | `Q: days=30, account_id` | `list[UpcomingOut]` | 200 |
| GET | `/recurring/detected` | **Suscripciones detectadas** en el histórico y aún no confirmadas (F-29): grupos de cargos similares con periodicidad estimada | S | `Q: min_occurrences=3, months=12` | `Page[DetectedRecurringOut]` | 200 |
| POST | `/recurring/detected/{group_id}/confirm` | Convierte un grupo detectado en un recurrente real y le vincula el histórico | S | `B: RecurringConfirmIn` | `RecurringOut` | 201, 404, 409 |
| POST | `/recurring/detected/{group_id}/dismiss` | Descarta la detección para que no vuelva a proponerse | S | — | — | 204, 404 |
| GET | `/recurring/{id}/price-history` | Evolución del importe cobrado, con las subidas marcadas (F-30) | S | — | `RecurringPriceHistoryOut` | 200, 404 |

### 3.9 `payees` — comercios y proveedores

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/payees` | Comercios con número de transacciones y total gastado | S | `Q: q, category_id, is_archived, include=stats` | `Page[PayeeOut]` | 200 |
| POST | `/payees` | Crea un comercio con temática por defecto y alias | S | `B: PayeeIn` | `PayeeOut` | 201, 409 `nombre_duplicado` |
| GET | `/payees/{id}` | Detalle con alias, temática por defecto y estadísticas | S | — | `PayeeOut` | 200, 404 |
| PATCH | `/payees/{id}` | Renombra, cambia temática por defecto, archiva | S | `B: PayeeUpdateIn` | `PayeeOut` | 200, 404, 409 |
| DELETE | `/payees/{id}` | Borra. Si tiene histórico exige `reassign_to` o lo deja a `null` en las transacciones según `?on_history=null\|reassign` | S | `Q: reassign_to, on_history` | — | 204, 404, 409 |
| POST | `/payees/merge` | Fusiona comercios duplicados («Netflix» y «NETFLIX.COM») reasignando el histórico y quedándose con los alias | S | `B: {"source_ids": […], "target_id": …}` | `PayeeMergeResultOut` | 200, 404, 422 `fusion_invalida` |
| GET | `/payees/suggestions` | Sugerencias por parecido difuso para el autocompletado y la normalización en importaciones | S | `Q: name` | `list[PayeeSuggestionOut]` | 200 |
| GET | `/payees/{id}/stats` | Gasto por mes y por temática en ese comercio | S | `Q: period_from, period_to` | `PayeeStatsOut` | 200, 404 |

### 3.10 `tags` — etiquetas libres

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/tags` | Etiquetas con contador de uso (F-35) | S | `Q: q, include=stats` | `Page[TagOut]` | 200 |
| POST | `/tags` | Crea una etiqueta con color | S | `B: TagIn` | `TagOut` | 201, 409 `nombre_duplicado` |
| PATCH | `/tags/{id}` | Renombra o cambia el color | S | `B: TagUpdateIn` | `TagOut` | 200, 404, 409 |
| DELETE | `/tags/{id}` | Borra la etiqueta y sus vínculos. No borra transacciones | S | — | — | 204, 404 |
| POST | `/tags/merge` | Fusiona etiquetas duplicadas | S | `B: {"source_ids": […], "target_id": …}` | `TagOut` | 200, 404, 422 |

### 3.11 `rules` — auto-categorización

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/rules` | Reglas por orden de prioridad (F-27) | S | `Q: is_active, category_id, q` | `Page[RuleOut]` | 200 |
| POST | `/rules` | Crea una regla: condiciones (`field`, `operator`, `value`) y acciones (temática, etiquetas, comercio, marcar como transferencia) | S | `B: RuleIn` | `RuleOut` | 201, 404, 422 |
| GET | `/rules/{id}` | Detalle con contador de aplicaciones | S | — | `RuleOut` | 200, 404 |
| PATCH | `/rules/{id}` | Edita condiciones, acciones, prioridad o activación | S | `B: RuleUpdateIn` | `RuleOut` | 200, 404, 422 |
| DELETE | `/rules/{id}` | Borra la regla. Lo ya categorizado no cambia | S | — | — | 204, 404 |
| POST | `/rules/reorder` | Reordena la prioridad de evaluación | S | `B: {"ids": […]}` | `list[RuleOut]` | 200, 404, 422 |
| POST | `/rules/test` | Prueba una regla **sin guardarla** contra un texto o contra el histórico: devuelve qué casaría | S | `B: RuleTestIn` | `RuleTestOut` | 200, 422 |
| POST | `/rules/apply` | Aplica reglas al histórico. `dry_run=true` devuelve el recuento sin tocar nada | S | `B: RuleApplyIn`, `H: Idempotency-Key` | `RuleApplyResultOut` | 200, 404, 422 |
| POST | `/rules/parse` | (P2, F-59) Convierte reglas escritas en texto simple (`si comercio contiene "mercadona" -> Alimentación`) en reglas estructuradas | S | `B: {"text": "…"}` | `list[RuleIn]` | 200, 422 |

### 3.12 `invoices` — facturas PDF, revisión y confirmación

Este es el flujo diferencial del producto. El orden de llamadas está en §3.13.

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| POST | `/invoices` | **Sube el PDF** con el campo de formulario **`fichero`** (el que ya usa `api.subir()`). Valida firma, tamaño y páginas antes de aceptar; encola la extracción y responde de inmediato | S | `M: fichero` + `account_id?`, `payee_id?`, `template_id?`, `H: Idempotency-Key` | `InvoiceOut` (`status: processing`) | **202**, 200 (mismo fichero ya subido, RN-44), 413 `fichero_demasiado_grande`, 415 `tipo_no_soportado`, 422 `pdf_invalido` / `pdf_demasiadas_paginas`, 409 `cuota_almacenamiento` |
| GET | `/invoices` | Bandeja de facturas | S | `Q: status*, payee_id, date_from, date_to, q, min_total, max_total, has_transaction, confidence_below` | `Page[InvoiceOut]` | 200 |
| GET | `/invoices/{id}` | Cabecera de la factura con método de extracción, confianza, avisos y resumen de líneas | S | `Q: include=lines,duplicates` | `InvoiceOut` | 200, 404 |
| GET | `/invoices/{id}/status` | **Sondeo del procesado**, barato y cacheable: `status`, `progress`, `method`, `pages`, `confidence`, `lines_count`, `error`. Devuelve `Retry-After` mientras procesa y admite `If-None-Match` | S | `H: If-None-Match` | `InvoiceStatusOut` | 200, **304**, 404 |
| GET | `/invoices/{id}/lines` | **Líneas extraídas para revisar**, con confianza por línea, aviso de descuadre, producto sugerido por parecido difuso, temática sugerida y variación de precio frente al último visto | S | `Q: include_suggestions=true` | `InvoiceLinesOut` | 200, 404 |
| PATCH | `/invoices/{id}` | **Corrige la cabecera** durante la revisión: emisor, NIF, número, fecha, base, impuestos, total, moneda, comercio, cuenta, temática por defecto | S | `B: InvoiceUpdateIn`, `H: If-Match` | `InvoiceOut` | 200, 404, 409 `factura_no_revisable`, 412, 422 |
| PUT | `/invoices/{id}/lines` | **Guarda la revisión completa de las líneas** (añadidas, corregidas y eliminadas) en una sola llamada. Idempotente: sustituye el conjunto | S | `B: InvoiceLinesReplaceIn`, `H: If-Match` | `InvoiceLinesOut` | 200, 404, 409 `factura_no_revisable`, 412, 422 |
| PATCH | `/invoices/{id}/lines/{line_id}` | **Corrige una línea**: descripción, cantidad, unidad, precio unitario, total, temática, producto, exclusión | S | `B: InvoiceLineUpdateIn`, `H: If-Match` | `InvoiceLineOut` | 200, 404, 409, 412, 422 |
| POST | `/invoices/{id}/lines` | Añade a mano una línea que el parser no vio | S | `B: InvoiceLineCreateIn` | `InvoiceLineOut` | 201, 404, 409, 422 |
| DELETE | `/invoices/{id}/lines/{line_id}` | Descarta una línea mal leída (cabecera de tabla, fila de totales) | S | — | — | 204, 404, 409 |
| POST | `/invoices/{id}/lines/{line_id}/link-product` | **Vincula la línea a un producto del catálogo**: a uno existente, o crea uno nuevo desde la descripción normalizada. Guarda el alias para que la próxima vez se reconozca solo | S | `B: LinkProductIn` | `InvoiceLineOut` | 200, 404, 409, 422 |
| DELETE | `/invoices/{id}/lines/{line_id}/link-product` | Desvincula la línea del producto (sin borrar el producto) | S | — | `InvoiceLineOut` | 200, 404, 409 |
| POST | `/invoices/{id}/lines/{line_id}/split` | Reparte una línea en varias (un pack que son dos productos distintos) | S | `B: {"parts": [{…}]}` | `list[InvoiceLineOut]` | 200, 404, 422 |
| POST | `/invoices/{id}/confirm` | **Confirma la revisión**: crea (o vincula) la transacción, genera los splits por temática a partir de las líneas, registra las observaciones de precio en el catálogo, dispara la detección de subidas y pasa la factura a `confirmed`. Solo una vez (RN-46) | S | `B: InvoiceConfirmIn`, `H: Idempotency-Key`, `If-Match` | `InvoiceConfirmResultOut` | 200, 404, 409 `factura_ya_confirmada` / `factura_duplicada`, 412, 422 `total_no_cuadra` |
| POST | `/invoices/{id}/unconfirm` | Revierte la confirmación: borra la transacción generada y las observaciones de precio de esta factura, y vuelve a `pending_review` | S | `Q: keep_transaction=false` | `InvoiceOut` | 200, 404, 409 |
| POST | `/invoices/{id}/reprocess` | Vuelve a extraer, opcionalmente con una plantilla de proveedor. Descarta las líneas no corregidas a mano y conserva las que sí (`keep_edited=true`) | S | `B: {"template_id": …, "force_ocr": false, "keep_edited": true}` | `InvoiceOut` (`status: processing`) | 202, 404, 409 `factura_no_revisable` |
| DELETE | `/invoices/{id}` | Descarta la factura y borra su PDF. Si está confirmada, exige `?force=true` y deja la transacción salvo `?delete_transaction=true` | S | `Q: force, delete_transaction` | — | 204, 404, 409 |
| GET | `/invoices/{id}/file` | Descarga o previsualiza el PDF original (la pantalla de revisión lo muestra al lado) | S | `Q: disposition=inline` | `application/pdf` | 200, 404 |
| GET | `/invoices/{id}/duplicates` | Facturas candidatas a duplicado por **emisor + número + fecha + total** (RN-45) | S | — | `list[InvoiceDuplicateOut]` | 200, 404 |
| GET | `/invoices/templates` | Plantillas de extracción por proveedor (F-40) | S | `Q: q` | `Page[InvoiceTemplateOut]` | 200 |
| POST | `/invoices/templates` | Crea una plantilla, opcionalmente **aprendida de una factura ya corregida** (`from_invoice_id`) | S | `B: InvoiceTemplateIn` | `InvoiceTemplateOut` | 201, 404, 422 |
| GET | `/invoices/templates/{id}` | Detalle de la plantilla | S | — | `InvoiceTemplateOut` | 200, 404 |
| PATCH | `/invoices/templates/{id}` | Edita patrones y mapeo de columnas | S | `B: InvoiceTemplateUpdateIn` | `InvoiceTemplateOut` | 200, 404, 422 |
| DELETE | `/invoices/templates/{id}` | Borra la plantilla | S | — | — | 204, 404 |
| POST | `/invoices/templates/{id}/test` | Prueba la plantilla contra una factura ya subida y devuelve qué habría extraído, sin guardar | S | `B: {"invoice_id": …}` | `InvoiceLinesOut` | 200, 404, 422 |

### 3.13 El flujo de revisión de facturas, paso a paso

`extraer_factura()` **no es fiable al 100 %** —lo dice su propio docstring— así que el contrato
está construido para que **sea imposible guardar sin revisar**. Máquina de estados:

```
                  ┌──────────────┐
POST /invoices ──▶ │  processing  │ (202; el PDF ya está validado y guardado)
                  └──────┬───────┘
              extracción │ en segundo plano (§10)
              ┌──────────┴───────────┐
              ▼                      ▼
      ┌────────────────┐      ┌──────────┐
      │ pending_review │      │  failed  │ (PDF ilegible: el usuario mete los datos a mano
      └───────┬────────┘      └────┬─────┘  sobre la misma factura, o reprocesa con OCR)
              │                    │
              │  PATCH cabecera    └──▶ PATCH /invoices/{id} + POST lines  ──┐
              │  PATCH/PUT líneas                                            │
              │  link-product                                                │
              ▼                                                              │
      ┌────────────────┐                                                     │
      │  (revisada)    │ ◀───────────────────────────────────────────────────┘
      └───────┬────────┘
              │ POST /invoices/{id}/confirm
              ▼
      ┌────────────────┐   POST unconfirm    ┌────────────────┐
      │   confirmed    │ ──────────────────▶ │ pending_review │
      └────────────────┘                     └────────────────┘
              │ DELETE ?force=true
              ▼
      ┌────────────────┐
      │   discarded    │
      └────────────────┘
```

Secuencia real desde el frontend:

1. **`POST /invoices`** con `fichero`. Antes de responder se valida de verdad el PDF
   (`validar_pdf()`: firma `%PDF-`, tamaño, páginas) y se calcula su SHA-256. Si ese hash ya
   existe para el usuario → `200` con la factura anterior (no se duplica el trabajo ni el
   fichero). Si no → se guarda, se encola la extracción y se responde **`202`** con
   `status: "processing"`.
2. **`GET /invoices/{id}/status`** cada 1,5 s (el propio `Retry-After` marca el ritmo) hasta
   `pending_review` o `failed`. Es una consulta de una sola fila, con `ETag`, así que sondear no
   cuesta nada.
3. **`GET /invoices/{id}/lines?include_suggestions=true`** para pintar la pantalla de revisión.
   Cada línea llega con lo que dio el extractor (`description`, `quantity`, `unit`,
   `unit_price`, `total`, `confidence`, `normalized`) **más** lo que el backend puede sugerir:
   `suggested_product` (parecido difuso con `mejor_coincidencia()`, con su `score`),
   `suggested_category` (temática por defecto del producto o del comercio, o la última usada
   para ese producto: F-17), `last_unit_price` y `change_pct` frente a la última observación del
   mismo producto. Las líneas con `confidence < 0.6` y los avisos de la factura vienen marcados
   para que la UI los destaque primero.
4. El usuario corrige. Cada celda editada puede ir por **`PATCH /invoices/{id}/lines/{line_id}`**
   (guardado incremental, lo natural en una tabla editable) o toda la revisión de golpe por
   **`PUT /invoices/{id}/lines`** al pulsar «Guardar borrador». La cabecera (emisor, fecha,
   número, total) se corrige con **`PATCH /invoices/{id}`**. Toda línea tocada a mano queda con
   `is_edited: true` y `confidence: 1.0`, y ya no la sobreescribe un reprocesado.
5. **`POST …/link-product`** por línea: vincular al producto del catálogo, crear uno nuevo o
   dejar la línea como «no es un producto» (`is_product: false`, típico de conceptos de una
   factura de luz: potencia contratada, alquiler de equipo, impuestos). Vincular guarda el alias
   de la descripción cruda para que la próxima factura del mismo proveedor se reconozca sola.
6. **`POST /invoices/{id}/confirm`**. El backend, en **una sola transacción de base de datos**:
   comprueba que las líneas suman el total (tolerancia de 0,02 € o base imponible, como hace
   `evaluar()`; si no cuadra exige `allow_total_mismatch: true`), comprueba duplicado por
   emisor + número + fecha + total, crea la transacción de gasto con sus splits por temática,
   registra una observación de precio por cada línea con producto (única por `invoice_line_id`,
   así que reconfirmar no puede duplicarla), calcula la variación frente al histórico y genera
   alertas de subida (F-16). Respuesta: `transaction_id`, `splits`, `prices_registered`,
   `products_created`, `price_alerts`.
7. Si se detecta el error después, **`POST /invoices/{id}/unconfirm`** deshace de forma limpia:
   borra la transacción generada y las observaciones de precio de esa factura, y devuelve la
   factura a revisión. Sin este endpoint, un error de confirmación obligaría a limpiar a mano en
   tres sitios.

### 3.14 `products` y `prices` — catálogo e histórico de precios

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/products` | Catálogo con último precio, variación y número de observaciones | S | `Q: q, category_id, payee_id, is_archived, has_increase, sort=name\|-last_price\|-change_pct\|-observations` | `Page[ProductOut]` | 200 |
| POST | `/products` | Crea un producto (nombre, marca, tamaño, unidad, temática por defecto, código de barras) | S | `B: ProductIn` | `ProductOut` | 201, 409 `nombre_duplicado` |
| GET | `/products/{id}` | Detalle con alias, estadísticas de precio y comercios donde se ha visto | S | — | `ProductOut` | 200, 404 |
| PATCH | `/products/{id}` | Renombra, corrige tamaño/unidad, cambia temática por defecto o archiva | S | `B: ProductUpdateIn`, `H: If-Match` | `ProductOut` | 200, 404, 409, 412 |
| DELETE | `/products/{id}` | Borra el producto. Con observaciones de precio exige `reassign_to` o `?force=true` (que también borra el histórico de precios) | S | `Q: reassign_to, force` | — | 204, 404, 409 |
| GET | `/products/suggestions` | Candidatos por parecido difuso a una descripción cruda (`normalizar_descripcion` + `mejor_coincidencia`). Lo usa la pantalla de revisión | S | `Q: description, limit=5, min_score=88` | `list[ProductSuggestionOut]` | 200, 422 |
| POST | `/products/merge` | **Fusiona productos** duplicados (F-39): mueve alias, observaciones de precio y líneas de factura a la destino y borra las origen | S | `B: ProductMergeIn`, `H: Idempotency-Key` | `ProductMergeResultOut` | 200, 404, 422 `fusion_invalida` |
| POST | `/products/{id}/split` | **Separa un producto mal fusionado**: extrae las observaciones/líneas indicadas (o todas las de un alias, o todas las de un comercio) a un producto nuevo o existente | S | `B: ProductSplitIn` | `ProductSplitResultOut` | 200, 404, 422 |
| GET | `/products/merges` | Fusiones de producto recientes, deshacibles 30 días | S | — | `Page[ProductMergeOut]` | 200 |
| POST | `/products/merges/{id}/undo` | **Deshace una fusión completa** restaurando los productos origen y devolviendo cada observación a su sitio | S | — | `ProductMergeResultOut` | 200, 404, 422 `producto_no_fusionado` |
| GET | `/products/{id}/aliases` | Descripciones crudas que se han reconocido como este producto | S | — | `list[ProductAliasOut]` | 200, 404 |
| POST | `/products/{id}/aliases` | Añade un alias a mano | S | `B: {"raw_description": "…"}` | `ProductAliasOut` | 201, 404, 409 |
| DELETE | `/products/{id}/aliases/{alias_id}` | Quita un alias mal aprendido | S | — | — | 204, 404 |
| GET | `/products/{id}/prices` | **Historial de precios** del producto (F-15): fecha, comercio, precio unitario, unidad, cantidad, factura de origen | S | `Q: payee_id, date_from, date_to, sort=-observed_at` | `Page[PriceOut]` | 200, 404 |
| GET | `/products/{id}/price-stats` | Mínimo, máximo, media, mediana, último, variación frente al anterior y frente a hace 12 meses | S | `Q: date_from, date_to` | `PriceStatsOut` | 200, 404 |
| GET | `/products/{id}/comparison` | **Comparativa entre comercios** del mismo producto (F-38): último precio por comercio, diferencia con el más barato, fecha de la observación | S | `Q: months=12` | `ProductComparisonOut` | 200, 404 |
| GET | `/prices` | Todas las observaciones de precio, filtrables | S | `Q: product_id, payee_id, date_from, date_to, invoice_id, source` | `Page[PriceOut]` | 200 |
| POST | `/prices` | Registra a mano un precio visto (sin factura: un escaparate, una etiqueta del súper) | S | `B: PriceIn` | `PriceOut` | 201, 404, 409 `conflicto` (misma línea de factura), 422 |
| PATCH | `/prices/{id}` | Corrige una observación mal registrada | S | `B: PriceUpdateIn` | `PriceOut` | 200, 404, 422 |
| DELETE | `/prices/{id}` | Borra una observación | S | — | — | 204, 404 |
| GET | `/baskets` | Cestas guardadas de productos habituales (F-60) | S | — | `Page[BasketOut]` | 200 |
| POST | `/baskets` | Crea una cesta con productos y cantidades | S | `B: BasketIn` | `BasketOut` | 201, 404, 409 |
| PATCH | `/baskets/{id}` | Edita nombre, productos o cantidades | S | `B: BasketUpdateIn` | `BasketOut` | 200, 404 |
| DELETE | `/baskets/{id}` | Borra la cesta | S | — | — | 204, 404 |

### 3.15 `goals` — fondos objetivo

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/goals` | Fondos objetivo con lo acumulado, lo que falta y el ritmo necesario (F-31) | S | `Q: is_completed, category_id, account_id` | `Page[GoalOut]` | 200 |
| POST | `/goals` | Crea un fondo: objetivo, fecha límite, temática y cuenta donde se guarda | S | `B: GoalIn` | `GoalOut` | 201, 404, 422 |
| GET | `/goals/{id}` | Detalle con aportaciones y proyección | S | — | `GoalOut` | 200, 404 |
| PATCH | `/goals/{id}` | Cambia importe objetivo, fecha, nombre o temática | S | `B: GoalUpdateIn` | `GoalOut` | 200, 404, 422 |
| DELETE | `/goals/{id}` | Borra el fondo. Las aportaciones (transferencias) se conservan salvo `?delete_movements=true` | S | `Q: delete_movements` | — | 204, 404 |
| POST | `/goals/{id}/contribute` | Aporta al fondo. Puede generar una transferencia real a la cuenta de ahorro | S | `B: GoalMovementIn`, `H: Idempotency-Key` | `GoalOut` | 200, 404, 422 |
| POST | `/goals/{id}/withdraw` | Retira del fondo. No puede dejarlo en negativo (RN-52) | S | `B: GoalMovementIn` | `GoalOut` | 200, 404, 422 `saldo_insuficiente` |
| GET | `/goals/{id}/movements` | Aportaciones y retiradas del fondo | S | — | `Page[GoalMovementOut]` | 200, 404 |

### 3.16 `alerts` — avisos

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/alerts` | Alertas: sobrepaso de presupuesto (F-20), subida de precio de producto (F-16), subida en recurrente (F-30), gasto inusual (F-48), vencimiento próximo (F-49), factura duplicada, objetivo en riesgo | S | `Q: type*, severity*, is_read, is_dismissed, period, date_from, date_to` | `Page[AlertOut]` | 200 |
| GET | `/alerts/unread-count` | Contador para el badge de la barra lateral. Consulta de un solo `COUNT` | S | — | `{"unread": 3, "by_severity": {…}}` | 200 |
| GET | `/alerts/{id}` | Detalle con el enlace al objeto que la originó | S | — | `AlertOut` | 200, 404 |
| POST | `/alerts/{id}/read` | Marca como leída | S | — | `AlertOut` | 200, 404 |
| POST | `/alerts/read-all` | Marca todas como leídas | S | `B: {"type": …, "period": …}` | `BulkResultOut` | 200 |
| POST | `/alerts/{id}/dismiss` | Descarta la alerta y silencia esa causa concreta durante `mute_days` | S | `B: {"mute_days": 30}` | — | 204, 404 |
| POST | `/alerts/recompute` | Recalcula las alertas de un periodo (tras reasignar presupuesto o corregir precios). Idempotente | S | `B: {"period": "2026-08"}` | `BulkResultOut` | 200, 422 |
| GET | `/alerts/digest` | Previsualiza el resumen semanal/mensual (F-45) tal y como se enviaría | S | `Q: period, range=week\|month` | `DigestOut` | 200, 422 |

### 3.17 `imports` — CSV, OFX y QIF

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| POST | `/imports` | Sube el extracto con el campo **`fichero`** (CSV, OFX o QIF; F-25, F-33). Detecta el formato por contenido, no por extensión. Analiza en segundo plano | S | `M: fichero` + `account_id`, `format?`, `mapping_id?` | `ImportOut` (`status: analyzing`) | 202, 404, 413, 415, 422 |
| GET | `/imports` | Importaciones con su estado y recuentos | S | `Q: status*, account_id` | `Page[ImportOut]` | 200 |
| GET | `/imports/{id}` | Detalle: formato detectado, mapeo, totales, duplicados y errores | S | — | `ImportOut` | 200, 404 |
| GET | `/imports/{id}/status` | Sondeo del análisis, con `Retry-After` | S | `H: If-None-Match` | `ImportStatusOut` | 200, 304, 404 |
| GET | `/imports/{id}/preview` | Filas interpretadas con temática sugerida por las reglas, comercio normalizado y **marca de duplicado** frente a lo ya existente (F-34) | S | `Q: page, size, only_duplicates, only_errors` | `Page[ImportRowOut]` | 200, 404 |
| PUT | `/imports/{id}/mapping` | Fija el mapeo de columnas del CSV, el formato de fecha, el separador decimal y el signo. Reanaliza las filas | S | `B: ImportMappingIn` | `ImportOut` | 200, 404, 409 `importacion_ya_confirmada`, 422 `mapeo_incompleto` |
| PATCH | `/imports/{id}/rows/{row_id}` | Corrige una fila antes de confirmar: temática, comercio, notas, o marcarla como omitida/duplicada | S | `B: ImportRowUpdateIn` | `ImportRowOut` | 200, 404, 409, 422 |
| POST | `/imports/{id}/commit` | **Crea las transacciones** de las filas no omitidas, aplica las reglas y vincula duplicados. Idempotente con `Idempotency-Key` | S | `B: ImportCommitIn`, `H: Idempotency-Key` | `ImportResultOut` | 200, 404, 409 `importacion_ya_confirmada`, 422 `mapeo_incompleto` |
| POST | `/imports/{id}/rollback` | **Deshace una importación confirmada** borrando exactamente las transacciones que creó | S | — | `ImportResultOut` | 200, 404, 409 |
| DELETE | `/imports/{id}` | Descarta la importación sin confirmar y borra el fichero | S | — | — | 204, 404, 409 |
| GET | `/imports/mappings` | Mapeos guardados por banco, para no repetir la configuración | S | — | `Page[ImportMappingOut]` | 200 |
| POST | `/imports/mappings` | Guarda el mapeo actual con un nombre | S | `B: ImportMappingSaveIn` | `ImportMappingOut` | 201, 409 `nombre_duplicado` |
| DELETE | `/imports/mappings/{id}` | Borra un mapeo guardado | S | — | — | 204, 404 |

### 3.18 `exports` — exportación y copia de seguridad

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| POST | `/exports` | Encola una exportación (F-43): `scope` (`all`, `transactions`, `invoices`, `products`, `budgets`, `settings`), `format` (`json`, `csv`, `zip`), rango de fechas y si incluye los PDF originales | S | `B: ExportIn`, `H: Idempotency-Key` | `ExportOut` (`status: pending`) | 202, 422 |
| GET | `/exports` | Exportaciones generadas y su caducidad (7 días) | S | — | `Page[ExportOut]` | 200 |
| GET | `/exports/{id}` | Estado y metadatos de la exportación | S | — | `ExportOut` | 200, 404 |
| GET | `/exports/{id}/file` | Descarga el fichero generado, en streaming | S | — | binario | 200, 404, 409 (aún no lista), 410 (caducada) |
| DELETE | `/exports/{id}` | Borra la exportación y su fichero | S | — | — | 204, 404 |
| GET | `/exports/quick` | Exportación inmediata en streaming de una sola entidad, con los mismos filtros que su listado. Sin trabajo en segundo plano | S | `Q: entity, format=csv\|json` + filtros del listado | `text/csv` \| `application/json` | 200, 422 |

### 3.19 `reports` — informes

Todos aceptan `format=json` (por defecto) o `format=csv` (streaming, sin paginación) y
responden con `ETag`; todos aceptan `period_from`/`period_to` **o** `date_from`/`date_to`, y
excluyen las transferencias del gasto y del ingreso (RN-21).

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/reports/spending-by-category` | **Gasto por temática** (F-18): importe, porcentaje del total, comparación con el presupuesto y con el periodo anterior. Agrupa al nivel `depth` y puede desglosar el subárbol | S | `Q: period, period_from, period_to, depth=1, category_id, account_id*, tag_id*, include_children, min_amount, format` | `SpendingByCategoryOut` | 200, 422 |
| GET | `/reports/monthly-comparison` | **Mes a mes** (F-19): serie del gasto total y por temática entre periodos, con variación | S | `Q: period_from, period_to, category_id*, kind, format` | `MonthlyComparisonOut` | 200, 422 |
| GET | `/reports/cash-flow` | **Cash flow** (F-36): entradas, salidas y neto por periodo, con desglose por temática de nivel 1 | S | `Q: period_from, period_to, granularity=month\|week, account_id*, format` | `CashFlowOut` | 200, 422 |
| GET | `/reports/top-payees` | **Top comercios** (F-37): ranking por gasto con número de operaciones y ticket medio | S | `Q: period_from, period_to, category_id, limit=20, format` | `TopPayeesOut` | 200, 422 |
| GET | `/reports/net-worth` | **Patrimonio neto** (F-11): serie mensual de activos, pasivos y neto, con detalle por cuenta | S | `Q: period_from, period_to, include_accounts, format` | `NetWorthOut` | 200, 422 |
| GET | `/reports/budget-vs-actual` | Presupuestado frente a real por temática y periodo, con el sobrepaso destacado | S | `Q: period_from, period_to, only_overspent, format` | `BudgetVsActualOut` | 200, 422 |
| GET | `/reports/product-price` | **Evolución del precio de un producto** (F-15): serie por fecha con una línea por comercio, media móvil y variación acumulada | S | `Q: product_id (obligatorio), payee_id*, date_from, date_to, format` | `ProductPriceReportOut` | 200, 404, 422 |
| GET | `/reports/price-increases` | **Subidas de precio detectadas** (F-16) en el periodo, ordenadas por impacto en euros (variación × cantidad habitual) | S | `Q: period_from, period_to, min_change_pct=3, payee_id, category_id, format` | `PriceIncreasesOut` | 200, 422 |
| GET | `/reports/basket` | **Cesta de la compra** (F-60): coste actual de la misma cesta en cada comercio visto, con cobertura (cuántos de los productos tiene cada uno) y el total del más barato | S | `Q: basket_id \| product_id*, months=3, format` | `BasketReportOut` | 200, 404, 422 |
| GET | `/reports/subscriptions` | Suscripciones activas, coste mensual y anual, y subidas del último año (F-29, F-30) | S | `Q: is_active, format` | `SubscriptionsReportOut` | 200 |
| GET | `/reports/projected-balance` | Saldo proyectado a fin de mes por cuenta (F-47): saldo actual + recurrentes pendientes − presupuesto restante | S | `Q: period, account_id*, format` | `ProjectedBalanceOut` | 200, 422 |
| GET | `/reports/anomalies` | Gasto inusual (F-48): transacciones que se desvían de la media histórica de su temática/comercio por encima de `z` desviaciones | S | `Q: period_from, period_to, z=2.5, min_amount, format` | `AnomaliesOut` | 200, 422 |
| GET | `/reports/income-vs-expense` | Resumen de ingresos, gastos, ahorro y tasa de ahorro por periodo. Es el encabezado del panel | S | `Q: period_from, period_to, format` | `IncomeVsExpenseOut` | 200, 422 |

### 3.20 `settings` — ajustes y vistas guardadas

| Método | Ruta | Descripción | Auth | Request | Response | Códigos |
|---|---|---|---|---|---|---|
| GET | `/settings` | Ajustes del usuario: moneda, idioma, zona horaria, primer día de la semana, rollover por defecto, umbrales de alerta, tema | S | — | `SettingsOut` | 200 |
| PATCH | `/settings` | Cambia ajustes. Cambiar un umbral recalcula las alertas abiertas | S | `B: SettingsUpdateIn` | `SettingsOut` | 200, 422 |
| GET | `/settings/notifications` | Preferencias de aviso por tipo de alerta y periodicidad del digest (F-45) | S | — | `NotificationSettingsOut` | 200 |
| PUT | `/settings/notifications` | Sustituye las preferencias de aviso | S | `B: NotificationSettingsIn` | `NotificationSettingsOut` | 200, 422 |
| GET | `/settings/views` | Vistas guardadas de filtros de transacciones (design system §5.18) | S | — | `list[SavedViewOut]` | 200 |
| POST | `/settings/views` | Guarda el conjunto de filtros actual con un nombre | S | `B: SavedViewIn` | `SavedViewOut` | 201, 409 `nombre_duplicado` |
| PATCH | `/settings/views/{id}` | Renombra o actualiza los filtros de una vista | S | `B: SavedViewUpdateIn` | `SavedViewOut` | 200, 404, 409 |
| DELETE | `/settings/views/{id}` | Borra la vista | S | — | — | 204, 404 |
| GET | `/settings/storage` | Espacio ocupado por facturas y adjuntos, y cuota | S | — | `StorageOut` | 200 |

---

## 4. Esquemas Pydantic v2

Los nombres de campo van **en inglés** y en `snake_case`, igual que las rutas. Los mensajes de
error van en español porque los ve el usuario. Los sufijos son `…In` (petición), `…Out`
(respuesta), `…UpdateIn` (parcheo con todo opcional).

Los bloques siguientes son el contrato, no el fichero literal: solo el primero lleva los
`import` completos y el resto los da por hechos (`re`, `Literal`, `Any`, `Decimal`, `UUID`,
`date`, `datetime`, los tipos de `schemas/base.py` y las referencias cruzadas entre módulos,
resueltas con `model_rebuild()` al final de cada uno).

### 4.1 Tipos base, importes y sobre de paginación

```python
# app/schemas/base.py
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Generic, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
)


def _reject_float(value: Any) -> Any:
    """Un importe nunca llega como número JSON: se perdería precisión (§1.7)."""
    if isinstance(value, float):
        raise ValueError('Envía el importe como cadena de texto: "12.34".')
    if isinstance(value, str) and ("," in value or "€" in value or "e" in value.lower()):
        raise ValueError('Usa el punto como separador decimal y sin símbolo: "1234.56".')
    return value


# Dinero: 2 decimales, coincide con Numeric(14, 2) de app/db/base.py.
# Sale a JSON SIEMPRE como cadena con dos decimales exactos: "45.00".
Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=14, decimal_places=2),
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str, when_used="json"),
]

# Precio unitario y cantidad: hasta 4 decimales, porque el kWh de la factura de la
# luz llega con cuatro o seis y redondearlo falsearía el histórico de precios.
Quantity = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=16, decimal_places=4),
    PlainSerializer(lambda v: format(v.normalize(), "f"), return_type=str, when_used="json"),
]
UnitPrice = Quantity

# Periodo de presupuesto: SIEMPRE AAAA-MM (RN-30).
Period = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Schema(BaseModel):
    """Base de las peticiones: rechaza campos desconocidos y recorta espacios."""

    model_config = ConfigDict(
        extra="forbid",  # un campo mal escrito es un error del cliente, no algo a ignorar
        str_strip_whitespace=True,
        validate_default=True,
        populate_by_name=True,
    )


class Out(BaseModel):
    """Base de las respuestas: se construyen desde modelos de SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")


class Timestamped(Out):
    id: UUID
    created_at: datetime
    updated_at: datetime


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Sobre único de todos los listados (§1.4)."""

    items: list[T]
    page: int = Field(ge=1, examples=[1])
    size: int = Field(ge=1, le=200, examples=[50])
    total: int = Field(ge=0, examples=[1284])
    pages: int = Field(ge=0, examples=[26])
    next_cursor: str | None = Field(
        default=None, description="Solo en modo cursor; en modo página va a null."
    )


class BulkResultOut(Out):
    affected: int
    skipped: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)


# --- Errores: se documentan para que aparezcan en OpenAPI, no se construyen a mano.
class ErrorDetail(Out):
    campo: str
    mensaje: str


class ErrorBody(Out):
    codigo: str
    mensaje: str
    detalles: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(Out):
    error: ErrorBody
```

### 4.2 Autenticación y usuario

```python
# app/schemas/auth.py
from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.base import Name, Out, Schema, Timestamped

PASSWORD_MIN = 10


class RegisterIn(Schema):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)
    name: Name

    @field_validator("password")
    @classmethod
    def _fuerte(cls, v: str) -> str:
        """RN-05: longitud y variedad mínimas, sin exigir jeroglíficos."""
        if v.isdigit() or v.isalpha():
            raise ValueError("Combina letras y números.")
        return v

    @field_validator("email")
    @classmethod
    def _minusculas(cls, v: str) -> str:
        return v.lower()


class LoginIn(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(Schema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN, max_length=128)

    @model_validator(mode="after")
    def _distinta(self) -> "ChangePasswordIn":
        if self.current_password == self.new_password:
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")
        return self


class UserOut(Timestamped):
    email: EmailStr
    name: str
    locale: str
    timezone: str
    currency: str
    theme: str
    onboarding_completed: bool


class MeOut(UserOut):
    """«Yo» con lo que la SPA necesita en el arranque, en una sola llamada."""

    accounts_count: int
    categories_count: int
    unread_alerts: int
    current_period: str
    session_expires_at: datetime


class UserUpdateIn(Schema):
    name: Name | None = None
    email: EmailStr | None = None
    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    theme: str | None = Field(default=None, pattern=r"^(dark|light|system)$")


class SessionOut(Out):
    id: UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_hint: str | None = Field(description="IP truncada: 192.168.1.x. Nunca la IP completa.")
    is_current: bool


class MetaOut(Out):
    """Público: lo que se puede saber sin sesión."""

    app_name: str
    allow_registration: bool
    first_run: bool
    default_currency: str
    default_locale: str
    max_upload_mb: int
    max_pdf_pages: int
    ocr_enabled: bool
```

### 4.3 Cuentas y patrimonio

```python
# app/schemas/accounts.py
class AccountType(StrEnum):
    CHECKING = "checking"
    SAVINGS = "savings"
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    DEBT = "debt"


# Los pasivos restan en el patrimonio neto (RN-25).
LIABILITY_TYPES = {AccountType.CREDIT_CARD, AccountType.DEBT}


class AccountIn(Schema):
    name: Name
    type: AccountType
    currency: Currency = "EUR"
    initial_balance: Money = Decimal("0.00")
    opened_on: date | None = None
    color: Color | None = None
    icon: str | None = Field(default=None, max_length=40)
    is_excluded_from_net_worth: bool = False
    # Solo para type=debt / credit_card
    credit_limit: Money | None = None
    interest_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | None = None
    monthly_payment: Money | None = None
    ends_on: date | None = None

    @model_validator(mode="after")
    def _coherencia_deuda(self) -> "AccountIn":
        if self.type is not AccountType.DEBT and self.monthly_payment is not None:
            raise ValueError("La cuota mensual solo aplica a cuentas de deuda.")
        return self


class AccountOut(Timestamped):
    name: str
    type: AccountType
    currency: str
    initial_balance: Money
    current_balance: Money
    available_balance: Money | None  # tarjetas: límite − saldo dispuesto
    is_liability: bool
    is_archived: bool
    is_excluded_from_net_worth: bool
    color: str | None
    icon: str | None
    last_transaction_on: date | None
    transactions_count: int
    reconciled_through: date | None


class AccountBalanceOut(Out):
    account_id: UUID
    as_of: date
    balance: Money
    reconciled_balance: Money
    unreconciled_amount: Money
    pending_recurring: Money


class AccountsSummaryOut(Out):
    as_of: date
    currency: str
    assets: Money
    liabilities: Money
    net_worth: Money
    by_type: list["AccountTypeTotalOut"]


class AccountTypeTotalOut(Out):
    type: AccountType
    total: Money
    accounts: int


class ReconcileIn(Schema):
    statement_balance: Money
    statement_date: date
    create_adjustment: bool = True
    adjustment_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class ReconcileOut(Out):
    account_id: UUID
    statement_balance: Money
    computed_balance: Money
    difference: Money
    adjustment_transaction_id: UUID | None
    reconciled_through: date
```

### 4.4 Temáticas: árbol, movimiento y fusión

```python
# app/schemas/categories.py
MAX_DEPTH = 6  # RN-11


class CategoryKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class CategoryIn(Schema):
    name: Name
    parent_id: UUID | None = None
    kind: CategoryKind = CategoryKind.EXPENSE
    color: Color | None = None
    icon: str | None = Field(default=None, max_length=40)
    rollover_enabled: bool = False
    is_locked: bool = Field(
        default=False, description="No reasignable arrastrando en la barra (hipoteca, seguros)."
    )
    monthly_target: Money | None = Field(default=None, ge=0)


class CategoryUpdateIn(Schema):
    """Renombrar NO rompe el histórico (F-05): el identificador no cambia."""

    name: Name | None = None
    color: Color | None = None
    icon: str | None = Field(default=None, max_length=40)
    rollover_enabled: bool | None = None
    is_locked: bool | None = None
    monthly_target: Money | None = Field(default=None, ge=0)
    # El padre NO se cambia aquí: para eso está POST /categories/{id}/move.


class CategoryOut(Timestamped):
    name: str
    parent_id: UUID | None
    kind: CategoryKind
    path: str = Field(description="Ruta materializada de UUID: 'a1b2/…/f9e8' (§7.3).")
    depth: int
    position: int
    color: str | None
    icon: str | None
    rollover_enabled: bool
    is_locked: bool
    is_archived: bool
    monthly_target: Money | None
    children_count: int
    descendants_count: int
    ancestors: list["CategoryRefOut"] = Field(default_factory=list)
    # Solo con include=stats o ?period=
    transactions_count: int | None = None
    spent: Money | None = None
    allocated: Money | None = None


class CategoryRefOut(Out):
    id: UUID
    name: str
    color: str | None


class CategoryNode(CategoryOut):
    children: list["CategoryNode"] = Field(default_factory=list)


class CategoryMoveIn(Schema):
    parent_id: UUID | None = Field(description="null la convierte en raíz.")
    position: int = Field(default=0, ge=0, description="Índice entre los hermanos.")


class CategoryReorderIn(Schema):
    items: list["CategoryPositionIn"] = Field(min_length=1, max_length=500)


class CategoryPositionIn(Schema):
    id: UUID
    parent_id: UUID | None = None
    position: int = Field(ge=0)


class CategoryMergeIn(Schema):
    """RN-17 a RN-20: ni consigo misma, ni con un descendiente, ni entre kinds distintos."""

    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID
    move_children: bool = Field(
        default=True, description="Los hijos de las origen pasan a la destino."
    )
    keep_source_names_as_alias: bool = Field(
        default=True, description="Guarda los nombres antiguos para buscar por ellos."
    )

    @model_validator(mode="after")
    def _no_consigo_misma(self) -> "CategoryMergeIn":
        if self.target_id in self.source_ids:
            raise ValueError("No se puede fusionar una temática consigo misma.")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("Hay temáticas repetidas en la lista de origen.")
        return self


class CategoryMergePreviewOut(Out):
    """Lo que se va a mover, antes de moverlo. Se muestra en el diálogo de confirmación."""

    target: CategoryRefOut
    sources: list[CategoryRefOut]
    transactions: int
    splits: int
    invoice_lines: int
    rules: int
    recurring: int
    products: int
    goals: int
    budget_periods: int
    allocations_merged: Money = Field(description="Suma de asignaciones que quedará en destino.")
    children_moved: int
    conflicts: list[str] = Field(
        default_factory=list, description="Ej.: 'El periodo 2026-03 está cerrado'."
    )


class CategoryMergeResultOut(CategoryMergePreviewOut):
    merge_id: UUID
    performed_at: datetime
    undo_available_until: datetime


class CategoryUsageOut(Out):
    category_id: UUID
    transactions: int
    splits: int
    invoice_lines: int
    rules: int
    recurring: int
    goals: int
    allocations: int
    first_used_on: date | None
    last_used_on: date | None
    can_hard_delete: bool = Field(description="False obliga a reasignar o archivar (RN-14).")
```

### 4.5 Transacciones, splits y transferencias

```python
# app/schemas/transactions.py
class TransactionKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"  # no cuenta como gasto ni como ingreso (RN-21)


class SplitIn(Schema):
    category_id: UUID
    amount: Money = Field(gt=0, description="Siempre positivo; el signo lo da el kind.")
    note: str | None = Field(default=None, max_length=280)


class SplitOut(Out):
    id: UUID
    category_id: UUID
    category: CategoryRefOut | None = None
    amount: Money
    note: str | None
    invoice_line_id: UUID | None = Field(
        default=None, description="Split generado al confirmar una factura."
    )


class TransactionIn(Schema):
    kind: TransactionKind = TransactionKind.EXPENSE
    account_id: UUID
    date: date
    amount: Money = Field(gt=0)
    currency: Currency = "EUR"
    category_id: UUID | None = Field(
        default=None, description="Nulo si hay splits o si se dejan actuar las reglas."
    )
    payee_id: UUID | None = None
    payee_name: str | None = Field(
        default=None, max_length=120, description="Crea el comercio si no existe."
    )
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    tag_ids: list[UUID] = Field(default_factory=list, max_length=20)
    splits: list[SplitIn] = Field(default_factory=list, max_length=100)
    apply_rules: bool = Field(default=True, description="Auto-categorización (F-27).")
    status: Literal["pending", "cleared", "reconciled"] = "cleared"

    @model_validator(mode="after")
    def _validar(self) -> "TransactionIn":
        if self.kind is TransactionKind.TRANSFER:
            raise ValueError("Las transferencias se crean con POST /transfers.")
        if self.amount == 0:  # RN-26
            raise ValueError("El importe no puede ser cero.")
        if self.splits:
            if self.category_id is not None:
                raise ValueError("Con splits no se envía category_id: la temática va en cada split.")
            total = sum(s.amount for s in self.splits)
            if total != self.amount:  # RN-15
                raise ValueError(
                    f"Los splits suman {total} y la transacción es de {self.amount}."
                )
            if len({s.category_id for s in self.splits}) != len(self.splits):
                raise ValueError("Hay dos splits con la misma temática: únelos en uno.")
        return self


class TransactionUpdateIn(Schema):
    date: date | None = None
    amount: Money | None = Field(default=None, gt=0)
    account_id: UUID | None = None
    category_id: UUID | None = None
    payee_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    tag_ids: list[UUID] | None = Field(default=None, max_length=20)
    splits: list[SplitIn] | None = Field(default=None, max_length=100)
    status: Literal["pending", "cleared", "reconciled"] | None = None
    # RN-16: cambiar amount con splits existentes obliga a reenviar splits que cuadren.


class TransactionOut(Timestamped):
    kind: TransactionKind
    account_id: UUID
    account: "AccountRefOut | None" = None
    date: date
    amount: Money
    signed_amount: Money = Field(description="Negativo si es gasto. Comodidad para gráficos.")
    currency: str
    category_id: UUID | None
    category: CategoryRefOut | None = None
    payee_id: UUID | None
    payee: "PayeeRefOut | None" = None
    description: str | None
    note: str | None
    is_split: bool
    splits: list[SplitOut] = Field(default_factory=list)
    tags: list["TagRefOut"] = Field(default_factory=list)
    attachments_count: int
    attachments: list["AttachmentOut"] = Field(default_factory=list)
    invoice_id: UUID | None
    recurring_id: UUID | None
    transfer_group_id: UUID | None
    transfer_counterpart_id: UUID | None
    status: Literal["pending", "cleared", "reconciled"]
    is_reconciled: bool = Field(description="Derivado: status == 'reconciled'.")
    is_anomaly: bool = Field(description="Gasto inusual detectado (F-48).")
    source: str = Field(description="manual | import | invoice | recurring | reconciliation")


class SplitsReplaceIn(Schema):
    splits: list[SplitIn] = Field(min_length=1, max_length=100)


class TransferIn(Schema):
    from_account_id: UUID
    to_account_id: UUID
    date: date
    amount: Money = Field(gt=0)
    fee: Money | None = Field(default=None, ge=0, description="Comisión, si la hubo.")
    fee_category_id: UUID | None = None
    description: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    goal_id: UUID | None = Field(default=None, description="Aportación a un fondo objetivo.")

    @model_validator(mode="after")
    def _cuentas_distintas(self) -> "TransferIn":
        if self.from_account_id == self.to_account_id:  # RN-22
            raise ValueError("La cuenta de origen y la de destino no pueden ser la misma.")
        if self.fee and not self.fee_category_id:
            raise ValueError("Indica la temática de la comisión.")
        return self


class TransferOut(Out):
    transfer_group_id: UUID
    date: date
    amount: Money
    fee: Money | None
    from_account: "AccountRefOut"
    to_account: "AccountRefOut"
    description: str | None
    note: str | None
    goal_id: UUID | None
    out_transaction_id: UUID
    in_transaction_id: UUID
    created_at: datetime


class DuplicateGroupOut(Out):
    """Candidatos a duplicado (F-34)."""

    key: str
    score: float = Field(ge=0, le=1)
    reason: str = Field(description="mismo_importe_y_fecha | mismo_comercio | importacion")
    transactions: list[TransactionOut]


class AttachmentOut(Timestamped):
    transaction_id: UUID | None
    invoice_id: UUID | None
    filename: str = Field(description="Nombre original saneado, solo informativo (§8.3).")
    content_type: str
    size_bytes: int
    pages: int | None
    checksum: str = Field(description="SHA-256 en hexadecimal.")
    download_url: str
```

### 4.6 Presupuesto, rollover y reasignación

```python
# app/schemas/budgets.py
class AllocationIn(Schema):
    category_id: UUID
    amount: Money = Field(ge=0, description="RN-28: nunca negativo.")
    rollover_enabled: bool | None = None
    note: str | None = Field(default=None, max_length=280)


class AllocationsReplaceIn(Schema):
    allocations: list[AllocationIn] = Field(max_length=500)
    remove_missing: bool = Field(
        default=True, description="Las temáticas ausentes se dejan a 0."
    )

    @model_validator(mode="after")
    def _sin_repetidos(self) -> "AllocationsReplaceIn":
        vistos = {a.category_id for a in self.allocations}
        if len(vistos) != len(self.allocations):
            raise ValueError("Hay dos asignaciones para la misma temática.")
        return self


class AllocationOut(Out):
    category_id: UUID
    category: CategoryRefOut
    allocated: Money
    rollover_in: Money = Field(description="Sobrante que entra del periodo anterior (F-26).")
    available: Money = Field(description="allocated + rollover_in − spent.")
    spent: Money
    spent_pct: float = Field(ge=0, description="1.0 = presupuesto justo consumido.")
    overspent: Money = Field(ge=0, description="max(0, spent − allocated − rollover_in).")
    rollover_enabled: bool
    is_locked: bool
    children: list["AllocationOut"] = Field(default_factory=list)


class BudgetSettingsIn(Schema):
    planned_income: Money | None = Field(default=None, ge=0)
    rollover_default: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class BudgetOut(Out):
    """Es exactamente lo que consume el componente BudgetBar del design system."""

    period: Period
    currency: str
    is_closed: bool
    closed_at: datetime | None
    income_actual: Money = Field(description="Suma de ingresos reales del periodo (F-01).")
    planned_income: Money | None
    income: Money = Field(description="El 100 % del carril: planned_income o income_actual.")
    allocated_total: Money
    spent_total: Money
    unassigned: Money = Field(description="income − allocated_total. Puede ser negativo.")
    overallocated: Money = Field(ge=0, description="max(0, allocated_total − income).")
    rollover_in_total: Money
    day_of_month: int
    days_in_month: int
    allocations: list[AllocationOut]


class BudgetSummaryOut(Out):
    period: Period
    income: Money
    allocated_total: Money
    spent_total: Money
    is_closed: bool


class BudgetReassignIn(Schema):
    """El arrastre en la barra: mover presupuesto de una temática a otra (RN-29)."""

    from_category_id: UUID
    to_category_id: UUID
    amount: Money = Field(gt=0)

    @model_validator(mode="after")
    def _distintas(self) -> "BudgetReassignIn":
        if self.from_category_id == self.to_category_id:
            raise ValueError("Elige dos temáticas distintas.")
        return self


class BudgetCopyIn(Schema):
    source_period: Period
    strategy: Literal["absolute", "proportional"] = "absolute"
    overwrite: bool = False
    only_missing: bool = True


class BudgetDistributeIn(Schema):
    strategy: Literal["equal", "last_period_share", "average_3m"] = "last_period_share"
    category_ids: list[UUID] = Field(default_factory=list, max_length=500)
    amount: Money | None = Field(default=None, gt=0, description="Por defecto, lo no asignado.")


class RolloverOut(Out):
    category_id: UUID
    category: CategoryRefOut
    previous_period: Period
    previous_allocated: Money
    previous_spent: Money
    carried_in: Money
    carried_negative: bool
```

### 4.7 Recurrentes y suscripciones

```python
# app/schemas/recurring.py
class Frequency(StrEnum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    BIMONTHLY = "bimonthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    EVERY_N_DAYS = "every_n_days"
    LAST_WEEKDAY_OF_MONTH = "last_weekday_of_month"


class RecurringIn(Schema):
    name: Name
    kind: Literal["expense", "income"] = "expense"
    account_id: UUID
    category_id: UUID | None = None
    payee_id: UUID | None = None
    amount: Money = Field(gt=0)
    currency: Currency = "EUR"
    frequency: Frequency
    interval: int = Field(default=1, ge=1, le=365)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    weekday: int | None = Field(default=None, ge=0, le=6)
    starts_on: date
    ends_on: date | None = None
    is_subscription: bool = False
    auto_post: bool = Field(default=False, description="Se materializa sin intervención.")
    remind_days_before: int = Field(default=3, ge=0, le=60)
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _coherencia(self) -> "RecurringIn":
        if self.frequency is Frequency.EVERY_N_DAYS and self.interval < 1:
            raise ValueError("Indica cada cuántos días se repite.")
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("La fecha de fin es anterior a la de inicio.")
        return self


class RecurringOut(Timestamped):
    name: str
    kind: str
    account_id: UUID
    category: CategoryRefOut | None
    payee: "PayeeRefOut | None"
    amount: Money
    currency: str
    frequency: Frequency
    interval: int
    starts_on: date
    ends_on: date | None
    next_occurrence_on: date | None
    last_posted_on: date | None
    is_active: bool
    is_paused: bool
    is_subscription: bool
    auto_post: bool
    occurrences_count: int
    average_amount: Money | None
    last_amount: Money | None
    price_change_pct: float | None = Field(description="Subida del último cargo (F-30).")
    annual_cost: Money | None


class RecurringPostIn(Schema):
    occurrence_date: date
    amount: Money | None = Field(default=None, gt=0, description="Por si vino distinto.")
    note: str | None = Field(default=None, max_length=2000)


class UpcomingOut(Out):
    recurring_id: UUID
    name: str
    account_id: UUID
    category: CategoryRefOut | None
    due_on: date
    days_until: int
    expected_amount: Money
    is_subscription: bool
    is_overdue: bool


class DetectedRecurringOut(Out):
    """Suscripción detectada en el histórico y aún sin confirmar (F-29)."""

    group_id: str
    payee_name: str
    suggested_name: str
    occurrences: int
    first_seen_on: date
    last_seen_on: date
    estimated_frequency: Frequency
    average_amount: Money
    last_amount: Money
    amount_stability: float = Field(ge=0, le=1)
    price_increase_pct: float | None
    transaction_ids: list[UUID]
    suggested_category: CategoryRefOut | None
```

### 4.8 Comercios, etiquetas y reglas

```python
# app/schemas/payees.py
class PayeeIn(Schema):
    name: Name
    default_category_id: UUID | None = None
    aliases: list[str] = Field(default_factory=list, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=20, description="NIF/CIF del emisor.")
    note: str | None = Field(default=None, max_length=1000)


class PayeeRefOut(Out):
    id: UUID
    name: str


class PayeeOut(Timestamped):
    name: str
    normalized_name: str
    default_category: CategoryRefOut | None
    aliases: list[str]
    tax_id: str | None
    website: str | None
    is_archived: bool
    # include=stats
    transactions_count: int | None = None
    total_spent: Money | None = None
    average_ticket: Money | None = None
    first_seen_on: date | None = None
    last_seen_on: date | None = None
    invoices_count: int | None = None


class PayeeSuggestionOut(Out):
    payee: PayeeRefOut
    score: float = Field(ge=0, le=100, description="Parecido de RapidFuzz.")
    matched_alias: str | None


# app/schemas/tags.py
class TagIn(Schema):
    name: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    color: Color | None = None


class TagRefOut(Out):
    id: UUID
    name: str
    color: str | None


class TagOut(TagRefOut):
    created_at: datetime
    transactions_count: int | None = None
    total_amount: Money | None = None


# app/schemas/rules.py
class RuleField(StrEnum):
    PAYEE = "payee"
    DESCRIPTION = "description"
    NOTE = "note"
    AMOUNT = "amount"
    ACCOUNT = "account"
    DATE = "date"


class RuleOperator(StrEnum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"
    GT = "gt"
    LT = "lt"
    BETWEEN = "between"


class RuleConditionIn(Schema):
    field: RuleField
    operator: RuleOperator
    value: str = Field(min_length=1, max_length=200)
    value_to: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _regex_segura(self) -> "RuleConditionIn":
        """RN-58: patrón compilable y acotado, para no abrir la puerta a un ReDoS."""
        if self.operator is RuleOperator.REGEX:
            if len(self.value) > 200:
                raise ValueError("La expresión regular es demasiado larga.")
            try:
                re.compile(self.value)
            except re.error as exc:
                raise ValueError(f"La expresión regular no es válida: {exc}") from exc
        if self.operator is RuleOperator.BETWEEN and self.value_to is None:
            raise ValueError("Indica el segundo valor del rango.")
        return self


class RuleActionIn(Schema):
    set_category_id: UUID | None = None
    set_payee_id: UUID | None = None
    add_tag_ids: list[UUID] = Field(default_factory=list, max_length=10)
    set_note: str | None = Field(default=None, max_length=500)
    mark_as_transfer: bool = False
    stop_processing: bool = Field(default=True, description="No evaluar más reglas si casa.")

    @model_validator(mode="after")
    def _algo_que_hacer(self) -> "RuleActionIn":
        if not any(
            [self.set_category_id, self.set_payee_id, self.add_tag_ids, self.set_note,
             self.mark_as_transfer]
        ):
            raise ValueError("La regla no hace nada: indica al menos una acción.")
        return self


class RuleIn(Schema):
    name: Name
    match: Literal["all", "any"] = "all"
    conditions: list[RuleConditionIn] = Field(min_length=1, max_length=10)
    actions: RuleActionIn
    priority: int = Field(default=100, ge=0, le=10_000)
    is_active: bool = True
    apply_to_imports: bool = True
    apply_to_invoices: bool = True


class RuleOut(Timestamped):
    name: str
    match: str
    conditions: list[RuleConditionIn]
    actions: RuleActionIn
    priority: int
    is_active: bool
    applied_count: int
    last_applied_at: datetime | None


class RuleTestIn(Schema):
    rule: RuleIn
    sample_text: str | None = Field(default=None, max_length=500)
    against_history: bool = True
    limit: int = Field(default=20, ge=1, le=200)


class RuleTestOut(Out):
    matches: int
    sample_matched: bool | None
    transactions: list[TransactionOut]


class RuleApplyIn(Schema):
    rule_ids: list[UUID] = Field(default_factory=list, description="Vacío = todas las activas.")
    scope: Literal["uncategorized", "all"] = "uncategorized"
    date_from: date | None = None
    date_to: date | None = None
    account_id: UUID | None = None
    dry_run: bool = True


class RuleApplyResultOut(Out):
    dry_run: bool
    evaluated: int
    matched: int
    updated: int
    by_rule: list[dict[str, Any]]
```

### 4.9 Facturas: subida, revisión, corrección y confirmación

Los nombres de campo son la traducción directa de `FacturaExtraida` y `LineaExtraida`
(`app/services/extraccion_pdf.py`), para que la capa de servicio no tenga que inventar nada:
`emisor→issuer`, `nif_emisor→issuer_tax_id`, `numero→number`, `fecha→date`,
`base_imponible→taxable_base`, `impuestos→tax_amount`, `total→total`, `moneda→currency`,
`metodo→extraction_method`, `paginas→pages`, `confianza→confidence`, `avisos→warnings`;
en cada línea, `descripcion→description`, `cantidad→quantity`, `unidad→unit`,
`precio_unitario→unit_price`, `total→total`, `confianza→confidence`,
`normalizada→normalized`.

```python
# app/schemas/invoices.py
class InvoiceStatus(StrEnum):
    PROCESSING = "processing"       # extracción en curso
    PENDING_REVIEW = "pending_review"  # extraída, ESPERANDO REVISIÓN HUMANA
    FAILED = "failed"               # PDF ilegible: alta manual sobre la misma factura
    CONFIRMED = "confirmed"         # revisada y volcada a transacción + precios
    DISCARDED = "discarded"


ExtractionMethod = Literal["tabla", "texto", "ocr", "ninguno"]


class NormalizedOut(Out):
    """Espejo de DescripcionNormalizada."""

    canonical: str
    brand_guess: str | None
    size_value: Quantity | None
    size_unit: str | None
    code: str | None


class InvoiceLineOut(Out):
    id: UUID
    line_number: int
    description: str
    quantity: Quantity | None
    unit: str | None
    unit_price: UnitPrice | None
    total: Money | None
    confidence: Confidence
    normalized: NormalizedOut | None
    # Revisión
    is_edited: bool = Field(description="Corregida a mano: un reprocesado no la toca.")
    is_excluded: bool = Field(description="Descartada: no genera split ni precio.")
    is_product: bool = Field(description="False para conceptos (potencia, impuestos, portes).")
    warnings: list[str]
    # Vínculos y sugerencias
    category_id: UUID | None
    category: CategoryRefOut | None
    product_id: UUID | None
    product: "ProductRefOut | None"
    suggested_product: "ProductSuggestionOut | None"
    suggested_category: CategoryRefOut | None
    last_unit_price: UnitPrice | None
    last_seen_on: date | None
    change_pct: float | None = Field(description="Variación frente al último precio visto.")


class InvoiceOut(Timestamped):
    status: InvoiceStatus
    # Cabecera extraída y corregible
    issuer: str | None
    issuer_tax_id: str | None
    number: str | None
    date: date | None
    taxable_base: Money | None
    tax_amount: Money | None
    total: Money | None
    currency: str
    # Extracción
    extraction_method: ExtractionMethod
    pages: int
    confidence: Confidence
    warnings: list[str]
    lines_count: int
    lines_sum: Money = Field(description="Suma de los totales de línea no excluidas.")
    total_mismatch: Money | None = Field(description="lines_sum − total, si descuadra.")
    low_confidence_lines: int
    # Fichero
    filename: str
    size_bytes: int
    checksum: str
    file_url: str
    # Vínculos
    payee_id: UUID | None
    payee: PayeeRefOut | None
    account_id: UUID | None
    transaction_id: UUID | None
    template_id: UUID | None
    duplicate_of_id: UUID | None
    uploaded_at: datetime
    processed_at: datetime | None
    reviewed_at: datetime | None
    confirmed_at: datetime | None
    error: str | None
    lines: list[InvoiceLineOut] = Field(default_factory=list)


class InvoiceStatusOut(Out):
    """Respuesta mínima del sondeo: una fila, con ETag."""

    id: UUID
    status: InvoiceStatus
    progress: int = Field(ge=0, le=100)
    extraction_method: ExtractionMethod
    pages: int
    confidence: Confidence
    lines_count: int
    low_confidence_lines: int
    warnings: list[str]
    error: str | None
    retry_after_seconds: int | None


class InvoiceUpdateIn(Schema):
    """Corrección de la cabecera en la pantalla de revisión."""

    issuer: str | None = Field(default=None, max_length=200)
    issuer_tax_id: str | None = Field(default=None, max_length=20)
    number: str | None = Field(default=None, max_length=60)
    date: date | None = None
    taxable_base: Money | None = None
    tax_amount: Money | None = None
    total: Money | None = None
    currency: Currency | None = None
    payee_id: UUID | None = None
    payee_name: str | None = Field(default=None, max_length=120)
    account_id: UUID | None = None
    default_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class InvoiceLineUpdateIn(Schema):
    description: str | None = Field(default=None, max_length=300)
    quantity: Quantity | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: UnitPrice | None = Field(default=None, ge=0)
    total: Money | None = None
    category_id: UUID | None = None
    is_excluded: bool | None = None
    is_product: bool | None = None
    # RN-41: el backend recalcula el hueco que falte y marca is_edited=True.


class InvoiceLineCreateIn(InvoiceLineUpdateIn):
    description: str = Field(min_length=1, max_length=300)
    position: int | None = Field(default=None, ge=0)


class InvoiceLinesReplaceIn(Schema):
    """Guardado de la revisión completa en una sola llamada. Idempotente."""

    lines: list["InvoiceLineReviewIn"] = Field(max_length=500)


class InvoiceLineReviewIn(Schema):
    id: UUID | None = Field(default=None, description="Nulo para una línea añadida a mano.")
    description: str = Field(min_length=1, max_length=300)
    quantity: Quantity | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: UnitPrice | None = Field(default=None, ge=0)
    total: Money
    category_id: UUID | None = None
    product_id: UUID | None = None
    is_excluded: bool = False
    is_product: bool = True


class InvoiceLinesOut(Out):
    invoice_id: UUID
    status: InvoiceStatus
    total: Money | None
    lines_sum: Money
    total_mismatch: Money | None
    tolerance: Money = Field(description="0.02 €, la misma que usa el extractor.")
    can_confirm: bool
    blocking_reasons: list[str] = Field(
        description="Ej.: 'Hay 3 líneas sin temática', 'Las líneas no suman el total'."
    )
    warnings: list[str]
    lines: list[InvoiceLineOut]


class LinkProductIn(Schema):
    """Vincular una línea con el catálogo de productos."""

    product_id: UUID | None = None
    new_product: "ProductIn | None" = None
    remember_alias: bool = Field(
        default=True, description="Aprende la descripción cruda para la próxima factura."
    )
    set_default_category: bool = Field(
        default=False, description="Guarda la temática de la línea como la del producto (F-17)."
    )

    @model_validator(mode="after")
    def _uno_de_los_dos(self) -> "LinkProductIn":
        if bool(self.product_id) == bool(self.new_product):
            raise ValueError("Indica un producto existente o los datos de uno nuevo, no ambos.")
        return self


class InvoiceConfirmIn(Schema):
    """Confirmación de la revisión. Solo se puede una vez (RN-46)."""

    account_id: UUID
    date: date | None = Field(default=None, description="Por defecto, la fecha de la factura.")
    payee_id: UUID | None = None
    default_category_id: UUID | None = Field(
        default=None, description="Para las líneas sin temática propia."
    )
    transaction_id: UUID | None = Field(
        default=None, description="Vincular a un gasto ya registrado en vez de crear uno nuevo."
    )
    create_splits: bool = Field(default=True, description="Un split por temática (F-17).")
    register_prices: bool = Field(default=True, description="Alimenta el histórico (F-15).")
    allow_total_mismatch: bool = Field(
        default=False, description="Confirmar aun sin cuadrar (RN-42)."
    )
    ignore_duplicate: bool = Field(
        default=False, description="Confirmar aun siendo duplicada (RN-45)."
    )
    tag_ids: list[UUID] = Field(default_factory=list, max_length=20)


class InvoiceConfirmResultOut(Out):
    invoice: InvoiceOut
    transaction_id: UUID
    splits_created: int
    prices_registered: int
    products_created: int
    products_linked: int
    price_alerts: list["PriceAlertOut"]


class InvoiceDuplicateOut(Out):
    invoice_id: UUID
    issuer: str | None
    number: str | None
    date: date | None
    total: Money | None
    status: InvoiceStatus
    match_reason: str = Field(description="checksum | issuer_number_date_total | total_date")
    confidence: Confidence


class InvoiceTemplateIn(Schema):
    """Plantilla de extracción por proveedor (F-40)."""

    name: Name
    payee_id: UUID | None = None
    issuer_pattern: str = Field(min_length=2, max_length=200)
    from_invoice_id: UUID | None = Field(
        default=None, description="Aprende los patrones de una factura ya corregida."
    )
    field_patterns: dict[str, str] = Field(default_factory=dict)
    table_columns: dict[str, int] = Field(default_factory=dict)
    default_category_id: UUID | None = None
    force_ocr: bool = False
    is_active: bool = True
```

### 4.10 Productos, precios y cesta

```python
# app/schemas/products.py
class ProductIn(Schema):
    name: Name
    brand: str | None = Field(default=None, max_length=80)
    size_value: Quantity | None = Field(default=None, gt=0)
    size_unit: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20, description="Unidad de venta: kg, l, ud.")
    barcode: str | None = Field(default=None, max_length=20)
    default_category_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class ProductRefOut(Out):
    id: UUID
    name: str
    brand: str | None
    size_text: str | None


class ProductOut(Timestamped):
    name: str
    brand: str | None
    canonical_name: str = Field(description="Clave de agrupación de normalizacion.py.")
    size_value: Quantity | None
    size_unit: str | None
    size_text: str | None
    unit: str | None
    barcode: str | None
    default_category: CategoryRefOut | None
    is_archived: bool
    aliases_count: int
    observations_count: int
    payees_count: int
    first_seen_on: date | None
    last_seen_on: date | None
    last_unit_price: UnitPrice | None
    min_unit_price: UnitPrice | None
    max_unit_price: UnitPrice | None
    average_unit_price: UnitPrice | None
    change_pct: float | None = Field(description="Última observación frente a la anterior.")
    change_pct_12m: float | None
    has_increase: bool


class ProductSuggestionOut(Out):
    product: ProductRefOut
    score: float = Field(ge=0, le=100, description="RapidFuzz; el umbral por defecto es 88.")
    matched_alias: str | None
    last_unit_price: UnitPrice | None
    last_payee: PayeeRefOut | None


class ProductMergeIn(Schema):
    source_ids: list[UUID] = Field(min_length=1, max_length=50)
    target_id: UUID
    keep_aliases: bool = True

    @model_validator(mode="after")
    def _no_consigo_mismo(self) -> "ProductMergeIn":
        if self.target_id in self.source_ids:
            raise ValueError("No se puede fusionar un producto consigo mismo.")
        return self


class ProductMergeResultOut(Out):
    merge_id: UUID
    target: ProductRefOut
    sources: list[ProductRefOut]
    prices_moved: int
    invoice_lines_moved: int
    aliases_moved: int
    performed_at: datetime
    undo_available_until: datetime


class ProductSplitIn(Schema):
    """Separar un producto mal fusionado. Se elige QUÉ se saca, de tres formas."""

    price_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    alias_ids: list[UUID] = Field(
        default_factory=list, description="Saca todo lo observado bajo estos alias."
    )
    payee_id: UUID | None = Field(
        default=None, description="Saca todo lo observado en este comercio."
    )
    target_product_id: UUID | None = Field(
        default=None, description="Destino existente; si no, se crea uno nuevo."
    )
    new_product: ProductIn | None = None

    @model_validator(mode="after")
    def _algo_que_sacar(self) -> "ProductSplitIn":
        if not (self.price_ids or self.alias_ids or self.payee_id):
            raise ValueError("Indica qué observaciones hay que separar.")
        if bool(self.target_product_id) == bool(self.new_product):
            raise ValueError("Indica un producto destino o los datos de uno nuevo, no ambos.")
        return self


class ProductSplitResultOut(Out):
    source: ProductRefOut
    target: ProductRefOut
    prices_moved: int
    invoice_lines_moved: int
    aliases_moved: int


class PriceIn(Schema):
    """Observación de precio registrada a mano (sin factura)."""

    product_id: UUID
    payee_id: UUID | None = None
    observed_at: date
    unit_price: UnitPrice = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)
    quantity: Quantity | None = Field(default=None, gt=0)
    total: Money | None = None
    currency: Currency = "EUR"
    note: str | None = Field(default=None, max_length=280)


class PriceOut(Out):
    id: UUID
    product_id: UUID
    product: ProductRefOut | None
    payee: PayeeRefOut | None
    observed_at: date
    unit_price: UnitPrice
    unit: str | None
    quantity: Quantity | None
    total: Money | None
    currency: str
    source: Literal["invoice", "manual", "import"]
    invoice_id: UUID | None
    invoice_line_id: UUID | None
    change_pct: float | None
    is_increase: bool
    created_at: datetime


class PriceStatsOut(Out):
    product_id: UUID
    observations: int
    period_from: date | None
    period_to: date | None
    min_unit_price: UnitPrice | None
    max_unit_price: UnitPrice | None
    average_unit_price: UnitPrice | None
    median_unit_price: UnitPrice | None
    last_unit_price: UnitPrice | None
    last_observed_at: date | None
    change_pct: float | None
    change_pct_12m: float | None
    cheapest_payee: PayeeRefOut | None


class ProductComparisonOut(Out):
    """Comparativa entre comercios del mismo producto (F-38)."""

    product: ProductRefOut
    unit: str | None
    cheapest: "PayeePriceOut | None"
    most_expensive: "PayeePriceOut | None"
    spread_pct: float | None
    by_payee: list["PayeePriceOut"]


class PayeePriceOut(Out):
    payee: PayeeRefOut | None
    last_unit_price: UnitPrice
    last_observed_at: date
    observations: int
    average_unit_price: UnitPrice
    diff_vs_cheapest: Money
    diff_vs_cheapest_pct: float


class PriceAlertOut(Out):
    product: ProductRefOut
    payee: PayeeRefOut | None
    previous_unit_price: UnitPrice
    new_unit_price: UnitPrice
    change_pct: float
    observed_at: date
    invoice_line_id: UUID | None


class BasketIn(Schema):
    name: Name
    items: list["BasketItemIn"] = Field(min_length=1, max_length=200)


class BasketItemIn(Schema):
    product_id: UUID
    quantity: Quantity = Field(default=Decimal("1"), gt=0)
```

### 4.11 Fondos objetivo, alertas e importaciones

```python
# app/schemas/goals.py
class GoalIn(Schema):
    name: Name
    target_amount: Money = Field(gt=0)
    target_date: date | None = None
    category_id: UUID | None = None
    account_id: UUID | None = Field(default=None, description="Dónde se guarda el dinero.")
    initial_amount: Money = Field(default=Decimal("0.00"), ge=0)
    monthly_contribution: Money | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class GoalOut(Timestamped):
    name: str
    target_amount: Money
    current_amount: Money
    remaining: Money
    progress_pct: float = Field(ge=0)
    target_date: date | None
    months_left: int | None
    required_monthly: Money | None
    monthly_contribution: Money | None
    is_on_track: bool
    is_completed: bool
    category: CategoryRefOut | None
    account_id: UUID | None


class GoalMovementIn(Schema):
    amount: Money = Field(gt=0)
    date: date
    account_id: UUID | None = Field(
        default=None, description="Si se indica, genera una transferencia real."
    )
    note: str | None = Field(default=None, max_length=280)


# app/schemas/alerts.py
class AlertType(StrEnum):
    BUDGET_OVERSPENT = "budget_overspent"        # F-20
    BUDGET_NEAR_LIMIT = "budget_near_limit"
    PRODUCT_PRICE_INCREASE = "product_price_increase"  # F-16
    RECURRING_PRICE_INCREASE = "recurring_price_increase"  # F-30
    UNUSUAL_SPENDING = "unusual_spending"        # F-48
    UPCOMING_CHARGE = "upcoming_charge"          # F-49
    DUPLICATE_SUSPECTED = "duplicate_suspected"  # F-34
    INVOICE_LOW_CONFIDENCE = "invoice_low_confidence"
    GOAL_AT_RISK = "goal_at_risk"
    ACCOUNT_UNRECONCILED = "account_unreconciled"


class AlertOut(Out):
    id: UUID
    type: AlertType
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str
    period: str | None
    amount: Money | None
    change_pct: float | None
    is_read: bool
    is_dismissed: bool
    created_at: datetime
    # Objeto que la originó: solo uno viene relleno.
    category_id: UUID | None
    transaction_id: UUID | None
    product_id: UUID | None
    recurring_id: UUID | None
    invoice_id: UUID | None
    goal_id: UUID | None
    account_id: UUID | None


# app/schemas/imports.py
class ImportFormat(StrEnum):
    CSV = "csv"
    OFX = "ofx"
    QIF = "qif"


class ImportStatus(StrEnum):
    ANALYZING = "analyzing"
    NEEDS_MAPPING = "needs_mapping"
    READY = "ready"
    COMMITTED = "committed"
    FAILED = "failed"
    DISCARDED = "discarded"


class ImportMappingIn(Schema):
    date_column: str
    amount_column: str | None = None
    debit_column: str | None = None
    credit_column: str | None = None
    description_column: str | None = None
    payee_column: str | None = None
    balance_column: str | None = None
    date_format: str = Field(default="%d/%m/%Y", max_length=32)
    decimal_separator: Literal[",", "."] = ","
    thousands_separator: Literal[".", ",", " ", ""] = "."
    invert_sign: bool = False
    skip_rows: int = Field(default=0, ge=0, le=50)
    encoding: str = Field(default="utf-8", max_length=20)
    delimiter: str = Field(default=";", min_length=1, max_length=1)

    @model_validator(mode="after")
    def _importe_definido(self) -> "ImportMappingIn":
        if not self.amount_column and not (self.debit_column or self.credit_column):
            raise ValueError("Indica la columna de importe, o las de cargo y abono.")
        return self


class ImportRowOut(Out):
    id: UUID
    row_number: int
    raw: dict[str, str]
    date: date | None
    amount: Money | None
    description: str | None
    payee_name: str | None
    suggested_payee: PayeeRefOut | None
    suggested_category: CategoryRefOut | None
    matched_rule_id: UUID | None
    is_duplicate: bool
    duplicate_of_id: UUID | None
    is_skipped: bool
    error: str | None


class ImportOut(Timestamped):
    status: ImportStatus
    format: ImportFormat
    account_id: UUID
    filename: str
    size_bytes: int
    checksum: str
    detected_columns: list[str]
    mapping: ImportMappingIn | None
    rows_total: int
    rows_valid: int
    rows_duplicated: int
    rows_skipped: int
    rows_error: int
    date_from: date | None
    date_to: date | None
    committed_at: datetime | None
    transactions_created: int
    error: str | None


class ImportCommitIn(Schema):
    skip_duplicates: bool = True
    apply_rules: bool = True
    create_missing_payees: bool = True
    default_category_id: UUID | None = None


class ImportResultOut(Out):
    import_id: UUID
    transactions_created: int
    transactions_deleted: int = 0
    duplicates_skipped: int
    rows_failed: int
    rules_applied: int
```

### 4.12 Informes

```python
# app/schemas/reports.py
class SpendingByCategoryRow(Out):
    category: CategoryRefOut
    depth: int
    parent_id: UUID | None
    amount: Money
    share_pct: float
    transactions: int
    allocated: Money | None
    variance: Money | None = Field(description="allocated − amount; negativo es sobrepaso.")
    previous_amount: Money | None
    change_pct: float | None
    children: list["SpendingByCategoryRow"] = Field(default_factory=list)


class SpendingByCategoryOut(Out):
    period_from: str
    period_to: str
    currency: str
    total: Money
    uncategorized: Money
    rows: list[SpendingByCategoryRow]


class MonthlyPointOut(Out):
    period: Period
    expense: Money
    income: Money
    net: Money
    by_category: dict[str, Money] = Field(
        default_factory=dict, description="UUID de temática → importe."
    )


class MonthlyComparisonOut(Out):
    periods: list[Period]
    series: list[MonthlyPointOut]
    average_expense: Money
    best_period: Period | None
    worst_period: Period | None


class CashFlowPointOut(Out):
    period: str
    inflow: Money
    outflow: Money
    net: Money
    cumulative: Money


class CashFlowOut(Out):
    granularity: Literal["month", "week"]
    points: list[CashFlowPointOut]
    total_inflow: Money
    total_outflow: Money
    net: Money
    savings_rate: float = Field(description="net / inflow; 0.23 = 23 %.")


class TopPayeeRow(Out):
    payee: PayeeRefOut | None
    amount: Money
    transactions: int
    average_ticket: Money
    share_pct: float
    top_category: CategoryRefOut | None
    previous_amount: Money | None
    change_pct: float | None


class TopPayeesOut(Out):
    period_from: str
    period_to: str
    total: Money
    rows: list[TopPayeeRow]


class NetWorthPointOut(Out):
    period: Period
    assets: Money
    liabilities: Money
    net_worth: Money
    change: Money
    change_pct: float | None


class NetWorthOut(Out):
    points: list[NetWorthPointOut]
    current: Money
    change_12m: Money | None
    by_account: list[dict[str, Any]] = Field(default_factory=list)


class ProductPricePointOut(Out):
    observed_at: date
    unit_price: UnitPrice
    payee: PayeeRefOut | None
    invoice_id: UUID | None
    change_pct: float | None


class ProductPriceReportOut(Out):
    product: ProductRefOut
    unit: str | None
    points: list[ProductPricePointOut]
    stats: PriceStatsOut
    by_payee: list[PayeePriceOut]


class PriceIncreaseRow(Out):
    product: ProductRefOut
    payee: PayeeRefOut | None
    previous_unit_price: UnitPrice
    new_unit_price: UnitPrice
    change_pct: float
    observed_at: date
    typical_quantity: Quantity | None
    estimated_monthly_impact: Money | None = Field(
        description="Variación × cantidad habitual: ordena por lo que duele, no por el %."
    )


class PriceIncreasesOut(Out):
    period_from: str
    period_to: str
    min_change_pct: float
    total_estimated_impact: Money
    rows: list[PriceIncreaseRow]


class BasketPayeeRow(Out):
    payee: PayeeRefOut | None
    total: Money
    covered_items: int
    missing_items: int
    coverage_pct: float
    diff_vs_cheapest: Money
    stale_prices: int = Field(description="Observaciones con más de 90 días.")


class BasketReportOut(Out):
    """Cesta de la compra comparada entre comercios (F-60)."""

    basket_id: UUID | None
    items: int
    cheapest: BasketPayeeRow | None
    by_payee: list[BasketPayeeRow]
    missing_by_payee: dict[str, list[ProductRefOut]] = Field(default_factory=dict)


class ProjectedBalanceOut(Out):
    period: Period
    as_of: date
    rows: list[dict[str, Any]] = Field(
        description="Por cuenta: saldo actual, recurrentes pendientes, presupuesto restante, "
        "saldo proyectado a fin de mes."
    )
    total_projected: Money
```

### 4.13 Ajustes

```python
# app/schemas/settings.py
class SettingsOut(Out):
    currency: str
    locale: str
    timezone: str
    first_day_of_week: int = Field(ge=0, le=6)
    theme: Literal["dark", "light", "system"]
    rollover_default: bool
    rollover_negative: Literal["carry", "reset"] = Field(
        description="Qué hacer con el sobregasto al cerrar el mes (RN-32)."
    )
    budget_alert_pct: float = Field(ge=0, le=2, description="0.9 avisa al 90 % consumido.")
    price_increase_pct: float = Field(ge=0, description="3.0 avisa a partir de +3 %.")
    anomaly_z: float = Field(ge=0, description="Desviaciones típicas para el gasto inusual.")
    duplicate_window_days: int = Field(ge=0, le=30)
    product_match_threshold: float = Field(ge=50, le=100, description="Umbral difuso (88).")
    digest: Literal["off", "weekly", "monthly"]


class SavedViewIn(Schema):
    name: Name
    resource: Literal["transactions", "invoices", "products", "alerts"] = "transactions"
    filters: dict[str, Any] = Field(description="La query string tal cual, ya validada.")
    is_pinned: bool = False


class StorageOut(Out):
    invoices_bytes: int
    attachments_bytes: int
    exports_bytes: int
    total_bytes: int
    quota_bytes: int | None
    files_count: int
```

---

## 5. Reglas de negocio y validaciones

Numeradas para poder citarlas en el código (`# RN-15`), en los tests
(`test_rn15_splits_deben_cuadrar`) y en las revisiones. **Ninguna se delega al frontend**: el
frontend las repite para dar buen feedback, pero el backend las impone siempre. La columna de
error indica qué se devuelve al incumplirla.

### 5.1 Identidad, sesión y alcance de los datos

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-01** | Toda entidad pertenece a un `user_id`. **Toda** consulta —listados, detalles, informes, agregados— filtra por el usuario de la sesión. El `user_id` se toma del token, nunca de la URL ni del cuerpo | Un `user_id` en el cuerpo se rechaza por `extra="forbid"` → `422` |
| **RN-02** | Acceder a un recurso de otro usuario responde `404 no_encontrado`, **nunca** `403`: distinguirlos permitiría enumerar qué identificadores existen | `404` |
| **RN-03** | La sesión solo se acepta por cookie. No hay cabecera `Authorization`. Un token de tipo distinto al esperado (refresco en lugar de acceso) se rechaza: `decode_token()` comprueba `typ` | `401 no_autenticado` |
| **RN-04** | El refresco es rotatorio y de un solo uso. Reutilizar un `jti` ya consumido revoca la familia completa de esa sesión | `401 sesion_expirada` |
| **RN-05** | Contraseña: mínimo 10 caracteres, no solo dígitos ni solo letras, distinta de la actual al cambiarla. Se hashea con bcrypt de 12 rondas truncando a 72 bytes (`hash_password()`). La contraseña no se devuelve, ni se registra, ni se compara en Python con `==` | `422 contrasenya_debil` |
| **RN-06** | Con `allow_registration=false` solo se permite el registro si **no existe ningún usuario** (arranque inicial de la instancia self-hosted) | `403 registro_deshabilitado` |

### 5.2 Cuentas y saldos

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-07** | El tipo de cuenta es un conjunto cerrado: `checking`, `savings`, `cash`, `credit_card`, `investment`, `debt`. No se puede cambiar el tipo si ya hay movimientos, porque alteraría el patrimonio neto histórico | `422 regla_de_negocio` |
| **RN-08** | El saldo es siempre **derivado**: `initial_balance` + Σ movimientos. Nunca se guarda un saldo editable a mano; la corrección se hace con una conciliación que deja rastro | `422` si se intenta enviar `current_balance` |
| **RN-09** | Una cuenta con movimientos **no se borra**: se archiva. El borrado duro solo está disponible si `transactions_count == 0` | `409 conflicto` |
| **RN-10** | La conciliación no edita saldos: crea una transacción de ajuste con `source="reconciliation"`, temática indicada y fecha del extracto, y avanza `reconciled_through` | `422` |

### 5.3 Temáticas: árbol, archivado y borrado

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-11** | El árbol admite hasta **6 niveles** (`depth ≤ 5` desde 0) y no puede contener ciclos: una temática no puede moverse dentro de su propio subárbol. Se comprueba con la columna `path` (§7.3), no recorriendo padres uno a uno | `422 profundidad_maxima` / `ciclo_en_arbol` |
| **RN-12** | El nombre es único **entre hermanos** (mismo `parent_id`), comparando sin acentos y sin distinguir mayúsculas. Dos temáticas «Ocio» en ramas distintas son legítimas | `409 nombre_duplicado` |
| **RN-13** | El `kind` (`expense`/`income`) lo hereda del padre y no se puede cambiar si ya hay histórico. Archivar una temática archiva sus descendientes; desarchivarla desarchiva sus antepasados (una temática activa no puede tener un padre archivado) | `422 regla_de_negocio` |
| **RN-14** | **No se borra una temática con histórico sin reasignar.** Si tiene transacciones, splits, líneas de factura, reglas, recurrentes, fondos o asignaciones de presupuesto, `DELETE` exige `reassign_to` con una temática destino válida (misma `kind`, no descendiente de la que se borra). Si tiene hijos, exige reasignarlos o moverlos. La alternativa recomendada, y la que ofrece la interfaz por defecto, es **archivar** (F-06) o **fusionar** (F-04). Nunca existe un camino que descoloque los informes pasados | `409 tematica_con_historico` / `tematica_con_descendientes` |

### 5.4 Splits

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-15** | **La suma de los splits es exactamente igual al importe de la transacción.** Comparación en `Decimal`, al céntimo, sin tolerancia: `Σ splits.amount == transaction.amount`. Además: mínimo 1 split, máximo 100, importe de cada split `> 0`, sin dos splits con la misma temática, ninguna temática archivada, y ninguna temática de `kind` distinto al de la transacción. Con splits, la transacción **no** tiene `category_id` propio: la temática vive en los splits | `422 splits_no_cuadran` con el detalle en el campo `splits` |
| **RN-16** | Cambiar el importe de una transacción que tiene splits obliga a reenviar los splits en la misma petición. No se «escalan» solos: repartir 48,50 € donde antes había 45,00 € es una decisión del usuario, no del servidor | `422 splits_no_cuadran` |

### 5.5 Fusión y reasignación de histórico

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-17** | **Una temática no se puede fusionar consigo misma.** `target_id` no puede estar en `source_ids`, ni haber repetidos en `source_ids` | `422 fusion_invalida` |
| **RN-18** | **Una temática no se puede fusionar con un descendiente suyo** (ni un descendiente absorber a su antepasado si eso deja el árbol inconsistente): destruiría la jerarquía. Se comprueba con `path` | `422 fusion_invalida` |
| **RN-19** | La fusión es **atómica y completa**: en una sola transacción de base de datos se reasignan `transactions.category_id`, `transaction_splits.category_id`, `invoice_lines.category_id`, `rules.actions.set_category_id`, `recurring.category_id`, `products.default_category_id`, `payees.default_category_id`, `goals.category_id` y `budget_allocations`; los hijos de las origen se recuelgan de la destino; los nombres antiguos quedan como alias buscables; y solo entonces se borran las origen. Si algo falla, no se mueve nada. Fusionar temáticas de `kind` distinto está prohibido | `422 fusion_invalida`, o `500` con *rollback* completo |
| **RN-20** | Al fusionar, las asignaciones de presupuesto del **mismo periodo** se **suman** en la destino (no se sobreescriben ni se pierden). Un periodo cerrado bloquea la fusión salvo `?force=true`, que lo reabre, recalcula y lo vuelve a cerrar. Toda fusión escribe un registro de reasignación (`merge_id`, filas afectadas y valor anterior de cada una) que permite **deshacerla durante 30 días**; pasado ese plazo, el registro se poda y `undo` responde `409` | `409 periodo_cerrado` / `409 conflicto` |

Las mismas reglas de fusión aplican a comercios (`POST /payees/merge`), etiquetas
(`POST /tags/merge`) y productos (`POST /products/merge`), cambiando el conjunto de tablas
reasignadas.

### 5.6 Transacciones, transferencias y patrimonio

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-21** | **Una transferencia no cuenta como gasto ni como ingreso.** Las transacciones con `kind="transfer"` quedan **excluidas** de: el gasto del presupuesto, `income_actual`, `spending-by-category`, `cash-flow` (inflow/outflow), `top-payees`, `monthly-comparison`, `anomalies` y el digest. Sí cuentan para el saldo de cada cuenta y son neutras en el patrimonio neto. La única excepción es la comisión (`fee`), que sí es un gasto real y se registra como una transacción de gasto aparte con su propia temática | `422` si se intenta asignar temática de gasto a una pata |
| **RN-22** | Origen y destino de una transferencia son cuentas distintas del mismo usuario | `422 transferencia_invalida` |
| **RN-23** | Las patas de una transferencia no admiten `category_id` ni splits, y comparten `transfer_group_id`, fecha, importe absoluto y moneda. Se crean y se modifican **siempre juntas**, en la misma transacción de base de datos | `422 transferencia_invalida` |
| **RN-24** | Borrar o editar una pata afecta a las dos. No existe una transferencia «a medias»: una pata huérfana es un error de integridad, no un estado alcanzable por la API | `409 conflicto` |
| **RN-25** | En el patrimonio neto, `credit_card` y `debt` son **pasivos** y restan; el resto son activos y suman. Una cuenta con `is_excluded_from_net_worth` no entra en el cálculo pero sigue apareciendo en sus informes de cuenta | — |
| **RN-26** | `amount ≠ 0` siempre: una transacción de cero euros es un error de captura o de importación. El signo del **efecto** lo lleva la persistencia (§1.7); en la API el importe se envía positivo salvo devoluciones, abonos y ajustes de conciliación, que se envían negativos manteniendo su `kind` (una devolución es un `expense` negativo, no un ingreso) | `422 datos_invalidos` |
| **RN-27** | La fecha de una transacción no puede ser más de **1 año en el futuro** (un error de teclado en el año descolocaría todos los informes) ni anterior a `1970-01-01`. Registrar en un periodo cerrado se permite, pero devuelve el aviso `periodo_cerrado_recalculado` en la respuesta y recalcula el rollover en cascada | `422 regla_de_negocio` |

### 5.7 Presupuesto, periodos y rollover

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-28** | **El presupuesto asignado nunca es negativo**: `amount ≥ 0` en cada asignación, en `PUT`, en `PATCH`, al copiar de otro periodo, al distribuir y al reasignar. Sí puede ser negativo el **disponible** (`available`) y el **sin asignar** (`unassigned`): eso es información real que la barra pinta como sobreasignación | `422 presupuesto_negativo` |
| **RN-29** | La reasignación entre temáticas es de suma cero: se resta exactamente lo que se suma, en la misma transacción de base de datos, y el total asignado del periodo no cambia. No puede dejar el origen por debajo de 0 ni tocar una temática con `is_locked=true` | `422 presupuesto_negativo` / `422 regla_de_negocio` |
| **RN-30** | **El periodo de presupuesto es siempre `AAAA-MM`**, validado con `^\d{4}-(0[1-9]|1[0-2])$`, con año entre 1970 y 2200. Se rechazan `2026-8`, `2026/08`, `08-2026` y `2026-13`. Es el mismo formato que produce `periodoDe()` en el frontend | `422 periodo_invalido` |
| **RN-31** | El gasto de un periodo se calcula por la **fecha de la transacción**, no por la de creación ni por la de la factura. Una transacción con splits aporta a cada temática el importe de su split, nunca el total duplicado | — |
| **RN-32** | Rollover (F-26), solo si `rollover_enabled` en la temática: `carry_in(p) = allocated(p−1) + carry_in(p−1) − spent(p−1)`. Si sale positivo, entra en el mes siguiente. Si sale negativo, el ajuste `rollover_negative` decide: `carry` lo arrastra (el sobregasto se paga el mes que viene, estilo YNAB) o `reset` lo deja en 0. Sin `rollover_enabled`, `carry_in = 0` | — |
| **RN-33** | Cerrar un periodo es **idempotente**: consolida el rollover y marca `is_closed`. Cerrarlo dos veces no duplica nada. No se puede cerrar un periodo futuro. Un periodo cerrado rechaza cambios de asignación (`409 periodo_cerrado`) hasta reabrirlo; reabrir recalcula en cascada los periodos posteriores | `409 periodo_cerrado` / `422` |
| **RN-34** | No se asigna presupuesto a una temática archivada, ni a una de `kind="income"`, ni a una que no exista. Una temática que se archiva conserva sus asignaciones pasadas (los informes históricos no cambian) y deja de recibir nuevas | `422 regla_de_negocio` |
| **RN-35** | `income` de la barra = `planned_income` si está definido; si no, la suma de los ingresos reales del periodo. Los dos valores viajan siempre en la respuesta para que la UI pueda explicar la diferencia | — |

### 5.8 Recurrentes y suscripciones

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-36** | Una ocurrencia se materializa **una sola vez**: unicidad `(recurring_id, occurrence_date)`. Un segundo `post` de la misma fecha responde `409` con la transacción existente | `409 conflicto` |
| **RN-37** | El día del mes se ajusta a meses cortos: un recurrente del día 31 cae el 28/29/30 cuando el mes no llega. Nunca se salta el mes | — |
| **RN-38** | Pausar impide generar, pero no borra las ocurrencias ya generadas. Borrar la plantilla **no borra** las transacciones ya creadas: quedan como movimientos normales con `recurring_id = null` | — |
| **RN-39** | La detección de suscripciones (F-29) exige al menos 3 cargos del mismo comercio con periodicidad estable (desviación ≤ 20 % del intervalo) e importe estable (`amount_stability ≥ 0.8`). Un grupo descartado no vuelve a proponerse | — |
| **RN-40** | La subida de precio de un recurrente (F-30) se mide contra el **último cargo materializado**, no contra la media, y genera alerta si supera `price_increase_pct` de los ajustes | — |

### 5.9 Facturas: subida, revisión y confirmación

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-41** | Al corregir una línea, el backend **recalcula el hueco que falte** con la misma lógica que `LineaExtraida.completar()` (con dos de los tres valores deduce el tercero y respeta el total cuando los tres no cuadran) y marca `is_edited=true`, `confidence=1.0`. Una línea editada a mano nunca se sobreescribe en un reprocesado | — |
| **RN-42** | Para confirmar, la suma de las líneas no excluidas debe coincidir con el total de la factura con **tolerancia de 0,02 €** —la misma constante `TOLERANCIA` del extractor— o coincidir con la base imponible (caso normal de líneas sin IVA y total con IVA). Si no cuadra, se exige `allow_total_mismatch: true` explícito, y la diferencia se registra en la transacción como `total_mismatch` para que el informe pueda explicarla | `422 total_no_cuadra` |
| **RN-43** | El PDF se valida **por contenido, no por `content-type`**: firma `%PDF-`, tamaño ≤ `max_upload_mb`, páginas ≤ `max_pdf_pages`, no cifrado, no dañado (`validar_pdf()`). El `content-type` que declara el navegador y la extensión del nombre **no** se usan para decidir nada (§8.3) | `413`, `415`, `422 pdf_invalido` / `pdf_demasiadas_paginas` |
| **RN-44** | Se calcula el SHA-256 del fichero. Si el usuario ya subió ese mismo fichero, `POST /invoices` responde `200` con la factura existente en lugar de crear otra, y no se guarda el fichero dos veces | `200` (no es error: es la respuesta correcta) |
| **RN-45** | **Detección de factura duplicada por emisor + número + fecha + total.** Se normaliza el emisor (sin acentos, minúsculas, sin forma jurídica) y el número (sin espacios ni separadores). Si los cuatro coinciden con una factura ya confirmada, la confirmación responde `409 factura_duplicada` con la factura previa en `detalles`, y solo continúa con `ignore_duplicate: true`. Coincidencias parciales (mismo total y misma fecha, o mismo número con emisor distinto) no bloquean: generan un aviso y una alerta `duplicate_suspected` | `409 factura_duplicada` |
| **RN-46** | **Una factura no se puede confirmar dos veces.** Solo se confirma desde `pending_review` o `failed`. En `confirmed`, `processing` o `discarded` → `409 factura_ya_confirmada`. La confirmación fija `confirmed_at` y `transaction_id`, y con `Idempotency-Key` un reintento devuelve la respuesta guardada en lugar de un error | `409 factura_ya_confirmada` |
| **RN-47** | La confirmación es **una sola transacción de base de datos**: transacción de gasto + splits + observaciones de precio + alias aprendidos + productos creados + alertas. Si falla cualquier paso, no queda nada a medias. Las observaciones de precio son únicas por `invoice_line_id`, así que ni un reintento ni un `unconfirm`+`confirm` pueden duplicar el histórico | `500` con *rollback* |
| **RN-48** | Solo generan observación de precio las líneas con `is_product=true`, `is_excluded=false`, `product_id` no nulo y `unit_price > 0`. Los conceptos de una factura de suministro (potencia contratada, alquiler de contador, impuestos) se marcan `is_product=false` y **no** contaminan el catálogo | — |
| **RN-49** | Editar líneas o cabecera solo se permite en `pending_review` y `failed`. En `processing` → `409 factura_no_revisable` (aún puede llegar el resultado del extractor y pisarlo). En `confirmed` hay que hacer `unconfirm` primero | `409 factura_no_revisable` |
| **RN-50** | `unconfirm` es la inversa exacta de `confirm`: borra la transacción generada (y sus splits) y las observaciones de precio de esa factura, revierte las alertas de precio que originó y vuelve a `pending_review`. Si la transacción se ha editado a mano desde entonces, se conserva y se responde con el aviso `transaccion_modificada` | `409 conflicto` |

### 5.10 Fondos objetivo

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-51** | `target_amount > 0`; `target_date`, si se indica, en el futuro al crearlo. `required_monthly` se recalcula en cada lectura, nunca se guarda | `422` |
| **RN-52** | Una retirada no puede dejar el fondo en negativo: `amount ≤ current_amount` | `422 saldo_insuficiente` |
| **RN-53** | Una aportación con `account_id` genera una **transferencia real** a la cuenta del fondo y queda sujeta a RN-21…RN-24. Sin `account_id` es una anotación contable del fondo y no toca ningún saldo | `422` |
| **RN-54** | Un fondo se marca `is_completed` cuando `current_amount ≥ target_amount`; sigue aceptando movimientos (se puede seguir ahorrando por encima del objetivo) | — |

### 5.11 Reglas de auto-categorización

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-55** | Las reglas se evalúan por `priority` ascendente y, a igualdad, por antigüedad. La primera que casa aplica sus acciones; si tiene `stop_processing`, se detiene la evaluación. El resultado de aplicar el mismo conjunto de reglas al mismo dato es siempre el mismo (determinista) | — |
| **RN-56** | Las reglas **no pisan una categorización manual**: solo actúan sobre transacciones con `category_id = null` o que ya fueron categorizadas por una regla (`categorized_by="rule"`). `POST /rules/apply` con `scope="all"` avisa en la respuesta de cuántas categorizaciones manuales se han respetado | — |
| **RN-57** | Las reglas no se aplican a las patas de transferencia ni a los ajustes de conciliación | — |
| **RN-58** | El operador `regex` acepta solo patrones compilables, de 200 caracteres como máximo, y se evalúa con un límite de tiempo por transacción; un patrón catastrófico se desactiva y genera un aviso en lugar de bloquear el proceso | `422 datos_invalidos` |
| **RN-59** | Una regla no puede asignar una temática archivada o inexistente. Si la temática se archiva después, la regla se desactiva automáticamente y se informa en su respuesta | `422 regla_de_negocio` |

### 5.12 Productos, precios y catálogo

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-60** | Dos descripciones son el mismo producto solo si lo dice `es_mismo_producto()`: código de barras idéntico manda; **tamaños distintos descartan la coincidencia** aunque el nombre sea idéntico (medio litro y un litro no comparten histórico de precio unitario); y el umbral difuso por defecto es 88. **El sistema nunca fusiona solo**: sugiere, y el usuario confirma en la revisión | — |
| **RN-61** | El precio unitario se guarda con hasta 4 decimales, sin redondear a céntimos: en luz, gas y telefonía redondear falsearía el histórico | `422 datos_invalidos` |
| **RN-62** | Una observación de precio es única por `invoice_line_id`. Las manuales (`source="manual"`) admiten varias el mismo día si el comercio difiere; el mismo producto, comercio, fecha y precio ya existente responde `409` | `409 conflicto` |
| **RN-63** | La variación (`change_pct`) se calcula contra la **última observación anterior del mismo producto en el mismo comercio**; si no hay ninguna en ese comercio, contra la última global, y se indica en la respuesta cuál se ha usado. Comparar entre unidades distintas (€/kg contra €/ud) está prohibido: si la unidad no coincide, no hay variación (`null`) | — |
| **RN-64** | Se genera alerta de subida (F-16) cuando `change_pct ≥ price_increase_pct` **y** el importe absoluto de la diferencia supera 0,05 € (para no avisar de un céntimo en un producto de 20 cts.). Las alertas se agrupan por factura: una alerta con N productos, no N alertas | — |
| **RN-65** | Separar un producto mal fusionado (`POST /products/{id}/split`) mueve observaciones, líneas y alias al destino y recalcula las estadísticas de los dos productos. `undo` de una fusión solo funciona mientras exista el registro de reasignación (30 días) | `422 producto_no_fusionado` |

### 5.13 Importaciones

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-66** | El formato se detecta por contenido (cabecera OFX/SGML, `!Type:` de QIF, delimitador y cabecera del CSV), no por la extensión del nombre | `422 datos_invalidos` |
| **RN-67** | Nada se crea hasta el `commit`. El análisis solo produce filas en una tabla intermedia, revisables y corregibles. Un `commit` sin las columnas obligatorias mapeadas (fecha e importe) → `422 mapeo_incompleto` | `422 mapeo_incompleto` |
| **RN-68** | Duplicado en importación: misma cuenta, mismo importe, fecha dentro de `duplicate_window_days` y descripción con parecido ≥ 90. Se marca, **no se descarta solo**: el usuario decide, y `skip_duplicates` por defecto los omite | — |
| **RN-69** | El `commit` es idempotente con `Idempotency-Key` y una importación ya confirmada no se vuelve a confirmar. `rollback` borra **exactamente** las transacciones creadas por esa importación (por `import_id`), y solo las que no se hayan modificado a mano después | `409 importacion_ya_confirmada` |
| **RN-70** | Los importes del extracto se interpretan con `parsear_importe()`, que ya resuelve la ambigüedad de `.` y `,` del formato español. El mapeo puede forzar el separador cuando el banco es raro | — |

### 5.14 Alertas y avisos

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-71** | Las alertas son **idempotentes por causa**: clave `(type, period, objeto_id, umbral)`. Recalcular no duplica; si la causa desaparece (se reasigna presupuesto y ya no hay sobrepaso), la alerta se cierra automáticamente | — |
| **RN-72** | Una alerta descartada silencia esa causa durante `mute_days`. El sobrepaso de presupuesto se avisa una vez al cruzar `budget_alert_pct` y otra al cruzar el 100 %, no en cada gasto | — |
| **RN-73** | Toda alerta es **accionable y financiera**. No hay alertas promocionales ni informativas de relleno (antipatrón documentado en `docs/competencia.md`) | — |
| **RN-74** | El digest (F-45) se compone con los mismos datos que los informes; no calcula nada por su cuenta, para que no haya dos verdades | — |

### 5.15 Ficheros, cuotas y límites

| # | Regla | Al incumplirla |
|---|---|---|
| **RN-75** | Tamaño máximo `settings.max_upload_mb` (20 MiB) y páginas máximas `settings.max_pdf_pages` (40), comprobados **antes** de procesar. El límite de tamaño se aplica mientras se recibe el flujo, no después de cargarlo en memoria | `413 fichero_demasiado_grande`, `422 pdf_demasiadas_paginas` |
| **RN-76** | Los adjuntos admiten `application/pdf`, `image/jpeg`, `image/png` y `image/webp`, validados por firma. Cualquier otra cosa → `415` | `415 tipo_no_soportado` |
| **RN-77** | El nombre original del fichero se guarda **solo como metadato saneado** y jamás se usa para construir la ruta en disco (§8.3) | — |
| **RN-78** | Cuota por usuario configurable (por defecto sin límite en self-hosted). Al superarla, la subida responde `409 cuota_almacenamiento` con el espacio ocupado en `detalles`. Borrar una factura o un adjunto borra también su fichero del disco, en la misma operación | `409 cuota_almacenamiento` |

---

## 6. Estructura de carpetas del backend

Continúa lo que ya existe (`app/core`, `app/db`, `app/services`, `app/api/v1`, `app/schemas`) sin
mover nada. Se añaden `app/models`, `app/repositories` y `app/workers`.

```
backend/app/
├── main.py                    # YA EXISTE. Middleware, CORS, estáticos, health, include_router
├── core/
│   ├── config.py              # YA EXISTE. Settings de entorno
│   ├── errors.py              # YA EXISTE. AppError y manejadores. NO se toca
│   ├── security.py            # YA EXISTE. JWT, bcrypt, CSRF de doble envío
│   ├── cookies.py             # Emitir/borrar las tres cookies con Path, SameSite y Secure
│   ├── ratelimit.py           # Cubo con fichas por IP e identidad + bloqueo persistido (§2.4)
│   ├── idempotency.py         # Almacén de Idempotency-Key: guardar y reproducir respuesta
│   ├── etag.py                # Cálculo y comprobación de ETag / If-Match / If-None-Match
│   ├── pagination.py          # Params de página, sobre Page[T], keyset para streaming
│   ├── logging.py             # Formato de log, X-Request-Id, filtro de datos sensibles (§9)
│   └── storage.py             # Rutas seguras en disco, nombres UUID, borrado, cuota
├── db/
│   ├── base.py                # YA EXISTE. Base declarativa, Money, UUIDPrimaryKey, Timestamps
│   └── session.py             # YA EXISTE. Motor async y dependencia get_session
├── models/                    # SQLAlchemy 2.0 (Mapped[...]), un módulo por agregado
│   ├── user.py                # User, RefreshSession (familias de jti revocables)
│   ├── account.py             # Account, Reconciliation
│   ├── category.py            # Category (con path materializado), CategoryAlias, CategoryMerge
│   ├── transaction.py         # Transaction, TransactionSplit, TransactionTag, Attachment
│   ├── budget.py              # BudgetPeriod, BudgetAllocation
│   ├── recurring.py           # Recurring, RecurringOccurrence
│   ├── payee.py               # Payee, PayeeAlias
│   ├── tag.py                 # Tag
│   ├── rule.py                # Rule, RuleCondition, RuleAction
│   ├── invoice.py             # Invoice, InvoiceLine, InvoiceTemplate
│   ├── product.py             # Product, ProductAlias, ProductMerge, PriceObservation, Basket
│   ├── goal.py                # Goal, GoalMovement
│   ├── alert.py               # Alert
│   ├── importing.py           # ImportBatch, ImportRow, ImportMapping
│   └── misc.py                # SavedView, IdempotencyKey, UserSettings, ExportJob
├── schemas/                   # Pydantic v2. Espejo de §4, sin lógica de negocio
│   ├── base.py                # Money, Quantity, Period, Schema, Out, Page[T], errores
│   ├── auth.py  accounts.py  categories.py  transactions.py  budgets.py
│   ├── recurring.py  payees.py  tags.py  rules.py  invoices.py  products.py
│   ├── goals.py  alerts.py  imports.py  exports.py  reports.py  settings.py
├── api/
│   ├── __init__.py            # YA EXISTE
│   └── v1/
│       ├── __init__.py        # YA EXISTE. Agregador api_router: aquí se registra cada router
│       ├── deps.py            # usuario_actual, sesion, csrf, paginación, ETag, idempotencia
│       ├── auth.py            # §3.1  register, login, refresh, logout, change-password, me
│       ├── users.py           # §3.2  perfil, borrado de cuenta, meta, onboarding
│       ├── accounts.py        # §3.3  cuentas, saldos, conciliación, amortización
│       ├── categories.py      # §3.4  árbol, move/reorder, archive, merge/preview/undo
│       ├── transactions.py    # §3.5  listado, splits, bulk, duplicados, adjuntos
│       ├── transfers.py       # §3.6  transferencias de dos patas
│       ├── budgets.py         # §3.7  barra, asignaciones, reassign, copy, close, rollover
│       ├── recurring.py       # §3.8  recurrentes, suscripciones, detección, upcoming
│       ├── payees.py          # §3.9  comercios, fusión, sugerencias
│       ├── tags.py            # §3.10 etiquetas
│       ├── rules.py           # §3.11 reglas, test, apply
│       ├── invoices.py        # §3.12 subida, estado, líneas, revisión, confirm, plantillas
│       ├── products.py        # §3.14 catálogo, merge/split, alias, comparativa
│       ├── prices.py          # §3.14 observaciones de precio y cestas
│       ├── goals.py           # §3.15 fondos objetivo
│       ├── alerts.py          # §3.16 alertas y digest
│       ├── imports.py         # §3.17 CSV/OFX/QIF, mapeo, preview, commit, rollback
│       ├── exports.py         # §3.18 exportación y copia de seguridad
│       ├── reports.py         # §3.19 informes
│       └── settings.py        # §3.20 ajustes, notificaciones, vistas guardadas
├── services/                  # Reglas de negocio. Sin FastAPI, sin Request, sin HTTP
│   ├── numeros.py             # YA EXISTE. Decimales y fechas de facturas españolas
│   ├── normalizacion.py       # YA EXISTE. Canónica, tamaño, código, similitud RapidFuzz
│   ├── extraccion_pdf.py      # YA EXISTE. extraer_factura() y validar_pdf()
│   ├── auth.py                # Alta, verificación, rotación de refresco, bloqueo
│   ├── categorias.py          # Árbol (path), move/reorder, archivado, FUSIÓN y undo (RN-17…20)
│   ├── transacciones.py       # Alta/edición, splits (RN-15), duplicados, anomalías
│   ├── transferencias.py      # Alta y edición de las dos patas (RN-21…24)
│   ├── presupuesto.py         # Barra, rollover (RN-32), reasignación, cierre de periodo
│   ├── recurrentes.py         # Calendario de repetición, materialización, detección (F-29)
│   ├── reglas.py              # Motor condición→acción, evaluación y aplicación masiva
│   ├── facturas.py            # Orquesta subida→extracción→revisión→confirmación (RN-41…50)
│   ├── productos.py           # Catálogo, emparejado difuso, merge/split de productos
│   ├── precios.py             # Observaciones, variación, detección de subidas (F-16)
│   ├── patrimonio.py          # Saldos, activos/pasivos, serie de patrimonio neto
│   ├── importacion.py         # Lectura de CSV/OFX/QIF, mapeo, duplicados, commit/rollback
│   ├── exportacion.py         # Volcado en JSON/CSV/ZIP en streaming
│   ├── informes.py            # Composición de los informes a partir de los repositorios
│   ├── alertas.py             # Generación, cierre y agrupación idempotente de alertas
│   └── digest.py              # Resumen semanal/mensual (F-45)
├── repositories/              # SQL. Consultas de lectura y agregados; nada de reglas
│   ├── base.py                # Helpers: filtros comunes, orden seguro, COUNT(*) OVER ()
│   ├── transacciones.py       # Listado filtrado, agregados por temática/mes/comercio
│   ├── categorias.py          # Árbol por path, contadores de uso, reasignación masiva
│   ├── presupuestos.py        # Asignado + gastado + rollover en UNA consulta
│   ├── productos.py           # Últimos precios, comparativa por comercio, cesta
│   ├── facturas.py            # Bandeja, líneas con sugerencias, candidatos a duplicado
│   └── informes.py            # Series temporales, patrimonio neto, top comercios, anomalías
├── workers/
│   ├── queue.py               # Cola en proceso con límite de concurrencia (§10)
│   ├── tasks.py               # extraer_factura_task, analizar_importacion_task, export_task
│   └── scheduler.py           # Tareas periódicas: recurrentes, alertas, digest, limpieza
└── tests/                     # YA EXISTE tests/. Un módulo por regla de negocio crítica
```

Criterios de reparto, para que no se difumine con el tiempo:

- **`api/v1/*`**: solo HTTP. Parsea la petición con un esquema, llama a **un** servicio, traduce
  el resultado a un esquema de respuesta y elige el código. Ni una consulta SQL, ni un `if` de
  negocio. Ningún fichero debería pasar de ~250 líneas.
- **`services/*`**: donde vive todo lo numerado en §5. Reciben `AsyncSession` y tipos del
  dominio, nunca `Request`, `UploadFile` ni `HTTPException`. Lanzan las clases de
  `core/errors.py`, que es lo que permite probarlas sin cliente HTTP.
- **`repositories/*`**: consultas y agregados. Existen porque los informes y la barra de
  presupuesto necesitan SQL de verdad (`GROUP BY`, ventanas, `CTE` recursivas) que no cabe en un
  servicio sin volverlo ilegible, y porque así se pueden optimizar y medir por separado.
- **`schemas/*`**: validación de forma y de invariantes locales (un `model_validator` que
  comprueba que los splits suman). Nada que necesite base de datos.
- **`models/*`**: solo mapeo y restricciones de integridad (`UniqueConstraint`, `CheckConstraint`,
  índices). Las reglas que la base de datos puede garantizar se declaran **también** aquí: es la
  última línea de defensa si un servicio se equivoca.

---

## 7. Rendimiento

### 7.1 Evitar el N+1, en concreto

El N+1 es el riesgo real de esta API: casi todas las respuestas incluyen relaciones (temática,
comercio, etiquetas, splits). Medidas obligatorias:

1. **Carga explícita, nunca perezosa.** Todas las relaciones se declaran
   `lazy="raise"` en los modelos. Con SQLAlchemy async, una carga perezosa no es una consulta
   lenta: es una excepción (`MissingGreenlet`) en producción. Con `lazy="raise"` el fallo
   aparece en el primer test, no en el servidor.
2. **`selectinload` para colecciones, `joinedload` para escalares.** Un listado de 50
   transacciones con splits, etiquetas, comercio y cuenta se resuelve en **5 consultas fijas**
   (transacciones + splits + etiquetas + comercios + cuentas), no en 200:
   ```python
   stmt = (
       select(Transaction)
       .where(Transaction.user_id == user_id, *filtros)
       .options(
           joinedload(Transaction.account),
           joinedload(Transaction.payee),
           joinedload(Transaction.category),
           selectinload(Transaction.splits).joinedload(TransactionSplit.category),
           selectinload(Transaction.tags),
       )
       .order_by(*orden)
       .limit(size).offset((page - 1) * size)
   )
   ```
3. **`include` para no pagar lo que no se usa.** El listado por defecto **no** trae splits ni
   adjuntos: trae `is_split` y `attachments_count`, que salen de columnas contador mantenidas por
   la propia escritura. La tabla del design system solo necesita eso. `include=splits,tags` es
   opt-in.
4. **Contadores desnormalizados** en las entidades muy leídas (`transactions_count`,
   `observations_count`, `children_count`, `unread_alerts`), actualizados en la misma transacción
   que el cambio. Evitan un `COUNT` por fila en cada listado.
5. **Agregar en SQL, jamás en Python.** Ningún informe carga transacciones para sumarlas en un
   bucle: `GROUP BY` con `SUM`, `CTE` recursiva para plegar el árbol de temáticas, y
   `generate_series` para rellenar los meses sin datos (que si no, la serie del gráfico sale con
   huecos y el frontend tendría que adivinarlos).
6. **La barra de presupuesto en una sola consulta**: asignado, gastado y rollover por temática
   con un `LEFT JOIN` entre `budget_allocations` y un agregado de `transaction_splits`, más una
   función de ventana para el arrastre. Es la pantalla de inicio: no puede costar 40 consultas.
7. **Test de regresión de consultas.** Los listados críticos tienen un test que cuenta las
   consultas emitidas (con un `event listener` sobre `before_cursor_execute`) y falla si suben.
   Sin eso, el N+1 vuelve solo en la siguiente refactorización.

### 7.2 Paginación y totales

- Página y total en **una** consulta: `COUNT(*) OVER () AS total_count` como columna adicional.
- `size` acotado a 200 por esquema. El streaming (`format=csv`, `/exports`) no pagina y va por
  *keyset* con `yield_per`, para no materializar la lista en memoria.
- Los `ORDER BY` se construyen desde una whitelist de columnas indexadas (§1.6).

### 7.3 Índices y modelo de árbol

- Ruta materializada en `categories`: la columna **`path_ids UUID[]`** (antepasados más ella
  misma, de raíz a hoja) con índice **GIN**, tal y como la define
  `docs/arquitectura/modelo-datos.md` §2.5, más `depth`. Con eso:
  - descendientes de una temática = `path_ids @> ARRAY[:id]::uuid[]` (una consulta, sin
    recursión y usando el índice), que es lo que resuelve `include_children`;
  - detección de ciclo al mover = comprobar si el nuevo padre ya está en el `path_ids` actual;
  - profundidad = `cardinality(path_ids) - 1`, sin consultar nada.
  Mover una rama reescribe `path_ids`/`depth` de su subárbol en un solo `UPDATE`. En el contrato
  esa ruta se expone como el campo `path` de `CategoryOut` (los UUID unidos por `/`), para que el
  cliente pueda ordenar y sangrar el árbol sin recorrerlo.
- Índices previstos (todos con `user_id` delante, porque todas las consultas lo filtran):
  `transactions (user_id, date DESC, id DESC)`, `transactions (user_id, account_id, date DESC)`,
  `transactions (user_id, payee_id, date DESC)`, `transactions (user_id, category_id, date)`,
  `transaction_splits (category_id, transaction_id)`,
  `budget_allocations (user_id, period, category_id)` único,
  `price_observations (product_id, payee_id, observed_at DESC)`,
  `price_observations (invoice_line_id)` único,
  `invoices (user_id, status, uploaded_at DESC)`, `invoices (user_id, checksum)` único,
  `invoices (user_id, issuer_normalized, number_normalized, date, total)` para RN-45,
  `products (user_id, canonical_name)`, `alerts (user_id, is_read, created_at DESC)`.
- Búsqueda de texto (`q`) con índice **GIN** `pg_trgm` sobre `description` y `payee.name`, que
  además da el `ILIKE '%…%'` rápido y el parecido difuso en SQL cuando RapidFuzz sería demasiado
  caro (miles de filas).

### 7.4 Coste de las facturas y del OCR

- La extracción **no ocurre en la petición**: `POST /invoices` responde `202` en milisegundos
  (§10). Una factura escaneada con OCR a 300 ppp puede tardar decenas de segundos; bloquear el
  *worker* de uvicorn con eso dejaría la aplicación colgada.
- Concurrencia de extracción limitada (por defecto 2 tareas), porque Tesseract y el rasterizado
  son intensivos en CPU y el despliegue es un contenedor modesto.
- `GET /invoices/{id}/status` es una consulta de una fila con `ETag`: sondear cada 1,5 s no
  cuesta nada. La respuesta indica `retry_after_seconds` para que el cliente no acelere.
- Las sugerencias de producto de la pantalla de revisión se calculan **una vez** al terminar la
  extracción y se guardan en la línea; no se recalculan en cada `GET /lines`. Los candidatos se
  preseleccionan con `pg_trgm` y solo los ~50 mejores pasan por RapidFuzz.
- `texto_crudo` se guarda comprimido y **con caducidad**: se borra al confirmar o a los 30 días.
  Sirve para depurar una extracción mala, no para conservarlo indefinidamente (§9).

### 7.5 Otros

- `GZipMiddleware` ya está activo para respuestas > 1000 bytes: los informes y los listados
  largos son el caso claro.
- `ETag` en informes y en el árbol de temáticas; el frontend cachea el árbol y solo lo revalida.
- Pool de conexiones ya configurado (`pool_size=10`, `max_overflow=20`, `pool_pre_ping`). Toda
  ruta es `async def`; cualquier trabajo bloqueante (PDF, OCR, hashing de contraseña) va a un
  hilo o a la cola, nunca en el bucle de eventos.
- Cada petición usa **una** transacción de base de datos (`get_session`), con `commit` al final;
  las operaciones compuestas (fusión, confirmación, transferencia, commit de importación) están
  dentro de ella por construcción.

---

## 8. Seguridad

### 8.1 Configuración obligatoria en producción

`SECRET_KEY` larga y aleatoria (mínimo 16 caracteres por esquema, recomendado 64),
`COOKIE_SECURE=true`, `APP_ENV=production`, `CORS_ORIGINS` vacío cuando el propio backend sirve
la SPA (mismo origen, no hace falta CORS) y HTTPS terminado en el proxy. El arranque falla si
`APP_ENV=production` y `COOKIE_SECURE=false`, o si `SECRET_KEY` es el valor de ejemplo.

### 8.2 Cabeceras

Ya implementadas en `app/main.py`: `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy` restrictiva y HSTS
en producción. Se añade **CSP** para los estáticos de la SPA:
`default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`.
`object-src 'none'` importa aquí: evita incrustar el PDF con un plugin; la previsualización de la
factura usa un visor propio o un `<iframe sandbox>` sobre `/invoices/{id}/file`.

### 8.3 Validación real del PDF y de los adjuntos

Nada de confiar en lo que dice el cliente:

1. **El `content-type` no decide nada.** Un `multipart` puede declarar `application/pdf` y
   traer un ejecutable. Se lee la **firma**: `datos.lstrip()[:5] == b"%PDF-"`, como ya hace
   `validar_pdf()`. La extensión del nombre tampoco decide: solo se usa para elegir el mensaje de
   error.
2. **Límite de tamaño mientras se recibe.** Se lee el flujo en trozos de 64 KiB acumulando el
   contador y se **aborta en cuanto se supera** `settings.max_upload_bytes`, devolviendo `413`.
   Leer primero `await fichero.read()` y comprobar después significa que un fichero de 2 GiB ya
   te ha reventado la memoria. En paralelo se calcula el SHA-256 (RN-44) y se escribe a un
   temporal en el mismo recorrido.
3. **Límite de páginas.** `max_pdf_pages` (40) comprobado antes de extraer. Un PDF de 5.000
   páginas es un ataque de agotamiento, no una factura.
4. **PDF cifrado o dañado** → `422 pdf_invalido`. No se intenta adivinar la contraseña ni se
   procesa parcialmente.
5. **Bombas de descompresión.** Un PDF de 30 KiB puede contener una imagen que descomprime a
   varios GiB, o un flujo con un ratio de compresión absurdo. Defensas acumuladas:
   - se comprueba el **ratio** entre el tamaño del fichero y el tamaño declarado de los flujos;
     por encima de 200:1 se rechaza;
   - el rasterizado para OCR fija el **DPI y el tope de píxeles** por página (300 ppp con límite
     de ~40 Mpx); por encima, se reduce la escala o se salta la página con un aviso;
   - se limita el **número de imágenes** procesadas por página y el texto extraído por documento
     (~2 MiB de caracteres);
   - cada extracción corre con **límite de tiempo** (60 s sin OCR, 300 s con OCR) y con techo de
     memoria; al agotarse, la factura queda en `failed` con un mensaje claro y el usuario puede
     meter los datos a mano.
6. **Sin ejecución de contenido activo.** No se resuelven JavaScript, formularios XFA, acciones
   de apertura ni recursos remotos del PDF. `pdfplumber` y PyMuPDF se usan solo para leer texto y
   rasterizar. Tesseract se invoca sobre un fichero ya validado, con su propio límite de tiempo.
7. **Nombre de fichero saneado y ruta calculada por el servidor.** El nombre que llega del
   cliente **nunca** se usa para construir una ruta: se guarda como
   `uploads/{user_id}/{aaaa}/{mm}/{uuid4}.pdf`. El nombre original se conserva solo como metadato
   tras normalizar Unicode (NFKC), quedarse con `[A-Za-z0-9 ._-]`, colapsar espacios, recortar a
   120 caracteres y eliminar `..`, `/`, `\`, bytes nulos y nombres reservados de Windows. Antes
   de escribir o de servir, la ruta resuelta se comprueba contra la raíz (`resolve()` +
   comprobación de `parents`), la misma técnica antitraversal que ya usa `servir_spa()`.
8. **Descarga endurecida.** `GET /attachments/{id}/content` responde con el `Content-Type`
   **fijado por el servidor** (nunca el que declaró el cliente), `Content-Disposition:
   attachment; filename*=UTF-8''…` salvo petición explícita de `inline`,
   `X-Content-Type-Options: nosniff` y `Content-Security-Policy: sandbox`. Así un SVG o un HTML
   colado como imagen no se ejecuta en el origen de la aplicación.
9. **Los ficheros no se sirven nunca desde el directorio de estáticos.** Salen por un endpoint
   autenticado que comprueba la propiedad (RN-01). El directorio `uploads/` no está publicado.

### 8.4 Límites de tasa fuera de autenticación

| Grupo | Límite | Motivo |
|---|---|---|
| `POST /invoices`, `POST /imports`, `POST /transactions/{id}/attachments` | 30 / hora y 5 / minuto | Cada una arranca trabajo intensivo de CPU |
| `POST /invoices/{id}/reprocess` | 10 / hora por factura | Reprocesar con OCR es lo más caro del sistema |
| `GET /reports/*` | 120 / minuto | Consultas agregadas |
| `POST /rules/apply`, `POST /alerts/recompute`, `POST /exports` | 10 / hora | Recorren el histórico completo |
| `GET /products/suggestions`, `GET /payees/suggestions` | 300 / minuto | Se llaman al teclear |
| Resto de la API | 600 / minuto por sesión | Red de seguridad ante un bucle del cliente |

### 8.5 Inyección, IDOR y asignación masiva

- **SQL**: solo consultas construidas con SQLAlchemy y parámetros ligados. Cero f-strings con
  datos del cliente. El `ORDER BY` y el `GROUP BY` salen de whitelists (§1.6). Ni un
  `text()` con interpolación.
- **IDOR**: RN-01 y RN-02. Los identificadores son UUID v4 (no adivinables, como ya justifica
  `UUIDPrimaryKey`), pero eso es una capa extra, no la defensa: la defensa es el filtro por
  `user_id` en **cada** consulta, incluidas las de los recursos anidados
  (`/invoices/{id}/lines/{line_id}` comprueba que la línea pertenece a la factura **y** la
  factura al usuario).
- **Asignación masiva**: `extra="forbid"` en todos los esquemas de entrada y esquemas de
  actualización que **no** incluyen campos derivados (`current_balance`, `confirmed_at`,
  `user_id`, `created_at`). Enviar uno de esos campos es un `422`, no un cambio silencioso.
- **Expresiones regulares del usuario** (reglas): RN-58.
- **Bombas de JSON**: cuerpo máximo 1 MiB, listas acotadas por `max_length` en cada esquema
  (splits ≤ 100, líneas ≤ 500, `ids` de operaciones en bloque ≤ 500), profundidad de anidación
  limitada por los propios esquemas.
- **Enumeración de usuarios**: mismo error y tiempo similar en login (§2.4); el registro con un
  correo existente devuelve `409` solo porque `allow_registration` es un escenario de instancia
  propia; si se despliega abierta al público, se recomienda `ALLOW_REGISTRATION=false`.

---

## 9. Privacidad: qué se registra y qué no

Esto es información financiera personal. El criterio es: **en el log entra lo que hace falta
para depurar un fallo, no lo que hace falta para reconstruir la vida de alguien.**

**Sí se registra** (formato `%(asctime)s %(levelname)-7s %(name)s | %(message)s`, ya configurado
en `main.py`, más `request_id` y `user_id`):

| Dato | Nivel | Por qué |
|---|---|---|
| `request_id`, método, ruta **con los `{id}` como plantilla** (`/invoices/{id}/confirm`), código, duración en ms, tamaño de la respuesta | INFO | Es la traza de acceso. La ruta plantilla evita que los UUID llenen el log |
| `user_id` (UUID) | INFO | Permite correlacionar sin identificar a la persona |
| Resultado de la extracción: método (`tabla`/`texto`/`ocr`), páginas, número de líneas, confianza — tal y como ya lo hace `extraer_factura()` | INFO | Es el dato que dice si el extractor está funcionando |
| Códigos de error de negocio (`codigo`, no el `mensaje` formateado con datos) | WARNING | Detecta reglas que se incumplen a menudo |
| Traza completa de una excepción no controlada, sin cuerpo de la petición | ERROR | Ya lo hace el manejador `_inesperado` de `errors.py` |
| Eventos de seguridad: login correcto/fallido (con el **hash** del email, nunca el email), bloqueo por intentos, CSRF inválido, reutilización de refresco, `413`/`415`/`422` en subidas | WARNING | Auditoría mínima imprescindible |
| Operaciones destructivas: fusión de temáticas/productos, borrado de cuenta, `rollback` de importación, `unconfirm`; con identificadores y **recuentos**, sin contenido | INFO | Sin esto es imposible explicar «¿dónde han ido mis datos?» |
| Métricas de rendimiento: consultas por petición, duración de la extracción, tamaño de la cola | DEBUG/INFO | Detectar el N+1 y la saturación |

**Nunca se registra, en ningún nivel, ni en producción ni en desarrollo:**

| Dato | Motivo |
|---|---|
| Contraseñas, en claro o hasheadas; el cuerpo de `/auth/*` | Evidente, y el hash también es material sensible |
| Tokens de acceso, de refresco o CSRF; cabeceras `Cookie`, `Set-Cookie`, `Authorization`, `X-CSRF-Token` | Un log con un refresco válido es una sesión regalada. El filtro de logging los redacta por nombre |
| `texto_crudo` de la factura y cualquier fragmento del texto extraído | Es la factura entera: dirección, NIF, consumo, cuenta bancaria del domiciliado |
| Descripciones de transacción, notas, nombres de comercio, nombres de producto | Es el detalle del gasto: dónde compra, qué consume, con quién |
| **Importes concretos**, saldos, patrimonio neto, ingresos | No hace falta el importe para depurar; y si hace falta, se pide reproducir con datos de prueba. Los mensajes de error del extractor que incluyen importes (`"Las líneas suman X €…"`) van al campo `warnings` de la factura, que es del usuario, **no al log** |
| Correo electrónico en claro | Se registra `sha256(email)[:12]` cuando hace falta correlacionar intentos de login |
| IP completa | Se guarda truncada (`192.168.1.x`) y solo en eventos de seguridad y sesiones |
| Contenido de los ficheros subidos, del CSV importado o de las exportaciones | Ídem que la factura |
| El JSON de las peticiones y de las respuestas | Aunque sea tentador para depurar. En desarrollo se puede activar con `DB_ECHO`/nivel DEBUG **bajo consentimiento explícito**, jamás por defecto |

Detalles de implementación:

- Un `logging.Filter` en `core/logging.py` redacta por nombre de campo (`password`, `token`,
  `cookie`, `csrf`, `authorization`, `secret`, `amount`, `note`, `description`, `texto_crudo`,
  `email`) cualquier valor que se cuele en un `extra` o en un `%s`. Es una red, no una excusa
  para no pensar antes de registrar.
- `settings.db_echo` **debe** ser `false` en producción: `echo=True` escribe los parámetros
  ligados, es decir, todos los importes y descripciones.
- Los mensajes de error que llegan al usuario (`mensaje`, `detalles`, `warnings`) pueden
  contener sus propios datos: son suyos y los necesita. Pero esos textos **no** se copian al log.
- Retención: los logs son responsabilidad del despliegue (EasyPanel/Docker). La aplicación no
  guarda un historial de auditoría con contenido; solo con identificadores y recuentos.

---

## 10. Procesado en segundo plano

El despliegue es **un único contenedor** (ventaja competitiva frente al Docker + BD + colas de
Firefly III, según `docs/competencia.md`), así que no hay Celery ni Redis. El contrato solo exige
que las tareas pesadas no bloqueen la petición:

- **Cola en proceso** (`workers/queue.py`): `asyncio.Queue` con N trabajadores arrancados en el
  `lifespan` de `app/main.py`. El trabajo intensivo de CPU (pdfplumber, PyMuPDF, Tesseract,
  bcrypt) se ejecuta con `run_in_executor` sobre un `ThreadPoolExecutor` acotado, para no
  bloquear el bucle de eventos.
- **Estado en base de datos, no en memoria**: `invoices.status`, `imports.status`,
  `exports.status`. Si el contenedor se reinicia a mitad, al arrancar se recuperan las tareas
  que quedaron en `processing` y se reencolan (o se marcan `failed` tras 3 intentos). Por eso
  `GET …/status` consulta la base de datos y no un objeto en memoria: sobrevive al reinicio.
- **Tareas periódicas** (`workers/scheduler.py`, bucle con `asyncio.sleep`): materializar
  recurrentes con `auto_post`, recalcular alertas del periodo, detectar suscripciones, componer
  el digest, purgar `jti` caducados, borrar exportaciones de más de 7 días, borrar
  `texto_crudo` de más de 30 días y limpiar temporales huérfanos.
- Si en el futuro hace falta escalar a varios procesos, la cola se sustituye sin tocar el
  contrato: los clientes solo conocen `202` + `GET …/status`.

---

## 11. Cobertura del catálogo funcional

Comprobación de que la API cubre **todos los P0 y P1** de `docs/competencia.md`.

| ID | Funcionalidad | Prioridad | Endpoints |
|---|---|---|---|
| F-01 | Ingreso mensual editable | P0 | `PUT /budgets/{period}`, `GET /budgets/{period}/incomes`, `POST /transactions` (`kind=income`) |
| F-02 | Barra de presupuesto por temática | P0 | `GET /budgets/{period}`, `PUT/PATCH …/allocations` |
| F-03 | Temáticas anidables multinivel | P0 | `GET /categories/tree`, `POST /categories`, `POST /categories/{id}/move` |
| F-04 | Fusión con reasignación de histórico | P0 | `POST /categories/merge/preview`, `POST /categories/merge`, `POST /categories/merges/{id}/undo` |
| F-05 | Renombrado sin romper histórico | P0 | `PATCH /categories/{id}` |
| F-06 | Ocultar temática en vez de borrar | P0 | `POST /categories/{id}/archive` · `/unarchive` |
| F-07 | Registro rápido de gasto | P0 | `POST /transactions` |
| F-08 | Splits | P0 | `PUT /transactions/{id}/splits`, `splits` en `POST /transactions` |
| F-09 | Transferencias entre cuentas | P0 | `POST /transfers`, RN-21 |
| F-10 | Tipos de cuenta | P0 | `POST /accounts` (`type`), `GET /accounts/summary` |
| F-11 | Patrimonio neto | P0 | `GET /accounts/summary`, `GET /reports/net-worth` |
| F-12 | Subida de factura PDF | P0 | `POST /invoices`, `GET /invoices/{id}/file` |
| F-13 | Extracción de líneas | P0 | `GET /invoices/{id}/status`, `GET /invoices/{id}/lines` |
| F-14 | Revisión y corrección manual | P0 | `PATCH /invoices/{id}`, `PATCH/PUT …/lines`, `POST …/confirm` (§3.13) |
| F-15 | Historial de precio por producto | P0 | `GET /products/{id}/prices`, `GET /prices`, `GET /reports/product-price` |
| F-16 | Detección de subida de precio | P0 | `GET /reports/price-increases`, alertas `product_price_increase` |
| F-17 | Línea de factura → temática | P0 | `PATCH …/lines/{line_id}` (`category_id`), `POST …/link-product` (`set_default_category`) |
| F-18 | Desglose de gasto por temática | P0 | `GET /reports/spending-by-category` |
| F-19 | Comparativa mes a mes | P0 | `GET /reports/monthly-comparison` |
| F-20 | Aviso de sobrepaso | P0 | `GET /alerts` (`budget_overspent`, `budget_near_limit`), `overspent` en `GET /budgets/{period}` |
| F-21 | Adjuntos en transacciones | P0 | `POST /transactions/{id}/attachments`, `GET /attachments/{id}/content` |
| F-22 | Login propio | P0 | §3.1 completo |
| F-23 | Modo oscuro | P0 | `PATCH /users/me` (`theme`), `GET /settings` |
| F-24 | PWA instalable | P0 | Frontend; la API solo aporta `GET /meta` |
| F-25 | Importación CSV | P0 | `POST /imports`, `PUT …/mapping`, `GET …/preview`, `POST …/commit` |
| F-26 | Rollover | P1 | `GET /budgets/{period}/rollover`, `POST /budgets/{period}/close`, `rollover_enabled` |
| F-27 | Reglas de auto-categorización | P1 | §3.11 completo |
| F-28 | Recurrentes/programadas | P1 | `POST /recurring`, `POST /recurring/{id}/post`, `GET /recurring/upcoming` |
| F-29 | Detección de suscripciones | P1 | `GET /recurring/detected`, `POST …/confirm`, `GET /reports/subscriptions` |
| F-30 | Alerta de subida en recurrente | P1 | `GET /recurring/{id}/price-history`, alertas `recurring_price_increase` |
| F-31 | Fondos objetivo | P1 | §3.15 completo |
| F-32 | Reconciliación de cuenta | P1 | `POST /accounts/{id}/reconcile`, `GET …/reconciliations` |
| F-33 | Importación OFX/QIF | P1 | `POST /imports` (`format`) |
| F-34 | Detección de duplicados | P1 | `GET /transactions/duplicates`, `POST /transactions/{id}/merge`, `GET /invoices/{id}/duplicates`, RN-45 |
| F-35 | Etiquetas libres | P1 | §3.10, `tag_id` en filtros, `POST /transactions/bulk-tag` |
| F-36 | Informe de cash flow | P1 | `GET /reports/cash-flow` |
| F-37 | Top comercios | P1 | `GET /reports/top-payees` |
| F-38 | Comparador de precio entre proveedores | P1 | `GET /products/{id}/comparison` |
| F-39 | Fuzzy-matching de producto | P1 | `GET /products/suggestions`, `POST /products/merge`, `POST /products/{id}/split` |
| F-40 | Plantillas de extracción por proveedor | P1 | `/invoices/templates*`, `POST /invoices/{id}/reprocess` |
| F-41 | Deuda/préstamo con calendario | P1 | `GET /accounts/{id}/amortization`, campos de deuda en `AccountIn` |
| F-42 | Búsqueda y filtros combinables | P1 | `GET /transactions` (§3.5), `/settings/views` |
| F-43 | Exportación/backup | P1 | §3.18 completo |
| F-44 | Notas/memo | P1 | `note` en transacciones, splits, facturas y recurrentes |
| F-45 | Digest semanal/mensual | P1 | `GET /alerts/digest`, `PUT /settings/notifications` |
| F-46 | Atajos de teclado | P1 | Frontend; requiere alta en una sola llamada: `POST /transactions` |
| F-47 | Saldo proyectado a fin de mes | P1 | `GET /reports/projected-balance`, `GET /recurring/upcoming` |
| F-48 | Detección de gasto inusual | P1 | `GET /reports/anomalies`, `is_anomaly`, alertas `unusual_spending` |
| F-49 | Recordatorio de vencimiento | P1 | `GET /recurring/upcoming`, alertas `upcoming_charge` |
| F-50 | Onboarding guiado | P1 | `/onboarding/status`, `/onboarding/seed`, `/onboarding/complete` |

**P2 con soporte ya previsto en el contrato** (sin coste añadido, porque el modelo lo permite):
F-52 multi-divisa (`currency` en cuentas, transacciones y precios), F-53 Sankey (se compone en
cliente con `GET /reports/cash-flow`), F-57 multiusuario (todo cuelga de `user_id`), F-58 API
propia documentada (**esto es la API**, con OpenAPI en `/api/openapi.json`), F-59 reglas en texto
(`POST /rules/parse`), F-60 cesta de la compra (`/baskets`, `GET /reports/basket`).
**P2 fuera de esta versión**: F-51 bandeja de facturas por email, F-54 forecast a años vista,
F-55 «disponible para gastar hoy», F-56 *age of money*.

---

## 12. Correspondencia con el modelo de datos

El contrato y la persistencia son capas distintas y **no tienen por qué llamar igual a las
cosas**: la API usa el vocabulario del cliente (rutas en plural, campos que el formulario
teclea) y `docs/arquitectura/modelo-datos.md` usa el de PostgreSQL. Esta tabla evita que la
diferencia se lea como una contradicción, y es la referencia para la capa
`repositories/`.

| Concepto del contrato (§3, §4) | Tabla/columna del modelo de datos | Nota |
|---|---|---|
| Propiedad de los datos (RN-01) | `household_id` (con `households` / `household_members`) | En un despliegue de un solo usuario hay un hogar por usuario. RN-01 se lee como «filtrar por el hogar de la sesión»; el contrato no expone el concepto hasta que F-57 (multiusuario, P2) lo necesite |
| `amount` (positivo) + `kind` | `transactions.amount` **firmado** + `kind` | §1.7 y RN-26: la API traduce en el borde. `signed_amount` de la respuesta es la columna tal cual |
| `path` de `CategoryOut` | `categories.path_ids UUID[]` (+ `depth`, `sort_key`) | §7.3. El array es lo indexado; la cadena es su proyección para el cliente |
| `PriceOut` / `/prices` | `product_prices` | «Observación de precio» es el nombre de dominio; la tabla usa el nombre corto |
| `RuleOut` / `/rules` | `categorization_rules` | — |
| `InvoiceTemplateOut` / `/invoices/templates` | `extraction_templates` | — |
| `CategoryMerge*` / `ProductMerge*` | `merge_operations` + `merge_operation_changes` | Un único mecanismo de fusión y de deshacer (RN-20, RN-65) para temáticas, comercios, etiquetas y productos |
| `AttachmentOut` (transacción o factura) | `attachments` | El PDF de la factura y el adjunto suelto comparten tabla y endpoint de descarga |
| `GoalMovementOut` | `goal_contributions` | Una retirada es una contribución negativa (RN-52 la acota) |
| `ImportOut` / `ImportRowOut` | `import_batches` / `import_rows` | — |
| `RecurringOut` | `recurring_rules` + `recurring_occurrences` | RN-36 es la unicidad `(recurring_id, occurrence_date)` de la tabla de ocurrencias |
| `NetWorthOut` | `net_worth_snapshots` + `account_valuations` | El informe lee la serie ya consolidada; el `as_of` puntual se calcula al vuelo |
| `DigestOut` | `digest_runs` | — |
| Agregados de informes | vistas `vw_movement_lines`, `vw_account_balances`, `vw_category_tree`, materializada `mv_product_price_monthly` | §7.1: los informes consultan las vistas, nunca reconstruyen el desglose en Python |

**Dos enums donde el contrato es más rico que el borrador del modelo de datos**, y hay que
alinearlos antes de escribir la migración (el contrato es el que ve el cliente, así que manda):

- `invoices.status`: el contrato necesita **cinco** estados por RN-46 y RN-49 —
  `processing`, `pending_review`, `failed`, `confirmed`, `discarded`—. La correspondencia con el
  borrador es `pending`/`processing` → `processing`, `extracted` → `pending_review`,
  `reviewed` → `confirmed`, `error` → `failed`, y falta añadir `discarded` (una factura
  descartada no puede quedar indistinguible de una confirmada, o `confirm` dejaría de ser
  irrepetible).
- `imports.status`: `analyzing`, `needs_mapping`, `ready`, `committed`, `failed`, `discarded`
  frente a `preview`/`running`/`done`/`reverted`/`failed`. `needs_mapping` es imprescindible
  porque es el estado que hace que la UI pida el mapeo de columnas (RN-67), y `reverted` se
  modela mejor como `committed` + `rollback_at`, para no perder que hubo un commit.



