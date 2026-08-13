# Flujos y wireframes — Gestor de presupuesto

Versión 1.0 · es-ES · EUR · complementa a `docs/ux/design-system.md` (v1.0), que define
color, tipografía, componentes y el comportamiento exacto de la `BudgetBar`. Este documento
no repite esas reglas: las usa. Donde haya cualquier duda de estilo visual, gana el sistema
de diseño; este documento manda en la estructura de pantallas, el contenido que llevan y el
orden de los pasos.

Fecha de referencia usada en los ejemplos: **13 de agosto de 2026** (día 13 de 31 del mes).

---

## Convenciones de estos wireframes

Son diagramas de caja, no maquetas de alta fidelidad. Ancho de cada bloque: entre 80 y 110
columnas. Símbolos usados de forma constante en todo el documento:

| Símbolo | Significado |
|---|---|
| `[[ Texto ]]` | botón primario (uno por pantalla, según el sistema de diseño) |
| `[ Texto ]` | botón secundario u *outline* |
| `( Texto )` | enlace o botón *ghost* |
| `‹Texto›` | chip de temática, cuenta o filtro |
| `{ Texto }` | campo de formulario o casilla de importe |
| `▾` | control desplegable (select) |
| `☐` / `☑` | casilla sin marcar / marcada |
| `●` / `○` | opción de radio marcada / sin marcar |
| `█` `▓` `░` | relleno de barra: gastado · asignado sin gastar todavía · sin asignar |
| `╱╱` | textura de exceso o sobrepasado (siempre acompaña a color + icono, nunca va sola) |
| `⚠` `✕` `✓` | aviso · error · correcto |
| `⋯` | menú contextual de fila |
| `[icono]` | icono Lucide referido por nombre, p. ej. `[triangle-alert]`, `[chevron-right]` |
| `NAV` | hueco de la barra lateral, dibujada completa una sola vez en el Panel (§2.3) |

Los importes siguen siempre el formato `1.234,56 €`; las fechas, `13 ago 2026`; los
porcentajes, `12,5 %`. Estas reglas están descritas con detalle en el §8 del sistema de
diseño y no se repiten aquí.

### Los seis estados de una temática

El backend no manda solo números: manda también el estado ya calculado. Todas las
pantallas que muestran una temática (Panel, Movimientos, Temáticas, Informes) pintan este
estado, no lo recalculan en el cliente.

| Estado | Significado | Lectura visual |
|---|---|---|
| `sin_gasto` | Hay presupuesto asignado, cero gastado todavía | carril con el tramo asignado en `--c-track`, sin relleno |
| `en_margen` | Gastando por debajo del 80 % de lo asignado | relleno normal, sin aviso |
| `ajustado` | 80 % o más consumido, sin llegar a pasarse | relleno + `--c-warning` + icono `circle-alert` + «Al 82 %» |
| `agotado` | Exactamente el 100 %, sin exceso | relleno completo, sin cresta ni aviso negativo |
| `sobrepasado` | Ha gastado más de lo asignado | cresta rayada + borde `--c-negative` + icono `triangle-alert` |
| `sin_asignar` | La temática no tiene presupuesto este mes | el carril se sustituye por una línea de 1 px + enlace «Asignar» |

Ejemplo de seis temáticas usado en todo el documento para que los números cuadren entre
pantallas (agosto de 2026, ingresos 2.450,00 €):

| Temática | Asignado | Arrastrado | Gastado | Disponible | % | Estado |
|---|---|---|---|---|---|---|
| Vivienda | 850,00 € | 0,00 € | 612,00 € | 238,00 € | 72 % | `en_margen` |
| Alimentación | 520,00 € | +10,00 € | 425,00 € | 105,00 € | 80 % | `ajustado` |
| Transporte | 180,00 € | -12,00 € | 198,40 € | -30,40 € | 118 % | `sobrepasado` |
| Ocio | 150,00 € | 0,00 € | 0,00 € | 150,00 € | 0 % | `sin_gasto` |
| Salud | 300,00 € | 0,00 € | 300,00 € | 0,00 € | 100 % | `agotado` |
| Regalos | 0,00 € | 0,00 € | 22,00 € | -22,00 € | — | `sin_asignar` |

`Disponible = asignado + arrastrado − gastado`. Totales: ingresos 2.450,00 € · asignado
2.000,00 € · gastado 1.557,40 € · sin asignar 450,00 €. «Arrastrado» es lo que sobró (o lo
que se pasó) el mes anterior en esa misma temática; positivo amplía lo disponible, negativo
lo reduce, y se muestra siempre como una línea propia, nunca mezclado en el número de
«Asignado» para no falsear lo que el usuario decidió este mes.

Avisos ya redactados por el backend para este ejemplo (llegan como texto plano, la
interfaz no los compone):

```
· "Transporte ha sobrepasado su presupuesto en 30,40 €."
· "Alimentación está al 80 % de lo asignado."
· "Salud ha agotado el presupuesto de este mes."
· "Regalos no tiene presupuesto asignado este mes: llevas 22,00 € gastados."
· "Vas por el día 13 de 31 y ya has gastado el 78 % de lo asignado."
```

---

## 1. Mapa de navegación

```
Gestor de presupuesto
│
├── Público (sin sesión)
│   ├── Login
│   ├── Registro
│   ├── Recuperar contraseña
│   └── Restablecer contraseña (enlace por correo)
│
├── Onboarding (solo la primera vez, obligatorio y secuencial)
│   ├── Paso 1 · Crear cuentas
│   ├── Paso 2 · Ingresos del mes
│   └── Paso 3 · Primeras temáticas
│
└── Aplicación (con sesión) ── barra lateral persistente + selector de mes
    │
    ├── Panel                              ← pantalla de inicio tras el login
    │
    ├── Movimientos
    │   ├── Lista (filtros combinables + fila expandible)
    │   ├── Alta rápida de gasto (modal)
    │   ├── Formulario completo (reparto entre temáticas)
    │   └── Detalle de movimiento (drawer)
    │
    ├── Temáticas
    │   ├── Árbol de temáticas (arrastrable)
    │   ├── Crear / editar temática (modal)
    │   ├── Fusionar dos temáticas (diálogo)
    │   └── Ficha de temática (histórico y subcategorías)
    │
    ├── Facturas
    │   ├── Lista de facturas
    │   ├── Subir factura — zona de arrastre
    │   ├── Subir factura — procesando
    │   ├── Subir factura — revisión y corrección de líneas
    │   └── Detalle de factura
    │
    ├── Productos
    │   ├── Buscador / lista de productos
    │   └── Ficha de producto (histórico de precio + comparativa por comercio)
    │
    ├── Informes
    │   ├── Ingresos y gastos
    │   ├── Gasto por temática
    │   ├── Comparativa de precios
    │   └── Evolución del ahorro
    │
    ├── Cuentas
    │   ├── Lista de cuentas
    │   └── Crear / editar cuenta (modal)
    │
    └── Ajustes
        ├── Perfil y seguridad
        ├── Preferencias (tema, idioma, formato)
        ├── Temáticas y colores
        ├── Notificaciones y avisos
        ├── Datos (exportar, importar, zona de peligro)
        └── Sesión (dispositivos, cerrar sesión)
```

**Elementos persistentes en toda pantalla con sesión:** barra lateral (Panel · Movimientos ·
Temáticas · Facturas · Productos · Informes · Cuentas · Ajustes), selector de mes arriba de
la barra, botón «Añadir gasto» a ancho completo destacado sobre la navegación, y menú de
usuario abajo. Ver §5.15 y §5.16 del sistema de diseño para su especificación completa.

**Nota sobre Cuentas.** No lleva wireframe propio en este documento porque reutiliza sin
cambios el patrón de tabla con fila expandible de Movimientos (§2.4): columnas Nombre · Tipo
· Saldo actual · Última actividad, fila expandible con el detalle de saldo inicial y ajustes
manuales, y el mismo modal de alta/edición que cualquier campo de importe del sistema.

---

## 2. Wireframes

### 2.1 Login / registro

**Objetivo del usuario.** Entrar en su cuenta lo antes posible, o crear una si es nueva, sin
fricción ni campos de más.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                        │
│                                    Gestor de presupuesto                              │
│                                                                                        │
│                    ┌──────────────────────────────────────────────┐                   │
│                    │  ( Iniciar sesión )     Crear cuenta          │  ← pestañas       │
│                    │ ───────────────────                          │                   │
│                    │                                                │                   │
│                    │  Correo electrónico                           │                   │
│                    │  { tu@correo.com                          }   │                   │
│                    │                                                │                   │
│                    │  Contraseña                                   │                   │
│                    │  { ••••••••••••                      [eye] }  │                   │
│                    │                                    (¿Olvidada?)│                   │
│                    │                                                │                   │
│                    │            [[      Entrar      ]]             │                   │
│                    │                                                │                   │
│                    │  ──────────────────  o  ──────────────────    │                   │
│                    │                                                │                   │
│                    │           [  Continuar con Google  ]          │                   │
│                    │                                                │                   │
│                    │  ¿No tienes cuenta?  ( Crear una )             │                   │
│                    └──────────────────────────────────────────────┘                   │
│                                                                                        │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Variante «Crear cuenta» (mismos márgenes, sustituye el cuerpo de la tarjeta):

```
                    ┌──────────────────────────────────────────────┐
                    │   Iniciar sesión     ( Crear cuenta )         │
                    │                       ───────────────         │
                    │  Nombre                                       │
                    │  { Cómo te llamamos                        }  │
                    │  Correo electrónico                           │
                    │  { tu@correo.com                            }  │
                    │  Contraseña                                   │
                    │  { ••••••••••••                     [eye] }   │
                    │  Mínimo 8 caracteres                          │
                    │  Repite la contraseña                         │
                    │  { ••••••••••••                            }  │
                    │  ☐ Acepto los términos y la política de datos │
                    │                                                │
                    │          [[  Crear cuenta  ]]                 │
                    └──────────────────────────────────────────────┘
```

**Datos que muestra.** Ningún dato de servidor; solo el formulario. Tras iniciar sesión con
éxito, el backend indica si la cuenta ya completó el onboarding o no.

**Acciones primarias.** «Entrar» (login) · «Crear cuenta» (registro).
**Acciones secundarias.** Cambiar de pestaña · «¿Olvidada?» → recuperar contraseña ·
continuar con Google · enlace cruzado entre pestañas.

**Estado vacío.** No aplica (es un formulario, no un listado).
**Estado cargando.** El botón primario pasa a *loading* (§5.1): ancho congelado, `loader-2`
girando, resto de campos deshabilitados.
**Estado de error.** Banda `--c-negative-wash` bajo la cabecera de la tarjeta con el mensaje
concreto («El correo o la contraseña no son correctos»); en registro, el error se ancla al
campo afectado (p. ej. correo ya registrado) además de la banda general.

---

### 2.2 Onboarding en 3 pasos

Flujo obligatorio y secuencial la primera vez que alguien entra. No se puede saltar a un
paso sin completar el anterior; sí se puede volver atrás. Cabecera común a los tres pasos:
indicador de progreso con los pasos completados, el activo y los pendientes.

#### Paso 1 · Crear cuentas

**Objetivo del usuario.** Decirle a la aplicación dónde tiene el dinero, para poder repartir
el presupuesto después.

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  ●───────○───────○      Paso 1 de 3 · Crear tus cuentas                            │
│                                                                                      │
│  Añade al menos una cuenta. Puedes tener varias: corriente, ahorro, efectivo…       │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────┐    │
│  │ Nombre de la cuenta          Tipo                    Saldo inicial         │    │
│  │ { Cuenta corriente        }  { Corriente          ▾}  { 1.240,00       € }  │    │
│  └────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                      │
│  Cuentas añadidas:                                                                  │
│  ‹💳 Cuenta corriente · 1.240,00 €›   ‹👛 Efectivo · 60,00 €›        [x] [x]        │
│                                                                                      │
│  ( + Añadir otra cuenta )                                                           │
│                                                                                      │
│                                                                                      │
│  [ Volver ]                                                    [[ Continuar ]]      │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Las cuentas ya añadidas en esta misma sesión de onboarding, con su
saldo inicial.
**Acciones primarias.** «Continuar» (deshabilitado hasta que exista al menos una cuenta).
**Acciones secundarias.** «Añadir otra cuenta» · quitar una cuenta añadida · «Volver» (sin
efecto real en el paso 1, aparece deshabilitado o directamente no se muestra).
**Estado vacío.** Es el estado inicial: el formulario de alta vacío y ninguna cuenta en la
lista; «Continuar» deshabilitado con ayuda «Añade al menos una cuenta para seguir».
**Estado cargando.** Al pulsar «Continuar», el botón entra en *loading* mientras se crean las
cuentas; el formulario queda bloqueado.
**Estado de error.** Si falla la creación de alguna cuenta, banda de error bajo la lista con
«No se ha podido guardar “Cuenta corriente”. Inténtalo otra vez» y esa cuenta queda marcada.

#### Paso 2 · Ingresos del mes

**Objetivo del usuario.** Decir cuánto entra este mes, para que la `BudgetBar` tenga un 100 %
que repartir.

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  ●───────●───────○      Paso 2 de 3 · Ingresos de agosto de 2026                   │
│                                                                                      │
│  ¿Cuánto esperas ingresar este mes? Podrás cambiarlo cualquier mes desde el Panel.  │
│                                                                                      │
│  ┌────────────────────────────────────────────────────────────────────────────┐    │
│  │ Concepto                        Importe              Repetir cada mes     │    │
│  │ { Nómina                    }   { 2.150,00        € }  ☑ Recurrente        │    │
│  └────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                      │
│  Ingresos añadidos:                                                                 │
│  ‹Nómina · 2.150,00 € · recurrente›     ‹Ingresos extra · 300,00 € · solo este mes›  │
│                                                                                      │
│  ( + Añadir otro ingreso )                                                          │
│                                                                                      │
│  Total de ingresos de agosto de 2026:                              2.450,00 €       │
│                                                                                      │
│  [ Volver ]                                                    [[ Continuar ]]      │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Suma en vivo de los ingresos declarados, que será el 100 % de la
`BudgetBar` desde el primer día.
**Acciones primarias.** «Continuar» (deshabilitado con 0,00 € de ingresos).
**Acciones secundarias.** «Añadir otro ingreso» · marcar/desmarcar «Recurrente» · quitar un
ingreso · «Volver» al paso 1.
**Estado vacío.** Campo de importe en blanco, total en `0,00 €`, ayuda «Sin ingresos no hay
nada que repartir».
**Estado cargando.** Igual que el paso 1: botón *loading*, formulario bloqueado.
**Estado de error.** Si el importe no es válido, error inline en el campo («Introduce un
importe mayor que 0»); no bloquea añadir otros ingresos correctos.

#### Paso 3 · Primeras temáticas

**Objetivo del usuario.** Salir del onboarding con un reparto mínimo ya hecho, no con una
`BudgetBar` vacía.

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│  ●───────●───────●      Paso 3 de 3 · Tus primeras temáticas                       │
│                                                                                      │
│  Elige de la lista o crea las tuyas. Luego decides cuánto asignar a cada una.       │
│                                                                                      │
│  ☑‹Vivienda›   ☑‹Alimentación›   ☑‹Transporte›   ☐‹Ocio›   ☐‹Salud›   ☐‹Ropa›       │
│  ☐‹Educación›  ☐‹Suscripciones›  ☐‹Mascotas›     ( + Crear una temática propia )     │
│                                                                                      │
│  Reparte 2.450,00 € entre las temáticas elegidas:                                   │
│  ┌────────────────────────────────────────────────────────────────────────────┐    │
│  │ ‹Vivienda›            { 850,00        € }                                   │    │
│  │ ‹Alimentación›        { 520,00        € }                                   │    │
│  │ ‹Transporte›          { 180,00        € }                                   │    │
│  └────────────────────────────────────────────────────────────────────────────┘    │
│  Sin asignar: 900,00 €  ·  no pasa nada si no lo repartes todo hoy                  │
│                                                                                      │
│  [ Volver ]                    ( Omitir por ahora )        [[ Terminar y ver el panel ]] │
└────────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Rejilla de temáticas sugeridas (las 9 más comunes, cada una con su
`colorSlot` ya reservado), contador de «Sin asignar» actualizado al teclear, igual que el
contador del modal «Cambiar asignación» (§6.7 del sistema de diseño).
**Acciones primarias.** «Terminar y ver el panel» (disponible siempre, aunque quede dinero
sin repartir: repartir del todo no es requisito).
**Acciones secundarias.** Marcar/desmarcar temáticas sugeridas · crear una temática propia ·
«Omitir por ahora» (salta directo al Panel con la `BudgetBar` en el estado G, «sin
presupuesto asignado») · «Volver» al paso 2.
**Estado vacío.** Ninguna temática marcada: la zona de reparto no aparece, solo la rejilla y
la ayuda «Elige al menos una para empezar a repartir, o pulsa Omitir por ahora».
**Estado cargando.** Al terminar: pantalla de transición breve «Preparando tu panel…» con
`role="status"`, máximo un segundo antes de navegar.
**Estado de error.** Si falla el guardado del reparto, se conserva todo lo tecleado y aparece
un toast de error persistente con «Reintentar»; nunca se pierde la introducción de datos de
un paso por un fallo de red.

---

### 2.3 Panel

**Objetivo del usuario.** En un vistazo: cuánto le queda este mes, qué necesita atención
ahora mismo, y acceso rápido a lo último que ha pasado.

```
┌────────────┬───────────────────────────────────────────────────────────────────────┐
│ Gestor      │ Agosto 2026 ▾                              [search] [bell] [user AV] │
│────────────│───────────────────────────────────────────────────────────────────────│
│[[+ Añadir  │  Presupuesto de agosto de 2026                                        │
│   gasto]]  │  Ingresos 2.450,00 €  ·  Asignado 2.000,00 €  ·  Gastado 1.557,40 €    │
│────────────│  Sin asignar 450,00 €                                                 │
│› Panel     │                                            ▏Día 13 de 31              │
│  Movimient. │  ┌────────────┬───────────┬────┬────────┬────────┬────────────────┐   │
│  Temáticas  │  │████████░░░░│███████░░░░│████│░░░░░░░░│████████│░░░░░░░░░░░░░░░░│   │
│  Facturas   │  │ Vivienda   │Alimenta…  │Tra…│ Ocio   │ Salud  │  Sin asignar   │   │
│  Productos  │  └────────────┴───────────┴────┴────────┴────────┴────────────────┘   │
│  Informes   │                              ╱╱╱╱  ← Transporte sobrepasado           │
│  Cuentas    │                                                                       │
│────────────│  Avisos                                                               │
│  Ajustes    │  ⚠ Transporte ha sobrepasado su presupuesto en 30,40 €.  [Reasignar]  │
│  (AV) Yo    │  ⚠ Alimentación está al 80 % de lo asignado.                          │
│             │  ⚠ Salud ha agotado el presupuesto de este mes.                       │
│             │  ⚠ Regalos no tiene presupuesto asignado este mes.        (Asignar)   │
│             │                                                                       │
│             │  Temáticas                                          ( Ver como tabla )│
│             │  ●Vivienda      612,00 € / 850,00 €    72 %  en margen                │
│             │  ●Alimentación  425,00 € / 520,00 €    80 %  ajustado ⚠               │
│             │  ●Transporte    198,40 € / 180,00 €   118 %  sobrepasado +30,40 € ⚠   │
│             │  ●Salud         300,00 € / 300,00 €   100 %  agotado                  │
│             │  ▪Regalos        22,00 € · sin asignación                 (Asignar)   │
│             │                                                                       │
│             │  Últimos movimientos                                  ( Ver todos )   │
│             │  13 ago  Mercadona            ‹Alimentación›   Corriente   -26,76 €    │
│             │  12 ago  Nómina               ‹Ingreso›        Corriente  +2.150,00 €  │
│             │  11 ago  Gasolinera Repsol     ‹Transporte›    Tarjeta      -42,00 €    │
└────────────┴───────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** `BudgetBar` del mes activo (ingresos, asignado, gastado, sin
asignar, marca de día) · lista de avisos ya redactados por el backend, con acción directa
cuando la tienen · las seis temáticas con su estado · las últimas transacciones. Ocio no
sale en avisos porque `sin_gasto` no es un problema.

**Acciones primarias.** «Añadir gasto» (siempre visible, fuera del flujo de lectura).
**Acciones secundarias.** Cambiar de mes · «Reasignar» desde un aviso concreto · «Asignar» en
una temática `sin_asignar` · «Ver como tabla» (alternativa accesible a la barra, §6.5) · «Ver
todos» los movimientos · clic en cualquier temática filtra Movimientos por ella y el mes
activo.

**Estado vacío.** Mes nuevo sin ingresos → estado H de la `BudgetBar` («Aún no has puesto
los ingresos»). Con ingresos pero sin repartir → estado G («Sin asignar · repartir
presupuesto»). Sin movimientos todavía → la sección de últimos movimientos muestra «Todavía
no has apuntado ningún movimiento» con acción «Añadir el primero».
**Estado cargando.** Skeleton de la `BudgetBar` a su altura real (§6.4.I) + 3 líneas skeleton
en avisos + 6 en temáticas + 5 en movimientos; nunca skeletons falsos con anchuras que luego
cambien.
**Estado de error.** Si falla la carga del presupuesto del mes, la `BudgetBar` se sustituye
por una tarjeta de error con «No se ha podido cargar el presupuesto de agosto» y «Reintentar»;
el resto de módulos (temáticas, movimientos) se cargan de forma independiente y no dependen
de que la barra haya cargado.

---

### 2.4 Movimientos — lista con filtros combinables

**Objetivo del usuario.** Encontrar un movimiento concreto o revisar el detalle de varios,
combinando los filtros que hagan falta sin perder de vista el total filtrado.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Movimientos                                        [search] [bell] [user AV]    │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │ [⌕ Buscar concepto, comercio o importe…] [Ago 2026▾][Temática▾][Cuenta▾][Más▾]   │
│    │                                                              ( Guardar vista )   │
│    │ ‹Temática: Alimentación x› ‹Solo con factura x›              ( Quitar todos )    │
│    │                                                                                  │
│    │ ┌──┬──────────┬───────────────────────┬──────────────┬───────────┬────────────┐ │
│    │ │▾ │ Fecha    │ Concepto              │ Temática     │ Cuenta    │   Importe  │ │
│    │ ├──┼──────────┼───────────────────────┼──────────────┼───────────┼────────────┤ │
│    │ │▸ │ 13 ago   │ Mercadona             │ ‹Alimentac.› │ Corriente │   -26,76 € │ │
│    │ ├──┼──────────┼───────────────────────┼──────────────┼───────────┼────────────┤ │
│    │ │▾ │ 10 ago   │ Compra semanal        │ repartido    │ Corriente │  -84,32 €  │ │
│    │ │  │ ┌────────────────────────────────────────────────────────────────────┐  │ │
│    │ │  │ │ Desglose del movimiento                                            │  │ │
│    │ │  │ │  ‹Alimentación›   62,20 €   74 %                                   │  │ │
│    │ │  │ │  ‹Hogar›          22,12 €   26 %                                   │  │ │
│    │ │  │ │  Cuenta: Corriente · Factura: F-2026-004471 (Ver factura)          │  │ │
│    │ │  │ │  Notas: — · Etiquetas: —                                           │  │ │
│    │ │  │ └────────────────────────────────────────────────────────────────────┘  │ │
│    │ ├──┼──────────┼───────────────────────┼──────────────┼───────────┼────────────┤ │
│    │ │▸ │ 08 ago   │ Suscripción streaming │ ‹Ocio›       │ Tarjeta   │   -12,99 € │ │
│    │ └──┴──────────┴───────────────────────┴──────────────┴───────────┴────────────┘ │
│    │  Total de 42 resultados filtrados:                                 -1.557,40 €  │
│    │                                                                                  │
│    │  Mostrando 1–25 de 42        [25▾]   ‹  1  2  ›                                 │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Movimientos del periodo con fecha, concepto, temática (o «repartido»
si tiene varias), cuenta e importe; al expandir, el desglose por temática con importe y
porcentaje, la cuenta, la factura vinculada si existe y notas/etiquetas.
**Acciones primarias.** Expandir/contraer una fila (`chevron-right` → `chevron-down`).
**Acciones secundarias.** Combinar filtros (mes, temática, cuenta, «más filtros»: rango de
importe, tipo, «solo con factura», «solo recurrentes», «solo sin categorizar») · quitar un
filtro por su chip o todos a la vez · buscar por texto o importe · guardar la combinación
como vista con nombre · ordenar por columna · paginar · abrir el detalle completo en un
drawer con clic en el concepto.
**Estado vacío — primer uso.** «Todavía no has apuntado ningún movimiento» + «Añadir el
primero».
**Estado vacío — sin resultados de filtro.** «Ningún movimiento coincide con estos filtros» +
«Quitar filtros», repitiendo el criterio aplicado.
**Estado cargando.** 8 filas skeleton con las anchuras reales de columna (§5.6); en
recargas, el contenido anterior queda al 55 % de opacidad en vez de mostrar skeleton.
**Estado de error.** Fila única de ancho completo: «No se han podido cargar los movimientos»
+ «Reintentar»; los filtros y la búsqueda permanecen intactos para no repetir el trabajo.

---

### 2.5 Alta rápida de gasto (modal)

**Objetivo del usuario.** Apuntar un gasto en el menor número de toques posible, sin salir
de donde está.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Añadir gasto                                                              [x]   │
│  ──────────────────────────────────────────────────────────────────────────────  │
│                                                                                    │
│   ( Gasto )   Ingreso   Transferencia                                             │
│                                                                                    │
│                              { 12,50                                    € }       │
│                                            [+10] [+50] [+100] [C]                 │
│                                                                                    │
│   Temática                                                                        │
│   ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐              │
│   │Vivienda│ │● Alim. │ │Transp. │ │  Ocio  │ │ Salud  │ │  Ropa  │  ( Ver todas )│
│   └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘              │
│                                                                                    │
│   Cuenta          { Corriente ▾ }        Fecha          { 13/08/2026  [calendar] } │
│   Concepto (opcional)                                                             │
│   { Mercadona                                                                  }  │
│                                                                                    │
│   ( Repartir entre varias temáticas ↗ )                                           │
│                                                                                    │
│                              [ Guardar y añadir otro ]      [[ Guardar ]]         │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Formulario completo — reparto entre varias temáticas.** Se abre al pulsar «Repartir entre
varias temáticas» (o directamente desde Movimientos con «Nuevo movimiento completo»):

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Nuevo movimiento                                                          [x]   │
│  ──────────────────────────────────────────────────────────────────────────────  │
│  Importe total                                            { 84,32          € }   │
│  Cuenta { Corriente ▾ }     Fecha { 13/08/2026 }     Tipo ( Gasto ) Ingreso Transf.│
│                                                                                    │
│  Reparto entre temáticas                                                          │
│  ┌──────────────────────────────────────────────────────────────────────────┐    │
│  │ ‹Alimentación   ▾›      { 62,20        € }      74 %              [x]    │    │
│  │ ‹Hogar          ▾›      { 22,12        € }      26 %              [x]    │    │
│  └──────────────────────────────────────────────────────────────────────────┘    │
│  ( + Añadir otra temática )                                                       │
│  Repartido: 84,32 € de 84,32 €  ·  cuadra ✓                                       │
│                                                                                    │
│  Concepto            { Compra semanal                                        }    │
│  Notas (opcional)    { …                                                     }    │
│  Etiquetas           ‹+ añadir›                                                   │
│  ☐ Es un movimiento recurrente     Factura   ( Adjuntar PDF )                     │
│                                                                                    │
│                                        [ Cancelar ]        [[ Guardar ]]          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** En el alta rápida, las temáticas más usadas (rejilla priorizada por
frecuencia real de uso, §9.3). En el formulario completo, cada línea de reparto con su
importe y el porcentaje que representa sobre el total, más un contador «Repartido: X de Y».
**Acciones primarias.** «Guardar».
**Acciones secundarias.** «Guardar y añadir otro» (para tickets seguidos) · cambiar de tipo
(Gasto/Ingreso/Transferencia) · elegir cuenta y fecha (por defecto, la última cuenta usada y
hoy) · «Repartir entre varias temáticas» · en el formulario completo: añadir/quitar líneas de
reparto, adjuntar factura, marcar como recurrente.
**Estado vacío.** Importe en blanco con placeholder `0,00`; el botón «Guardar» queda
deshabilitado hasta que haya importe y temática.
**Estado cargando.** «Guardar» pasa a *loading*; el modal no se puede cerrar mientras dura.
**Estado de error.** En el alta rápida: error inline bajo el importe («Introduce un importe
mayor que 0»). En el reparto: si la suma no coincide con el total, la línea de «Repartido»
pasa a `--c-negative` con «El reparto no suma el importe total. Faltan 4,20 €» (o «sobran»
si se pasa) y «Guardar» queda deshabilitado hasta que cuadre.

---

### 2.6 Gestor de temáticas — árbol arrastrable

**Objetivo del usuario.** Organizar sus temáticas y subcategorías, y limpiar duplicados
fusionando sin perder el histórico.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Temáticas                                          [search] [bell] [user AV]    │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │ [⌕ Buscar temática…]                                    [[ + Nueva temática ]]  │
│    │                                                                                  │
│    │ ⠿ ●Vivienda                        612,00 € / 850,00 €   72 %           ⋯       │
│    │   ████████████████████████████░░░░░░░░░░░░                                     │
│    │      ⠿   ↳ Hipoteca                480,00 € / 480,00 €  100 %           ⋯       │
│    │      ⠿   ↳ Suministros             132,00 € / 200,00 €   66 %           ⋯       │
│    │ ⠿ ●Alimentación · ajustado ⚠       425,00 € / 520,00 €   80 %           ⋯       │
│    │   ████████████████████████████████████████████████░░░░░░░░░                    │
│    │ ⠿ ●Transporte · sobrepasado ⚠      198,40 € / 180,00 €  118 %           ⋯       │
│    │   ████████████████████████████████████████████████████████╱╱╱╱╱╱               │
│    │ ⠿ ●Ocio                              0,00 € / 150,00 €     0 %           ⋯       │
│    │   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                        │
│    │ ⠿ ●Salud · agotado                 300,00 € / 300,00 €  100 %           ⋯       │
│    │   ████████████████████████████████████████████████████████████████████████     │
│    │ ⠿ ▪Regalos · sin asignación           22,00 €                (Asignar)  ⋯       │
│    │                                                                                  │
│    │ ⠿  Archivadas (2)                                              ( Mostrar )      │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

Menú `⋯` de fila: `Editar · Ver movimientos · Fusionar con… · Archivar · Eliminar`. El asa
`⠿` a la izquierda arrastra para reordenar o anidar como subcategoría de la fila de encima;
`Ctrl+↑/↓` hace lo mismo por teclado (§10, «Roles ARIA»).

**Datos que muestra.** Árbol con jerarquía temática → subcategoría, la barra compacta de
cada una (§6.6), su estado con badge cuando no es `en_margen`/`sin_gasto`, y un contador de
archivadas oculto por defecto.
**Acciones primarias.** «+ Nueva temática».
**Acciones secundarias.** Arrastrar para reordenar/anidar · «Editar» (nombre, color,
icono) · «Fusionar con…» (§2.7) · «Archivar» (deja de aparecer en la `BudgetBar`, conserva el
histórico) · «Eliminar» (solo si no tiene movimientos; si tiene, se ofrece fusionar o
archivar en su lugar) · «Asignar» en las `sin_asignar`.
**Estado vacío.** «Todavía no has creado ninguna temática» + «Crear la primera», con la
rejilla de sugeridas del onboarding (§2.2, paso 3) como acceso directo.
**Estado cargando.** Skeleton de 6 filas con la altura real de la barra compacta (8 px).
**Estado de error.** Tarjeta de error de ancho completo con «No se han podido cargar las
temáticas» + «Reintentar»; las acciones de arrastre y menú quedan deshabilitadas hasta que
cargue.

#### Diálogo «Fusionar con…»

**Objetivo del usuario.** Unir dos temáticas duplicadas o mal repartidas, entendiendo antes
de confirmar qué pasa exactamente con lo que ya tiene registrado.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  Fusionar «Transporte»                                                     [x]   │
│  ──────────────────────────────────────────────────────────────────────────────  │
│                                                                                    │
│  Vas a fusionar   ‹Transporte›   con destino:                                    │
│                                                                                    │
│  Temática de destino                                                              │
│  { Elige una temática…                                                    ▾ }     │
│                                                                                    │
│  ‹Transporte› tiene 18 movimientos por 1.198,40 € desde enero de 2026.            │
│                                                                                    │
│  Qué va a pasar:                                                                  │
│  · Los 18 movimientos de «Transporte» pasarán a estar etiquetados como el         │
│    destino elegido, conservando su fecha e importe originales.                    │
│  · Los informes de meses anteriores también cambiarán: ese gasto pasado se         │
│    contará desde ahora bajo el destino, no bajo «Transporte».                     │
│  · El presupuesto asignado este mes a «Transporte» (180,00 €) se sumará al del    │
│    destino.                                                                       │
│  · El color de «Transporte» quedará libre para una temática nueva.                │
│  · Esta acción no se puede deshacer.                                             │
│                                                                                    │
│  ☐ Entiendo que esta acción no se puede deshacer                                 │
│                                                                                    │
│                                        [ Cancelar ]      [[ Fusionar ]] (danger)  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Número real de movimientos e importe acumulado de la temática origen,
y el efecto exacto sobre el histórico y el presupuesto del mes en curso.
**Acciones primarias.** «Fusionar» — variante `danger`, deshabilitado hasta elegir destino y
marcar la casilla; nunca recibe el foco inicial del diálogo (§5.1 y §5.7).
**Acciones secundarias.** «Cancelar» · cambiar la temática de destino.
**Estado vacío.** No aplica; si la temática origen no tiene movimientos, el texto cambia a
«‹Regalos› no tiene movimientos. Se fusionará igualmente para conservar su presupuesto» y se
simplifica la lista de efectos.
**Estado cargando.** Al confirmar, el diálogo pasa a *guardando* (§5.7): botón primario en
*loading*, cierre bloqueado, resto de campos deshabilitados.
**Estado de error.** Banda `--c-negative-wash` bajo la cabecera: «No se ha podido completar la
fusión. Tus temáticas no han cambiado» + «Reintentar»; al ser una operación destructiva, si
falla a mitad de camino el backend garantiza que no queda a medias (todo o nada).

---

### 2.7 Subir factura — zona de arrastre

**Objetivo del usuario.** Meter el ticket o la factura sin escribir nada a mano.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Facturas                                           [search] [bell] [user AV]    │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │                                                                                  │
│    │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │
│    │                                                                                  │
│    │                            [file-up]                                            │
│    │                  Arrastra aquí tu factura o ticket                              │
│    │                     o  ( selecciona un archivo )                                 │
│    │                                                                                  │
│    │              PDF, JPG o PNG · hasta 10 MB · una factura por archivo              │
│    │                                                                                  │
│    │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │
│    │                                                                                  │
│    │  ( Añadir la factura a mano, sin PDF )                                          │
│    │                                                                                  │
│    │  Últimas facturas                                                               │
│    │  13 ago  Mercadona     84,32 €   Confianza alta    ( Ver )                       │
│    │  09 ago  Endesa        68,10 €   Confianza media   ( Revisar )                   │
│    │  02 ago  Repsol        42,00 €   Confianza alta    ( Ver )                       │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Formatos y tamaño admitidos, y un listado breve de las últimas
facturas con su confianza global (para saltar directo a «Revisar» las que lo necesiten).
**Acciones primarias.** Soltar o seleccionar el archivo.
**Acciones secundarias.** «Añadir la factura a mano» (sin PDF, va directo al formulario de
movimiento con campos de factura) · abrir una factura anterior desde la lista.
**Estado vacío.** El propio recuadro discontinuo *es* el estado vacío: «Todavía no has subido
ninguna factura» aparece en el bloque de «Últimas facturas» cuando no hay ninguna.
**Estado cargando.** Al soltar el archivo, la zona pasa a §2.8 (Procesando); no hay un estado
de carga propio de esta pantalla, solo la transición.
**Estado de error.** Si el archivo no cumple el formato o tamaño: borde de la zona en
`--c-negative` y mensaje «Solo se admiten archivos PDF, JPG o PNG de hasta 10 MB», sin salir
de esta pantalla.

---

### 2.8 Subir factura — procesando

**Objetivo del usuario.** Saber que su archivo se está leyendo y cuánto puede tardar, sin
quedarse mirando una pantalla muda.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Facturas › Procesando                                                          │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │                                                                                  │
│    │                     ticket-mercadona-13ago.pdf · 340 KB                         │
│    │                                                                                  │
│    │        ┌──────────────────────────────────────────────────────────┐             │
│    │        │████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░│  62 %        │
│    │        └──────────────────────────────────────────────────────────┘             │
│    │                                                                                  │
│    │        ✓ Subido                                                                 │
│    │        ✓ Leyendo el documento                                                   │
│    │        ⟳ Extrayendo líneas…                                                     │
│    │        ○ Comprobando importes                                                   │
│    │                                                                                  │
│    │        Suele tardar menos de 20 segundos.                                       │
│    │                                                                                  │
│    │                                    [ Cancelar ]                                  │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Nombre y tamaño del archivo, progreso general y los cuatro pasos del
proceso con su estado (hecho, en curso, pendiente).
**Acciones primarias.** Ninguna: es una pantalla de espera; el usuario solo observa.
**Acciones secundarias.** «Cancelar» (aborta la subida y vuelve a la zona de arrastre).
**Estado vacío.** No aplica.
**Estado cargando.** Es, en sí misma, la representación del estado de carga:
`role="progressbar"` con `aria-valuenow` y el paso actual anunciado por `aria-live="polite"`
(§10).
**Estado de error.** Si un paso falla (p. ej. el PDF está corrupto o el OCR no encuentra
texto), esa línea cambia a `✕` en `--c-negative` con el motivo («No se ha podido leer el
documento: el archivo está dañado») y aparecen «Reintentar» y «Subir otro archivo»; los pasos
ya completados no se repiten.

---

### 2.9 Subir factura — revisión y corrección de las líneas extraídas

**Objetivo del usuario.** Comprobar rápido lo que la lectura automática ha entendido bien y
corregir solo lo que haga falta, con la vista puesta primero en lo que tiene confianza baja.

Esta es la pantalla más importante del módulo de facturas: cada línea llega con una
confianza de 0 a 1, y todos sus campos son editables.

```
┌────┬──────────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Facturas › Revisar                                                                  │
├────┼──────────────────────────────────────────────────────────────────────────────────────┤
│    │ ⚠ El total no coincide con la suma de las líneas. Diferencia de 0,12 €.              │
│    │ ⚠ 2 líneas tienen confianza baja y conviene revisarlas.                              │
│    │                                                                                        │
│    │ Emisor       { Mercadona, S.A.                    }   NIF     { A46103834          }  │
│    │ Número       { F-2026-004471                       }   Fecha   { 13/08/2026 [cal] }  │
│    │ Base imponible { 24,90         € }  Impuestos { 1,98        € }  Total { 26,88   € }  │
│    │                                                                                        │
│    │ Lectura: ‹tabla›   Confianza global: 77 % · Media                                     │
│    │                                                                                        │
│    │ ┌──┬───────────────────────┬────────┬──────┬────────────┬────────┬─────────────┬────┐ │
│    │ │  │ Descripción            │Cantidad│Unidad│Precio unit.│ Total  │ Temática    │Conf│ │
│    │ ├──┼───────────────────────┼────────┼──────┼────────────┼────────┼─────────────┼────┤ │
│    │ │✓ │{Manzana Golden       }│{1,240 }│{kg▾} │{2,1900   €}│{2,72 €}│‹Alimentac. ▾›│97 %│ │
│    │ ├──┼───────────────────────┼────────┼──────┼────────────┼────────┼─────────────┼────┤ │
│    │ │✓ │{Aceite oliva 1 L    }│{2     }│{ud▾} │{5,4900   €}│{10,98€}│‹Alimentac. ▾›│93 %│ │
│    │ ├──┼───────────────────────┼────────┼──────┼────────────┼────────┼─────────────┼────┤ │
│    │ │⚠ │{Detergente ropa     }│{3     }│{l ▾} │{2,3300   €}│{6,99 €}│‹Sin clasif.▾›│58 %│ │
│    │ │  │ revisa esta línea: confianza baja en cantidad y temática                       │ │
│    │ ├──┼───────────────────────┼────────┼──────┼────────────┼────────┼─────────────┼────┤ │
│    │ │⚠ │{Pechuga d? pollo    }│{0,850 }│{kg▾} │{6,7900   €}│{5,77 €}│‹Alimentac. ▾›│41 %│ │
│    │ │  │ revisa esta línea: la descripción puede estar incompleta                       │ │
│    │ ├──┼───────────────────────┼────────┼──────┼────────────┼────────┼─────────────┼────┤ │
│    │ │✓ │{Bolsa plástico      }│{2     }│{ud▾} │{0,1500   €}│{0,30 €}│‹Alimentac. ▾›│99 %│ │
│    │ └──┴───────────────────────┴────────┴──────┴────────────┴────────┴─────────────┴────┘ │
│    │ ( + Añadir línea manual )                                                             │
│    │                                                                                        │
│    │ Suma de líneas: 26,76 €   ·   Total de la factura: 26,88 €   ·   Diferencia: 0,12 €  │
│    │                                                                                        │
│    │ [ Cancelar ]      [ Guardar como borrador ]           [[ Guardar factura ]]           │
└────┴──────────────────────────────────────────────────────────────────────────────────────┘
```

**Cómo se lee la confianza.** Alta (≥ 85 %) marca la fila con `✓` y sin realce de fondo.
Media (60–84 %) también con `✓` pero conviene repasarla igual si el usuario tiene tiempo.
Baja (< 60 %) marca la fila con `⚠` en `--c-warning`, fondo `--c-warning-wash` sutil y una
segunda línea de texto explicando *qué* dudó el sistema (cantidad, descripción, importe o
temática), para no obligar a adivinar qué revisar. El número de confianza siempre acompaña al
color y al icono, nunca va solo (§2.3 del sistema de diseño).

**Datos que muestra.** Cabecera editable de la factura (emisor, NIF, número, fecha, base
imponible, impuestos, total), método de lectura (`tabla` / `texto` / `ocr`) como chip,
confianza global, avisos redactados por el backend, y la tabla de líneas con descripción,
cantidad, unidad (`kg`, `l`, `kWh` —esta última en facturas de suministros como electricidad
o gas—, `ud`), precio unitario con hasta 4 decimales, total, temática asignada y confianza
por línea.
**Acciones primarias.** «Guardar factura» (crea la factura y el/los movimientos asociados,
uno por temática según el reparto de las líneas).
**Acciones secundarias.** Editar cualquier campo de cabecera o de línea · reasignar la
temática de una línea · «Añadir línea manual» · dividir o eliminar una línea (menú `⋯` por
fila, no dibujado por espacio, con «Dividir línea» y «Eliminar línea») · «Guardar como
borrador» (queda en Facturas con estado «Pendiente de revisar», por si no hay tiempo de
terminar ahora) · «Cancelar» (descarta el archivo).
**Estado vacío.** No aplica: solo se llega aquí tras una extracción con al menos una línea; si
la extracción no encontró ninguna línea, se muestra un aviso «No se ha detectado ninguna
línea en este documento» con «Añadir línea manual» como único camino y sin bloquear el
guardado de la cabecera.
**Estado cargando.** Mientras se guarda: banda de progreso en el pie, «Guardar factura» en
*loading*, tabla bloqueada.
**Estado de error.** Si una línea no tiene temática al intentar guardar, el campo se marca en
`--c-negative` con «Esta línea no tiene temática asignada» y el foco salta a la primera
línea sin resolver; el guardado no continúa hasta que todas las líneas tengan temática. Si
falla el guardado por red, se conserva todo lo corregido en el formulario (nada se pierde) y
aparece un toast de error con «Reintentar».

---

### 2.10 Detalle de una factura

**Objetivo del usuario.** Consultar una factura ya guardada: qué se compró, por cuánto y qué
movimiento generó, sin volver a corregir nada salvo que lo pida expresamente.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Factura de Mercadona, S.A.                                                    [x]   │
│  ──────────────────────────────────────────────────────────────────────────────────  │
│  NIF A46103834 · Número F-2026-004471 · 13 ago 2026                                  │
│  Lectura: ‹tabla›  ·  Confianza 77 % · Media       [thumbnail PDF]  ( Ver PDF original)│
│                                                                                        │
│  Base imponible 24,90 €   ·   Impuestos 1,98 €   ·   Total 26,88 €                    │
│                                                                                        │
│  Líneas                                                                               │
│  ┌───────────────────────┬────────┬──────┬────────────┬────────┬───────────────┐    │
│  │ Manzana Golden        │ 1,240  │ kg   │ 2,1900 €   │ 2,72 € │ ‹Alimentación› │    │
│  │ Aceite oliva 1 L      │ 2      │ ud   │ 5,4900 €   │10,98 € │ ‹Alimentación› │    │
│  │ Detergente ropa 3 L   │ 3      │ l    │ 2,3300 €   │ 6,99 € │ ‹Hogar›        │    │
│  │ Pechuga de pollo      │ 0,850  │ kg   │ 6,7900 €   │ 5,77 € │ ‹Alimentación› │    │
│  │ Bolsa plástico        │ 2      │ ud   │ 0,1500 €   │ 0,30 € │ ‹Alimentación› │    │
│  └───────────────────────┴────────┴──────┴────────────┴────────┴───────────────┘    │
│                                                                                        │
│  Movimiento vinculado: 13 ago · Compra semanal · -26,76 €   ( Ver movimiento )        │
│                                                                                        │
│  [ Descargar PDF ]   [ Editar ]                                    [danger-ghost Eliminar factura] │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Todo lo confirmado en la revisión, en modo lectura, más el enlace al
movimiento (o movimientos, si se repartió) que generó.
**Acciones primarias.** «Ver movimiento» (el objetivo más común al abrir una factura ya
guardada).
**Acciones secundarias.** «Ver PDF original» · «Descargar PDF» · «Editar» (vuelve a la
pantalla de revisión, §2.9, con los valores guardados) · «Eliminar factura» (destructiva).
**Estado vacío.** No aplica a una factura ya guardada; si no llegó a vincularse a ningún
movimiento (se guardó como borrador y luego se completó a mano en otro sitio), el bloque de
«Movimiento vinculado» se sustituye por «Sin movimiento vinculado» + «Vincular a un
movimiento».
**Estado cargando.** Skeleton del panel completo mientras carga (drawer, §5.8): cabecera con
el título ya conocido, cuerpo en skeleton.
**Estado de error.** «No se ha podido cargar esta factura» + «Reintentar»; si falla solo la
carga del PDF original, el resto de datos se muestra igualmente y solo el visor de PDF
queda en error con su propio «Reintentar».

---

### 2.11 Ficha de producto

**Objetivo del usuario.** Ver si un producto que compra habitualmente ha subido o bajado, y
en qué comercio le sale mejor.

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│  Aceite de oliva virgen extra 1 L                                                    │
│  ──────────────────────────────────────────────────────────────────────────────────  │
│  Precio actual                              Comparado con el anterior                │
│  5,49 €/l                                   ▲ +6,6 %   +0,34 €   desde 15 jul 2026    │
│                                                                                        │
│  Mínimo 4,89 €/l   ·   Máximo 5,79 €/l   ·   Medio (6 meses) 5,32 €/l  ·  Tendencia ‹sube›│
│                                                                                        │
│  Histórico de precio                                              ( Ver datos )      │
│  ┌────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 5,8 €│                                                        ●                │  │
│  │      │                                        ●───────────────┘                │  │
│  │ 5,3 €│               ●───────────●────────────┘                                │  │
│  │      │  ●────────────┘                                                        │  │
│  │ 4,9 €│──┘                                                                     │  │
│  │      └────────────────────────────────────────────────────────────────────────│  │
│  │        feb    mar    abr    may    jun    jul    ago                          │  │
│  └────────────────────────────────────────────────────────────────────────────────┘  │
│  ● = compra registrada, línea escalonada entre compras                              │
│                                                                                        │
│  Comparativa por comercio                                                            │
│  Lidl        ██████████████████████████████████████               5,15 €/l           │
│  Mercadona   ██████████████████████████████████████████████       5,49 €/l  (actual) │
│  Eroski      ████████████████████████████████████████████████     5,69 €/l           │
│  Carrefour   ██████████████████████████████████████████████████   5,80 €/l           │
│                                                                                        │
│  Ahorras 0,34 €/l comprando en Lidl en vez de Mercadona (un 6,2 % menos).             │
│                                                                                        │
│  Historial de compras                                                                │
│  15 jul  Mercadona   2 ud   5,4900 €   10,98 €   ( Ver factura )                      │
│  22 jun  Lidl         1 ud   5,1500 €    5,15 €   ( Ver factura )                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Precio actual, anterior, mínimo, máximo, medio y tendencia
(`sube`/`baja`/`estable`) · gráfico de línea escalonada con las compras reales marcadas ·
comparativa por comercio (máximo 5, por regla del sistema de diseño) con el ahorro por
unidad frente al más barato · historial de compras con enlace a cada factura de origen.
**Acciones primarias.** Ninguna acción transaccional: es una pantalla de consulta; la
interacción principal es explorar el histórico.
**Acciones secundarias.** «Ver datos» (tabla gemela del gráfico, obligatoria por regla del
sistema) · «Ver factura» desde cualquier compra del historial · cambiar el rango del
gráfico.
**Estado vacío.** «Este producto no tiene compras registradas todavía» cuando se crea desde
una línea de factura sin histórico previo; sin gráfico ni comparativa hasta la segunda
compra («Sin histórico suficiente» sustituye a la variación, según §8.3).
**Estado cargando.** Skeleton de las cifras superiores + bloque skeleton a la altura real del
gráfico (nunca ejes o barras falsas) + 4 líneas skeleton en la comparativa.
**Estado de error.** «No se ha podido cargar el histórico de este producto» + «Reintentar»,
localizado en el bloque del gráfico; las cifras superiores, si llegaron, se mantienen.

---

### 2.12 Informes

**Objetivo del usuario.** Entender tendencias que no se ven en el día a día: cómo evoluciona
el gasto, en qué se concentra, y qué productos suben más.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Informes                                           [search] [bell] [user AV]    │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │ Ingresos y gastos   ( Gasto por temática )   Comparativa de precios   Ahorro     │
│    │ ───────────────────────────────────                                             │
│    │ Periodo { Últimos 6 meses ▾ }                          [ Exportar ▾ ]           │
│    │                                                                                  │
│    │ En qué se te va el dinero (agosto 2026)                        ( Ver datos )    │
│    │ Vivienda      ████████████████████████████████████████████████  612,00 €        │
│    │ Salud         ██████████████████████████████████████████████████ 300,00 €       │
│    │ Alimentación  █████████████████████████████████████████████████████ 425,00 €    │
│    │ Transporte    ████████████████████████████████████████ 198,40 €                 │
│    │ Regalos        █████ 22,00 €                                                    │
│    │ Ocio                0,00 €                                                      │
│    │                                                                                  │
│    │ Evolución mensual                                              ( Ver datos )    │
│    │ ┌──────────────────────────────────────────────────────────────────────────┐    │
│    │ │  2,6 mil €│  ▄▄  ▄▄  ▄▄  ▄▄  ▄▄  ▄▄       ── saldo acumulado                 │  │
│    │ │  1,3 mil €│  ██  ██  ██  ██  ██  ██                                          │  │
│    │ │       0 € │──────────────────────────────────────                           │  │
│    │ │           │  mar   abr   may   jun   jul   ago                              │  │
│    │ └──────────────────────────────────────────────────────────────────────────┘    │
│    │ ▄ ingresos  █ gastos  ── saldo acumulado                                        │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

**Datos que muestra.** Depende de la pestaña activa: gasto por temática (barras horizontales
ordenadas de mayor a menor, con su gemela en tabla), evolución mensual de ingresos y gastos
con saldo acumulado, comparativa de precios (dumbbell antes→después) o evolución del ahorro.
**Acciones primarias.** Cambiar de pestaña de informe.
**Acciones secundarias.** Cambiar el periodo · «Exportar» (CSV o PDF) · «Ver datos» en cada
gráfico · clic en una barra de temática filtra Movimientos por ella y el periodo activo.
**Estado vacío.** «No hay movimientos en este periodo» cuando el rango elegido no tiene datos
(p. ej. un mes anterior al alta de la cuenta), con acción «Elegir otro periodo».
**Estado cargando.** Bloque skeleton a la altura real de cada gráfico (220–300 px según
breakpoint, §9.2); nunca aparecen ejes ni barras de relleno mientras carga.
**Estado de error.** «No se ha podido generar este informe» + «Reintentar», localizado en el
gráfico afectado; el selector de periodo y las otras pestañas siguen operativos.

---

### 2.13 Ajustes

**Objetivo del usuario.** Cambiar algo de su cuenta o de sus preferencias sin tener que
buscarlo por toda la aplicación.

```
┌────┬─────────────────────────────────────────────────────────────────────────────────┐
│NAV │ Ajustes                                            [search] [bell] [user AV]    │
├────┼─────────────────────────────────────────────────────────────────────────────────┤
│    │ ┌──────────────────┐  Perfil y seguridad                                        │
│    │ │› Perfil y         │  ────────────────────────────────────────────────────     │
│    │ │  seguridad       │                                                            │
│    │ │  Preferencias    │  Nombre          { Ana Gómez                            }  │
│    │ │  Temáticas y     │  Correo          ana@correo.com              ( Cambiar )  │
│    │ │  colores         │  Contraseña      ••••••••                    ( Cambiar )  │
│    │ │  Notificaciones  │  Verificación en dos pasos                      ○ Activar │
│    │ │  y avisos        │                                                            │
│    │ │  Datos           │  Dispositivos con sesión abierta                          │
│    │ │  Sesión          │  Este dispositivo · Chrome, macOS      (Es este)           │
│    │ └──────────────────┘  iPhone de Ana · hace 3 días          ( Cerrar sesión )    │
│    │                                                                                  │
│    │                                                    [[ Guardar cambios ]]        │
└────┴─────────────────────────────────────────────────────────────────────────────────┘
```

Panel «Datos» (al seleccionarlo en la lista izquierda), con la zona de peligro siempre al
final y separada visualmente:

```
    ┌──────────────────┐  Datos
    │  Perfil y         │  ────────────────────────────────────────────────────
    │  seguridad       │
    │› Datos            │  Exportar todos tus datos (CSV)             ( Exportar )
    │  Sesión          │  Importar movimientos desde un fichero       ( Importar )
    └──────────────────┘
                          ──────────────────────────────────────────────────────
                          Zona de peligro
                          Eliminar tu cuenta borra movimientos, facturas,
                          temáticas y cuentas. No se puede deshacer.

                                                    [danger  Eliminar mi cuenta  ]
```

**Datos que muestra.** Depende de la sección: perfil y seguridad (nombre, correo, contraseña,
verificación en dos pasos, dispositivos), preferencias (tema, idioma, formato de fecha),
temáticas y colores (redirige a la vista de §2.6 con foco en el color de cada una),
notificaciones (qué avisos llegan y por qué canal), datos (exportar, importar, zona de
peligro) y sesión (cerrar sesión en este u otros dispositivos).
**Acciones primarias.** «Guardar cambios» (una por sección, aparece solo cuando hay cambios
sin guardar).
**Acciones secundarias.** Cambiar de sección · «Cambiar» correo o contraseña (abre modal) ·
activar verificación en dos pasos · cerrar sesión en un dispositivo remoto · exportar o
importar datos · «Eliminar mi cuenta».
**Estado vacío.** No aplica a Perfil; en «Sesión», si solo hay un dispositivo, la lista muestra
únicamente «Este dispositivo».
**Estado cargando.** Skeleton de los campos de la sección activa mientras carga el perfil;
«Guardar cambios» no aparece hasta que los datos han cargado (no hay nada que guardar
todavía).
**Estado de error.** Si falla el guardado, banda de error sobre el formulario con «No se han
podido guardar los cambios» + «Reintentar»; los valores tecleados se conservan. Al cerrar
sesión en un dispositivo remoto, un fallo se muestra como toast de error sin afectar al resto
de la lista.

---

## 3. Flujos críticos

### 3.1 Apuntar un gasto en menos de 10 segundos

Caso de uso real: de pie en la caja de un supermercado, con una mano libre.

1. **Toque 1.** Pulsa el botón flotante «Añadir gasto» (móvil) o el botón de la barra lateral
   (escritorio). Se abre el alta rápida (§2.5) con el teclado numérico ya desplegado y el
   foco en el importe.
2. **Tecleo.** Escribe el importe, p. ej. `12,50`. No hace falta pulsar nada para confirmarlo,
   solo seguir al siguiente campo.
   - *Punto de decisión:* si se equivoca, corrige inline; no hay validación bloqueante hasta
     intentar guardar.
3. **Toque 2.** Elige la temática de la rejilla de las más usadas (una sola fila de fichas de
   72 px).
   - *Punto de decisión:* ¿la temática sugerida es la correcta? Si sí, un toque y sigue. Si
     no está en las 8 más usadas, pulsa «Ver todas» y la busca — rompe el objetivo de 10
     segundos, pero es un camino minoritario y aceptado.
4. **Cuenta y fecha.** Ya vienen precargadas (última cuenta usada, fecha de hoy). No requieren
   ninguna acción en el caso común.
   - *Punto de decisión:* si el gasto es de otro día o de otra cuenta, lo cambia aquí — de
     nuevo, camino minoritario, más lento pero disponible sin salir del modal.
5. **Toque 3.** Pulsa «Guardar» (o `Enter` desde teclado físico). El concepto es opcional: no
   bloquea el guardado.
6. **Confirmación.** El modal se cierra, aparece un toast «Gasto guardado. [Deshacer]» durante
   4 segundos, y la `BudgetBar` de la temática elegida se actualiza sin recargar la pantalla.
   - *Punto de decisión:* sin conexión, el gasto se guarda en local con un badge «Pendiente de
     sincronizar» y se sube en cuanto vuelve la red; el usuario nunca pierde el dato ni ve un
     error bloqueante por estar sin cobertura.

Total en el camino feliz: 3 toques y una cifra tecleada. Encaja en el presupuesto de 10
segundos que exige la regla de diseño móvil del §9.3 del sistema de diseño.

### 3.2 Fusionar dos temáticas

1. Entra en **Temáticas** (§2.6) y abre el menú `⋯` de la temática que quiere hacer
   desaparecer (la que se fusiona, no necesariamente la que menos usa).
2. Selecciona **«Fusionar con…»**. Se abre el diálogo con la temática origen ya fijada.
3. **Punto de decisión:** elige la temática de destino en el desplegable.
   - No puede elegir la misma temática como destino («No puedes fusionar una temática con ella
     misma»).
   - El sistema muestra de inmediato cuántos movimientos e importe acumulado tiene la temática
     origen, para que la decisión se tome con datos y no de memoria.
4. Lee el bloque «Qué va a pasar»: los movimientos pasan a estar etiquetados como el destino
   (con su fecha e importe originales intactos), los informes de meses pasados también
   cambian, el presupuesto asignado este mes se suma al del destino, y el color de la temática
   origen queda libre.
5. **Punto de decisión:** marca la casilla «Entiendo que esta acción no se puede deshacer».
   Sin ella, «Fusionar» permanece deshabilitado — es la última salida antes de un cambio
   irreversible.
6. Pulsa **«Fusionar»** (botón `danger`). El diálogo entra en estado *guardando*: no se puede
   cerrar hasta terminar.
7. Si todo va bien: el diálogo se cierra, la temática origen desaparece del árbol, la de
   destino refleja ya el presupuesto y el gasto combinados, y un toast confirma «Fusionado
   correctamente» — sin acción de «Deshacer», porque el diálogo ya avisó de que es
   irreversible y no tendría sentido ofrecer una salida que contradice esa advertencia.
   - *Punto de decisión (fallo):* si la fusión falla a mitad, el backend garantiza que no
     queda a medias — o se completa entera o no cambia nada — y el diálogo muestra el error
     con «Reintentar» sin haber tocado ya ningún movimiento.

### 3.3 Subir y revisar una factura

1. Entra en **Facturas** y arrastra el PDF (o toca «Seleccionar un archivo») sobre la zona de
   arrastre (§2.7).
2. La pantalla pasa a **Procesando** (§2.8): Subido → Leyendo → Extrayendo líneas →
   Comprobando importes, con progreso visible.
   - **Punto de decisión (fallo de lectura):** si el documento está dañado o no tiene texto
     legible, aparece el paso en error con «Reintentar» y «Subir otro archivo»; el flujo no
     avanza a revisión con datos a medias.
3. Si la lectura termina bien, pasa a **Revisión** (§2.9). Primero mira arriba: los avisos
   generales («el total no coincide», «2 líneas con confianza baja») dicen por dónde empezar.
4. **Punto de decisión por cabecera:** comprueba emisor, NIF, número, fecha y los tres
   importes (base, impuestos, total); si algo está mal leído, lo corrige directamente en el
   campo.
5. **Punto de decisión por línea:** recorre la tabla fijándose en las filas marcadas con `⚠`
   (confianza baja). Cada una explica qué dudó el sistema (cantidad, descripción o temática).
   Para cada línea decide entre: aceptar tal cual, corregir el campo señalado, dividirla en
   dos líneas, eliminarla, o dejarla para después.
6. **Punto de decisión de temática:** las líneas sin temática asignada (o con «Sin
   clasificar») necesitan una elegida a mano antes de poder guardar.
7. **Punto de decisión final:** si la suma de líneas y el total de la factura no cuadran,
   decide si ajusta un importe o guarda igual con la diferencia visible (no es bloqueante,
   solo informativo, salvo la falta de temática que sí lo es).
8. Pulsa **«Guardar factura»**. El sistema crea el movimiento (o varios, uno por temática
   distinta entre las líneas) y vincula la factura a él/ellos.
   - **Alternativa:** «Guardar como borrador» si no hay tiempo de terminar ahora; la factura
     queda en la lista con estado «Pendiente de revisar» y se puede reabrir después exactamente
     donde se dejó.
9. Aterriza en el **Detalle de factura** (§2.10) con un toast «Factura guardada. Se ha creado 1
   movimiento» (o el número que corresponda si hubo reparto entre temáticas).

### 3.4 Reasignar presupuesto entre temáticas arrastrando en la barra

1. En el **Panel**, sitúa el puntero sobre el asa entre dos segmentos vecinos de la
   `BudgetBar` (visible al hacer *hover*, área de arrastre de 24 px aunque se pinte más fina).
   - **Punto de decisión:** si alguno de los dos segmentos está bloqueado (p. ej. la
     hipoteca dentro de Vivienda), no hay asa entre ellos: hay que usar «Cambiar asignación»
     (paso 6) en su lugar.
2. Empieza a arrastrar. El resto de la interfaz se atenúa al 60 % y aparece bajo el asa una
   etiqueta doble en vivo con los importes de ambas temáticas, moviéndose en saltos de 5 €.
3. **Punto de decisión (límite):** el asa no deja bajar una temática por debajo de lo que ya
   tiene gastado; si lo intenta, se frena con un aviso «no puedes bajar de 198,40 € — ya lo
   has gastado» y un `--glow-negative` de 1 px.
4. **Punto de decisión (cancelar):** pulsar `Esc` en cualquier momento restaura los valores
   previos sin guardar nada.
5. Suelta el asa en el punto elegido. Ambos importes se guardan en una sola operación (no
   puede quedar solo uno de los dos cambiados).
6. Aparece un toast «Presupuesto reasignado. 30,00 € de Ocio a Transporte. [Deshacer]» — aquí
   sí hay «Deshacer», porque es un ajuste numérico reversible sin efecto sobre el histórico,
   a diferencia de la fusión de temáticas.
   - **Alternativa siempre disponible, sin arrastrar:** el botón «Cambiar asignación» abre un
     modal con un campo de importe por temática y un contador «Sin asignar: X €» que se
     actualiza al teclear — el mismo camino que usa alguien con lector de pantalla, teclado
     sin ratón, o simplemente sin ganas de arrastrar nada.

---

## 4. Microcopy

Español de España, tono directo y sin exclamaciones. Los importes y fechas de ejemplo son
los mismos que en el resto del documento para que se puedan copiar tal cual a un prototipo.

| Tipo | Contexto | Texto |
|---|---|---|
| Botón | Guardar un movimiento, cuenta o temática | `Guardar` |
| Botón | Alta rápida, para varios tickets seguidos | `Guardar y añadir otro` |
| Botón | Revisión de factura sin terminar | `Guardar como borrador` |
| Botón | Cerrar un formulario sin guardar | `Cancelar` |
| Botón | Popover de filtros | `Aplicar filtros` |
| Botón | Quitar un filtro concreto | `Quitar filtros` |
| Botón | Quitar todos los filtros a la vez | `Quitar todos` |
| Botón | Alta rápida → formulario completo | `Repartir entre varias temáticas` |
| Botón | Formulario de reparto | `Añadir otra temática` |
| Botón | Onboarding, paso 1 | `Añadir otra cuenta` |
| Botón | Onboarding, paso 2 | `Añadir otro ingreso` |
| Botón | Tras un error de carga | `Reintentar` |
| Botón | Toast tras guardar o reasignar | `Deshacer` |
| Botón | Segmento de la `BudgetBar` | `Ver movimientos` |
| Botón | Alternativa accesible a la `BudgetBar` | `Ver como tabla` |
| Botón | Alternativa accesible a un gráfico | `Ver datos` |
| Botón | Aviso de temática sobrepasada | `Reasignar` |
| Botón | Sin arrastre, alternativa siempre disponible | `Cambiar asignación` |
| Botón | Menú de fila de una temática | `Fusionar con…` |
| Botón | Menú de fila (edición) | `Editar` |
| Botón | Menú de fila (borrado) | `Eliminar` |
| Botón | Menú de fila (temática sin uso reciente) | `Archivar` |
| Botón | Detalle de movimiento con factura | `Vincular a un movimiento` |
| Botón | Detalle de factura | `Descargar PDF` |
| Botón | Informes | `Exportar` |
| Botón | Onboarding, paso 3 | `Omitir por ahora` |
| Botón | Onboarding, paso 3 (acción final) | `Terminar y ver el panel` |
| Botón | Panel sin presupuesto repartido | `Repartir presupuesto` |
| Botón | Panel sin presupuesto repartido | `Usar el reparto del mes pasado` |
| Botón | Panel sin ingresos declarados | `Poner ingresos de agosto` |
| Botón | Menú de usuario | `Cerrar sesión` |
| Botón | Ajustes, perfil | `Cambiar contraseña` |
| Botón | Ajustes, zona de peligro | `Eliminar mi cuenta` |
| Estado vacío | Movimientos, primer uso | `Todavía no has apuntado ningún movimiento.` |
| Estado vacío | Movimientos, sin resultados de filtro | `Ningún movimiento coincide con estos filtros.` |
| Estado vacío | Movimientos, sin resultados de búsqueda | `Sin resultados para «{término}».` |
| Estado vacío | Temáticas, primer uso | `Todavía no has creado ninguna temática.` |
| Estado vacío | Facturas, primer uso | `Todavía no has subido ninguna factura.` |
| Estado vacío | Producto sin compras | `Este producto no tiene compras registradas.` |
| Estado vacío | Informes sin datos en el rango | `No hay movimientos en este periodo.` |
| Estado vacío | Cuentas, primer uso | `Todavía no has añadido ninguna cuenta.` |
| Estado vacío | `BudgetBar` sin ingresos | `Aún no has puesto los ingresos.` |
| Estado vacío | `BudgetBar` sin repartir | `Sin asignar · 2.450,00 €` |
| Estado vacío | Select con búsqueda interna | `Sin resultados` |
| Estado vacío | Factura sin líneas detectadas | `No se ha detectado ninguna línea en este documento.` |
| Error de validación | Importe en 0 o vacío | `Introduce un importe mayor que 0.` |
| Error de validación | Importe por encima del máximo | `El importe no puede pasar de 999.999,99 €.` |
| Error de validación | Campo obligatorio genérico | `Este campo es obligatorio.` |
| Error de validación | Correo con formato inválido | `Introduce un correo electrónico válido.` |
| Error de validación | Correo ya usado en el registro | `Ya existe una cuenta con este correo.` |
| Error de validación | Contraseña demasiado corta | `La contraseña debe tener al menos 8 caracteres.` |
| Error de validación | Confirmación de contraseña distinta | `Las contraseñas no coinciden.` |
| Error de validación | Fecha con formato incorrecto | `Introduce una fecha con el formato 13/08/2026.` |
| Error de validación | Reparto que no llega al importe total | `El reparto no suma el importe total. Faltan 4,20 €.` |
| Error de validación | Reparto que se pasa del importe total | `El reparto supera el importe total. Sobran 4,20 €.` |
| Error de validación | Fusión sin destino elegido | `Elige la temática de destino.` |
| Error de validación | Fusión con la misma temática | `No puedes fusionar una temática con ella misma.` |
| Error de validación | Total de factura y suma de líneas distintos | `El total no coincide con la suma de las líneas. Diferencia de 0,12 €.` |
| Error de validación | Línea de factura sin temática | `Esta línea no tiene temática asignada.` |
| Error de validación | Login con credenciales incorrectas | `El correo o la contraseña no son correctos.` |
| Error de validación | IBAN de una cuenta mal formado | `Introduce un IBAN válido.` |
| Error de validación | Archivo de factura no admitido | `Solo se admiten archivos PDF, JPG o PNG de hasta 10 MB.` |
| Confirmación destructiva | Eliminar un movimiento | `¿Eliminar este movimiento? Se eliminará el gasto de 12,50 € del 13 ago 2026. Esta acción no se puede deshacer.` |
| Confirmación destructiva | Eliminar una temática sin movimientos | `¿Eliminar «Regalos»? No tiene movimientos asociados.` |
| Confirmación destructiva | Eliminar una temática con movimientos | `«Transporte» tiene 18 movimientos. Puedes fusionarla con otra temática o eliminarla junto con su histórico.` |
| Confirmación destructiva | Casilla obligatoria antes de fusionar | `Entiendo que esta acción no se puede deshacer.` |
| Confirmación destructiva | Eliminar una factura | `¿Eliminar esta factura? Los movimientos que creó no se eliminarán, pero perderán el enlace al PDF.` |
| Confirmación destructiva | Eliminar una cuenta bancaria con movimientos | `Esta cuenta tiene 128 movimientos. Elige qué hacer con ellos antes de eliminarla.` |
| Confirmación destructiva | Cerrar sesión en otro dispositivo | `¿Cerrar la sesión en “iPhone de Ana”?` |
| Confirmación destructiva | Cerrar un modal con cambios sin guardar | `Tienes cambios sin guardar. ¿Quieres descartarlos?` |
| Confirmación destructiva | Eliminar la cuenta de usuario en Ajustes | `Esto elimina todos tus datos: movimientos, facturas, temáticas y cuentas. No se puede deshacer. Escribe ELIMINAR para confirmar.` |
