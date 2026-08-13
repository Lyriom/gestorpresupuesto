# Auditoría de interfaz — Gestor de presupuesto

Revisión de `frontend/` contra `docs/ux/design-system.md` (v1.0) y
`docs/ux/flujos-y-wireframes.md` (v1.0).
Fecha: 13 de agosto de 2026 · Alcance: `frontend/` (no se ha tocado `backend/` ni el resto de `docs/`).

Verificación final: `npx vue-tsc -b --force` → **código de salida 0** ·
`npm run build` → **código de salida 0**, `✓ built`, sin avisos.

---

## 1. Resumen ejecutivo

La implementación es sólida y, en lo esencial, fiel a la especificación: los tokens de
`src/styles/tema.css` reproducen los 60 colores de ambos temas sin faltar ninguno, la
`BudgetBar` cumple su contrato ARIA casi entero (incluida la tabla gemela obligatoria), el
foco global, los enlaces de salto, `prefers-reduced-motion` y `prefers-contrast` están de
verdad, y no hay ni una sola clase de la paleta por defecto de Tailwind ni un `rgb()` a ojo
en todo el árbol. El trabajo de los agentes en paralelo se nota, sin embargo, en las
**costuras**: donde dos personas resolvieron lo mismo por separado, las soluciones no
coinciden.

Los tres problemas de más peso eran:

1. **Un componente usado sin importar.** `MovimientosVista.vue` renderizaba `<CampoTexto>` en
   el modal «Guardar vista» sin haberlo importado, así que el campo del nombre no aparecía y
   la función era inservible. No lo detecta `vue-tsc` porque el `tsconfig` no activa
   `strictTemplates`.
2. **La tabla perdía el formato en móvil.** Las dos líneas de metadatos de la ficha de móvil
   de `TablaDatos` no pasaban por los slots `celda-<clave>` que usan las vistas para aplicar
   `euros()`, de modo que en un teléfono se leía `1234.56` en el saldo de Cuentas, `2.46` en
   el precio de Productos y `[object Object]` en la temática de Movimientos.
3. **El 422 del backend no llegaba a los campos.** `erroresPorCampo()` estaba escrito y
   documentado en `stores/comun.ts` pero **no lo llamaba ni un formulario**: los `detalles[]`
   con `campo` y `mensaje` se tiraban y solo se veía la banda general, incumpliendo el §2.1
   («el error se ancla al campo afectado además de la banda general»).

Además había un **bloqueo funcional de accesibilidad**: el conmutador de tema y el botón de
renovar sesión que el §5.16 coloca dentro del menú de usuario no se alcanzaban con el teclado,
porque el menú solo recorría los `[role="menuitem"]` y `Tab` lo cerraba.

Se han corregido **28 hallazgos**. Quedan pendientes, y así se documentan, un grupo de
**acciones prescritas que directamente no existen** (el `Exportar` de Informes, «Añadir la
factura a mano», «Dividir línea», el `Guardar cambios` por sección de Ajustes) y la
**reasignación arrastrando del §6.7**, que no está implementada en absoluto. No se han
construido aquí por criterio de alcance: esto es una revisión, no una segunda versión, y
levantar pantallas o funciones que faltan es trabajo de implementación, no de auditoría.

---

## 2. Tabla de hallazgos

| Gravedad | Pantalla o componente | Qué incumple | Referencia | Estado |
|---|---|---|---|---|
| **Alta** | `views/MovimientosVista.vue` | `<CampoTexto>` usado sin importar: el campo del nombre del modal «Guardar vista» no se renderiza y la acción es inservible | §2.4 «guardar la combinación como vista» | Arreglado |
| **Alta** | `components/ui/TablaDatos.vue` | La ficha de móvil no pasaba los metadatos por los slots `celda-*`: salían valores crudos de la API (`1234.56`, `2.46`) y `[object Object]` | §5.6 «Móvil», §8.1 | Arreglado |
| **Alta** | `lib/api.ts` | Mensaje al usuario `Error 409` / `Error 404`: ni español ni comprensible, y filtra el código HTTP | §7 (formato de error), tono §4 | Arreglado |
| **Alta** | `components/ui/MenuDesplegable.vue` + `layouts/LayoutApp.vue` | El conmutador de tema y «Renovar sesión» de la cabecera del menú no se alcanzaban con el teclado; además las flechas se descuadraban al haber items deshabilitados | §5.16, §10 «Menús… una sola parada» | Arreglado |
| **Alta** | Todos los formularios | `erroresPorCampo()` (los `detalles[]` del 422) no lo usaba ningún formulario: los errores por campo se descartaban | §7, §2.1 «se ancla al campo afectado», §5.2 | Arreglado en login, registro y alta de movimiento |
| **Alta** | `FichaProductoVista`, `InformesVista`, `ProductosVista`, `RevisionFacturaVista` | `.toFixed(1)` en porcentajes visibles → separador decimal inglés: «+6.6 %» en vez de «+6,6 %» | §8.3, §8 (es-ES) | Arreglado |
| **Alta** | `views/MovimientosVista.vue` | Eliminar un movimiento no pedía confirmación: borraba al primer clic | §4 «¿Eliminar este movimiento? …» | Arreglado |
| **Alta** | `components/ui/InterruptorBase.vue` | Con la etiqueta visible (el caso normal) el `role="switch"` no tenía nombre accesible | §10 «todo icono informativo lleva texto accesible», §5 | Arreglado |
| **Alta** | `ModalBase.vue`, `CajonLateral.vue` | `inert` y el bloqueo de scroll se ponían y quitaban sin contar capas: cerrar una capa interior devolvía la navegación al fondo con otra abierta | §5.7 «`inert` en el resto de la app» | Arreglado (`lib/capaModal.ts`) |
| **Alta** | `components/ui/CajonLateral.vue` | Sin trampa de foco cuando bloquea (hoja inferior en móvil) | §5.8, §10 | Arreglado |
| Media | `views/PanelVista.vue` | El error del presupuesto decía «No se ha podido cargar el presupuesto de 2026-08» | §2.3 «…de agosto», §8.2 | Arreglado (`etiquetaPeriodo()`) |
| Media | `views/PanelVista.vue` | El módulo de temáticas no tenía estado de error: un fallo de red se confundía con «no hay temáticas». Avisos no tenía esqueleto de carga | §2.3 (estados cargando y error) | Arreglado |
| Media | `views/MovimientosVista.vue` | Faltaban los dos estados vacíos prescritos; heredaba los genéricos de `TablaDatos` | §2.4, §4 | Arreglado (con el criterio de filtro repetido) |
| Media | `CampoTexto`, `CampoImporte`, `CampoFecha`, `BarraBusqueda` | `outline: none` sustituido solo por un brillo de 1 px, y en `:focus` en vez de `:focus-visible` | §5 «nunca `outline: none` sin sustituto», §10 (≥ 3:1) | Arreglado (anillo real de 2 px / 2 px) |
| Media | `DetalleFactura`, `RevisionFactura`, `FichaProducto`, `Informes` (×2) | Cinco zonas con scroll horizontal sin `tabindex="0"`: no se desplazaban con el teclado. Otras cuatro sí lo tenían | §10 «Orden de tabulación» | Arreglado |
| Media | `DetalleFacturaVista`, `FichaProductoVista` | Cantidades y precios unitarios crudos de la API: «1.240» se lee en español como mil doscientos cuarenta | §8.1 «Precio unitario», §8.4 «Cantidades» | Arreglado (`cantidad()`, `precioUnitario()`) |
| Media | Varias vistas | Microcopy fuera de la tabla: «Quitar filtros» por `Quitar todos`, «Asignar presupuesto» por `Asignar`, puntos finales caídos, comillas inglesas `“ ”`, marca «Presupuesto» al entrar y «Gestor de presupuesto» al salir | §4, §2.1 | Arreglado |
| Media | Kit de UI (8 controles) | Objetivos táctiles por debajo de 44 px: flechas de mes (28), densidad de tabla (32×28), casilla de fila (18), cierre de modal (40) y de aviso (24), limpiar búsqueda (24), expandir fila (32), items de menú (36) | §10 «Mínimo 44 × 44 px», §5 | Arreglado |
| Media | `views/componentes/ModalMovimiento.vue` | Cerrar con datos a medias los descartaba en silencio | §4 «Tienes cambios sin guardar…», §5.7 | Arreglado |
| Media | `components/ui/TablaDatos.vue` | `aria-selected` en un `<tr>` de tabla no `grid` (lo ignora el lector); la zona con scroll era una parada de tabulación sin nombre; en carga no había texto oculto | §5.6, §5.13, §10 | Arreglado |
| Media | `components/presupuesto/colores.ts` | `aclarado()` mezclaba con `white`: en tema claro deslavaba el hue sobre una tarjeta blanca en vez de destacarlo | §2.1 «ningún componente escribe un color», §6.5 | Arreglado (mezcla con `--c-text-1`, que se invierte con el tema) |
| Media | `composables/useTema.ts`, `index.html` | Dos hex copiados de `tema.css` para `theme-color`, y en `index.html` un `#0d1117` que no corresponde a ningún token (destello de color equivocado en el primer pintado) | §2.1 «Ningún componente escribe un hex» | Arreglado (se resuelve `--c-app-bg` en tiempo de ejecución) |
| Media | `components/ui/PestanyasBase.vue` | El `tabpanel` no apuntaba a su pestaña con `aria-labelledby` | §5.10 | Arreglado |
| Media | Campos de formulario | `role="alert"` en el mensaje **de campo**: interrumpía al lector de pantalla en cada pulsación | §5.2 (el resumen es el que lleva `role="alert"`) | Arreglado (`aria-live="polite"`; el resumen y la banda del modal lo conservan) |
| Media | `components/presupuesto/ResumenPresupuesto.vue` | Ingreso y gasto llevaban icono y color pero la cifra salía sin signo: faltaba el segundo canal | §2.3 (signo `+`/`-` obligatorio) | Arreglado |
| Media | `views/InformesVista.vue` | La subida de precio se codificaba con color y signo, sin la flecha que exige la regla | §2.3 «Subida de precio: `▲` + porcentaje con signo» | Arreglado |
| Media | `layouts/LayoutApp.vue` | «Saltar a la navegación» apuntaba a un `id` que no existe por debajo de 1024 px con el cajón cerrado | §10 «Orden de tabulación» | Arreglado |
| Baja | 18 ficheros | El mismo ayudante de texto solo para lectores declarado 18 veces con dos nombres (`.oculto` y `.oculto-visualmente`) | §2.1 (una sola fuente de verdad) | Arreglado (definido una vez en `tema.css`; las copias locales quedan, son idénticas e inocuas) |
| Baja | `views/FacturasVista`, `RevisionFactura`, `DetalleFactura` | El tramo de confianza estaba duplicado en tres vistas con formas distintas, y en el detalle faltaba la palabra junto al número | §2.9, §2.3 | Arreglado (`tonoConfianza()` y `ETIQUETA_CONFIANZA` en `api/facturas.ts`) |
| Baja | `views/PanelVista.vue` | El interruptor de la tabla se apagaba con «Ver como lista» y el mismo control en la barra con «Ocultar la tabla» | §4 `Ver como tabla` | Arreglado (un solo par de rótulos) |
| Baja | `components/graficos/base.ts` | 17 colores CSS con nombre como respaldo de `getComputedStyle`; el respaldo de las 12 ranuras categóricas es el mismo `'gray'`, así que la degradación destruye la distinción de series | §2.1 | **Pendiente** — es un camino de último recurso deliberado y documentado en el propio fichero; se deja como está y se anota |
| Baja | `components/presupuesto/BarraPresupuesto.demo.vue` | 108 hex que duplican la tabla de tokens de `tema.css`; además el fichero es **código muerto** (no lo importa nadie) | §2.1 | **Pendiente** — no es código de producto; conviene decidir si se borra o se apoya en una clase de tema |
| Baja | `lib/formato.ts` | `fechaCorta()` pone siempre el año; la especificación pide omitirlo en el año en curso | §8.2 «Del año en curso, sin año» | **Pendiente** — afecta a muchas pantallas a la vez y cambia densidad visual; conviene decidirlo de una pasada |
| Baja | `views/OnboardingVista.vue` | `fallida` no se asigna nunca: la cuenta que falla no queda marcada | §2.2 paso 1 (estado de error) | **Pendiente** |
| Baja | `views/RegistroVista.vue` | Longitud mínima de contraseña 10, la tabla de microcopy dice 8 | §4 vs backend RN-05 | **Pendiente** — hay que decidir quién manda; el código sigue al backend, que es lo seguro |
| Baja | `composables/useTema.ts` | Sin preferencia guardada el tema es oscuro aunque el sistema esté en claro | §2.1 (comentario contradictorio: «el sistema claro también se respeta» / «el oscuro es el de la marca») | **Pendiente** — la especificación se contradice; el código elige una lectura y la documenta |
| Baja | `components/ui/SelectorBase.vue` | `<label for>` apuntando a un `<button>` (el nombre accesible sale del contenido, no de la etiqueta); con el buscador interno abierto el foco está en un `input` sin `role="combobox"` | §5.3 | **Pendiente** |
| Baja | `components/ui/TablaDatos.vue` | En escritorio la fila se activa solo con ratón: `@click` en el `<tr>` sin equivalente de teclado | §11 «¿Se puede operar solo con el teclado?» | **Pendiente** — el detalle sí se abre desde el concepto y desde la ficha de móvil, que es un `<button>` real |
| Baja | `styles/tema.css` | `forced-colors: active` no activa el canal de textura, así que en alto contraste los tramos de la barra pierden hue y patrón | §2.7, §10 | **Pendiente** |
| Baja | Kit de UI | Objetivos táctiles que siguen por debajo de 44 px: días del calendario (34), opciones de select (36), atajos de fecha (32), etiquetas de tema (32) | §10 | **Pendiente** — el calendario a 44 px obliga a rediseñar la rejilla; escribir la fecha a mano ya funciona (§5.4) |

### Acciones prescritas que no existen (pendientes de implementación, no de arreglo)

| Gravedad | Pantalla | Qué falta | Referencia |
|---|---|---|---|
| Media | Informes | Botón `Exportar` (CSV o PDF) | §2.12, §4 |
| Media | Facturas | «Añadir la factura a mano, sin PDF» | §2.7 |
| Media | Revisión de factura | Menú `⋯` por fila con «Dividir línea» y «Eliminar línea»; banda de progreso y tabla bloqueada al guardar | §2.9 |
| Media | Revisión de factura (fallo) | «Reintentar» y «Subir otro archivo» en el paso que falla | §2.8 |
| Media | Ajustes | `Guardar cambios` por sección (Preferencias y Avisos autoguardan); sección «Temáticas y colores»; `Cambiar` junto al correo; confirmación al cerrar sesión remota | §2.13, §4 |
| Media | Temáticas / Onboarding | Rejilla de temáticas sugeridas en el estado vacío; «Crear una temática propia» en el paso 3 | §2.6, §2.2 |
| Media | Toda la app | `Deshacer` en los avisos tras guardar o reasignar: la cadena no existe en producción | §4, §5.9 |
| Media | Panel | Reasignación arrastrando el borde de dos tramos, con asas `role="separator"` y `aria-value*` | §6.7 |
| Baja | Ficha de producto | Selector de rango del gráfico | §2.11 |
| Baja | Informes | Clic en una barra de temática que filtre Movimientos | §2.12 |

La alternativa accesible de la reasignación (**«Cambiar asignación»**, con un campo de importe
por temática y el contador «Sin asignar») **sí existe**, así que el criterio 2.5.7 de WCAG 2.2
se cumple: no hay ninguna función que dependa solo del arrastre. Lo que falta es el atajo
agradable, no el camino garantizado.

---

## 3. Accesibilidad: qué se ha comprobado

Comprobado contra el §10, los apartados de accesibilidad del §5 y el §6.5.

**Correcto tal cual estaba**

- **Foco global**: `:focus-visible` con anillo de 2 px `--c-accent` y `outline-offset: 2px` en
  `tema.css`, y `scroll-margin-top: 80px` en todo lo enfocable, así que una cabecera pegajosa
  nunca tapa el foco.
- **Enlaces de salto**: «Saltar al contenido principal» y «Saltar a la navegación» son los dos
  primeros elementos tabulables del documento, en el orden que pide el §10. (El segundo se ha
  corregido para no apuntar al vacío en móvil.) No se solapan: el que no tiene el foco queda
  desplazado fuera de la pantalla.
- **Pestañas**: `tablist`/`tab`/`tabpanel`, `aria-selected`, activación **manual** con
  `Enter`/`Espacio` (no al mover el foco, que es lo que pide el §5.10 porque cada pestaña
  dispara una consulta), flechas, `Home`/`End`, una sola parada de tabulación y panel
  enfocable.
- **Combobox**: `SelectorBase` implementa el patrón completo: `role="combobox"`,
  `aria-expanded`, `aria-controls`, `aria-activedescendant`, `listbox`/`option` con
  `aria-selected`, flechas, `Home`/`End`, salto por letra, `Enter`, `Esc` con devolución del
  foco y `Tab` que cierra confirmando.
- **Modal**: `role="dialog"` + `aria-modal` + `aria-labelledby` a un `id` real, foco atrapado,
  devolución al disparador, `Esc` que pregunta si hay cambios, y compensación del ancho de la
  barra de scroll para que no salte la maquetación.
- **`BudgetBar`**: `section` con encabezado, `role="group"` con `aria-describedby` al resumen,
  cada tramo `role="img"` con etiqueta completa («nombre, gastado de asignado, % de lo
  asignado, % del total, segmento N de M»), recorrido con flechas y `Home`/`End`, `Enter` y
  `Espacio`, anillo de foco hacia dentro para no tapar a los vecinos, anuncios por
  `aria-live="polite"` y la **tabla gemela obligatoria** con `caption`, `scope` y contenedor
  enfocable.
- **El color no es el único canal en el caso crítico del sobrepaso**: icono `triangle-alert`,
  texto «Sobrepasado», el importe del exceso, el borde de 2 px y las rayas a 45 º, tanto en la
  barra grande como en la compacta. La sobreasignación va en ámbar con `circle-alert`, texto y
  trama, no en rojo, como manda el estado C.
- **Chips de temática**: el punto de color va `aria-hidden`, el nombre se pinta siempre y el
  texto nunca toma el hue. Es lo que hace segura una paleta de 12.
- **`prefers-reduced-motion`** y **`prefers-contrast: more`** implementados, con la excepción
  intencionada de los fundidos a 100 ms.

**Corregido en esta revisión**

- Bloqueo funcional: el conmutador de tema y «Renovar sesión» dentro del menú de usuario ya se
  alcanzan con las flechas; el recorrido se lee del DOM, así que también deja de caer en items
  deshabilitados.
- Todo interruptor con etiqueta visible tiene ya nombre accesible.
- `inert` con cuenta de capas: un diálogo anidado ya no devuelve la navegación al fondo.
- Trampa de foco en el cajón cuando bloquea, y foco inicial al primer campo (antes iba siempre
  al contenedor). El selector de foco inicial ya no se salta un `SelectorBase` ni cae en un
  campo deshabilitado o de solo lectura.
- Anillo de foco real de 2 px en los cuatro campos que lo habían suprimido, y anclado al
  `input` para que enfocar el botón del calendario no ilumine el campo entero.
- Las cinco zonas con scroll horizontal que faltaban son ya enfocables, y la de `TablaDatos`
  tiene nombre (`role="region"` + `aria-label`).
- `aria-selected` retirado del `<tr>`, donde el lector lo descartaba; la selección se sigue
  leyendo por la casilla marcada.
- Los mensajes de campo pasan de `role="alert"` a `aria-live="polite"`: dejaban de interrumpir
  en cada tecla. El resumen del formulario y la banda del modal conservan `role="alert"`.
- El foco salta al importe cuando el importe es lo que está mal, en el alta de movimiento.
- Ocho objetivos táctiles subidos a 44 px de área efectiva, con pseudo-elemento donde el
  pintado debía seguir siendo pequeño (§10: «se amplía con un pseudo-elemento, no agrandando
  el borde visible»).
- El `tabpanel` ya dice a qué pestaña pertenece.
- Segundo canal añadido donde faltaba: signo en el resumen de presupuesto, flecha en la subida
  de precio de Informes, y texto solo para lectores («Ha subido» / «Ha bajado») en los tres
  indicadores de variación, que antes dependían de la flecha y el color.

**Contradicción de la especificación detectada**

El §10 pide que **cada** tramo de la `BudgetBar` lleve `tabindex="0"`; el §6.5 dice que «el
carril es un solo elemento tabulable» y que dentro se navega con flechas. Son incompatibles.
El código implementa el §6.5 con `tabindex` móvil, que es la opción correcta según el propio
§10 («Menús, selects y tabs son una sola parada de tabulación; dentro se navega con
flechas»). **Conviene corregir el §10 del documento, no el código.**

---

## 4. Pendiente por falta de backend

Nada de esto se ha inventado. Donde el contrato no publica el endpoint, la interfaz dice la
verdad o el control queda deshabilitado y explicado.

| Función | Situación | Qué hace hoy la interfaz |
|---|---|---|
| **Restablecer contraseña por correo** (§1 la lista como pantalla) | No hay endpoint: el §3.1 solo tiene `change-password`, que exige sesión, y es una instalación autoalojada sin servidor de correo garantizado | `RecuperarVista.vue` lo explica y remite a Ajustes o a quien administre la instalación, en vez de fingir que ha enviado un enlace. **Correcto: estado honesto** |
| **«Continuar con Google»** (§2.1) | No hay proveedor OAuth en el contrato | El botón no existe. Un botón que no lleva a ninguna parte es peor que no tenerlo |
| **Verificación en dos pasos** (§2.13) | Sin endpoint | No se ofrece |
| **Importar movimientos (CSV, OFX, QIF)** (§2.13) | Sin flujo de revisión de importación en el backend | Botón `Importar` **deshabilitado con explicación** junto a él |
| **`Exportar` en Informes** (§2.12) | Existe `/exports/quick?entity=&format=`, que usa Ajustes, pero no hay parámetros de rango documentados para exportar el informe del periodo activo | No implementado. Enganchar el endpoint genérico ignorando el periodo elegido sería engañoso |
| **IBAN de una cuenta** (§4 pide «Introduce un IBAN válido») | No hay campo IBAN en el contrato de cuentas | No hay campo, así que el mensaje no es alcanzable |
| **Eliminar una cuenta bancaria con movimientos** (§4) | Solo hay archivar | No hay acción de borrado; la confirmación prescrita no es alcanzable |
| **Miniatura y visor de PDF incrustado** (§2.10) | El fichero se sirve, pero no hay miniatura | Enlaces «Ver PDF original» y «Descargar PDF»; sin visor, no hay error propio del visor que mostrar |
| **Funcionamiento sin conexión y badge «Pendiente de sincronizar»** (§9.3.8, §3.1) | Requiere cola local y sincronización, que no existen | No implementado; un fallo de red se muestra como error normal |
| **Rejilla de temáticas por frecuencia real de uso** (§2.5, §9.3) | El árbol cacheado no trae contador de uso | Se usa el orden que el usuario dio en el árbol, documentado en el propio componente |
| **«La última cuenta usada» como valor por defecto** (§2.5) | No está en el contrato | Se toma la primera cuenta activa, documentado |
| **Estado calculado de la temática y avisos redactados** | Sí llegan del backend | La interfaz los pinta sin recalcularlos, como pide el §2.3 de los wireframes |

---

## 5. Nota de método

Se ha auditado con cuatro barridos independientes (formato de datos, colores codificados a
mano, microcopy contra la tabla del §4, y accesibilidad contra el §10 y el §5) y lectura
directa de las 18 pantallas, los 20 componentes del kit, los dos marcos y los tokens.

Sobre los porcentajes: el §8.3 pide un decimal y el código los componía a mano en once sitios,
con `Math.round` en unos y `.toFixed(1)` en otros, lo que además rompía el separador decimal
español. Todos pasan ya por `porcentaje()`. Se ha añadido a esa función un segundo parámetro
para pedir cero decimales, y se usa en los indicadores gruesos donde los wireframes muestran
enteros de forma repetida y explícita —la confianza de una línea de factura, el umbral de aviso
de presupuesto—, de modo que ni esos se construyen a mano. Es una decisión consciente entre
el §8.3 del sistema de diseño y el §2.9 de los wireframes, no un descuido.

Las funciones nuevas de `lib/formato.ts` (`precioUnitario()` y `cantidad()`) existen porque el
contrato manda precios y cantidades como cadena decimal con punto y no había forma de
pintarlos bien: `euros()` redondea a dos decimales y se comía la precisión de un precio
unitario, y una cantidad cruda como `"1.240"` se lee en español como mil doscientos cuarenta.
No se ha añadido ninguna dependencia.
