# Componentes base (`@/components/ui`)

Catálogo para usarlos sin leer el código. Todos son SFC con `<script setup lang="ts">`, texto
en español de España, foco visible, objetivo táctil de 44 px y **cero hex escritos a mano**:
todo el color sale de los tokens de `@/styles/tema.css`.

Convenciones comunes:

- Los props booleanos son `false` por defecto y se pasan como atributo suelto (`requerido`).
- El estado inválido se pasa siempre por un prop `error` con **el mensaje ya redactado**;
  el componente pone `aria-invalid`, el icono y el `aria-describedby`.
- Todo lo que tiene valor usa `v-model` (`modelValue` + `update:modelValue`).
- Las cifras monetarias van en **céntimos enteros** (`number`) y se pintan con
  `dinero()` de `@/lib/formato`. Nunca euros en coma flotante.
- Los importes de una tabla llevan `data-numeric` o la clase `num`, que aplica
  `tabular-nums` y alineación a la derecha.

---

## BotonBase

Botón real (`<button type>`, o `<a>` si se pasa `href`). `variante`:
`primaria` (una por vista) · `secundaria` · `fantasma` (filas y barras de herramientas) ·
`contorno` (alternativa a primaria en modales) · `peligro` · `peligro-fantasma` · `enlace`.
`tamanyo`: `sm` 32 px · `md` 40 px (por defecto) · `lg` 48 px. Además: `icono` e `iconoFinal`
(componentes de `lucide-vue-next`), `contador`, `cargando` (congela el ancho, pone el spinner
y `aria-busy`), `deshabilitado`, `anchoCompleto`, `soloIcono` (obliga a `etiquetaAccesible`),
`tipo` y `href`. La etiqueta va en el slot por defecto. No existe estado de error: el error
vive en el formulario o en un toast.

## CampoTexto

Campo de texto con etiqueta arriba. Props: `modelValue`, `etiqueta` (obligatoria, el
placeholder nunca la sustituye), `tipo` (`text|email|password|search|tel|url`), `placeholder`,
`ayuda`, `error`, `correcto`, `cargando`, `deshabilitado`, `soloLectura`, `requerido`,
`etiquetaOculta`, `monoespaciado` (solo NIF, IBAN, nº de factura), `maxLongitud`, `contador`,
`iconoInicio`, `sufijo`, `autocompletar`, `ancho`. Emite `update:modelValue` y `enter`. Expone
`enfocar()` para llevar el foco al primer campo inválido al enviar.

## CampoImporte

El control más usado. `modelValue` en **céntimos** (`number | null`), € como sufijo fijo fuera
del área de texto, valor a la derecha con `tabular-nums`. La máscara inserta separadores de
millar al escribir, admite coma o punto (el punto se convierte en coma), corta al segundo
decimal, normaliza al salir (`12` → `12,00`, vacío → vacío, nunca `0,00`) y **resuelve
aritmética simple** (`12,50+3,20` → `15,70`, con el rótulo de la expresión 2 s). Si se pega un
valor negativo se ignora el signo y se avisa: el signo lo decide el tipo de movimiento. Props:
`etiqueta`, `ayuda`, `error`, `deshabilitado`, `soloLectura` (se pinta como texto plano),
`requerido`, `etiquetaOculta`, `tamanyo` (`cuerpo` | `display` para el modal rápido),
`teclasRapidas` (`+10 +50 +100 C`), `maximo` en céntimos (por defecto 999.999,99 €). Expone
`enfocar()`.

## CampoFecha

Input con máscara `dd/mm/aaaa` más panel de calendario; **escribir la fecha a mano siempre
funciona**. `modelValue` es ISO `AAAA-MM-DD` o `null`. Props: `etiqueta`, `ayuda`, `error`,
`deshabilitado`, `requerido`, `minima`, `maxima` (ISO) y `diasConDatos`, un mapa
`{ '2026-08-12': 3 }` que pinta el punto de 3 px y lo mete en el `aria-label` del día. Semana
desde el lunes, cabeceras `L M X J V S D`, hoy con borde de acento, días de otros meses
ocultos. Teclado: flechas, `Home/End`, `PageUp/PageDown` de mes, con `Shift` de año, `Esc`
cierra. La columna de atajos es de fecha única (Hoy, Ayer, primer y último día del mes, hace
30 días); la variante de **rango** no está implementada todavía.

## SelectorBase

Combobox de selección (patrón ARIA `combobox` + `listbox`). Props: `modelValue`
(`string | number | null`), `opciones` (`{ valor, etiqueta, grupo?, deshabilitada?, ranura? }`,
donde `ranura` 1..12 pinta el punto del hue de la temática), `etiqueta`, `placeholder`,
`ayuda`, `error`, `deshabilitado`, `cargando` (tres filas de esqueleto dentro de la lista),
`requerido`, `etiquetaOculta`, `buscable` (automático a partir de 8 opciones). Teclado:
`↑↓` mueven, `Home/End` a los extremos, letra salta, `Enter` confirma, `Esc` cierra y devuelve
el foco, `Tab` cierra confirmando. Las opciones con `grupo` se agrupan conservando el orden.

## TablaDatos

Tabla genérica (`<TablaDatos<MiFila> …>`), semántica y con cabecera pegajosa. Props:
`columnas` (`{ clave, etiqueta, numerica?, ordenable?, ancho?, fija?: 'inicio'|'fin', valor?:
(fila) => string, soloEscritorio? }`), `filas`, `claveFila: (fila) => string | number`,
`titulo` (`<caption>`, con `tituloOculto`), `densidad` (`comoda` 48 px | `compacta` 36 px),
`orden` (`{ clave, sentido } | null`), `cargando` (8 filas de esqueleto con las anchuras
reales), `recargando` (contenido anterior al 55 %), `expandible`, `seleccionables`,
`seleccionadas`, `rotuloTotales`, `vacioPorFiltro`, `error`. Emite `update:densidad`,
`update:orden` (ciclo asc → desc → sin orden), `update:seleccionadas`, `filaClic`,
`reintentar` y `quitarFiltros`. Slots: `herramientas`, `celda-<clave>` (`{ fila, valor }`),
`detalle` (`{ fila }`), `pie` y `vacio`. Sin zebra. Por debajo de 768 px se convierte en
tarjetas apiladas y **nunca** hay scroll horizontal. La ordenación la hace quien la usa: el
componente solo dice qué columna y en qué sentido.

## ModalBase

Diálogo centrado con scrim borroso, foco atrapado, `inert` en el resto de la app y bloqueo del
scroll compensando la barra. Props: `abierto`, `titulo`, `subtitulo`, `tamanyo`
(`sm` 420 / `md` 560 / `lg` 720 / `xl` 960), `guardando` (bloquea el cierre), `error` (banda
bajo la cabecera), `cambiosSinGuardar`, `cerrarConEscape`, `ocultarCierre`. Emite
`update:abierto`, `cerrar` y `descartar` (se dispara en lugar de cerrar cuando hay cambios sin
guardar: el padre decide qué preguntar). Slots: por defecto el cuerpo y `pie` para las
acciones, con la secundaria primero. Al abrir el foco va al primer campo; al cerrar, al
disparador.

## CajonLateral

Panel derecho de 420 px (`tamanyo: 'lg'` → 560) que **conserva el contexto de la lista**. Por
defecto no bloquea en escritorio y sí en móvil, donde pasa a hoja inferior al 92 % con asa y
cierre por gesto; `bloqueante` fuerza el comportamiento. Props: `abierto`, `titulo`,
`subtitulo`, `cargando`, `conNavegacion`, `hayAnterior`, `haySiguiente`. Emite
`update:abierto`, `cerrar`, `anterior` y `siguiente` (chevrons de la cabecera y `↑`/`↓`
cuando el foco no está en un campo). Slots: por defecto y `pie`.

## AvisoFlotante

Región única de toasts. **No tiene props**: se monta una sola vez (ya lo hacen los dos
layouts) y lee la cola de `useAvisos()`. Abajo a la derecha en escritorio, arriba en móvil
para no tapar el botón flotante. Máximo 3 visibles, el resto encolado; se pausa con el puntero
o el foco; `role="status"` para éxito e info y `role="alert"` para error.

## PestanyasBase

Pestañas con **activación manual** (`Enter`/`Espacio`), porque cada pestaña dispara una
consulta. Props: `modelValue`, `pestanyas` (`{ valor, etiqueta, contador?, deshabilitada? }`)
y `etiqueta` (el `aria-label` de la lista). Emite `update:modelValue`. El contenido va en el
slot por defecto, dentro del `tabpanel` enfocable. Indicador inferior de 2 px que se desliza;
con desbordamiento aparecen flechas en escritorio y scroll desvanecido en táctil.

## EtiquetaCategoria

Chip de identidad de temática: punto de 8 px con el hue y **siempre el nombre**, que es lo que
hace segura una paleta de 12. Props: `nombre`, `ranura` (1..12; `0` = «Otros», gris), `madre`
(se pinta `Madre · Hija`), `nivel` 0..3 (aclara el hue de la subcategoría sin cambiarlo),
`icono` (sustituye al punto), `eliminable`, `seleccionable` (con `aria-pressed`),
`seleccionada`, `tamanyo` (`sm` 20 px | `md` 24 px). Emite `quitar` y `alternar`. El texto
nunca se colorea con el hue.

## PistaAyuda

Tooltip que envuelve su disparador (slot por defecto). Props: `texto`, `posicion`
(`arriba|abajo|izquierda|derecha`, voltea si choca con el borde) y `retardo` (400 ms; 0 para
la lateral colapsada). Aparece con puntero y con `:focus-visible`, se cierra con `Esc` y se
conecta por `aria-describedby`. No admite controles dentro ni información que no esté en otro
sitio.

## EsqueletoCarga

Bloques con la geometría real del contenido. Props: `variante`
(`texto` 14 px · `importe` 15×88 · `avatar` 32 circular · `barra` 40 · `bloque` 44), `lineas`
(tope 8; la última sale al 62 % de ancho), `ancho`, `alto` y `anuncio` (texto oculto
«Cargando…»). Solo para la **primera** carga de una zona: en las recargas se mantiene el
contenido anterior atenuado con la clase global `recargando`.

## EstadoVacio

Cuatro vacíos distintos, no uno. Props: `tipo` (`primer-uso` | `sin-filtros` | `sin-busqueda` |
`error`, que elige el icono y el color), `titulo`, `descripcion`, `criterio` (el término o el
filtro aplicado, que se le repite al usuario), `icono` para sustituir el del tipo y `nivel`
(2, 3 o 4) para que el encabezado encaje en la jerarquía de la vista. Slots: `accion` y
`ayuda`.

## PaginacionBase

Props: `pagina` (empieza en 1), `tamanyoPagina`, `total`, `tamanyos` (25/50/100/200),
`cargando`, `unidad` (para el rótulo «de 1.284 movimientos»). Emite `update:pagina` y
`update:tamanyoPagina`. Máximo 7 números con elisión, `aria-current="page"` en el activo y
anuncio «Página 3 de 26» por `aria-live`. Con una sola página desaparecen los números y queda
el contador.

## BarraBusqueda

Una sola fila con la búsqueda, los filtros y las acciones. Props: `modelValue`, `placeholder`,
`retardo` (250 ms de antirrebote), `minimoCaracteres` (2), `buscando`, `resultados`,
`filtrosActivos` (badge en «Más filtros») y `chips` (`{ clave, etiqueta, ranura? }`). Emite
`update:modelValue`, `buscar` (ya con antirrebote), `limpiar`, `quitarChip`, `quitarTodos` y
`abrirFiltros`. Slots `filtros` (los desplegables de la fila) y `acciones`. La tecla `/`
enfoca el campo desde cualquier parte y `Esc` lo limpia. Si el término parece un importe lo
dice en un rótulo.

## MenuDesplegable

Menú ARIA (`menu`/`menuitem`) cuyo disparador lo pone quien lo usa. Props: `items`
(`{ clave, etiqueta, icono?, atajo?, peligrosa?, deshabilitada?, separadorAntes? }`),
`etiqueta`, `alineacion` (`izquierda|derecha`), `haciaArriba` y `ancho`. Emite `seleccionar`
(la clave) y `update:abierto`. Slots: `disparador` — recibe `{ abierto, alternar, atributos }`
y hay que hacer `v-bind="atributos"` y `@click="alternar()"` —, `cabecera` y `pie`. Teclado:
`↑↓`, `Home/End`, `Enter`, `Esc` (devuelve el foco) y `Tab` cierra. Expone `abrir`, `cerrar` y
`alternar`.

## InterruptorBase

`role="switch"` con `aria-checked`. Props: `modelValue`, `etiqueta`, `descripcion`,
`deshabilitado`, `etiquetaOculta`, `tamanyo` (`sm` | `md`). Emite `update:modelValue`. La
etiqueta también es pulsable y el objetivo táctil llega a 44 px por pseudo-elemento.

## IndicadorProgreso

`role="progressbar"`. Props: `valor`, `maximo` (100), `etiqueta` (obligatoria),
`estado` (texto que se anuncia por `aria-live`, p. ej. «Analizando la página 2 de 5»),
`indeterminado`, `tono` (`accent|positive|negative|warning|info`), `alto` en px y
`mostrarTexto` para pintar el porcentaje con `porcentaje()` de formato.ts.

---

## Composables (`@/composables`)

- **`useTema()`** → `{ tema, preferencia, esOscuro, opciones, establecer, alternar }`.
  `preferencia` es `dark | light | sistema`; `tema` es el resuelto. Guarda la elección en
  `tema-preferencia` y **el tema resuelto en `tema`**, que es la clave que lee `index.html`
  antes de la primera pintura. Sin nada guardado, oscuro.
- **`useAvisos()`** → `{ avisos, enEspera, pausado, avisar, exito, info, aviso, error, cerrar,
  pausar, reanudar, limpiar }`. Duraciones: éxito 4 s, info 5 s, aviso 7 s, error no se cierra
  solo. `avisar({ mensaje, tipo, titulo, duracion, accion: { etiqueta, alPulsar } })`.
- **`useAtajos(atajos)`** con `{ combinacion, descripcion, accion, enCampos?, grupo? }`.
  `combinacion` admite `'/'`, `'mod+k'` (⌘ o Ctrl) y secuencias `'g t'`. Por defecto no
  dispara mientras se escribe en un campo. `atajosRegistrados()` lista los vivos para la
  ayuda.
- **`useMedia()`** → `{ sm, md, lg, xl, xxl, tramo, punteroFino, movimientoReducido, esMovil,
  esTableta, esEscritorio }`, con los breakpoints de §9.1 (los mismos que Tailwind).

## Tokens y utilidades

`@/styles/tema.css` declara los `--c-*`, `--sp-*`, `--r-*`, `--t-*`, `--dur-*`, `--ease-*`,
`--elev-*` y `--glow-*`, y los expone a Tailwind con `@theme inline`: `bg-surface`,
`bg-surface-2`, `text-ink`, `text-ink-2`, `border-line`, `text-positive`, `bg-cat-1`,
`text-h2`, `text-cuerpo`, `text-meta`, `text-micro`, `rounded-md`… Clases globales útiles:
`num` y `num-grande` (cifras tabulares), `tarjeta`, `elev-1/2/3`, `toque-44`, `esqueleto`,
`recargando`, `rayas` / `rayas-espejo` (el canal de textura) y `fade-only`.
