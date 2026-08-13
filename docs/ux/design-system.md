# Sistema de diseño — Gestor de presupuesto

Versión 1.0 · es-ES · EUR · Modo oscuro por defecto
Stack de destino: Vue 3 + TypeScript + Vite + Tailwind CSS v4 + Chart.js + Lucide.

---

## 1. Filosofía visual

1. **Serio antes que simpático.** Esto administra el dinero de una persona: nada de degradados alegres, emojis en la interfaz ni ilustraciones. La confianza se gana con precisión.
2. **La cifra es la protagonista.** El color, el borde y el espacio existen para que un número se lea rápido y sin ambigüedad; todo lo demás se retira.
3. **Densidad alta pero respirable.** Muchas filas por pantalla, sí, pero con alturas de fila constantes, separadores de 1 px y aire suficiente para recorrer la columna de importes con la vista.
4. **Oscuro por diseño, no por inversión.** Superficies que suben en pasos medidos, elevación por borde y luz, jamás sombras negras aplastadas.
5. **El significado nunca depende del color.** Cada estado lleva icono, signo o texto además de color; el color es refuerzo, no información.

---

## 2. Color

### 2.1 Cómo se declaran los tokens (patrón Tailwind v4)

Dos capas: valores crudos por tema en `:root` / `[data-theme="light"]`, y un mapeo `@theme inline` que genera las utilidades. Así el cambio de tema es una sola línea en el `<html>` y no obliga a recompilar nada.

```css
/* ============================================================
   TEMA OSCURO — tema principal y valor por defecto
   ============================================================ */
:root {
  color-scheme: dark;

  /* --- Superficies ------------------------------------------------ */
  --c-app-bg:        #0E1116;  /* fondo de la aplicación */
  --c-surface:       #151A21;  /* tarjetas, tablas, superficie de gráficos */
  --c-surface-2:     #1C222B;  /* elevada: modal, drawer, popover, menú */
  --c-surface-3:     #232B36;  /* hover sobre elevada, chips, celdas activas */
  --c-surface-sunken:#0A0D12;  /* carriles vacíos, pozos, code blocks */
  --c-border:        #2A323D;  /* borde por defecto (1 px) */
  --c-border-strong: #3A4552;  /* divisores fuertes, borde de input hover */
  --c-border-soft:   #1E2530;  /* separadores de fila en tabla densa */
  --c-overlay:       rgb(4 6 9 / 0.72); /* scrim de modal */

  /* --- Texto ------------------------------------------------------ */
  --c-text-1:        #F2F5F9;  /* principal   17,3:1 sobre app-bg */
  --c-text-2:        #A7B2C0;  /* secundario   8,8:1 */
  --c-text-3:        #7E8A99;  /* terciario    5,4:1 */
  --c-text-disabled: #5A6472;  /* deshabilitado 3,2:1 (nunca informativo) */
  --c-text-on-fill:  #0A0E14;  /* texto sobre relleno de acento o semántico */

  /* --- Acento de marca -------------------------------------------- */
  --c-accent:        #4E7FFF;
  --c-accent-hover:  #6B92FF;
  --c-accent-press:  #3D6CE8;
  --c-accent-text:   #7099FF;  /* acento COMO TEXTO o enlace (5,9:1) */
  --c-accent-wash:   color-mix(in oklab, #4E7FFF 14%, transparent);
  --c-accent-ring:   color-mix(in oklab, #4E7FFF 55%, transparent);

  /* --- Semánticos (estado, no identidad) -------------------------- */
  --c-positive:      #3FBF6F;  /* ingreso, ahorro, bajada de precio  8,0:1 */
  --c-negative:      #F2555A;  /* gasto, exceso, subida de precio    5,6:1 */
  --c-warning:       #E3A008;  /* cerca del límite                   8,4:1 */
  --c-info:          #3FB6E8;  /* informativo, previsión             8,2:1 */
  --c-positive-wash: color-mix(in oklab, #3FBF6F 16%, transparent);
  --c-negative-wash: color-mix(in oklab, #F2555A 16%, transparent);
  --c-warning-wash:  color-mix(in oklab, #E3A008 16%, transparent);
  --c-info-wash:     color-mix(in oklab, #3FB6E8 16%, transparent);

  /* --- Cromo de gráficos ------------------------------------------ */
  --c-grid:          #232A34;  /* rejilla, hairline 1 px, sólida */
  --c-axis:          #38414D;  /* eje y línea base */
  --c-axis-text:     #7E8A99;
  --c-track:         #1E2530;  /* carril vacío de barras y medidores */
  --c-deemphasis:    #4A5462;  /* series de contexto en gráficos de énfasis */

  /* --- Paleta categórica (12) ------------------------------------- */
  --c-cat-1:  #568EF9;  /* azul       */
  --c-cat-2:  #C2520B;  /* naranja    */
  --c-cat-3:  #02A6AD;  /* cian       */
  --c-cat-4:  #CE3344;  /* rojo       */
  --c-cat-5:  #3FAC4A;  /* verde      */
  --c-cat-6:  #B343AD;  /* magenta    */
  --c-cat-7:  #AC9008;  /* oro        */
  --c-cat-8:  #6F5DDF;  /* violeta    */
  --c-cat-9:  #20A888;  /* turquesa   */
  --c-cat-10: #9D6000;  /* ámbar      */
  --c-cat-11: #D36C9D;  /* rosa       */
  --c-cat-12: #026FB9;  /* azul acero */
  --c-cat-other: #4A5462; /* «Otros» — gris, NUNCA un hue 13 */

  /* --- Rampa secuencial (azul, 100→700) --------------------------- */
  --c-seq-100: #132B5A;  --c-seq-200: #1C3E81;  --c-seq-300: #2552AA;
  --c-seq-400: #3368D0;  --c-seq-500: #4680F1;  --c-seq-600: #679CFF;
  --c-seq-700: #91B7FE;

  /* --- Rampa divergente (ámbar ↔ azul, gris neutro) --------------- */
  --c-div-warm-3: #E8B14A;  --c-div-warm-2: #C08A2A;  --c-div-warm-1: #8A6014;
  --c-div-neutral:#39414D;
  --c-div-cool-1: #2C5A8E;  --c-div-cool-2: #4A82C8;  --c-div-cool-3: #8FB6F0;
}

/* ============================================================
   TEMA CLARO — solo overrides
   ============================================================ */
[data-theme="light"] {
  color-scheme: light;

  --c-app-bg:        #F2F5F8;
  --c-surface:       #FFFFFF;
  --c-surface-2:     #FFFFFF;
  --c-surface-3:     #F7F9FB;
  --c-surface-sunken:#EDF1F5;
  --c-border:        #D5DDE7;
  --c-border-strong: #B9C4D2;
  --c-border-soft:   #E6EBF1;
  --c-overlay:       rgb(15 20 25 / 0.42);

  --c-text-1:        #0F1419;  /* 18,5:1 sobre blanco */
  --c-text-2:        #4C5867;  /*  7,2:1 */
  --c-text-3:        #5E6B7E;  /*  5,4:1 sobre blanco · 5,0:1 sobre app-bg */
  --c-text-disabled: #9AA5B4;
  --c-text-on-fill:  #FFFFFF;

  --c-accent:        #2C5FE0;
  --c-accent-hover:  #2451C7;
  --c-accent-press:  #1D45AC;
  --c-accent-text:   #2C5FE0;
  --c-accent-wash:   color-mix(in oklab, #2C5FE0 10%, transparent);
  --c-accent-ring:   color-mix(in oklab, #2C5FE0 55%, transparent);

  --c-positive:      #11803D;  /* 5,0:1 */
  --c-negative:      #C4283A;  /* 5,7:1 */
  --c-warning:       #8A5A00;  /* 5,9:1 */
  --c-info:          #0B6C9E;  /* 5,8:1 */
  --c-positive-wash: color-mix(in oklab, #11803D 10%, transparent);
  --c-negative-wash: color-mix(in oklab, #C4283A 10%, transparent);
  --c-warning-wash:  color-mix(in oklab, #8A5A00 10%, transparent);
  --c-info-wash:     color-mix(in oklab, #0B6C9E 10%, transparent);

  --c-grid:          #E8EDF3;
  --c-axis:          #C9D3DF;
  --c-axis-text:     #5E6B7E;
  --c-track:         #EDF1F5;
  --c-deemphasis:    #AAB6C4;

  --c-cat-1:  #1E59CD;  --c-cat-2:  #DA682C;  --c-cat-3:  #06949A;
  --c-cat-4:  #E75F66;  --c-cat-5:  #026A1A;  --c-cat-6:  #CB5AC3;
  --c-cat-7:  #AA8F02;  --c-cat-8:  #5737C8;  --c-cat-9:  #08987A;
  --c-cat-10: #CB862E;  --c-cat-11: #D05B95;  --c-cat-12: #015590;
  --c-cat-other: #8593A4;

  --c-seq-100: #CDDFFF;  --c-seq-200: #A8C5F9;  --c-seq-300: #81AAF7;
  --c-seq-400: #5A8FF3;  --c-seq-500: #3672E9;  --c-seq-600: #1E59CD;
  --c-seq-700: #1043A8;

  --c-div-warm-3: #7A4E00;  --c-div-warm-2: #B07A18;  --c-div-warm-1: #E0B871;
  --c-div-neutral:#DCE3EB;
  --c-div-cool-1: #9BBCE8;  --c-div-cool-2: #3D74BE;  --c-div-cool-3: #10437F;
}

/* Si el usuario no ha elegido tema, el sistema claro también se respeta.
   El tema oscuro sigue siendo el de la marca: es lo que ve un visitante nuevo. */
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]):not([data-theme="light"]) {
    /* repetir aquí el bloque de overrides claros, o marcar data-theme="light"
       desde el arranque de la app leyendo matchMedia. Preferimos lo segundo:
       una sola fuente de verdad y sin duplicar 60 declaraciones. */
  }
}

/* ============================================================
   MAPEO A UTILIDADES TAILWIND v4
   ============================================================ */
@theme inline {
  --color-app:            var(--c-app-bg);
  --color-surface:        var(--c-surface);
  --color-surface-2:      var(--c-surface-2);
  --color-surface-3:      var(--c-surface-3);
  --color-sunken:         var(--c-surface-sunken);
  --color-line:           var(--c-border);
  --color-line-strong:    var(--c-border-strong);
  --color-line-soft:      var(--c-border-soft);

  --color-ink:            var(--c-text-1);
  --color-ink-2:          var(--c-text-2);
  --color-ink-3:          var(--c-text-3);
  --color-ink-off:        var(--c-text-disabled);
  --color-on-fill:        var(--c-text-on-fill);

  --color-accent:         var(--c-accent);
  --color-accent-hover:   var(--c-accent-hover);
  --color-accent-text:    var(--c-accent-text);

  --color-positive:       var(--c-positive);
  --color-negative:       var(--c-negative);
  --color-warning:        var(--c-warning);
  --color-info:           var(--c-info);

  --color-cat-1:  var(--c-cat-1);   /* … hasta cat-12 y cat-other */
}
```

> **Regla de implementación.** Ningún componente escribe un hex. Si un valor no está
> en esta lista, no existe. Las variantes translúcidas se generan con `color-mix(in oklab, …)`
> sobre el token, nunca con un `rgba()` a ojo.

### 2.2 Contrastes verificados

Medidos con la fórmula WCAG 2.1 sobre el fondo real de renderizado.

| Token | Oscuro sobre `--c-app-bg` | Oscuro sobre `--c-surface-2` | Claro sobre blanco | Requisito |
|---|---|---|---|---|
| `--c-text-1` | **17,3:1** | 14,6:1 | **18,5:1** | ≥ 7:1 ✔ |
| `--c-text-2` | **8,8:1** | 7,4:1 | **7,2:1** | ≥ 4,5:1 ✔ |
| `--c-text-3` | 5,4:1 | 4,6:1 | 5,4:1 | ≥ 4,5:1 ✔ |
| `--c-text-disabled` | 3,2:1 | 2,7:1 | 2,5:1 | sin requisito; **jamás lleva información** |
| `--c-accent` | 5,2:1 | 4,4:1 | 5,5:1 | ≥ 3:1 como marca ✔ |
| `--c-accent-text` | 7,0:1 | 5,9:1 | 5,5:1 | ≥ 4,5:1 como texto ✔ |
| `--c-positive` | 8,0:1 | 6,8:1 | 5,0:1 | ≥ 4,5:1 ✔ |
| `--c-negative` | 5,6:1 | 4,7:1 | 5,7:1 | ≥ 4,5:1 ✔ |
| `--c-warning` | 8,4:1 | 7,1:1 | 5,9:1 | ≥ 4,5:1 ✔ |
| `--c-info` | 8,2:1 | 6,9:1 | 5,8:1 | ≥ 4,5:1 ✔ |
| `--c-text-on-fill` sobre acento | 5,3:1 | — | 5,5:1 | ≥ 4,5:1 ✔ |

Nota: `--c-accent` a 4,4:1 sobre `--c-surface-2` no llega a 4,5:1, y por eso existe
`--c-accent-text`. **Los enlaces y el texto de acento usan `--c-accent-text`; los rellenos,
iconos y bordes usan `--c-accent`.** No se intercambian.

### 2.3 El color nunca es el único canal

Regla dura, aplicable en revisión de código:

| Significado | Color | + Segundo canal obligatorio |
|---|---|---|
| Ingreso | `--c-positive` | signo `+` explícito e icono `arrow-up-right` |
| Gasto | `--c-negative` | signo `-` explícito e icono `arrow-down-right` |
| Sobrepasado | `--c-negative` | icono `triangle-alert` + texto «Sobrepasado» + patrón 45° en la barra |
| Cerca del límite | `--c-warning` | icono `circle-alert` + texto «Al 92 %» |
| Subida de precio | `--c-negative` | `▲` + porcentaje con signo |
| Bajada de precio | `--c-positive` | `▼` + porcentaje con signo |
| Categoría | `--c-cat-n` | **siempre** el nombre de la temática junto al punto de color |
| Fila seleccionada | `--c-accent-wash` | borde izquierdo de 2 px + `aria-selected` |

### 2.4 Paleta categórica de 12

Doce hues, orden fijo, en dos juegos escalonados: uno para el fondo oscuro y otro para
el claro. **No es la misma lista aclarada; son dos selecciones validadas por separado.**

| Ranura | Hue | Oscuro | Claro | Uso típico inicial |
|---|---|---|---|---|
| 1 | azul | `#568EF9` | `#1E59CD` | Vivienda |
| 2 | naranja | `#C2520B` | `#DA682C` | Alimentación |
| 3 | cian | `#02A6AD` | `#06949A` | Transporte |
| 4 | rojo | `#CE3344` | `#E75F66` | Ocio |
| 5 | verde | `#3FAC4A` | `#026A1A` | Salud |
| 6 | magenta | `#B343AD` | `#CB5AC3` | Suscripciones |
| 7 | oro | `#AC9008` | `#AA8F02` | Ropa |
| 8 | violeta | `#6F5DDF` | `#5737C8` | Educación |
| 9 | turquesa | `#20A888` | `#08987A` | Mascotas |
| 10 | ámbar | `#9D6000` | `#CB862E` | Regalos |
| 11 | rosa | `#D36C9D` | `#D05B95` | Cuidado personal |
| 12 | azul acero | `#026FB9` | `#015590` | Impuestos |
| — | «Otros» | `#4A5462` | `#8593A4` | agregado, gris, nunca identidad |

**Validación.** Ambos juegos pasan las seis comprobaciones (banda de luminosidad OKLCH,
suelo de croma ≥ 0,10, separación bajo protanopía y deuteranopía simuladas
Machado–Oliveira–Fernandes a severidad 1,0, suelo de visión normal y contraste vs superficie):

- Oscuro sobre `#151A21`: peor par adyacente **ΔE 8,3** (deuteranopía), peor par en visión normal **ΔE 20,1**, contraste mínimo **3,31:1**.
- Claro sobre `#FFFFFF`: peor par adyacente **ΔE 8,3** (protanopía), peor par en visión normal **ΔE 18,6**, contraste mínimo **3,00:1**.

El mecanismo de seguridad es el **orden**, no los hues: las ranuras alternan luminosidad
alta/baja precisamente porque bajo daltonismo rojo-verde la luminosidad es el canal que
sobrevive. **Reordenar la lista rompe la validación.** Si alguna vez hay que tocarla, se
re-valida con el script del método (`validate_palette.js`, modos `light` y `dark` con las
superficies de este documento) antes de mezclarla.

**Orden de asignación.**

1. La temática recibe la primera ranura libre del orden 1→12 en el momento de crearse. Es una asignación **persistente**: se guarda en el registro de la temática (`colorSlot: number`), no se recalcula nunca.
2. El color sigue a la entidad, no a su posición en una lista. Filtrar, ordenar o esconder temáticas **no repinta** las demás.
3. Con más de 12 temáticas, la 13.ª y siguientes reciclan ranura empezando por la 1, y el usuario ve un aviso discreto: «Ya usas los 12 colores. Esta temática comparte color con Vivienda; puedes cambiarlo en Ajustes.» El chip siempre lleva nombre, así que no hay ambigüedad real.
4. Las **subcategorías heredan** el hue de su temática madre y se distinguen por luminosidad, no por hue: `color-mix(in oklab, var(--c-cat-n) X%, var(--c-track))` con X = 100, 78, 60, 46 para los cuatro primeros niveles. Es una rampa ordinal dentro de la temática y así se lee «esto pertenece a aquello».
5. Al **fusionar** dos temáticas, sobrevive la ranura de la temática destino; la ranura de la absorbida se libera y vuelve a la cola de asignación.

**Tope de series en gráficos.** La paleta de 12 es para **identidad de temática** en la
interfaz (chips, la BudgetBar, leyendas con nombre). En un gráfico, el tope duro es **8
series con nombre + «Otros»**; formas donde cualquier par puede quedar contiguo (dispersión,
burbujas, mapas de calor categóricos, múltiplos pequeños) bajan el tope a **3** y el resto
se pliega en «Otros» o se factoriza en múltiplos pequeños. Nunca se generan hues extra.

### 2.5 Rampa secuencial

Un solo hue, azul, `100 → 700`, para magnitud continua: mapa de calor de gasto por día del
mes, intensidad de uso de una temática, densidad de compras por comercio.

- **Oscuro:** más gasto = paso más claro (700 es el extremo «mucho»).
- **Claro:** más gasto = paso más oscuro (700 es el extremo «mucho»).
- Para rampas **ordinales** (tramos discretos ordenados, p. ej. «bajo / medio / alto / muy alto»), el paso más cercano a la superficie debe seguir distinguiéndose: **empieza en `--c-seq-300`** (2,4:1 en oscuro, 2,3:1 en claro). Los pasos 100–200 solo valen para escalas continuas donde «casi cero» puede fundirse con el fondo.

### 2.6 Rampa divergente

**Ámbar ↔ azul**, con gris neutro en el centro. Para variación de precio en mapas de calor
(qué productos han subido y cuánto, frente a los que han bajado), y para desvío frente a
presupuesto.

Elección deliberada: **verde ↔ rojo no es una escala divergente válida** porque colapsa
bajo daltonismo rojo-verde. Verde y rojo se reservan para el **texto y los indicadores de
delta**, donde siempre van acompañados de signo y flecha. Una escala continua no puede
llevar flechas en cada celda, así que ahí manda cálido↔frío.

### 2.7 Textura, el canal de reserva

Un solo relleno de rayas diagonales, a **45° y su espejo a 135°**, tono sobre tono. Se
activa con `prefers-contrast: more`, `forced-colors: active`, al imprimir o con el ajuste
«Reforzar patrones» de la app. Nunca decorativo. **Excepción permanente:** la zona
de exceso de presupuesto de la BudgetBar lleva rayas a 45° siempre, porque ahí el patrón
es parte del significado, no un refuerzo opcional.

---

## 3. Tipografía

### 3.1 Familias

```css
:root {
  --font-sans: "InterVariable", ui-sans-serif, system-ui, -apple-system,
               "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo,
               Consolas, monospace;
}
```

- **Sin Google Fonts en tiempo de ejecución.** Cero peticiones a terceros.
- `InterVariable` es **opcional y autoalojada**: `.woff2` variable, subconjunto `latin` + `latin-ext`, `font-display: swap`, `<link rel="preload" as="font" crossorigin>`. Si no está, la pila de sistema es un destino final aceptable, no un plan B degradado.
- **`--font-mono` solo** para identificadores que se comparan carácter a carácter: NIF/CIF, número de factura, IBAN, hash de importación. Nunca para importes.
- Sin fuentes display ni serif en ningún sitio, incluida la cifra héroe.

### 3.2 Escala modular

Base 16 px. Razón ≈ 1,2 en la zona de texto y saltos mayores arriba.

| Token | rem | px | Peso | Interlineado | Uso |
|---|---|---|---|---|---|
| `--t-hero` | 2.5rem | 40 | 600 | 1.05 | cifra héroe del Dashboard (una por vista) |
| `--t-display` | 1.75rem | 28 | 600 | 1.15 | importe grande en fichas y modales |
| `--t-h1` | 1.5rem | 24 | 600 | 1.25 | título de pantalla |
| `--t-h2` | 1.25rem | 20 | 600 | 1.3 | título de sección/tarjeta |
| `--t-h3` | 1.0625rem | 17 | 600 | 1.35 | subsección, cabecera de grupo |
| `--t-body` | 0.9375rem | 15 | 400 | 1.5 | texto por defecto, celdas de tabla |
| `--t-body-strong` | 0.9375rem | 15 | 600 | 1.5 | importes en fila, nombres de temática |
| `--t-sm` | 0.875rem | 14 | 400 | 1.45 | texto auxiliar, ayuda de campo |
| `--t-caption` | 0.8125rem | 13 | 500 | 1.4 | metadatos, fechas, contadores |
| `--t-micro` | 0.75rem | 12 | 600 | 1.35 | etiquetas de columna en versalitas, `letter-spacing: .04em` |

**12 px es el tamaño mínimo absoluto** y solo para etiquetas cortas no esenciales. Pesos
permitidos: 400, 500, 600, 700. **Nada por debajo de 400**: en fondo oscuro los pesos finos
se deshilachan por el halo de la subpíxel inversa.

### 3.3 Regla de números — no negociable

```css
.num,
[data-money],
th[data-numeric], td[data-numeric] {
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "zero" 0;
  text-align: right;
  white-space: nowrap;
}
```

1. **`tabular-nums` en toda cifra monetaria**, sin excepción: filas, tarjetas, tooltips, ejes, resúmenes, cifra héroe. Un importe cambia y la columna no debe moverse ni un píxel.
2. **Alineación a la derecha** para cualquier columna numérica de tabla, incluida la cabecera. La etiqueta de la columna se alinea con sus datos.
3. **La cifra héroe y los importes ≥ 28 px** llevan `letter-spacing: -0.012em` para compensar el aire que introducen las cifras de ancho fijo a tamaño grande. Así se conserva la alineación sin que el número parezca suelto.
4. **El símbolo € nunca se alinea**: va pegado al número con espacio duro (`1.234,56 €`), y la columna se alinea por el borde derecho del símbolo.
5. Los porcentajes siguen la misma regla; el signo (`+` / `-`) forma parte de la cifra y ocupa ancho de dígito, de modo que positivos y negativos alinean sus unidades.

---

## 4. Espaciado, forma, elevación y movimiento

### 4.1 Espaciado — escala de 4 px

```
--sp-0: 0      --sp-1: 4px    --sp-2: 8px    --sp-3: 12px   --sp-4: 16px
--sp-5: 20px   --sp-6: 24px   --sp-8: 32px   --sp-10: 40px  --sp-12: 48px
--sp-16: 64px  --sp-20: 80px
```

Convenciones fijas:

| Contexto | Valor |
|---|---|
| Relleno interno de tarjeta | `--sp-5` (20 px); en móvil `--sp-4` |
| Separación entre tarjetas | `--sp-4` |
| Relleno horizontal de celda de tabla | `--sp-3` |
| Altura de fila, densidad cómoda | 48 px |
| Altura de fila, densidad compacta | 36 px |
| Separación etiqueta ↔ campo | `--sp-2` |
| Separación entre campos de formulario | `--sp-4` |
| Margen de la zona de contenido | `--sp-6` escritorio · `--sp-4` móvil |
| Ancho máximo de columna de lectura | 68ch |

### 4.2 Radios

```
--r-xs: 3px    /* punto de categoría, marca de segmento */
--r-sm: 5px    /* badge, chip, celda de input pequeña */
--r-md: 7px    /* botón, input, select */
--r-lg: 10px   /* tarjeta, tooltip, popover */
--r-xl: 14px   /* modal, drawer, hoja inferior */
--r-bar: 4px   /* extremo de dato de una barra — coincide con el método de gráficos */
--r-full: 9999px /* avatar, chip de filtro activo, píldora de estado */
```

### 4.3 Elevación en modo oscuro

En oscuro **no se apila negro**: se sube la superficie, se dibuja un borde y se insinúa un
brillo superior de 1 px, como si la luz cayera desde arriba.

```css
--elev-0: none;                                    /* base, sobre app-bg */
--elev-1: inset 0 1px 0 0 rgb(255 255 255 / 0.045);/* tarjeta: + 1px borde */
--elev-2: inset 0 1px 0 0 rgb(255 255 255 / 0.07); /* elevada: popover, menú */
--elev-3: inset 0 1px 0 0 rgb(255 255 255 / 0.09),
          0 24px 48px -24px rgb(0 0 0 / 0.6);      /* SOLO capas flotantes */
--glow-accent:   0 0 0 1px var(--c-accent-ring), 0 0 24px -6px var(--c-accent-wash);
--glow-negative: 0 0 0 1px color-mix(in oklab, var(--c-negative) 55%, transparent);
```

Reglas:

- **Las tarjetas no llevan sombra.** Se separan del fondo por el paso de superficie (`--c-surface` sobre `--c-app-bg`) más un borde de 1 px `--c-border`.
- La sombra difusa de `--elev-3` está permitida **solo** en modal, drawer, popover y menú, siempre acompañada del scrim o del borde; su función es despegar la capa, no dramatizar.
- En tema claro sí se usa sombra convencional: `--elev-1: 0 1px 2px rgb(15 20 25 / .06)`, `--elev-2: 0 4px 12px -2px rgb(15 20 25 / .10)`, `--elev-3: 0 16px 32px -8px rgb(15 20 25 / .16)`.
- El **brillo** (`--glow-*`) es exclusivo del foco y de la alerta de exceso. No es decoración: si algo brilla, es porque reclama la atención del usuario.

### 4.4 Movimiento

```
--dur-instant: 80ms    /* cambio de estado de un control: hover, press */
--dur-fast:   120ms    /* tooltip, badge, cambio de icono */
--dur-base:   180ms    /* despliegue de fila, tabs, toast */
--dur-slow:   240ms    /* modal, drawer, hoja inferior */
--dur-bar:    320ms    /* recomposición de segmentos de la BudgetBar */

--ease-out:      cubic-bezier(0.22, 1, 0.36, 1);   /* entradas */
--ease-in:       cubic-bezier(0.4, 0, 1, 1);       /* salidas */
--ease-in-out:   cubic-bezier(0.4, 0, 0.2, 1);     /* movimientos internos */
--ease-emphasis: cubic-bezier(0.2, 0.9, 0.25, 1);  /* la BudgetBar al reasignar */
```

- Solo se animan `transform`, `opacity`, `width`, `background-color`, `border-color` y `box-shadow`. Nada que provoque `layout` en cada fotograma salvo el ancho de los segmentos de la BudgetBar, que está aislado en su propio contenedor con `contain: layout paint`.
- **Sin animaciones de entrada en listas ni tablas.** Los datos aparecen, no desfilan.
- **Recarga de datos:** el render anterior se mantiene a `opacity: .55`; nunca se vuelve al skeleton. Sin saltos de maquetación.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  /* Excepción intencionada: los fundidos de opacidad puros se conservan a 100 ms.
     Eliminarlos hace que los cambios de estado pasen desapercibidos, lo cual
     empeora la accesibilidad en vez de mejorarla. */
  .fade-only { transition-duration: 100ms !important; }
}
```

Con movimiento reducido, la BudgetBar **no interpola** anchos: los aplica de golpe y anuncia
el cambio por `aria-live="polite"`. El arrastre de reasignación sigue funcionando; lo que
desaparece es el rebote de asentamiento.

---

## 5. Componentes

Convenciones comunes a todos:

- **Foco:** `outline: 2px solid var(--c-accent); outline-offset: 2px;` mediante `:focus-visible`. Nunca `outline: none` sin sustituto. En superficies de acento el anillo pasa a `--c-text-1` para conservar contraste.
- **Deshabilitado:** `--c-text-disabled` + `cursor: not-allowed` + `aria-disabled="true"`. Un control deshabilitado **sigue siendo enfocable** si su motivo hay que explicarlo; si no, se retira del orden de tabulación.
- **Toque:** área efectiva mínima **44 × 44 px** en cualquier punto de entrada, aunque el pintado sea menor (se consigue con pseudo-elemento, no agrandando el borde visible).
- **Carga:** el control conserva su ancho, sustituye la etiqueta por un `loader-2` girando y expone `aria-busy="true"`.

### 5.1 Botón

**Anatomía:** `[icono 16px] · etiqueta · [icono 16px] · [contador]`. Alturas: `sm 32px`,
`md 40px` (por defecto), `lg 48px`. Relleno horizontal `--sp-4`; con icono, `--sp-3` del
lado del icono. Radio `--r-md`. Peso 600.

**Variantes**

| Variante | Relleno | Texto | Borde | Cuándo |
|---|---|---|---|---|
| `primary` | `--c-accent` | `--c-text-on-fill` | ninguno | acción principal, **una por vista** |
| `secondary` | `--c-surface-3` | `--c-text-1` | `--c-border` | acción de apoyo |
| `ghost` | transparente | `--c-text-2` | ninguno | acciones de fila y barra de herramientas |
| `outline` | transparente | `--c-text-1` | `--c-border-strong` | alternativa a primaria en modales |
| `danger` | `--c-negative` | `--c-text-on-fill` | ninguno | destructiva confirmada |
| `danger-ghost` | transparente | `--c-negative` | ninguno | destructiva en fila (con confirmación) |
| `link` | — | `--c-accent-text` | subrayado en hover | navegación en línea |

**Estados:** *default* → *hover* (relleno un paso más claro, `--dur-instant`) → *focus-visible*
(anillo de acento, el relleno no cambia) → *active* (`--c-accent-press` + `transform: translateY(.5px)`) →
*disabled* (`--c-surface-3` + texto deshabilitado, sin hover) → *loading* (spinner, ancho
congelado, no clicable) → *error* (no existe estado de error en el botón; el error vive en el
formulario o en un toast).

**Accesibilidad:** `<button type>` real siempre. Un botón solo con icono lleva `aria-label`
y tooltip. Los botones destructivos **no** son la acción por defecto de un formulario y
nunca reciben el foco inicial de un modal.

### 5.2 Input (texto)

**Anatomía:** etiqueta (arriba, `--t-sm`, `--c-text-2`) · campo (40 px, `--c-surface-2`,
borde `--c-border`, radio `--r-md`, relleno `--sp-3`) · afijo opcional (icono o unidad) ·
línea de ayuda (`--t-caption`, `--c-text-3`) · contador de caracteres opcional a la derecha.

**Estados:** default · hover (`--c-border-strong`) · focus (borde `--c-accent` + anillo) ·
relleno (`--c-text-1`) · placeholder (`--c-text-3`, nunca sustituye a la etiqueta) ·
disabled (`--c-surface`, texto deshabilitado) · readonly (sin borde, fondo `--c-surface`) ·
loading (spinner en el afijo derecho, p. ej. validación de IBAN) · **error** (borde
`--c-negative` + icono `circle-alert` + mensaje que reemplaza la ayuda) · success (icono
`check` verde, sin borde de color: el verde en bordes se reserva para lo excepcional).

**Accesibilidad:** `<label for>` explícito; **nunca solo placeholder**. El mensaje de error
se vincula con `aria-describedby` y el campo lleva `aria-invalid="true"`. Al enviar con
errores, el foco va al primer campo inválido y el resumen se anuncia por `role="alert"`.

### 5.3 Select

**Anatomía:** disparador idéntico a un input + `chevron-down` a la derecha · lista flotante
(`--c-surface-2`, `--elev-3`, radio `--r-lg`, máx. 320 px de alto con scroll) · opción
(36 px, `check` de 16 px a la izquierda cuando está seleccionada) · grupos con cabecera
`--t-micro` · buscador interno automático a partir de 8 opciones.

**Estados:** cerrado · hover · abierto (borde de acento) · opción hover (`--c-surface-3`) ·
opción seleccionada (`--c-accent-wash` + check) · vacío («Sin resultados») · disabled ·
loading (tres filas skeleton dentro de la lista).

**Accesibilidad:** patrón *combobox* de ARIA: `role="combobox"`, `aria-expanded`,
`aria-controls`, `aria-activedescendant`; lista `role="listbox"`, opciones `role="option"`
con `aria-selected`. Teclado: `↑ ↓` mueve, `Home/End` extremos, letra salta, `Enter`
confirma, `Esc` cierra y devuelve el foco al disparador, `Tab` cierra confirmando.

### 5.4 DatePicker

**Anatomía:** input con máscara `dd/mm/aaaa` + botón `calendar` · panel con **columna de
atajos a la izquierda** (Hoy, Ayer, Esta semana, Este mes, Mes anterior, Últimos 30 días,
Personalizado) y rejilla mensual a la derecha · pie con «Borrar» y «Aplicar».

**Detalles:** semana empieza en **lunes**; cabeceras `L M X J V S D`; fines de semana en
`--c-text-3`; hoy con borde de acento de 1 px; seleccionado con relleno de acento; rango con
`--c-accent-wash` y extremos rellenos; días de otros meses ocultos, no atenuados. Los días
con transacciones llevan un punto de 3 px debajo.

**Estados:** cerrado · abierto · rango en curso (segundo extremo sigue al puntero) ·
fuera de rango permitido (deshabilitado con explicación en tooltip) · error de máscara
(«Introduce una fecha con el formato 13/08/2026»).

**Accesibilidad:** `role="dialog"` con `aria-modal="false"` y `aria-label="Elegir fecha"`;
la rejilla es `role="grid"` con `gridcell`; `PageUp/PageDown` cambian de mes,
`Shift+PageUp/PageDown` de año; el día enfocado se anuncia completo («jueves, 13 de agosto
de 2026, 3 transacciones»). **Escribir la fecha a mano siempre funciona**: el calendario es
un atajo, no la única vía.

### 5.5 Campo de importe (máscara EUR)

El control más usado de la aplicación. Merece reglas propias.

**Anatomía:** etiqueta · campo con **€ como sufijo fijo** (`--c-text-3`, no editable, fuera
del área de texto) · valor alineado a la **derecha**, `--t-display` en el modal rápido y
`--t-body-strong` en formularios largos, siempre `tabular-nums` · fila de teclas de atajo
opcional (`+10`, `+50`, `+100`, `C`).

**Comportamiento de la máscara**

1. `inputmode="decimal"`, `autocomplete="off"`, `enterkeyhint="done"`. En móvil sale el teclado numérico con coma.
2. Se acepta **coma o punto** como separador decimal; internamente siempre coma. El punto tecleado se convierte en coma salvo que ya haya una coma, caso en que se ignora.
3. Los **separadores de millar se insertan al escribir** (`1.234,5`) y el cursor se mantiene en su posición lógica, no en la de caracteres.
4. Máximo **2 decimales**; el tercero no se acepta. Al perder el foco se normaliza: `12` → `12,00`, `12,5` → `12,50`, vacío → vacío (no `0,00`).
5. **Se admite aritmética simple**: si el usuario escribe `12,50+3,20` y sale del campo, el valor pasa a `15,70` y se muestra durante 2 s un rótulo «12,50 + 3,20». Es lo que hace todo el mundo al repartir una cuenta.
6. El valor se guarda en **céntimos enteros** (`number`), nunca en coma flotante de euros.
7. Los negativos no se teclean: el signo lo determina el tipo de movimiento (gasto/ingreso). Si se pega un valor con `-`, se ignora el signo y se avisa.

**Estados:** vacío (placeholder `0,00`) · escribiendo (sin validación aún) · válido ·
**error** («Introduce un importe mayor que 0») · límite superado («El importe no puede pasar
de 999.999,99 €») · calculando (tras una expresión) · disabled · readonly (se pinta como
texto plano, sin caja).

**Accesibilidad:** `aria-describedby` apunta a la ayuda del formato; el valor normalizado se
anuncia al salir del campo (`aria-live="polite"`); el sufijo € está en el `<label>` accesible,
así que un lector de pantalla lee «Importe en euros, 15,70».

### 5.6 Tabla de datos

**Anatomía:** barra de herramientas (búsqueda, filtros, densidad, columnas, exportar) ·
cabecera pegajosa (`--c-surface`, borde inferior `--c-border`) · filas (borde inferior
`--c-border-soft`) · fila expandible · pie con totales · paginación.

**Especificación**

| Aspecto | Regla |
|---|---|
| Densidad | `cómoda` 48 px · `compacta` 36 px. La elección se recuerda por usuario y tabla. |
| Cabecera | `--t-micro` en versalitas, `--c-text-3`. Pegajosa con `position: sticky; top: 0`. |
| Orden | Clic en la cabecera: asc → desc → sin orden. Icono `arrow-up` / `arrow-down` a la derecha del rótulo, siempre visible en la columna activa y en hover en las demás. `aria-sort` en el `<th>`. |
| Columnas numéricas | Alineadas a la derecha, `tabular-nums`, cabecera también a la derecha. |
| Zebra | **No.** Separadores de 1 px; el rayado es ruido en densidad alta. |
| Hover de fila | `--c-surface-3`, sin desplazamiento. |
| Selección | Casilla en la primera columna, borde izquierdo de 2 px en acento, `aria-selected`. Cabecera con casilla de tres estados. |
| Columna fija | La primera columna de texto y la última de acciones se fijan al hacer scroll horizontal, con un borde `--c-border-strong` de separación. |
| Fila expandible | Botón `chevron-right` de 32 px en la primera celda; al abrir gira a `chevron-down`. El detalle se inserta como una fila hija con fondo `--c-surface-sunken` y relleno `--sp-4`. Altura animada `--dur-base`. Varias filas pueden estar abiertas a la vez. |
| Pie de totales | Fila fija abajo, `--c-surface`, borde superior `--c-border-strong`, peso 600. Refleja **el filtro activo**, no el total absoluto, y lo dice: «Total de 42 resultados filtrados». |
| Móvil | La tabla se convierte en tarjetas: título (concepto), importe a la derecha, dos líneas de metadatos, chevron de detalle. Nunca scroll horizontal en móvil. |

**Estados:** cargando (8 filas skeleton con las anchuras reales de columna) · recargando
(contenido anterior al 55 % de opacidad) · vacío por falta de datos · vacío por filtro
(con botón «Quitar filtros») · error de carga (fila única con mensaje y «Reintentar»).

**Accesibilidad:** `<table>` semántica con `<caption>` (puede ser visualmente oculta),
`scope="col"`. El botón de expandir lleva `aria-expanded` y `aria-controls`. Navegación por
celdas no se implementa a mano: se usa el modo de tabla nativo del lector de pantalla.

### 5.7 Modal

**Anatomía:** scrim (`--c-overlay`, `backdrop-filter: blur(2px)`) · contenedor
(`--c-surface-2`, radio `--r-xl`, `--elev-3`, anchos `sm 420` / `md 560` / `lg 720` /
`xl 960`) · cabecera (título `--t-h2`, subtítulo opcional, cierre `x` de 40 px) · cuerpo
(scroll propio, `max-height: calc(100dvh - 160px)`) · pie (acciones a la derecha, secundaria
primero por lectura natural en español).

**Estados:** entrando (`opacity 0→1`, `scale .98→1`, `--dur-slow --ease-out`) · abierto ·
cuerpo con scroll (aparecen bordes de 1 px arriba y abajo del cuerpo para indicar corte) ·
guardando (primaria en loading, resto deshabilitado, cierre bloqueado) · error (banda
`--c-negative-wash` bajo la cabecera) · saliendo.

**Accesibilidad:** `role="dialog"` + `aria-modal="true"` + `aria-labelledby`. Foco atrapado;
al abrir va al primer campo o, si no hay, al contenedor; al cerrar vuelve al disparador.
`Esc` cierra **salvo** si hay cambios sin guardar, y entonces se pregunta. `inert` en el
resto de la app. Scroll del `body` bloqueado sin salto de anchura (compensar la barra).

### 5.8 Drawer (panel lateral)

Igual que el modal en semántica, distinto en propósito: **el drawer conserva el contexto de
la lista que hay detrás**; se usa para el detalle de una transacción, de una factura o de
un producto.

**Anatomía:** panel derecho de 420 px (`lg 560`), altura completa, radio solo a la izquierda,
borde izquierdo `--c-border`, `--elev-3` · cabecera pegajosa con título, subtítulo y cierre ·
cuerpo con scroll · pie de acciones opcional · **navegación entre elementos**: `↑`/`↓` o los
botones `chevron-up`/`chevron-down` en la cabecera pasan al anterior/siguiente de la lista
sin cerrar el panel.

**Estados:** entrando (`translateX(100%)→0`) · abierto · cargando (skeleton dentro del panel,
la cabecera con el título ya conocido) · error · saliendo. En móvil pasa a **hoja inferior**
al 92 % de alto, con asa de arrastre y cierre por gesto hacia abajo.

**Accesibilidad:** `role="dialog"` con `aria-modal="true"` cuando bloquea; si es un panel de
inspección no bloqueante, `aria-modal="false"` y foco no atrapado. La opción por defecto en
esta app es **no bloqueante en escritorio** y bloqueante en móvil.

### 5.9 Toast

**Anatomía:** contenedor 360 px máx., `--c-surface-2`, borde de 1 px, `--elev-3`, radio
`--r-lg`, apilado **abajo a la derecha** en escritorio y **arriba** en móvil (para no tapar
el botón de añadir gasto). Icono de 16 px a la izquierda según tipo · mensaje `--t-sm` ·
acción opcional en `link` · cierre `x`.

**Tipos y duración:** éxito 4 s · info 5 s · aviso 7 s · error **no se cierra solo**.
Máximo 3 visibles; el resto se encola. Se pausa al pasar el puntero o al recibir el foco.

**Estados:** entrando (`translateY(8px)` + fundido) · visible · con temporizador (línea de
progreso de 2 px en el borde inferior, en el color del tipo) · pausado · saliendo.

**Accesibilidad:** región `role="status"` `aria-live="polite"` para éxito e info;
`role="alert"` `aria-live="assertive"` para error. Nunca se roba el foco. Si el toast lleva
una acción imprescindible (**«Deshacer»**), esa acción está además disponible en la
interfaz: un toast no puede ser el único camino.

### 5.10 Tabs

**Anatomía:** lista horizontal, pestaña de 40 px, relleno `--sp-3`, peso 500 inactiva y 600
activa · indicador inferior de 2 px en `--c-accent` que se desliza `--dur-base` · contador
opcional en badge · borde inferior de 1 px `--c-border` a lo largo de toda la fila.

**Estados:** inactiva (`--c-text-2`) · hover (`--c-text-1` + subrayado al 30 %) · activa
(`--c-text-1` + indicador) · focus-visible (anillo alrededor de la pestaña, no del
indicador) · disabled · con desbordamiento (flechas de desplazamiento en escritorio, scroll
con desvanecido lateral en móvil).

**Accesibilidad:** `role="tablist"` / `tab` / `tabpanel`, `aria-selected`, `aria-controls`.
Activación **manual** (`Enter`/`Espacio`), no automática al mover el foco, porque cada
pestaña dispara una consulta. `←`/`→` mueven, `Home`/`End` a los extremos. El panel es
enfocable (`tabindex="-1"`) para que `Tab` desde la pestaña entre en el contenido.

### 5.11 Badge y chip de categoría

Son dos cosas y conviene no mezclarlas.

**Badge (estado):** 20 px de alto, radio `--r-sm`, `--t-caption` peso 600, relleno
`--sp-1 --sp-2`, fondo `*-wash`, texto en el color semántico, **icono de 12 px obligatorio**.
Variantes: neutro, positivo, negativo, aviso, info. Ejemplos: «Pendiente», «Conciliado»,
«Sobrepasado», «Recurrente».

**Chip de categoría (identidad):** 24 px de alto, radio `--r-full`, **punto de 8 px** en
`--c-cat-n` a la izquierda + nombre en `--c-text-1`, fondo `--c-surface-3`, borde
`--c-border-soft`. Para subcategorías, el nombre se muestra como `Madre · Hija` con la madre
en `--c-text-3`.

**Reglas:** el chip **nunca** colorea su texto con el hue de la categoría (ilegible y rompe
la jerarquía); el color vive en el punto. El chip de categoría **siempre lleva nombre**: es
lo que hace segura una paleta de 12. Variante `removable` con `x` de 16 px y área de toque
de 24 px, `aria-label="Quitar filtro Alimentación"`. Variante `selectable` (filtros) con
estado `aria-pressed`.

### 5.12 Tooltip

**Anatomía:** `--c-surface-2`, borde 1 px, radio `--r-lg`, relleno `--sp-2 --sp-3`,
`--t-caption`, `--elev-3`, ancho máx. 280 px, flecha de 6 px opcional. Retardo de apertura
**400 ms**, de cierre **80 ms**; sin retardo si ya hay un tooltip abierto en el mismo grupo.

**Estados:** oculto · apareciendo (fundido + `translateY(2px)`) · visible · reposicionado
(colisión con el borde de la ventana: voltea eje y luego desplaza) · táctil (en táctil no hay
hover: el tooltip se convierte en `popover` al pulsar, o la información se muestra en línea).

**Accesibilidad:** se conecta con `aria-describedby`; **jamás contiene información que no
esté en otro sitio** ni controles interactivos (para eso, popover). Aparece también con
`:focus-visible`, no solo con el puntero. Se cierra con `Esc`.

### 5.13 Skeleton

**Anatomía:** bloques `--c-surface-3` con radio `--r-sm` que replican la **geometría real**
del contenido: altura de línea de texto 14 px, importe 15 px de alto y ancho 88 px, avatar
circular, barra 40 px. Animación: barrido de gradiente de 1,4 s hacia la derecha; con
`prefers-reduced-motion`, opacidad estática al 60 % sin barrido.

**Reglas:** se usa **solo en la primera carga** de una zona. En recargas se mantiene el
contenido anterior atenuado. Nunca más de 8 filas de skeleton. El contenedor lleva
`aria-busy="true"` y un texto oculto «Cargando transacciones». Prohibido el destello: si la
respuesta llega antes de 200 ms, el skeleton no se muestra.

### 5.14 Empty state

**Anatomía:** icono Lucide de 32 px trazo 1,5 en `--c-text-3` (no ilustración) · título
`--t-h3` · explicación de una o dos líneas `--t-sm` en `--c-text-2` · acción primaria ·
enlace secundario de ayuda opcional. Centrado, `max-width: 42ch`, relleno vertical `--sp-12`.

**Cuatro tipos, no uno:**

| Tipo | Diferencia clave |
|---|---|
| Primer uso | Explica qué aparecerá aquí y ofrece la acción que lo crea. |
| Sin resultados de filtro | Repite el criterio aplicado y ofrece «Quitar filtros». |
| Sin resultados de búsqueda | Muestra el término buscado y sugiere corregirlo. |
| Error | Icono en `--c-negative`, causa comprensible y «Reintentar». |

**Accesibilidad:** el título es un encabezado real del nivel que corresponda; el estado se
anuncia con `role="status"` al aparecer tras una acción del usuario.

### 5.15 Barra de navegación lateral

**Anatomía:** 240 px expandida / 64 px colapsada, `--c-app-bg` con borde derecho
`--c-border` · logotipo y nombre arriba (56 px) · **selector de mes** justo debajo, porque
es el ámbito de casi todo · grupos de navegación con cabecera `--t-micro` · elemento de 40 px
con icono de 18 px + etiqueta + contador opcional · abajo: tema, ajustes y menú de usuario.

**Estados de elemento:** default (`--c-text-2`) · hover (`--c-surface-3` + `--c-text-1`) ·
**activo** (`--c-surface-3`, `--c-text-1`, barra izquierda de 3 px en `--c-accent` y icono
en `--c-accent`) · focus-visible · colapsado (solo icono, tooltip a la derecha con retardo 0).

**Estructura:** Resumen · Transacciones · Temáticas · Facturas · Productos · Informes.
Fuera del grupo, arriba y destacado, el botón **«Añadir gasto»** a ancho completo.

**Responsive:** ≥1280 px expandida · 1024–1279 px colapsada con expansión al pasar el puntero
(en superposición, sin desplazar el contenido) · <1024 px oculta tras `menu`, se abre como
drawer izquierdo · <768 px se sustituye por **barra inferior de 5 destinos** de 56 px con
etiquetas de 11 px, y el botón de añadir gasto pasa a botón flotante de 56 px.

**Accesibilidad:** `<nav aria-label="Navegación principal">` con `<ul>`; el activo lleva
`aria-current="page"`. Enlace «Saltar al contenido» como primer elemento tabulable del
documento.

### 5.16 Avatar y menú de usuario

**Anatomía:** avatar circular 32 px (28 en barra densa, 40 en ajustes); si no hay imagen,
iniciales en `--t-caption` peso 600 sobre `--c-surface-3` con **borde de 1 px en el hue de
categoría derivado del identificador** (color determinista, nunca aleatorio por render).
Disparador: avatar + nombre + `chevron-down` (solo avatar en barra colapsada).

**Menú:** `--c-surface-2`, `--elev-3`, 240 px. Cabecera con nombre y correo (`--c-text-3`,
truncado con tooltip) · «Mi perfil» · «Ajustes» · conmutador de tema con tres opciones
(Oscuro / Claro / Según el sistema) · «Ayuda» · separador · «Cerrar sesión» en
`danger-ghost`.

**Estados:** cerrado · abierto · cargando imagen (skeleton circular) · imagen fallida
(iniciales, sin icono roto) · sesión a punto de caducar (punto de aviso de 6 px sobre el
avatar + entrada «Tu sesión caduca en 4 min. Renovar»).

**Accesibilidad:** `role="menu"` / `menuitem`, `aria-haspopup="menu"`, `aria-expanded`.
Teclado: `↑ ↓` recorre, `Enter` activa, `Esc` cierra y devuelve el foco. El conmutador de
tema es un `radiogroup` dentro del menú.

### 5.17 Paginación

**Anatomía:** a la izquierda, «Mostrando 1–50 de 1.284» en `--t-caption` · a la derecha,
selector de tamaño de página (25/50/100/200), `chevron-left`, números, `chevron-right`.
Botón numérico de 32 px, activo con relleno de acento.

**Reglas:** máximo 7 números visibles con elisión (`1 … 4 5 6 … 43`). Al cambiar de página, el
scroll sube al inicio de la tabla, no del documento. La página vive en la URL para poder
compartir el enlace. Para listas muy largas se ofrece además «Cargar 50 más», pero **la
paginación numérica no se elimina**: sin ella no se puede llegar al final de un año de
transacciones.

**Estados:** default · hover · activo · disabled (primera/última) · cargando (números al
55 % de opacidad, el activo con spinner) · página única (el bloque de números desaparece y
solo queda el contador).

**Accesibilidad:** `<nav aria-label="Paginación">`; el actual lleva `aria-current="page"`;
las flechas tienen `aria-label` («Página anterior»). El cambio de página se anuncia por
`aria-live="polite"`: «Página 3 de 26».

### 5.18 Barra de búsqueda con filtros

**Anatomía en una fila** (según la regla de composición: **una sola fila de filtros encima
de todo lo que afecta**):

```
[search  Buscar concepto, comercio o importe…    ][ Mes ▾ ][ Temática ▾ ][ Cuenta ▾ ][ Más filtros ▾ ]  [Guardar vista]
```

Debajo, si hay filtros aplicados, una fila de chips eliminables + «Quitar todos».

**Comportamiento:** búsqueda con retardo de 250 ms, mínimo 2 caracteres, `x` para limpiar,
`/` la enfoca desde cualquier parte, `Esc` la limpia y devuelve el foco a la lista. Si el
término parece un importe (`12,50`), se busca también por importe exacto y por rango ±0,05 €
y se explica en un rótulo: «Buscando “12,50” en conceptos e importes».

**«Más filtros»** abre un popover con: rango de importe (dos campos), tipo (gasto/ingreso/
transferencia), etiquetas, «solo recurrentes», «solo con factura», «solo sin categorizar».
Cada filtro aplicado suma un chip. El conjunto se puede **guardar como vista** con nombre y
aparece en la barra lateral.

**Estados:** vacía · escribiendo · buscando (spinner en el afijo) · con resultados (contador
junto a la búsqueda) · sin resultados · filtros activos (el botón «Más filtros» muestra un
badge con el número) · vista guardada modificada (badge «Modificada» + «Restablecer»).

**Accesibilidad:** `role="search"` en el contenedor; el campo es un `combobox` cuando ofrece
sugerencias; el número de resultados se anuncia por `aria-live="polite"` tras la
estabilización. Los filtros se reflejan en la URL para que un enlace reproduzca el estado.

---

## 6. `BudgetBar` — el componente estrella

Es la idea de producto convertida en un solo objeto visual: **los ingresos del mes como una
barra que se reparte por temáticas y se va consumiendo con el uso.** Todo lo demás en la
aplicación es un detalle de esta barra.

### 6.1 Modelo de datos que representa

```ts
interface BudgetBarData {
  ingresos: number          // céntimos; el 100 % del carril
  categorias: Array<{
    id: string
    nombre: string
    colorSlot: number       // 1..12
    asignado: number        // céntimos reservados este mes
    gastado: number         // céntimos ya gastados
    bloqueado?: boolean     // no reasignable arrastrando (p. ej. hipoteca)
  }>
  diaActual: number
  diasDelMes: number
}
```

Derivados: `asignadoTotal = Σ asignado` · `gastadoTotal = Σ gastado` ·
`sinAsignar = ingresos − asignadoTotal` · `excesoCat = max(0, gastado − asignado)` ·
`sobreasignado = max(0, asignadoTotal − ingresos)`.

### 6.2 Las tres capas de codificación

Una única barra lleva tres informaciones sin convertirse en un jeroglífico, porque cada una
usa un canal distinto:

| Información | Canal | Aspecto |
|---|---|---|
| **Asignado** por temática | **anchura** del segmento | `asignado / D`, donde `D = max(ingresos, asignadoTotal)` |
| **Gastado** dentro de lo asignado | **saturación** dentro del segmento | relleno sólido `--c-cat-n` desde el borde izquierdo del segmento, ancho `min(gastado, asignado) / asignado`; el resto es el mismo hue al 22 % sobre `--c-track` |
| **Sin asignar** | color neutro | cola en `--c-track` con borde interior de 1 px `--c-border-strong` |
| **Exceso** de una temática | **carril superior + patrón** | cresta de 6 px sobre el segmento, en `--c-negative` con rayas a 45°, ancho `min(exceso / asignado, 1)` del segmento |
| **Ritmo del mes** | **marca vertical** | línea de 2 px `--c-text-3` al `diaActual / diasDelMes` del ancho útil, con etiqueta «Día 13 de 31» |

Separación entre segmentos: **hueco de 2 px del color de la superficie**, nunca un borde
dibujado. Radio: `--r-bar` (4 px) solo en los extremos exteriores del carril; los cortes
internos son rectos.

### 6.3 Geometría

| Medida | Escritorio | Tableta | Móvil |
|---|---|---|---|
| Alto del carril | 44 px | 40 px | 28 px |
| Alto de la cresta de exceso | 6 px | 6 px | 4 px |
| Hueco entre segmentos | 2 px | 2 px | 2 px |
| Ancho mínimo de segmento | 24 px (para poder arrastrar) | 20 px | 8 px |
| Radio exterior | 8 px | 8 px | 6 px |
| Etiqueta interna | si caben ≥ 8 caracteres con 8 px de aire a cada lado | igual | nunca |

Con 2 o 3 temáticas el carril **sube a 56 px** y las etiquetas van dentro con nombre e
importe. No es un capricho: con pocos segmentos, la barra puede hacer el trabajo de una
tarjeta y ahorrar una lectura.

### 6.4 Estados con diagramas

#### A. Estado sano — presupuesto asignado y consumido en parte

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Agosto 2026                                                    Ingresos del mes │
│ 2.450,00 €                                                                       │
│ Asignado 2.150,00 €  ·  Gastado 1.312,45 €  ·  Disponible 837,55 €              │
│                                                                                  │
│                                            ▏Día 13 de 31                         │
│ ┌────────────────────────────────────────┬─┬─────────────────────────────────┐   │
│ │████████████████░░░░░░░░│██████░░░░░░│██│█░░░░░│███░░│░░░░░░░░░░░░░░░░░░░░░░│   │
│ │ Vivienda        850 €  │ Alimenta… │Tr│ Ocio │Sal…│      Sin asignar      │   │
│ └────────────────────────────────────────┴─┴─────────────────────────────────┘   │
│   ██ gastado   ░░ asignado sin gastar   ▒▒ sin asignar                           │
│                                                                                  │
│ ● Vivienda 612/850 €  ● Alimentación 385/520 €  ● Transporte 118/180 €           │
│ ● Ocio 142/300 €      ● Salud 55/300 €          ▪ Sin asignar 300 €              │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Lectura en un segundo: el ancho es lo que reservé, la parte sólida es lo que ya me he
gastado, la cola gris es lo que aún no he decidido, y la marca de día me dice si voy
adelantado o retrasado respecto al ritmo del mes.

#### B. Una temática sobrepasada

```
                                             ▏Día 22 de 31
                    ╱╱╱╱╱╱                                        ← cresta de exceso
 ┌────────────────┬────────────┬────┬────────┬───────────────────────────────┐
 │████████████░░░░│████████████│████│███░░░░░│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
 │ Vivienda       │ Alimenta…  │Tra…│ Ocio   │          Sin asignar          │
 └────────────────┴────────────┴────┴────────┴───────────────────────────────┘
                     ▲ 68,40 € de más

 ⚠ Alimentación sobrepasada en 68,40 €        [ Reasignar ]  [ Ver movimientos ]
```

El segmento sobrepasado: relleno sólido al 100 %, **borde superior de 2 px en
`--c-negative`**, cresta rayada encima proporcional al exceso, icono `triangle-alert` de
12 px pegado al borde derecho del segmento, y el importe del exceso como etiqueta bajo el
carril. En la leyenda su entrada pasa a `520/520 € · +68,40 €` con badge «Sobrepasado».
Cuatro canales: color, borde, patrón e icono con texto.

#### C. Sobreasignación — has repartido más de lo que ingresas

```
 Asignado 2.700,00 €  de  2.450,00 €          ⚠ Has asignado 250,00 € más de lo que ingresas

 ┌──────────────────────────────────────────────────────────────────┬───────────┐
 │████████░░░░│██████░░░│███░│██░░░░░│████████░░░░░░░░░░░░░░░░░░░░░│╱╱╱╱╱╱╱╱╱╱╱│
 │ Vivienda   │ Aliment │Tra…│ Ocio  │ Ahorro                      │ De más    │
 └──────────────────────────────────────────────────────────────────┴───────────┘
                                       ┊ límite de ingresos ─────────┘
```

El denominador pasa a ser `asignadoTotal`, así que todo se comprime y aparece a la derecha
una zona rayada «De más». Una **línea vertical punteada de 1 px** marca dónde acababan los
ingresos: es el dato importante y no debe desaparecer al comprimir. La cabecera muestra
`Asignado X de Y` en `--c-warning`, no en rojo: sobreasignar es un plan arriesgado, no un
error consumado.

#### D. Gasto total por encima de los ingresos

```
 Gastado 2.612,00 €  ·  Ingresos 2.450,00 €          ⚠ Este mes gastas 162,00 € más de lo que ingresas

 ┌──────────────────────────────────────────────────────────────────┬───────────┐
 │███████████│█████████│█████│███████│██████████████████████████████│╱╱╱╱╱╱╱╱╱╱╱│
 │ Vivienda  │ Aliment │ Tra…│ Ocio  │ Suscripciones                │ En rojo   │
 └──────────────────────────────────────────────────────────────────┴───────────┘
```

Todos los segmentos llenos, sin zona clara, y una cola `--c-negative` rayada. El fondo de
la tarjeta gana un borde de 1 px en `--c-negative` y un `--glow-negative` muy tenue. Es el
único momento en que la barra alza la voz.

#### E. Solo 2 temáticas — carril alto y etiquetas dentro

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                                                                             │
 │  Vivienda                             │  Todo lo demás                      │
 │  ████████████████████████░░░░░░░░░░░░ │  ██████████░░░░░░░░░░░░░░░░░░░░░░░░ │
 │  980,00 € de 1.400,00 €   70 %        │  310,00 € de 1.050,00 €   30 %      │
 └─────────────────────────────────────────────────────────────────────────────┘
```

Carril de 56 px, nombre arriba a la izquierda, importe y porcentaje abajo. El porcentaje es
**del total del presupuesto**, no del segmento, y así se dice en el tooltip para que no haya
duda.

#### F. 15 temáticas — plegado a 8 + «Otros»

```
                                                    ▏Día 13 de 31
 ┌──┬──┬─┬─┬──┬─┬─┬──┬─────────────────────┬──────────────────────────────────┐
 │██│█░│█│░│█░│█│░│██│░░░░░░░░░░░░░░░░░░░░░│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
 └──┴──┴─┴─┴──┴─┴─┴──┴─────────────────────┴──────────────────────────────────┘
                        ▲ Otros (7)                    ▲ Sin asignar

 ● Vivienda 850 €   ● Alimentación 520 €  ● Transporte 180 €  ● Ocio 300 €
 ● Salud 120 €      ● Suscripciones 95 €  ● Ropa 80 €        ● Educación 60 €
 ▪ Otros (7) 145 €  ▪ Sin asignar 100 €                        [ Ver todas ]
```

**Algoritmo de plegado**, determinista:

1. Ordena por `asignado` descendente.
2. Mientras haya más de 8 segmentos con nombre **o** algún segmento por debajo del 3 % del ancho, mueve el más pequeño a «Otros».
3. «Otros» va siempre en penúltima posición, antes de «Sin asignar», en `--c-cat-other` (gris). **Nunca recibe un hue.**
4. Al pulsar «Otros» el segmento se expande *in situ*: la barra se sustituye por una segunda BudgetBar anidada con solo esas temáticas, con una miga «Presupuesto › Otros (7)» y botón de volver. Sin cambiar de pantalla.
5. Una temática **sobrepasada nunca se plega**, aunque sea diminuta: si tiene exceso, tiene sitio propio. Esa es la excepción explícita al punto 2.

#### G. Sin presupuesto asignado — estado inicial

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ Agosto 2026                                                                  │
 │ 2.450,00 €  de ingresos sin repartir                                         │
 │                                                                              │
 │ ┌──────────────────────────────────────────────────────────────────────────┐ │
 │ │                        Sin asignar · 2.450,00 €                          │ │
 │ └──────────────────────────────────────────────────────────────────────────┘ │
 │                                                                              │
 │ Reparte tus ingresos entre temáticas para ver en qué se te va el mes.        │
 │ [ Repartir presupuesto ]   [ Usar el reparto del mes pasado ]                │
 └──────────────────────────────────────────────────────────────────────────────┘
```

#### H. Sin ingresos declarados

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ Agosto 2026                                                                  │
 │ ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐ │
 │                        Aún no has puesto los ingresos                        │
 │ └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘ │
 │ Sin ingresos no hay barra que repartir. Es un minuto.                        │
 │ [ Poner ingresos de agosto ]                                                 │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Carril vacío con borde discontinuo de 1 px `--c-border-strong` (el **único** borde
discontinuo permitido en todo el sistema, y solo aquí: significa «esto está por rellenar»).

#### I. Cargando

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ ▒▒▒▒▒▒▒▒▒▒▒                                                                  │
 │ ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                                          │
 │ ┌──────────────────────────────────────────────────────────────────────────┐ │
 │ │▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒│ │
 │ └──────────────────────────────────────────────────────────────────────────┘ │
 │ ▒▒▒▒▒▒▒▒▒  ▒▒▒▒▒▒▒▒▒▒▒  ▒▒▒▒▒▒▒                                              │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Un solo bloque a la altura real del carril (44 px), nunca segmentos falsos: inventar
divisiones que luego cambian produce un salto desagradable.

### 6.5 Interacción por segmento

**Puntero**

| Gesto | Respuesta |
|---|---|
| Hover | El segmento sube su luminosidad un 8 % (`color-mix` con blanco al 8 %); los demás bajan a `opacity: .72`; aparece tooltip a los 120 ms; el chip correspondiente de la leyenda se resalta. |
| Salida | Todo vuelve en `--dur-fast`. |
| Clic | Navega a Transacciones con el filtro de esa temática y del mes activo ya aplicado. |
| Clic derecho / `⋯` | Menú contextual: Ver movimientos · Cambiar asignación · Añadir gasto aquí · Ocultar del resumen. |
| Arrastre del borde | Reasigna presupuesto entre dos segmentos vecinos (§6.7). |

**Tooltip de segmento** — el valor manda, el nombre acompaña:

```
┌──────────────────────────────┐
│ 385,00 €  de 520,00 €        │  ← --t-h3, tabular-nums
│ ▬ Alimentación               │  ← llave de línea del hue, nombre en --c-text-2
│ 74 % de lo asignado          │
│ 15,7 % del presupuesto total │
│ Quedan 135,00 € y 18 días    │
│ ─────────────────────────────│
│ Ritmo: 12,42 €/día · vas bien│
└──────────────────────────────┘
```

**Teclado**

- El carril es un solo elemento tabulable; dentro, `←`/`→` se mueven entre segmentos y `Home`/`End` van a los extremos.
- `Enter` abre las transacciones de la temática enfocada; `Espacio` abre el modo reasignación.
- El segmento enfocado lleva `outline: 2px solid var(--c-accent); outline-offset: -2px` (hacia dentro, para no tapar a los vecinos) y muestra el mismo tooltip que el hover.
- Cada movimiento se anuncia: «Alimentación, 385 de 520 euros, 74 por ciento, segmento 2 de 6».

**Estructura ARIA**

```html
<section aria-labelledby="bb-titulo">
  <h2 id="bb-titulo">Presupuesto de agosto de 2026</h2>
  <p id="bb-resumen">2.450 € de ingresos. 2.150 € asignados. 1.312,45 € gastados.</p>

  <div role="group" aria-describedby="bb-resumen" aria-label="Reparto por temáticas">
    <div role="img" aria-label="Vivienda: 612 de 850 euros asignados, 72 %"
         tabindex="0" data-slot="1"> … </div>
    …
  </div>

  <ul aria-label="Leyenda del presupuesto"> … </ul>
  <button type="button">Ver como tabla</button>
</section>
```

La barra **no es la única vía** a los datos: «Ver como tabla» abre la misma información en
una tabla con columnas Temática / Asignado / Gastado / Restante / % del total. Regla del
sistema: ninguna cifra vive solo dentro de un gráfico.

### 6.6 Versión compacta por temática

Se usa en la fila de la lista de temáticas, en la ficha de temática, en la tarjeta de
subcategoría y en la vista móvil de la BudgetBar.

```
Alimentación                                            385,00 € / 520,00 €   74 %
████████████████████████████████████████░░░░░░░░░░░░░░
                              ▏hoy

Ocio                                                    142,00 € / 300,00 €   47 %
████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
                              ▏hoy

Alimentación · sobrepasada                              588,40 € / 520,00 €  113 %
██████████████████████████████████████████████████████╱╱╱╱╱╱  ⚠ +68,40 €
```

- Alto del carril **8 px**, radio 4 px, `--c-track` de fondo, relleno `--c-cat-n`.
- Marca de ritmo: muesca de 1 × 12 px `--c-text-3` que sobresale por arriba y por abajo.
- Exceso: el carril se completa y el sobrante continúa en `--c-negative` rayado **más allá
  del 100 %**, hasta un tope visual del 130 % del ancho; a partir de ahí solo crece el número.
- Sin asignación (`asignado = 0`): el carril se sustituye por una línea de 1 px `--c-border`
  y el texto pasa a `385,00 € · sin asignación`, con enlace «Asignar».
- Interacción: toda la fila es un enlace; el carril no es interactivo por sí mismo (evita el
  objetivo de 8 px de alto). El área de toque de la fila es de 48 px.

### 6.7 Reasignación arrastrando

**Asas.** Entre dos segmentos vecinos hay un asa de 12 px de ancho visible (2 px pintados
`--c-border-strong` que aparecen en hover) con **área de arrastre de 24 px** y
`cursor: col-resize`. Los segmentos `bloqueado` no tienen asa a ninguno de sus lados y
muestran un icono `lock` de 10 px.

**Durante el arrastre.** El carril entra en modo reasignación: el resto de la interfaz se
atenúa al 60 %, aparece bajo el asa una **etiqueta doble** en vivo, con salto de 5 € y
adherencia a números redondos y al gasto ya realizado:

```
 ┌────────────────────────┬┃┬──────────────────────────────────────────────────┐
 │████████████░░░░░░░░░░░░│┃│██████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
 └────────────────────────┴┃┴──────────────────────────────────────────────────┘
                    ┌──────┴───────────────┐
                    │ Vivienda    780,00 € │  −70,00 €
                    │ Ahorro      520,00 € │  +70,00 €
                    └──────────────────────┘
        ▏no puedes bajar de 612,00 € — ya lo has gastado
```

**Límites.** Un segmento nunca baja por debajo de su `gastado`: el asa se frena ahí, se
marca con un `--glow-negative` de 1 px y aparece la explicación. Al soltar, ambos importes
se guardan en una sola operación y sale un toast: «Presupuesto reasignado. 70,00 € de
Vivienda a Ahorro. [Deshacer]».

**Teclado y accesibilidad.** El asa es un `role="separator"` enfocable con
`aria-orientation="vertical"`, `aria-valuemin`, `aria-valuemax`, `aria-valuenow` y
`aria-valuetext="Vivienda 780 euros, Ahorro 520 euros"`. `←`/`→` mueven **5 €**,
`Shift+←/→` mueven **50 €**, `PageUp/PageDown` **100 €**, `Home/End` llevan al límite,
`Esc` cancela y restaura, `Enter` confirma. Cada paso se anuncia por `aria-live="polite"`
con antirrebote de 300 ms para no atropellar al lector de pantalla.

**Alternativa sin arrastre, siempre disponible.** «Cambiar asignación» abre un modal con un
campo de importe por temática y un contador «Sin asignar: 300,00 €» que se actualiza al
teclear. El arrastre es un atajo agradable; el formulario es el camino garantizado.

---

## 7. Reglas de gráficos (Chart.js)

### 7.1 Qué gráfico para qué pregunta

| Pregunta del usuario | Forma | Color |
|---|---|---|
| ¿Cuánto llevo gastado este mes? | **BudgetBar** + cifra héroe | categórico |
| ¿Cómo voy respecto a los meses anteriores? | líneas, 1 serie por año o barras por mes | 1 hue + gris de contexto |
| ¿En qué se me va el dinero? | **barras horizontales** ordenadas de mayor a menor | slot 1 para todas (una serie) |
| ¿Cómo se reparte el mes? | **barra apilada horizontal** (= la BudgetBar) | categórico |
| ¿Entra más de lo que sale? | barras divergentes sobre línea cero (ingresos arriba, gastos abajo) + línea de saldo acumulado | divergente + `--c-info` |
| ¿Ha subido este producto? | **línea escalonada** (`stepped: true`) con puntos de compra | slot 1 |
| ¿Qué productos han subido más? | **dumbbell** (antes → después) o barras de variación % | 1 hue, 2 pasos |
| ¿Qué días gasto más? | **mapa de calor** semana × día | secuencial azul |
| ¿Dónde compro más barato? | barras agrupadas por comercio, máximo 5 comercios | categórico (≤ 5) |
| Un solo número con tendencia | **tarjeta de dato** con delta y sparkline | acento + gris |

### 7.2 Prohibiciones

- **Nada de 3D, sombras en las series, degradados de relleno ni bordes gruesos.** Marca fina y limpia.
- **Sin doble eje Y.** Nunca. Dos magnitudes distintas son dos gráficos, múltiplos pequeños, o ambas series indexadas a base 100.
- **Tartas y donuts:** solo para parte-de-un-todo de un vistazo, **máximo 5 porciones**, siempre con porcentajes visibles y una tabla al lado. Para comparar valores parecidos, barras.
- **Sin rejilla vertical** en gráficos temporales; solo horizontal.
- **Rejilla y ejes:** hairline de 1 px **sólido** (`--c-grid`), jamás discontinuo. Sin borde de marco alrededor del área de trazado.
- **Sin un número sobre cada punto.** Se etiqueta el último valor, el máximo y el mínimo, y ya.
- Nada de animación de entrada por serie: `animation: { duration: 180 }` y a 0 con movimiento reducido.

### 7.3 Especificaciones de marca

| Marca | Especificación |
|---|---|
| Barra / columna | grosor máximo 24 px (`barThickness` con tope, `maxBarThickness: 24`); extremo de dato redondeado 4 px, base recta (`borderRadius: { topLeft: 4, topRight: 4 }` en columnas) |
| Línea | 2 px, `tension: 0`, unión y remate redondos; escalonada para precios |
| Punto | radio 4 px (8 px de diámetro), `hitRadius: 12`, anillo de 2 px del color de la superficie |
| Área | el hue de la serie al 10 % de opacidad |
| Apilado | hueco de 2 px del color de la superficie entre segmentos |
| Leyenda | **siempre presente con 2 o más series**; nunca con una sola (el título ya la nombra); rectángulo para barras y áreas, línea para líneas |

### 7.4 Ejes, moneda y tooltips

- **Eje Y monetario:** números redondos y **compactos** (`0 · 500 € · 1 mil € · 1,5 mil €`), el símbolo solo en la marca superior si el espacio aprieta. Etiquetas en `--c-axis-text`, 12 px, `tabular-nums`.
- **Eje X temporal:** `ago` para meses, `13 ago` para días, `2026` cuando cambia el año. Sin rotación de etiquetas: si no caben, se muestran una de cada dos.
- **El eje Y de importes empieza en 0.** Siempre. Truncar la base de una escala monetaria exagera diferencias y en una app de dinero eso es mentir.
- **Tooltip:** fondo `--c-surface-2`, borde 1 px, radio `--r-lg`, 12 px de relleno; el valor en `--t-h3` `--c-text-1`, la serie en `--c-text-2` con una llave de línea de su color; importe completo con dos decimales (`1.234,56 €`), nunca compacto; una línea por serie, todas las del mismo punto. Modo `interaction: { mode: 'index', intersect: false }` en temporales y `nearest` en barras.
- **Cruz de guía** vertical de 1 px `--c-border-strong` en gráficos de líneas, que se ajusta al punto más cercano.
- **Toda gráfica tiene su gemela en tabla**, accesible con un botón «Ver datos» en la esquina de la tarjeta.
- Los nombres de temática y de producto vienen del usuario o de un PDF: se insertan con `textContent`, nunca con `innerHTML`.

---

## 8. Formato de datos (España, EUR)

### 8.1 Importes

| Caso | Formato | Ejemplo |
|---|---|---|
| Estándar | `#.###,## €` con **espacio duro** antes del € | `1.234,56 €` |
| Cero | siempre con decimales | `0,00 €` |
| Miles compactos | 1 decimal + palabra | `1,2 mil €` |
| Millones compactos | 1 decimal + `M` | `1,4 M €` |
| Negativo | signo delante, sin paréntesis | `-1.234,56 €` |
| Positivo explícito | solo en contextos mixtos | `+1.234,56 €` |
| Rango | guion con espacios | `100,00 € – 250,00 €` |
| Precio unitario | hasta 3 decimales, con unidad | `2,459 €/kg` |
| En eje o etiqueta muy estrecha | compacto sin decimales | `1 mil €` |

```ts
const eur = new Intl.NumberFormat('es-ES', {
  style: 'currency', currency: 'EUR',
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})                                          // 1.234,56 €
const eurCompacto = new Intl.NumberFormat('es-ES', {
  style: 'currency', currency: 'EUR',
  notation: 'compact', maximumFractionDigits: 1,
})                                          // 1,2 mil €
```

**Reglas de uso:** compacto **solo** en ejes, en la barra de navegación y en tarjetas de
dato por debajo de 360 px de ancho. En tablas, formularios, tooltips y cualquier sitio donde
se cuadren cuentas, **importe completo con dos decimales**. Un usuario tiene que poder sumar
una columna a mano y que le cuadre.

### 8.2 Fechas

| Caso | Formato | Ejemplo |
|---|---|---|
| Estándar | día + mes abreviado sin punto + año | `13 ago 2026` |
| Del año en curso | sin año | `13 ago` |
| Relativa (≤ 7 días) | palabra + fecha entre paréntesis | `Ayer (12 ago)` |
| Con hora | coma y 24 h | `13 ago 2026, 18:42` |
| Mes | mes en minúscula + año | `agosto de 2026` |
| Rango dentro del mes | día–día mes | `1–15 ago 2026` |
| Entrada manual | numérica con barras | `13/08/2026` |
| Cabecera de grupo en lista | día de la semana en mayúscula inicial | `Jueves, 13 ago` |

Abreviaturas de mes, en minúscula y **sin punto**: `ene feb mar abr may jun jul ago sep oct
nov dic`. Semana desde el **lunes**. Todo el almacenamiento en UTC ISO-8601; todo el
formateo en la zona del usuario.

### 8.3 Porcentajes y variación de precio

- Formato: `12,5 %` — un decimal, **espacio** antes del signo, según norma española.
- Variación siempre con signo: `+8,3 %` / `-2,1 %`. El `0` se escribe `0,0 %` con la palabra «igual» y color neutro, nunca en verde ni en rojo.
- Composición del indicador de variación, en este orden: **flecha · porcentaje · importe absoluto · periodo**.

```
▲ +8,3 %   +0,18 €   desde jun 2026        ← subida  (--c-negative en precios de compra)
▼ -3,1 %   -0,07 €   desde jul 2026        ← bajada  (--c-positive)
■  0,0 %    igual    desde may 2026        ← sin cambio (--c-text-3)
```

- **Ojo con la polaridad:** en precios de producto, subir es **malo** (rojo) y bajar es **bueno** (verde). En saldo, ingresos o ahorro es lo contrario. Cada indicador declara su polaridad (`polarity: 'up-is-bad' | 'up-is-good'`) y el color se deriva de ella. Se escribe explícitamente en el tooltip: «Ha subido 0,18 € por unidad».
- Variaciones **superiores al 999 %** se muestran como `>999 %`; comparar con una base de 0,01 € no dice nada útil.
- Si la variación proviene de menos de 2 observaciones, no se muestra porcentaje: se escribe «Sin histórico suficiente».

### 8.4 Otros

- **Cantidades:** `2 uds.` · `1,5 kg` · `750 ml` · `3 × 0,89 €`.
- **Números grandes no monetarios:** `1.284 movimientos`.
- **Truncado:** por el final con elipsis y `title` completo; los nombres de temática nunca se truncan por debajo de 12 caracteres, antes se reduce otra columna.
- **Vacío frente a cero:** una celda sin dato lleva `—` en `--c-text-3`; un cero es `0,00 €`. No son lo mismo y no se pintan igual.

---

## 9. Responsive

### 9.1 Breakpoints

| Nombre | Ancho | Contexto |
|---|---|---|
| `base` | 0–639 | móvil en vertical |
| `sm` | 640–767 | móvil grande, vertical grande |
| `md` | 768–1023 | tableta vertical |
| `lg` | 1024–1279 | tableta horizontal, portátil pequeño |
| `xl` | 1280–1535 | escritorio |
| `2xl` | ≥ 1536 | escritorio ancho (contenido tope 1440 px, centrado) |

### 9.2 Qué cambia en cada uno

| Zona | base / sm | md | lg | xl / 2xl |
|---|---|---|---|---|
| Navegación | barra inferior de 5 destinos + botón flotante | drawer con `menu` | lateral colapsada (64 px) | lateral expandida (240 px) |
| BudgetBar | carril 28 px sin etiquetas + lista de barras compactas | carril 40 px, etiquetas solo en segmentos anchos | carril 44 px | carril 44 px, etiquetas y leyenda completas |
| Rejilla del resumen | 1 columna | 2 columnas | 2 columnas | 3 columnas + columna lateral de 320 px |
| Transacciones | tarjetas apiladas | tabla de 4 columnas | tabla de 6 columnas | tabla de 8 columnas + panel de detalle |
| Filtros | botón «Filtros» → hoja inferior | una fila con desbordamiento por scroll | una fila | una fila + vistas guardadas |
| Detalle | hoja inferior al 92 % | hoja inferior | drawer 420 px | drawer 480 px, no bloqueante |
| Añadir gasto | pantalla completa | modal 560 px | modal 560 px | modal 560 px |
| Revisión de factura | una línea por tarjeta, edición en hoja | tabla de 5 columnas con scroll | tabla completa | tabla + previsualización del PDF al lado |
| Gráficos | 1 por fila, alto 220 px | 1 por fila, 260 px | 2 por fila, 280 px | 2–3 por fila, 300 px |
| Densidad de tabla | cómoda forzada (48 px) | elegible | elegible | elegible, recuerda la preferencia |

### 9.3 Móvil primero de verdad, para meter un gasto

El caso de uso real es una persona de pie en la caja de un supermercado, con una mano.

1. **Botón flotante** de 56 px abajo a la derecha, a 16 px de los bordes, respetando `env(safe-area-inset-bottom)`.
2. Al pulsarlo se abre a pantalla completa con el **teclado numérico ya desplegado** y el foco en el importe. Sin animación de entrada superior a 240 ms.
3. Orden de campos por frecuencia real de uso: **Importe → Temática → Cuenta → Fecha → Concepto**. Fecha por defecto hoy; cuenta, la última usada; temática, sugerida.
4. Las temáticas son una **rejilla de fichas de 72 px** (icono + nombre), las 8 más usadas primero, ordenadas por frecuencia en ese día de la semana. Un toque, no un desplegable.
5. **«Guardar» ocupa el ancho completo, 52 px de alto**, fijado sobre el teclado. «Guardar y añadir otro» como acción secundaria a su lado, porque en la compra semanal se meten varios tickets seguidos.
6. Todo objetivo de toque ≥ 44 px, con 8 px de separación entre objetivos adyacentes.
7. Sin dependencia del hover en ningún punto: cada tooltip tiene su equivalente pulsable.
8. Funciona **sin conexión**: la transacción se guarda en local y se sincroniza después, con badge «Pendiente de sincronizar» en la fila.

---

## 10. Accesibilidad

**Objetivo: WCAG 2.2 nivel AA, con AAA en el texto principal.**

### Foco

- `:focus-visible` con anillo de 2 px `--c-accent` y `outline-offset: 2px`; sobre superficies de acento, el anillo pasa a `--c-text-1`. Nunca se elimina un foco sin sustituirlo.
- Foco **nunca oculto** por una cabecera pegajosa: `scroll-margin-top: 80px` en todo lo enfocable dentro de zonas con scroll.
- Contraste del indicador de foco ≥ 3:1 contra el fondo adyacente y contra el propio componente.

### Orden de tabulación

- Sigue el orden visual; cero `tabindex` positivos.
- Primer elemento del documento: «Saltar al contenido principal». Segundo: «Saltar a la navegación».
- Modales y drawers bloqueantes atrapan el foco y lo devuelven al disparador al cerrarse.
- Las zonas con scroll horizontal (tabla ancha) son enfocables (`tabindex="0"`) para poder desplazarlas con el teclado.
- Menús, selects y tabs son **una sola parada** de tabulación; dentro se navega con flechas.

### Roles ARIA de los componentes complejos

| Componente | Patrón |
|---|---|
| BudgetBar | `section` con encabezado + `role="group"`; cada segmento `role="img"` con `aria-label` completo y `tabindex="0"`; asas `role="separator"` con `aria-valuenow` / `aria-valuetext`; resumen en `aria-describedby`; alternativa en tabla obligatoria |
| Tabla de datos | `<table>` nativa, `aria-sort` en `<th>`, expansor con `aria-expanded` + `aria-controls` |
| Árbol de temáticas | `role="tree"` / `treeitem` con `aria-expanded`, `aria-level`, `aria-selected`; reordenación accesible con `Ctrl+↑/↓` y «mover a…» en el menú, además del arrastre |
| Select / autocompletar | `role="combobox"` + `listbox` + `option`, `aria-activedescendant` |
| Tabs | `tablist` / `tab` / `tabpanel`, activación manual |
| Modal / Drawer | `role="dialog"`, `aria-modal`, `aria-labelledby`, `inert` en el resto |
| Toast | `role="status"` (polite) o `role="alert"` (assertive) |
| Dropzone de facturas | `<input type="file">` real visualmente oculto + `role="button"` en la zona, con `aria-describedby` de formatos y tamaño máximo |
| Progreso de proceso | `role="progressbar"` con `aria-valuenow` y texto de estado en `aria-live="polite"` |
| Paginación | `<nav aria-label="Paginación">` + `aria-current="page"` |
| Barra de búsqueda | `role="search"`, número de resultados en `aria-live="polite"` |

### Toque y puntero

- **Mínimo 44 × 44 px** de área efectiva en todo control, en cualquier tamaño de pantalla. Si el elemento pintado es menor (casilla de 18 px, punto de color, asa de 12 px), se amplía con un pseudo-elemento.
- Separación mínima de 8 px entre objetivos adyacentes.
- Ningún gesto es la única vía: arrastrar tiene siempre su alternativa por menú o formulario (obliga el criterio 2.5.7 de WCAG 2.2, y además es de sentido común).
- Nada depende del hover ni de mantener pulsado. `hover:` solo refina lo que ya se puede hacer con clic.

### Contenido

- Jerarquía de encabezados sin saltos, un solo `<h1>` por vista.
- Todo icono informativo lleva texto accesible; todo icono decorativo, `aria-hidden="true"`.
- Los importes se leen bien porque van dentro de texto normal: «gastado 1.312,45 €», no separados en spans que el lector trocea. Las abreviaturas compactas llevan `aria-label` con el valor completo: `<span aria-label="1.234,56 euros">1,2 mil €</span>`.
- Zoom de texto al 200 % sin pérdida de contenido ni de funciones; reflujo a 320 px de ancho equivalente sin scroll en dos ejes.
- Soporte de `prefers-contrast: more` (bordes a `--c-border-strong`, texto terciario a secundario) y de `forced-colors: active` (se apoya en colores de sistema y activa el canal de textura).
- Ninguna sesión caduca sin avisar: 2 minutos antes aparece un diálogo con opción de ampliar, y los datos del formulario en curso se conservan.

---

## 11. Lista de comprobación antes de dar por buena una pantalla

- [ ] ¿El texto principal llega a 7:1 y el secundario a 4,5:1 sobre su fondo **real**?
- [ ] ¿Hay algún significado codificado **solo** con color?
- [ ] ¿Toda cifra monetaria lleva `tabular-nums` y va alineada a la derecha en tabla?
- [ ] ¿Cada gráfico tiene leyenda (con 2 o más series) y su gemela en tabla?
- [ ] ¿Ningún gráfico pasa de 8 series con nombre (3 si es de dispersión o mapa)?
- [ ] ¿Existen los estados vacío, cargando y error, y son distintos entre sí?
- [ ] ¿Se puede recorrer y operar la pantalla completa solo con el teclado?
- [ ] ¿Todo objetivo de toque llega a 44 px?
- [ ] ¿Toda acción por arrastre tiene alternativa por teclado y por formulario?
- [ ] ¿Funciona con `prefers-reduced-motion` y a 200 % de zoom?
- [ ] ¿Hay exactamente **una** acción primaria y **una** cifra héroe por vista?
- [ ] ¿Ningún hex escrito a mano fuera de este documento?
