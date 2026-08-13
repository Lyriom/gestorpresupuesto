# Auditoría del backend

Revisión de seguridad y corrección del backend (`backend/app`, 22.755 líneas, 222
endpoints) hecha desde fuera del equipo que lo escribió. Punto de partida: 663
pruebas en verde, `ruff` limpio y PostgreSQL con las migraciones aplicadas. El
objetivo era justamente lo que las pruebas verdes no dicen.

Al terminar: **683 pruebas en verde** (663 existentes + 20 nuevas en
`backend/tests/test_auditoria.py`), `ruff format` y `ruff check` limpios.

## Resumen ejecutivo

**38 hallazgos** (2 críticos, 7 altos, 18 medios, 11 bajos) y 18 sospechas sin
reproducir. **15 arreglados** —los 2 críticos, 5 de los altos, 6 medios y 2
bajos—, cada uno con su prueba en `backend/tests/test_auditoria.py`; se verificó
una por una que **falla con el código anterior** (la única excepción está marcada
como tal en su fila). Los 23 restantes quedan documentados sin tocar.

Lo que hay que saber si solo se leen tres párrafos:

1. **La tercera capa de tenencia no existe.** La migración
   `20260813_0934_row_level_security.py` crea las políticas pero deja fuera
   `FORCE ROW LEVEL SECURITY`, y la aplicación se conecta con el rol propietario
   de las tablas, que en PostgreSQL **está exento de sus propias políticas sin
   `FORCE`**. La condición que la propia migración se puso para activarlo («cuando
   la dependencia de sesión llame a `set_config`») ya se cumple desde
   `deps.py:150`. Hoy solo protegen el filtro `household_id` de cada consulta y
   las 44 claves ajenas compuestas. No se arregla desde el código: hace falta el
   rol `app_rw` del despliegue (ver «Pendiente de despliegue»).
2. **Dos escrituras cruzadas entre hogares, reales y explotables**, justamente en
   las dos columnas que **no** pueden tener clave ajena compuesta:
   `transactions.goal_id` (`POST /transfers`) e
   `invoices.extraction_template_id` (`POST /invoices`, `POST /invoices/{id}/reprocess`).
   Las dos devolvían 201/202 y dejaban la fila apuntando al hogar vecino.
   Arregladas.
3. **El deshacer de una fusión de varios orígenes restauraba mal el dinero.** El
   diario se aplicaba con `max()` sobre el **texto** del importe y con
   `UPDATE ... FROM` sin desempate; con dos orígenes la misma fila queda anotada
   dos veces y se restauraba un estado intermedio. En el caso de los repartos el
   fallo era determinista: la transacción quedaba descuadrada, el invariante de la
   base tumbaba la operación y **la fusión ya no se podía deshacer nunca** (500
   permanente). Arreglado con desempate por `seq`.

Lo que está sólido y no hay que tocar: el helper `del_hogar()` y los `_x_o_404()`
de cada router filtran por hogar sin una sola excepción en los 222 endpoints;
`verificar_csrf` está en **todos** los endpoints mutantes (barrido automático de
los 118 `POST`/`PATCH`/`PUT`/`DELETE`: cero omisiones; `register` y `login` no
pueden usarlo porque la cookie aún no existe y comprueban el origen en su lugar);
el cuadre de splits es exacto y sin tolerancia en las tres capas (esquema Pydantic,
servicio y `ck_transactions_split_invariant`); los importes viajan como cadena
decimal y ni un campo de dinero está tipado como `float`; la fusión es atómica de
verdad (ningún `commit` dentro de `services/fusion.py`); y las rutas de fichero
las calcula siempre el servidor, con comprobación antitraversal.

## Hallazgos

### Arreglados

| Gravedad | Fichero:línea | Qué falla | Cómo se explota o se manifiesta | Estado |
|---|---|---|---|---|
| **Crítica** | `app/services/fusion.py:1088` (`SQL_DESHACER_SPLITS`) | El diario de repartos se aplicaba con `max(old_value #>> '{}')`, un máximo **lexicográfico sobre el texto** del importe, no el valor original | Transacción de −600,00 € repartida entre destino (−40), origen A (−20) y origen B (−540); `POST /categories/merge` con los dos orígenes; `undo` → el superviviente vuelve a −60,00 en vez de −40,00, el reparto suma −620,00 ≠ −600,00, salta `ck_transactions_split_invariant` y el `undo` responde 500 **para siempre**: la fusión ya no es reversible | Arreglado (desempate por `seq`) |
| **Crítica** | `app/api/v1/transferencias.py:348` | `datos.goal_id` llegaba crudo a las dos patas. `transactions.goal_id` es la única FK de `transactions` **sin** `fk_tenencia` (`goals` no declara `UNIQUE (household_id, id)`) | `POST /api/v1/transfers` con `goal_id` = fondo del hogar B → **201** y las dos patas del hogar A apuntando al fondo de B. Si B borra el fondo, el `SET NULL` alcanza las transacciones de A; y el par 500/201 es un oráculo de existencia de identificadores | Arreglado (404) |
| **Alta** | `app/api/v1/facturas.py:808` y `:2250` | `template_id` no se validaba (sí `payee_id` y `account_id`, justo encima). `extraction_templates.household_id` es **nulable** —las plantillas de serie son de la instalación—, así que esa tabla no puede tener FK compuesta y no había ninguna otra defensa | `POST /api/v1/invoices` (multipart) con `template_id` = plantilla del hogar B → **202** y la factura persistida apuntando a ella; lo mismo por `POST /invoices/{propia}/reprocess`. Con la extracción por plantilla activa, los PDF de A se interpretarían con las reglas de B | Arreglado (404, aceptando las plantillas de la instalación) |
| **Alta** | `app/api/deps.py:217` (`cliente_de`) + `app/api/v1/auth.py:139` (`exigir_cuota`) | Se creía `X-Forwarded-For` viniera de donde viniera, y esa IP es la clave del cubo de fichas. §2.4 lo prohíbe explícitamente: «solo si la petición llega de un proxy de confianza configurado» | Una cabecera distinta en cada intento da un cubo nuevo: el tope de 10 logins/minuto, 5 altas/hora y 60 refrescos/hora **no existía**. Deja el barrido de contraseñas contra muchas cuentas sin ningún freno (el bloqueo por credencial solo protege cuenta a cuenta) | Arreglado (`TRUSTED_PROXIES`, ver «Nota de despliegue») |
| **Alta** | `app/services/fusion.py:833` | El diario anotaba `archived_at = None` como valor previo, **cableado**, en lugar del que tenía la temática | Archivar una temática, fusionarla y deshacer la devuelve **activa** aunque estuviera archivada antes, con sus hijas archivadas: un árbol que la API no sabe producir por ningún otro camino | Arreglado |
| **Alta** | `app/services/fusion.py:1169` (`deshacer`) | Se aceptaba deshacer una operación **hija** de una fusión múltiple: solo se filtraba por hogar y tipo | `POST /categories/merges/{hija}/undo` revierte media fusión y deja la madre en `done` con `can_undo=true`; el `undo` de la madre vuelve a insertar filas ya restauradas → 500. Explotabilidad baja (los ids de las hijas no se publican), corrección clara | Arreglado (404) |
| **Alta** | `app/api/v1/cuentas.py:868` (`amortizacion`) | El tipo de interés se cuantizaba con el redondeo **del dinero**: `_dinero(annual_rate)`. `annual_rate` es `Numeric(7,4)` | 150.000 € al 2,7550 % a 240 meses: el tipo pasa a 2,76 %, la cuota sale 813,99 € en vez de 813,62 € y el cuadro acumula **88,93 € de intereses inventados**. La respuesta se contradecía: devolvía `interest_rate = 2,7550` con un cuadro calculado al 2,76 % | Arreglado |
| **Media** | `app/services/fusion.py:1137` (`_sql_revertir_columna`) | `UPDATE ... FROM merge_operation_changes` sin desempate. Con varios orígenes hay dos anotaciones candidatas para la misma fila y PostgreSQL no promete cuál usa | La asignación de presupuesto del destino podía volver a un importe intermedio (500,00 € en vez de 320,00 €), y con ella el total asignado del mes. La prueba fija el invariante pero **no reproduce el fallo**: con pocas filas el plan elige la correcta por suerte | Arreglado (`DISTINCT ON … ORDER BY seq`) |
| **Media** | `app/api/v1/cuentas.py:653` (`saldo`) | `pending_recurring` sumaba **todos** los vencimientos pendientes del hogar: faltaba el join con `recurring_rules`, que es donde vive la cuenta | `GET /accounts/{id}/balance` devolvía el mismo pendiente para todas las cuentas del hogar, así que la proyección de saldo de F-47 estaba mal en cuanto hubiera más de una cuenta | Arreglado |
| **Media** | `app/services/fusion.py:393` (`previsualizar`) | `allocated_total` ya incluye las asignaciones del destino y se acumulaba **una vez por origen** | `POST /categories/merge/preview` con dos orígenes infla `allocations_merged` (880,00 € donde la fusión real deja 560,00 €). Es la cifra del diálogo de confirmación: el usuario decide sobre un número falso | Arreglado (una sola consulta sobre el conjunto) |
| **Media** | `app/api/v1/productos.py:365`, `:1597`, `:2009`, `:2065` | `default_category_id` y `payee_id` entraban sin comprobar el hogar. La FK compuesta lo impedía, pero en el `COMMIT` | `POST /products`, `PATCH /products/{id}`, `POST /prices`, `PATCH /prices/{id}` con un id de otro hogar → **500 `error_interno`** en lugar del 404 que manda RN-02, y el aislamiento dependía en exclusiva de una restricción de la base | Arreglado (404) |
| **Media** | `app/services/numeros.py:172`, `app/services/formato.py:31`, `app/api/v1/facturas.py:1315`, `app/services/extraccion_pdf.py:73` | Dinero cuantizado con el redondeo **bancario** (el defecto de Python), no HALF_UP | `parsear_importe("12,345")` daba 12,34 € (entra por facturas y por CSV bancario); `euros(2,665)` se leía «2,66 €» en los avisos; 10 kWh a 0,2165 €/kWh se guardaban como 2,16 € en vez de 2,17 €. PostgreSQL redondea al alza al guardar en `numeric(14,2)`, así que el mismo importe salía distinto según quién lo cuantizara | Arreglado en los cuatro sitios; **quedan ~30** (ver pendientes) |
| **Media** | `app/api/v1/transacciones.py:1604` (`_nombre_saneado`) | El saneado de los adjuntos era propio y mucho más laxo que `facturas.sanear_nombre()`: sin NFKC, sin lista blanca, recortando a 200 en vez de 120 y sin nombres reservados de Windows (RN-77) | El nombre acaba dentro de `Content-Disposition`; `%`, `;` y `"` pasaban tal cual. Un cliente que no sea un navegador puede mandar una comilla sin codificar y el cliente que descarga acaba interpretando parámetros que no escribió el servidor | Arreglado (mismas reglas que las facturas) |
| **Baja** | `app/api/v1/transacciones.py:1722` (`descargar_adjunto`) | Faltaban `X-Content-Type-Options: nosniff` y `Content-Security-Policy: sandbox`, que §8.3.8 exige en la descarga | Un PDF servido `inline` (el valor por defecto) se abre en el origen de la aplicación sin sandbox | Arreglado (las dos cabeceras) |
| **Baja** | `app/api/v1/auth.py:143` y `:489` | Los 429 salían sin `Retry-After`, que §2.4 pide. El comentario del código decía que `AppError` no transporta cabeceras, y sí lo hace desde `errors.py:37` | El cliente no sabe cuánto esperar y reintenta a ciegas | Arreglado (limitador y bloqueo por credencial) |

### Pendientes

Ninguno se ha tocado: o no he conseguido demostrarlo con una prueba, o el arreglo
es una decisión de diseño o de despliegue que no me corresponde tomar.

| Gravedad | Fichero:línea | Qué falla | Cómo se manifiesta | Estado |
|---|---|---|---|---|
| **Alta** | `alembic/versions/20260813_0934_row_level_security.py:9-20` | La tercera capa de tenencia está **inerte**: políticas creadas, `FORCE ROW LEVEL SECURITY` no, y la aplicación conecta como propietaria | Cualquier consulta a la que le falte el filtro `household_id` y que no esté cubierta por una FK compuesta es explotable directamente. Además `deps.py:150` fija `app.household_id` con `set_config(..., true)`, que es **transaccional**: hay endpoints que `commit()` y siguen leyendo (`categorias.py:456`, `objetivos.py:391`, `presupuestos.py:671`), así que encender `FORCE` sin tocar eso deja esas lecturas en cero filas | Pendiente (necesita el rol `app_rw` y una revisión de las lecturas post-`commit`) |
| **Alta** | `app/services/fusion.py:1137-1250` (reversión) | El deshacer pisa sin condición lo que el usuario cambió **después** de la fusión: la columna `new_value` se guarda (`:390`) y no se usa jamás, y `SQL_CONFLICTO_POSTERIOR` solo detecta otras fusiones | Fusionar A→D, subir la asignación de D de 500 a 700 con `PATCH /budgets/.../allocations`, deshacer → D vuelve a 320 y reaparece la de A: los 200 € añadidos desaparecen y el total asignado del mes cambia. Con splits editados a mano o con la transacción borrada, el `undo` responde 500 | Pendiente (comparar con `new_value` y responder 409 es un cambio de contrato de RN-20) |
| **Media** | `app/services/fusion.py:1160-1250` | El deshacer no comprueba el árbol antes de resucitar la lápida, al contrario que `desarchivar` (`categorias.py:869`), que sí llama a `_exigir_nombre_libre` | Fusionar «Compra semanal»→«Supermercado», crear una temática nueva con el nombre libre (el índice único excluye lápidas, así que se permite) y deshacer → violación del índice → **500 `error_interno`** en vez de 409, y la fusión se queda sin poder deshacerse | Pendiente |
| **Media** | `app/services/fusion.py:646-666` (`SQL_REPARENTAR_HIJAS`) | La fusión recuelga las hijas sin validar RN-11 (profundidad ≤ 6), mientras `mover` (`categorias.py:755`) y `crear` sí lo hacen | Con el destino más profundo que el origen, la misma geometría da 422 `profundidad_maxima` por `move` y 200 por `merge`; si el salto pasa de 8 niveles, `refresh_category_paths` incumple `ck_categories_depth` y sale un 500 después de haberlo hecho todo | Pendiente |
| **Media** | `app/services/fusion.py:700-709` | RN-20 dice que `?force=true` **reabre** el periodo cerrado, recalcula y lo vuelve a cerrar; el código solo avisa y escribe dentro del periodo cerrado sin tocar `closed_at` ni recalcular el arrastre en cascada | Si el `rollover_mode` de origen y destino difiere, el `carryover_in` del mes siguiente ya escrito no se recalcula y el disponible queda desalineado hasta que alguien reabre y recierra a mano | Pendiente |
| **Media** | `app/services/fusion.py:119-130` y `app/schemas/categoria.py:137` | `keep_source_names_as_alias` se acepta, se guarda en `options` y **nunca se usa**: RN-19 («los nombres antiguos quedan como alias buscables») no está implementado. `collapse_duplicate_splits` no existe en el esquema de entrada, así que el reparto siempre se colapsa | Buscar por el nombre viejo de una temática fusionada no encuentra nada; la casilla de §4.4 no tiene efecto | Pendiente |
| **Media** | `app/api/v1/informes.py:1183`, `:1199`, `:1210` | El coste anual de una suscripción se deriva del **mensual ya redondeado** | Una suscripción semanal de 10,00 €: mensual 43,33 € → `annual_cost` 519,96 € en lugar de 520,00 €, y `annual_total` multiplica por 12 la suma de mensuales redondeados, así que el error crece con el número de suscripciones | Pendiente |
| **Media** | `app/api/v1/informes.py:1278` | Prorrateo del presupuesto restante entre cuentas sin imputar el resto: `(restante / len(cuentas)).quantize(CENTIMO)` | 100,00 € entre 3 cuentas reparte 99,99 €. Es el único prorrateo del proyecto que no cuadra; `_repartir()` (`facturas.py:1654`) y `reparto_sugerido()` sí lo hacen | Pendiente |
| **Media** | `app/api/v1/importaciones.py:822` (`corregir_fila`) | La huella de duplicados se calcula con el `Decimal` sin cuantizar, y `calcular_huella` lo interpola como texto | Corregir el importe de una fila enviando `"12.3"` en lugar de `"12.30"` produce una huella distinta y **el duplicado deja de detectarse** al reimportar el extracto. Los otros dos caminos de análisis (`importacion.py:386`, `importaciones.py:439`) sí cuantizan | Pendiente |
| **Media** | `app/api/v1/facturas.py:1682` (`_repartir`) | `defecto or repartos[0].category_id` con la lista vacía | Confirmar una factura con **todas** las líneas excluidas y sin `default_category_id` → `IndexError` → 500 en lugar de un 422 explicado | Pendiente |
| **Media** | ~30 sitios (`services/precios.py:85,122,197,274,296,327`; `api/v1/informes.py` (≈35); `productos.py:660,721,741`; `recurrentes.py:226,239,670,995`; `comercios.py:104,547`; `facturas.py:271,631,1169,1322,1679,1735`; `importacion.py:386`; `importaciones.py:439`) | `quantize()` sin `rounding=`, o sea redondeo bancario, sobre dinero | Mismo fallo que el ya arreglado: el empate baja donde la base sube. Lo correcto es un único cuantizador de dinero compartido, y esa es una decisión de diseño transversal que no toco a mitad de auditoría | Pendiente |
| **Media** | `app/api/v1/objetivos.py:82` | `required_monthly` se redondea con HALF_UP | 100,00 € en 3 meses → 33,33 €; aportando eso tres meses se ingresan 99,99 € y el objetivo **no se alcanza**, pero `is_on_track` dice que sí. Un «cuánto necesito aportar» se redondea hacia arriba (`ROUND_CEILING`) | Pendiente |
| **Media** | `app/api/v1/facturas.py:895` (`listar`) | N+1 en el listado: `respuesta_factura()` por factura hace `_lineas_de` + `get(Payee)`, y con `include=lines` dos consultas más | `GET /invoices?size=50` son ~150 consultas por página, ~200 con líneas. Con 40 líneas, el detalle (`:1063-1090`) suma otro `get(Product)` + `get(Category)` por línea. Lo mismo, más pequeño, en `presupuestos.py:851` (un `get(Category)` por asignación) y `usuarios.py:158-170` | Pendiente |
| **Media** | `app/main.py:66-79` | Falta la CSP que pide §8.2 (`default-src 'self'; …; object-src 'none'; frame-ancestors 'none'`). Están las otras cinco cabeceras | Sin `object-src 'none'` un PDF se puede incrustar con un plugin, que es justo lo que la sección quiere evitar | Pendiente |
| **Baja** | `app/api/v1/auth.py:487` | Un correo bloqueado responde 429 y uno inexistente 401, así que el código de estado revela si la cuenta existe (el **mensaje** sí es genérico, como pide §2.4) | Cinco intentos fallidos con un correo candidato: 429 en el sexto = existe; 401 = no existe. Antes del arreglo del limitador hacía falta esquivarlo con `X-Forwarded-For`; ahora hace falta esperar la ventana | Pendiente (comportamiento avalado por §2.4; se anota porque la enumeración sigue siendo posible) |
| **Baja** | `app/api/deps.py:63` (`usuario_actual`) | El token de acceso solo se valida por firma: no se comprueba `password_changed_at` ni la revocación | Tras `logout-all`, `change-password` o revocar una sesión, un token de acceso robado sigue sirviendo hasta 30 minutos. §2.3 promete «revocación inmediata en servidor» | Pendiente (compromiso conocido del diseño; se cerraría comparando `iat` con `password_changed_at`) |
| **Baja** | `app/api/v1/auth.py:530` (`refrescar`) | §2.4 pide 30 refrescos/hora **por familia de sesión** y solo hay límite por IP. Y dos refrescos simultáneos con el mismo token pueden pasar los dos el `revoked_at is None` | La detección de reutilización (RN-04) se puede esquivar con una carrera; no he conseguido provocarla de forma fiable en pruebas | Pendiente |
| **Baja** | `app/api/v1/objetivos.py:115` y `:423` | `goal_contributions` se consulta solo por `goal_id`, sin `household_id`, y esa FK **no** es compuesta (`app/models/objetivo.py:89`) | Hoy no es explotable —el `goal_id` sale siempre de un `del_hogar()`—, pero es el sitio del proyecto donde no queda ninguna de las tres capas. Recomiendo añadir el filtro y `fk_tenencia("goal_contributions", "goal_id", …)` | Pendiente |
| **Baja** | `app/api/v1/productos.py:1368` (`_revertir_cambios`) | `UPDATE {tabla} SET {columna} = … WHERE id = :row_pk` sin `household_id`: el único UPDATE del proyecto sin filtro de hogar | El `row_pk` lo escribe el servidor en el diario y la operación padre sí se valida, así que no hay entrada por donde colar uno ajeno | Pendiente |
| **Baja** | `app/api/v1/importaciones.py:816` | `__payee_id` se guarda en `import_rows.raw` sin validar el hogar (el `category_id` de la línea de arriba sí se valida) | Inerte: el `commit` solo lee `__category_id` y `__note`. Se convierte en escritura cruzada el día que alguien conecte esa clave | Pendiente |
| **Baja** | `app/api/v1/ajustes.py:148` y `:247` | `GET /settings` y `GET /settings/notifications` crean y **confirman** una fila de `saved_views` | Un `GET` escribe, y lo hace también un miembro de solo lectura. No es un problema de tenencia, pero rompe la lectura pura y con dos peticiones simultáneas puede chocar | Pendiente |
| **Baja** | `app/api/v1/usuarios.py:152-176` (`borrar_cuenta`) | Recorre todas las pertenencias y, si el llamante es el último miembro de un hogar, borra el hogar entero, incluso siendo `viewer` | Requiere que el `owner` se haya ido antes; es un borde de autorización, no de tenencia | Pendiente |
| **Baja** | `app/services/fusion.py:500-512` (`SQL_COLAPSAR_SPLITS`) | El colapso de repartos borra la fila sobrante y con ella el `invoice_line_id`: se pierde la trazabilidad línea de factura → reparto (solo recuperable deshaciendo). Además no renumera `line_number` (deja huecos), no toca `sort_order` al recolgar hijas (dos hermanas pueden empatar y el orden del árbol deja de ser determinista) y el `string_agg` de las notas no lleva `ORDER BY` | Pérdida de un enlace del histórico y orden no determinista en el selector de temáticas | Pendiente |

## Sospechas no confirmadas

No he conseguido reproducirlas y por eso no he tocado el código.

1. **Ciclo en el árbol por caché desfasada** (`app/services/fusion.py:245`). Todo
   el guardia de RN-18 se apoya en `path_ids`, que es caché y dentro de la
   transacción de fusión no se refresca entre orígenes ni entre niveles de
   recursión (`refresh_category_paths` se llama una sola vez al final). No he
   encontrado una combinación que cierre el ciclo, pero si existe el fallo sería
   **silencioso**: `ck_categories_no_cycle` se evalúa contra el `path_ids` viejo y
   `refresh_category_paths` recorre solo desde las raíces, así que un subárbol en
   ciclo simplemente no se visita. Merecería una prueba de propiedad del tipo
   «tras fusionar, ningún `depth`/`path_ids` difiere del recalculado».
2. **`Variacion.porcentaje` viaja por `float`** (`productos.py:564-606`) y de ahí
   se persiste (`:665`, columna `Numeric(7,2)`) y se decide una alerta
   (`facturas.py:1988`). El viaje `Decimal→float→str→Decimal` es exacto con dos
   decimales, así que no he construido un caso donde salga un número mal; es una
   violación de la convención «nunca `float`», no un error de cálculo demostrado.
3. **Umbral de alerta de precio con la proporción cuantizada**
   (`services/precios.py:85`): una subida real del 4,996 % se cuantiza a 0,0500 y
   dispara la alerta del 5 %. El umbral efectivo no es el que dice la constante,
   pero puede ser deliberado.
4. **`spent_pct` como `float`** (`presupuestos.py:315`): doble redondeo (el
   servicio ya cuantiza a dos decimales y aquí se divide por 100 en `float`). Para
   pintar la barra es aceptable; deja de serlo si el frontend compara ese valor
   con `budget_alert_pct` en el borde exacto.
5. **Importes que nacen de JSONB**: `alertas.py:151` (`Decimal(str(payload["amount"]))`
   hacia un campo de dos decimales → 500 si alguien guarda tres) y
   `services/reglas.py:125` (umbral de comparación de importes leído de JSONB, que
   pudo nacer como número JSON). Hoy todos los escritores guardan cadenas.
6. **Carrera de registro**: dos altas simultáneas en una instalación vacía pueden
   ver las dos `hay_usuarios = 0` y quedar las dos como administradoras.
7. **`_bloqueado()` antes de verificar la contraseña** (`auth.py:487`): la
   respuesta de una cuenta bloqueada no paga el bcrypt, así que queda una
   diferencia de tiempo medible; el 429 ya lo delata de forma más directa.
8. **`statement_timeout` en la fusión** (`fusion.py:886`): acota cada sentencia,
   no la transacción, aunque el comentario promete lo segundo.
9. **`SQL_DESACTIVAR_REGLAS_DUPLICADAS`** (`fusion.py:586`): particiona sobre
   **todas** las reglas activas del destino, no solo las movidas, así que puede
   desactivar un par duplicado que ya existía antes de la fusión (queda anotado en
   el diario, así que el deshacer lo restaura).
10. **`recurring_rules.template_splits` tras la fusión**: la reescritura JSONB
    (`fusion.py:783`) no colapsa duplicados, así que una plantilla puede quedar con
    dos repartos de la misma temática e incumplir RN-15 al materializarse.
11. **Exportación CSV** (`informes.py:248`): importes con punto decimal y
    delimitador `;`. Coherente con el contrato de la API, incoherente con un CSV
    es-ES abierto en Excel.
12. **`descargar_adjunto` por defecto `inline`** (`transacciones.py:1705`): §8.3.8
    pide `attachment` salvo petición explícita de `inline`. No lo he cambiado
    porque el frontend puede depender del valor por defecto para la vista previa, y
    la interfaz la está revisando otra persona.
13. **`etiquetas.py:207` y `:230`**: subconsultas de `transaction_tags` sin
    `household_id` y `tag_id` sin FK compuesta. Los `DELETE`/`UPDATE` que las
    consumen sí filtran por hogar, así que el peor efecto sería un `usage_count`
    contaminado; no he encontrado el camino para provocarlo.
14. **`productos.py:1948`**: `invoice_line_id` es la única FK de `product_prices`
    sin `fk_tenencia`, y esa consulta no filtra por hogar. Hoy es inalcanzable
    porque ningún esquema de entrada expone `invoice_line_id`.
15. **`ajustes.py:326`**: el nombre duplicado de una vista guardada se comprueba
    sin `household_id`, al contrario que las otras dos comprobaciones del mismo
    fichero. Efecto: un 409 espurio si el mismo usuario reutiliza un nombre en otro
    de sus hogares.

## Nota de despliegue

El arreglo del limitador añade un ajuste nuevo, `TRUSTED_PROXIES`, y su valor por
defecto es **no confiar en nadie** (se usa la IP de la conexión). Detrás de
EasyPanel o Traefik hay que declarar el par del proxy para que la IP real vuelva a
la lista de sesiones activas y a las claves del limitador:

```bash
TRUSTED_PROXIES=10.0.0.1        # una o varias, separadas por comas
TRUSTED_PROXIES=*               # solo si el contenedor no está expuesto directamente
```

No he tocado `.env.example` porque está fuera de `backend/`.

## Alcance de la revisión

Revisado: `deps.py`, `core/security.py`, `core/errors.py`, los 18 routers de
`api/v1` línea a línea (aislamiento entre hogares y cobertura de CSRF), los 39
modelos y las 4 migraciones (para saber qué garantiza de verdad la base),
`services/fusion.py` completo contra §4 del modelo de datos y las reglas RN-17 a
RN-20, y todo el uso del dinero en `app/` con ejemplos numéricos ejecutados.

Menos a fondo: rendimiento (los N+1 que aparecen arriba salen de un barrido
automático de accesos a la base dentro de bucles, no de medir con `EXPLAIN`); los
índices de los informes no los he contrastado uno a uno con las consultas; y la
extracción de PDF la he mirado solo en lo que toca al dinero, al límite de tamaño
y al saneado del nombre.
