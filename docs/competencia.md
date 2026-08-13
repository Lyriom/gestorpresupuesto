# Análisis de competencia

## Resumen ejecutivo

El mercado de presupuesto personal está muy maduro en el modelo "categoría + rollover + gráficos"
(YNAB, Monarch, Actual Budget, Firefly III, MoneyWiz, Wallet) y hay consenso en qué features son
tabla de apuestas: jerarquía de categorías, splits, transferencias, recurrentes, cash flow, patrimonio
neto. Casi todas dependen de agregación bancaria (Plaid/open banking) o, si son self-hosted
(Actual, Firefly III), son 100% manuales sin ningún tipo de OCR. **Nadie combina** presupuesto
completo + extracción de líneas de factura/ticket + historial de precio por producto multi-proveedor
+ alerta de subida, en un producto self-hosted. Monarch Money es lo más cerca: extrae líneas de
recibos y de Amazon/Target para auto-categorizar mejor, pero no construye histórico de precio por
producto ni compara proveedores, y es SaaS cerrado ligado a banca de EEUU. Apps de "grocery price
tracking" (Groceries Tracker, Grocery Budget: Receipt Scan) sí hacen precio por producto, pero son
mono-función (solo supermercado, solo ticket fotografiado, sin presupuesto ni patrimonio neto, sin
self-host). Ahí está nuestro hueco. Las quejas repetidas del sector (precio de suscripción, sync
bancario que falla, curva de aprendizaje, pérdida de histórico al borrar categorías, falta de app
móvil decente) son evitables por diseño porque partimos de self-hosted y entrada manual/factura.

## Tabla comparativa

| Producto | Modelo de presupuesto | Categorías | Splits/transferencias | Recurrentes | Cuentas/patrimonio | Informes clave | OCR de recibos/facturas | Self-hosted |
|---|---|---|---|---|---|---|---|---|
| YNAB | Zero-based, rollover, "age of money" | Grupos + categorías, sin límite de anidación real (categoría→grupo, 1 nivel) | Sí, sí (transferencias no cuentan como gasto) | Transacciones programadas, no auto-detección | Multi-cuenta, patrimonio neto básico, multi-divisa por presupuesto separado | Gasto por categoría, tendencias, age of money | No | No |
| Monarch Money | Categoría por periodo + "flex budgeting" (fijo/no-mensual/flexible) | Grupos + categorías + tags | Sí, sí, auto-split de pedidos Amazon/Target | Auto-detección de recurrentes/suscripciones con aviso previo | Multi-cuenta, patrimonio neto en tiempo real, inversiones | Cash flow (Sankey/barras), año en revisión, gasto por comercio | Sí (líneas de recibo/email/Amazon para categorizar, no para histórico de precio) | No |
| Actual Budget | Envelope (estilo YNAB), rollover | Grupos + categorías, reglas de categorización | Sí (splits), sí, conciliación | Schedules (recurrentes) | Multi-cuenta, patrimonio neto, cash flow, Sankey | Net worth, cash flow, Sankey, análisis por categoría | No | Sí (self-hosted, MIT) |
| Firefly III | Presupuesto mensual con sobregasto visible, sin "age of money" | Categorías planas + budgets + tags (no hay subcategorías nativas) | Sí (split de transacción), sí (doble entrada) | Recurrencias con patrones complejos ("último viernes del mes") + bills | Multi-cuenta, multi-divisa con tipo de cambio, patrimonio neto | Gráficos por categoría/budget, informes por bill | No (solo adjuntos genéricos sin parsing) | Sí (self-hosted, AGPL) |
| Fintonic | Presupuesto por categoría con % consumido, sin envelope real | Categorías/subcategorías automáticas por motor propio | Limitado | Detecta recibos/comisiones bancarias | Multi-cuenta vía agregación bancaria, sin gestión de deuda avanzada | Informe semanal, alertas de comisión | Sí (ticket/factura por foto, sin histórico de precio confirmado) | No |
| Mint (cerrado 2024) / sucesores | Presupuesto por categoría clásico | Categorías planas con auto-categorización | Sí | Detección de suscripciones (heredada en Rocket Money) | Multi-cuenta agregada, patrimonio neto | Tendencias, comparativa mensual | No | No |
| Money Manager EX | Presupuesto por categoría, mensual/anual | Árbol de categorías anidado, payees reutilizables | Sí (splits), sí | Recordatorios con reglas de repetición | Multi-cuenta, informes SQL personalizados | Cash flow, gráficos configurables | No | Parcial (app de escritorio/local, no servidor multiusuario) |
| MoneyWiz | Presupuesto por categoría + objetivos | Categorías + tags + payees | Sí, sí, conciliación | Recurrentes con reglas | Multi-cuenta, inversiones, préstamos | Net worth, balance over time, cashflow | No | No |
| Wallet (BudgetBakers) | Envelope + presupuesto recurrente combinando categorías | Categorías + labels (tags) | Sí, sí | Pagos planificados con aviso | Multi-cuenta (15.000+ bancos vía Plaid/Salt Edge), deuda | Informes de tendencia y comparativa | Ticket por foto (extracción básica, sin histórico de precio) | No |
| Tiller | Hoja de cálculo, sin motor de presupuesto propio (lo define el usuario) | Categorías + grupos definidos en la plantilla | Manual en la hoja | AutoCat (reglas de categorización), sin detección de recurrentes nativa | Multi-cuenta vía feed diario a Sheets/Excel | Lo que la plantilla calcule (gráficos, budget vs actual) | No | No (SaaS + Google Sheets) |
| Copilot Money | Categoría por periodo con rollover opcional | Grupos + categorías propias/predefinidas | Sí, sí | Auto-detección con aviso de "spot a price increase" en recurrentes | Multi-cuenta, patrimonio neto, inversiones | Tendencias, categorías, recurrentes | No (solo detecta subida de precio en cargos recurrentes, no en productos de ticket) | No |
| Rocket Money | No es de presupuesto por categoría, es gestión de suscripciones + budget simple | Categorías básicas | Limitado | Detección de subida de precio y cancelación/negociación de facturas | Multi-cuenta agregada | Resumen de suscripciones y gasto | No | No |
| PocketSmith | Forecast de cash flow a futuro (calendario, hasta 30 años) | Categorías estándar | Sí | Proyección de recurrentes a futuro | Multi-cuenta, multi-divisa nativo | Calendario de saldo proyectado, cash flow statement | No | No |
| Groceries Tracker / Grocery Budget: Receipt Scan / Grocery Prices History | No tienen presupuesto general, son mono-función | Categoría de producto básica | No aplica | No aplica | No aplica (no son gestores financieros) | Precio por producto, comparación entre tiendas | **Sí, este es su único objetivo**: OCR de ticket con historial de precio por producto | No |

## Producto a producto

### YNAB
**Qué hace bien**: metodología zero-based muy pedagógica (dale un trabajo a cada euro), rollover
automático de saldo no gastado, métrica "age of money" para medir colchón real, splits y
transferencias bien resueltas, atajos de teclado extensos y app rápida, "reflect" de tarjetas de
crédito como categoría de deuda (evita duplicar el gasto). **Qué le falta**: sin adjuntos de recibo
nativos (queja recurrente), sin OCR de ningún tipo, subcategorías limitadas a un solo nivel
grupo→categoría, multi-divisa requiere presupuestos separados, precio de suscripción alto y
creciente (109 $/año) que genera fatiga de suscripción. **Qué le robamos**: el concepto de "dale un
trabajo a cada euro" aplicado a la barra de presupuesto, el rollover de saldo no gastado por
temática, y la disciplina de age-of-money como métrica opcional de salud financiera.

### Monarch Money
**Qué hace bien**: es el más completo en automatismos: auto-detecta recurrentes/suscripciones con
aviso antes del cobro, splitea automáticamente pedidos de Amazon/Target por línea de producto,
tiene reportes de cash flow tipo Sankey y "año en revisión", permite adjuntar y ahora también
escanear recibos con extracción de comercio/importe/fecha/líneas cuando el formato lo permite.
**Qué le falta**: la extracción de líneas es para mejorar la categorización de una transacción
puntual, no construye histórico de precio por producto ni compara precios entre tiendas o a lo
largo del tiempo; depende 100% de vincular bancos (EEUU/Canadá), cerrado y de pago (14,99 $/mes);
sin self-host ni control de datos. **Qué le robamos**: el patrón de "flex budgeting" (fijo /
no-mensual recurrente / flexible), el auto-split de una compra en varias temáticas a partir de las
líneas detectadas, y el diseño del informe de cash flow tipo Sankey.

### Actual Budget
**Qué hace bien**: es la referencia de "YNAB self-hosted": envelope budgeting, importador nativo de
YNAB4/nYNAB, reglas de categorización y normalización de comercio, schedules para recurrentes,
Sankey y net worth ya integrados, API local completa para scripting, licencia MIT. **Qué le falta**:
sin app móvil nativa mantenida (solo PWA/web responsive, queja habitual), cero OCR/adjuntos con
parsing, multi-divisa limitado, sin detección automática de suscripciones. **Qué le robamos**: el
modelo de reglas de categorización + normalización de payee, el enfoque "importador de todo lo que
exporte un banco" (CSV/OFX/QIF) y el patrón de fusión de transacciones duplicadas como base para
nuestra fusión de temáticas.

### Firefly III
**Qué hace bien**: es el self-hosted más "serio" en contabilidad: doble entrada real, piggy banks
(fondos objetivo/sinking funds) enlazables a transferencias automáticas, reglas de automatización
muy potentes (condición sobre importe/descripción/cuenta → categoría/tag/budget), bills con patrones
de recurrencia complejos, API REST completa, multi-divisa con tipo de cambio y patrimonio neto
correcto. **Qué le falta**: sin subcategorías nativas (categorías planas, queja repetida de
usuarios), setup técnico exigente (Docker + BD + colas), sin ningún OCR ni parsing de adjuntos
(los archivos adjuntos son ficheros sueltos sin extracción), UI percibida como densa/poco pulida.
**Qué le robamos**: piggy banks como inspiración directa para "fondos objetivo" ligados a una
temática, el motor de reglas condición→acción, y el patrón de bills con recurrencia compleja.

### Fintonic
**Qué hace bien**: para el mercado español es la referencia histórica: categorización automática
por motor propio, informe semanal todos los lunes, alertas de comisiones bancarias y cargos
duplicados/no autorizados, sincronización bancaria gratuita (raro en el sector). **Qué le falta**:
quejas muy consistentes de fallos de sincronización con bancos, funciones de presupuesto y ahorro
recortadas con el tiempo, soporte lento, exceso de comunicaciones comerciales (venta cruzada de
préstamos y seguros), app sin actualizaciones significativas recientes. **Qué le robamos**: el
formato de informe semanal como notificación (adaptado a "resumen semanal de tu barra de
presupuesto") y la idea de alertas de anomalía bancaria como categoría de alerta a futuro.

### Mint y sucesores (Credit Karma, Monarch, Rocket Money, Quicken Simplifi)
Mint cerró en marzo de 2024 tras 15 años y su base de 25 millones de usuarios se dispersó: Credit
Karma (el sucesor oficial de Intuit) eliminó presupuestos por categoría, alertas personalizadas e
histórico de patrimonio neto porque su negocio real es scoring de crédito y ofertas, no presupuesto.
Los usuarios migraron sobre todo a Monarch Money (el sucesor "espiritual" más cercano en UX) y a
Rocket Money (gestión de suscripciones). **Lección clave**: un producto de presupuesto gratuito
financiado por venta de datos/leads es frágil a largo plazo; refuerza el valor de un self-hosted
sin ese incentivo perverso.

### Money Manager EX
**Qué hace bien**: árbol de categorías anidado real (no solo un nivel), payees reutilizables con
auto-relleno, informes construidos sobre SQL personalizable (muy potente para usuarios avanzados),
gratuito y multiplataforma (incluye escritorio, útil como referencia de UI densa tipo hoja de
cálculo). **Qué le falta**: sin sync ni backend multiusuario real, UI anticuada, sin ningún tipo de
OCR, sin detección de recurrentes inteligente (son recordatorios fijos). **Qué le robamos**: el
árbol de categorías con niveles ilimitados y el motor de informes configurables como referencia de
flexibilidad de consulta.

### MoneyWiz
**Qué hace bien**: catálogo de informes predefinidos muy claro (Net Worth, Balance Over Time,
Balance Summary, Cashflow), objetivos de ahorro, gestión de préstamos con calendario de
amortización, tags independientes de categorías. **Qué le falta**: de pago con sync en la nube
propietaria, sin OCR de tickets con línea de producto, curva de aprendizaje media-alta por la
cantidad de opciones. **Qué le robamos**: el catálogo de informes "listos para usar" con nombre
claro (Balance Summary, Balance Over Time) como plantilla de nuestra sección de informes.

### Wallet (BudgetBakers)
**Qué hace bien**: combina envelope budgeting con presupuestos recurrentes configurables, "labels"
como capa de etiquetado ortogonal a la categoría (permite ver el mismo gasto desde dos ejes:
categoría + etiqueta libre), escaneo de tickets por foto, alcance geográfico amplio (soporta miles
de bancos). **Qué le falta**: el escaneo de ticket es solo para registrar el gasto más rápido, no
construye historial de precio por producto ni compara con compras anteriores; de pago para
funciones avanzadas; depende de agregación bancaria para el valor completo. **Qué le robamos**: el
patrón "labels" como etiqueta libre ortogonal a la temática (nosotros ya tenemos temáticas
anidables, pero un tag libre adicional es útil para cosas transversales tipo "viaje Roma 2026" o
"deducible IRPF").

### Tiller
**Qué hace bien**: máxima flexibilidad porque el usuario controla la hoja de cálculo (Google
Sheets/Excel) con feed diario automatizado de transacciones, reglas de auto-categorización
(AutoCat) editables como fórmulas, comunidad con 35+ plantillas para casos específicos (deuda,
inversión, alquiler). **Qué le falta**: no es una app per se, requiere mantenimiento de la hoja,
sin app móvil real, sin ningún OCR, curva de entrada alta para quien no domina hojas de cálculo.
**Qué le robamos**: la idea de reglas de categorización expresadas como texto simple editable por
el usuario (similar a las reglas de Firefly III/Actual) y el catálogo de plantillas por caso de uso
como inspiración para vistas/informes predefinidos.

### Copilot Money
**Qué hace bien**: UI muy pulida (solo Apple), IA para categorización, detección de recurrentes con
aviso explícito de "spot a price increase" antes de la renovación, rollover opcional por categoría,
inversiones y patrimonio neto integrados. **Qué le falta**: la detección de subida de precio es solo
sobre cargos recurrentes idénticos en el extracto bancario (SaaS, Apple-only), no sobre productos
dentro de un ticket/factura; sin Android ni self-host; sin OCR de líneas de producto. **Qué le
robamos**: el copy y el concepto de "alerta de subida de precio" tal cual, pero aplicado a nuestro
nivel más granular (producto dentro de una factura, no solo el cargo recurrente completo).

### Otros relevantes
- **Money Lover** (popular en España): permite fotografiar tickets para añadir el gasto y vincular
  cuentas bancarias; el foco es velocidad de entrada, no histórico de precio.
- **Rocket Money**: gestión de suscripciones con alerta de subida de precio de cargos recurrentes y
  servicio de negociación de facturas (con comisión sobre el ahorro). Confirma que "avisar de subida
  de precio" es un dolor validado y monetizable, pero solo a nivel de cargo recurrente, nunca a nivel
  de producto de un ticket.
- **PocketSmith**: su diferenciador es el forecast de cash flow día a día hasta 30 años vista en
  formato calendario; útil como inspiración para una vista de "saldo proyectado" a fin de mes dentro
  de la barra de presupuesto.
- **Goodbudget / EveryDollar / PocketGuard**: envelope apps americanas clásicas; aportan el concepto
  de "sinking fund"/fondo por evento (coche, vacaciones) y, en PocketGuard, el indicador "In My
  Pocket" (cuánto puedes gastar hoy después de cubrir fijos y objetivos) como métrica derivada de la
  barra de presupuesto.
- **Groceries Tracker / Grocery Budget: Receipt Scan / Grocery Prices History**: apps mono-función
  que sí construyen historial de precio por producto a partir de tickets fotografiados y comparan
  precio entre tiendas/marcas; son la prueba de que el dolor "el súper me está subiendo el precio
  sin que me dé cuenta" existe y tiene demanda, pero ninguna las integra con un presupuesto completo,
  patrimonio neto, ni facturas PDF de proveedores no-retail (luz, gas, telco, seguros), y ninguna es
  self-hosted.

## Catálogo de funcionalidades priorizado

| ID | Funcionalidad | Descripción en una línea | Prioridad | Complejidad | Inspirado en |
|---|---|---|---|---|---|
| F-01 | Ingreso mensual editable | Registrar uno o varios ingresos del mes que alimentan el total a repartir | P0 | S | Genérico (todos) |
| F-02 | Barra de presupuesto por temática | Barra visual que se consume según el gasto acumulado por temática y periodo | P0 | M | YNAB, Fintonic |
| F-03 | Temáticas anidables multinivel | Categorías jerárquicas sin límite de profundidad, no solo un nivel grupo→categoría | P0 | M | Money Manager EX |
| F-04 | Fusión de temáticas con reasignación de histórico | Combinar dos temáticas y mover todas las transacciones/facturas asociadas sin perder datos | P0 | M | Actual Budget (merge duplicados), YNAB (merge categorías) |
| F-05 | Renombrado de temática sin romper histórico | Cambiar nombre/color/icono de una temática sin afectar informes pasados | P0 | S | Copilot Money |
| F-06 | Ocultar temática en vez de borrar | Archivar una temática que ya no se usa conservando su histórico visible en informes | P0 | S | Actual Budget |
| F-07 | Registro rápido de gasto | Formulario mínimo (importe, temática, fecha) para apuntar un gasto en menos de 10 segundos | P0 | S | YNAB, Copilot |
| F-08 | Splits de una transacción | Repartir un único gasto entre varias temáticas con importes independientes | P0 | M | YNAB, Monarch, Actual |
| F-09 | Transferencias entre cuentas | Movimiento entre dos cuentas propias que no cuenta como gasto/ingreso | P0 | S | YNAB, Firefly III |
| F-10 | Tipos de cuenta (corriente, ahorro, tarjeta, efectivo, inversión, deuda) | Clasificar cada cuenta por tipo para cálculos de patrimonio neto correctos | P0 | S | MoneyWiz, Firefly III |
| F-11 | Patrimonio neto | Suma de activos menos pasivos de todas las cuentas, con evolución en el tiempo | P0 | M | Monarch, Actual, MoneyWiz |
| F-12 | Subida de factura PDF | Subir un PDF de factura/ticket y guardarlo vinculado a un gasto | P0 | S | Diferenciador propio |
| F-13 | Extracción de líneas de producto | Extraer nombre, cantidad, precio unitario y total de cada línea de la factura (pdfplumber/PyMuPDF + fallback OCR Tesseract) | P0 | L | Diferenciador propio, invoice2data |
| F-14 | Revisión y corrección manual de líneas extraídas | Pantalla para corregir lo que el parser interpretó mal antes de confirmar | P0 | M | Diferenciador propio |
| F-15 | Historial de precio por producto | Guardar cada precio unitario visto de un producto con fecha y proveedor | P0 | M | Groceries Tracker, Grocery Prices History |
| F-16 | Detección de subida de precio por producto | Comparar el precio nuevo contra el histórico del mismo producto y marcarlo si sube | P0 | M | Groceries Tracker, Copilot (recurrentes) |
| F-17 | Vinculación línea de factura → temática | Asignar cada línea de producto a una temática, con recuerdo de la última asignación | P0 | M | Monarch (auto-split Amazon) |
| F-18 | Desglose de gasto por temática (informe) | Tabla/gráfico de cuánto se ha gastado en cada temática en el periodo | P0 | S | Todos |
| F-19 | Comparativa mes a mes | Gráfico de evolución del gasto total y por temática entre meses | P0 | M | Monarch, MoneyWiz |
| F-20 | Aviso de sobrepaso de presupuesto | Notificación/indicador visual cuando una temática supera su presupuesto asignado | P0 | S | YNAB, Fintonic, Wallet |
| F-21 | Adjuntos en transacciones | Adjuntar imagen/PDF a cualquier gasto, no solo a facturas parseadas | P0 | S | Firefly III, Monarch |
| F-22 | Login propio con usuario/contraseña | Autenticación simple sin dependencia de terceros ni banca abierta | P0 | S | Requisito del proyecto |
| F-23 | Modo oscuro | Tema oscuro como principal en toda la interfaz | P0 | S | YNAB, Firefly III |
| F-24 | PWA instalable | App instalable en móvil/escritorio desde el navegador, funcional sin tienda de apps | P0 | M | Actual Budget (web responsive) |
| F-25 | Importación CSV de movimientos bancarios | Subir extracto CSV del banco para dar de alta transacciones en bloque | P0 | M | Actual Budget, Firefly III, Money Manager EX |
| F-26 | Rollover de saldo no gastado | El sobrante de una temática al cierre del mes se traspasa (o no, configurable) al mes siguiente | P1 | M | YNAB, Actual Budget, Copilot |
| F-27 | Reglas de auto-categorización por comercio/texto | Reglas "si el comercio contiene X → temática Y" aplicadas a nuevas transacciones e importaciones | P1 | M | Actual Budget, Firefly III, Tiller (AutoCat) |
| F-28 | Transacciones recurrentes/programadas | Definir un gasto o ingreso que se repite (alquiler, nómina) y se genera automáticamente | P1 | M | Firefly III (bills), YNAB (scheduled) |
| F-29 | Detección automática de suscripciones | Identificar cargos recurrentes similares en el histórico y listarlos como "suscripciones" | P1 | L | Monarch, Copilot, Rocket Money |
| F-30 | Alerta de subida de precio en suscripción/recurrente | Avisar cuando el importe de un cargo recurrente detectado sube respecto al anterior | P1 | M | Copilot, Rocket Money |
| F-31 | Fondos objetivo / sinking funds | Meta de ahorro ligada a una temática con importe objetivo y fecha, tipo "vacaciones" o "coche" | P1 | M | Firefly III (piggy banks), Goodbudget, EveryDollar |
| F-32 | Reconciliación de cuenta | Comparar saldo real del banco con el saldo registrado y ajustar diferencias | P1 | M | YNAB, MoneyWiz |
| F-33 | Importación OFX/QIF | Soporte de formatos bancarios adicionales a CSV | P1 | S | Actual Budget, Firefly III |
| F-34 | Detección de duplicados en importación/facturas | Evitar dar de alta dos veces la misma transacción o la misma factura reimportada | P1 | M | Actual Budget (merge), gestores de facturas |
| F-35 | Etiquetas (tags) libres ortogonales a temática | Marcar transacciones con etiquetas libres transversales (ej. "viaje", "deducible") además de la temática | P1 | S | Wallet (labels), MoneyWiz (tags) |
| F-36 | Informe de cash flow | Gráfico de entradas vs salidas de dinero por periodo | P1 | M | Monarch, Actual Budget, MoneyWiz |
| F-37 | Informe top comercios/proveedores | Ranking de dónde se gasta más, con filtro por periodo y temática | P1 | S | Monarch, MoneyWiz |
| F-38 | Comparador de precio entre proveedores del mismo producto | Ver el mismo producto comprado en distintos sitios y comparar precio | P1 | M | Groceries Tracker (comparación entre tiendas) |
| F-39 | Normalización/fuzzy-matching de nombre de producto | Reconocer que "Leche Pascual 1L" y "LECHE PASCUAL 1L BRIK" son el mismo producto (RapidFuzz) | P1 | L | Diferenciador propio |
| F-40 | Plantillas de extracción por proveedor | Guardar cómo se interpreta el PDF de un proveedor concreto para acelerar futuras facturas suyas | P1 | L | invoice2data (plantillas YAML) |
| F-41 | Gestión de deuda/préstamo con calendario | Cuenta de tipo deuda con cuota, interés y fecha de fin, con amortización visible | P1 | M | MoneyWiz, Firefly III |
| F-42 | Búsqueda y filtros combinables de transacciones | Filtrar por temática, cuenta, rango de fechas, importe y texto libre a la vez | P1 | M | Money Manager EX, MoneyWiz |
| F-43 | Exportación/backup de datos propios | Exportar todo (transacciones, facturas, configuración) en formato abierto | P1 | S | Actual Budget, Firefly III |
| F-44 | Notas/memo en transacciones | Campo de texto libre adicional en cada movimiento | P1 | S | Todos |
| F-45 | Digest semanal/mensual por email o notificación | Resumen periódico de cómo va la barra de presupuesto y qué subió de precio | P1 | M | Fintonic (informe semanal) |
| F-46 | Atajos de teclado para entrada rápida | Navegación y alta de transacciones sin ratón para power users | P1 | S | YNAB |
| F-47 | Multi-cuenta con saldo proyectado a fin de mes | Estimar saldo a fin de mes según recurrentes pendientes y presupuesto restante | P1 | M | PocketSmith (forecast) |
| F-48 | Detección de gasto inusual | Marcar una transacción cuyo importe se desvía mucho de la media histórica de esa temática/comercio | P1 | L | Fintonic (alertas), Monarch |
| F-49 | Recordatorio de vencimiento de factura/recurrente | Aviso antes de la fecha esperada de cobro de un recurrente detectado | P1 | S | Rocket Money, Firefly III (bills) |
| F-50 | Onboarding guiado inicial | Asistente de primeros pasos: crear cuentas, temáticas base e ingreso del mes | P1 | S | Genérico (todos) |
| F-51 | Bandeja de entrada de facturas por email | Reenviar la factura a un correo propio del sistema para que se procese sola | P2 | L | Monarch (email forwarding) |
| F-52 | Multi-divisa con tipo de cambio | Soportar cuentas en divisas distintas al euro con conversión para informes | P2 | L | Firefly III, PocketSmith, YNAB |
| F-53 | Informe Sankey de flujo de dinero | Visualización de flujo ingreso→cuenta→temática→gasto | P2 | M | Actual Budget, Monarch |
| F-54 | Forecast de saldo a largo plazo (calendario) | Vista de calendario con saldo proyectado día a día a varios meses/años vista | P2 | L | PocketSmith |
| F-55 | Indicador "disponible para gastar hoy" | Métrica derivada: dinero libre tras cubrir fijos y objetivos del mes | P2 | S | PocketGuard ("In My Pocket") |
| F-56 | Métrica tipo "age of money" | Indicador de cuántos días de colchón hay entre ingreso y gasto | P2 | M | YNAB |
| F-57 | Multiusuario con roles (solo lectura/edición) | Permitir un segundo miembro de la familia con permisos distintos | P2 | M | MoneyWiz, Monarch (shared) |
| F-58 | API REST propia documentada | Exponer los datos vía API para scripts/integraciones propias | P2 | M | Firefly III, Actual Budget |
| F-59 | Reglas de categorización editables por el usuario en texto simple | Editor de reglas tipo "si contiene X → Y" expuesto como texto, no solo UI de formulario | P2 | M | Tiller (AutoCat) |
| F-60 | Comparativa de cesta de la compra entre supermercados | Vista dedicada que suma el precio actual de los productos habituales en cada proveedor visto | P2 | L | Groceries Tracker |

## Huecos del mercado que podemos explotar

- **Nadie junta presupuesto + factura + precio por producto + self-hosted.** Los self-hosted
  (Actual Budget, Firefly III) son 100% manuales y sin OCR. Los que tienen OCR de recibo (Monarch,
  Wallet, Money Lover) lo usan solo para acelerar el alta del gasto o mejorar la categorización, no
  para construir histórico de precio ni comparar proveedores. Los que sí hacen precio por producto
  (Groceries Tracker y similares) son apps mono-función sin presupuesto, sin cuentas, sin patrimonio
  neto y sin self-host.
- **Facturas PDF de proveedor, no solo tickets fotografiados de supermercado.** Todo el ecosistema
  de "grocery price tracking" está pensado para tickets de caja fotografiados con el móvil. Nadie
  está resolviendo el caso de la factura PDF de luz, gas, telco, seguro o proveedor B2C con IVA
  desglosado y formato variable por emisor — que es justamente donde `invoice2data`/plantillas por
  proveedor aportan más valor y donde el usuario final español tiene más dolor real (comparar cuánto
  ha subido la luz o el gas mes a mes, línea a línea).
- **Fusión de temáticas con reasignación de histórico como primera clase.** YNAB y Actual permiten
  fusionar categorías, pero es un flujo secundario. Hacerlo un concepto central (con fusión de
  producto/proveedor también, vía fuzzy-matching) es diferencial: nadie reconcilia "esto que llamé
  Netflix en enero y Netflix.com en marzo son la misma suscripción/producto".
- **Alerta de subida de precio a nivel de producto, no solo de cargo recurrente.** Copilot y Rocket
  Money avisan si sube un cargo recurrente completo (la cuota de Netflix). Ninguno avisa si dentro de
  la compra del súper una marca de aceite subió un 8% mientras el resto de la cesta se mantuvo igual.
  Ese nivel de granularidad es nuestro terreno propio.
- **Self-hosted sin fricción de setup.** Firefly III es potente pero su queja principal es el setup
  técnico (Docker + BD + colas) para quien no es técnico. Al ser monolito FastAPI+Postgres pensado
  para EasyPanel con un solo contenedor, podemos ofrecer la robustez de un Firefly III con el setup de
  un Actual Budget, y sumar el diferenciador de facturas que ninguno de los dos tiene.
- **Sin incentivo de venta cruzada.** Fintonic, YNAB, Monarch, Rocket Money monetizan con
  suscripción, venta de leads (préstamos/seguros) o servicios de negociación con comisión. Al ser
  autoconsumo self-hosted no hay ese conflicto de interés, lo que permite alertas y recomendaciones
  puramente a favor del usuario (algo que los usuarios de Fintonic explícitamente reclaman que se ha
  perdido).

## Antipatrones

- **Sync bancario que falla silenciosamente o deja de estar disponible** (Fintonic, Wallet): genera
  desconfianza y abandono. Nuestra entrada es manual/por factura, así que hay que evitar el
  antipatrón inverso: que la entrada manual sea tan lenta que el usuario abandone el hábito.
- **Curva de aprendizaje empinada sin motivo** (YNAB, especialmente el manejo de tarjetas de
  crédito): documentar y simplificar el modelo mental de "barra que se consume" desde el primer uso,
  con onboarding guiado (F-50).
- **Subida de precio de suscripción constante y percibida como injusta** (YNAB pasó de 60 $ único a
  109 $/año): al ser self-hosted no aplica directamente, pero refuerza que el mensaje de producto
  ("tú controlas tu servidor y tus datos") debe mantenerse como ventaja, no solo como detalle técnico.
- **Pérdida de histórico al borrar una categoría**: varios usuarios de distintas apps reportan
  sorpresa cuando borrar una categoría descoloca informes pasados. Nuestra fusión (F-04) y archivado
  (F-06) deben ser el único camino soportado; nunca ofrecer un borrado duro sin reasignación.
  Categorías planas sin subcategorías nativas (queja repetida de usuarios de Firefly III): la
  jerarquía multinivel (F-03) debe estar en el MVP, no como mejora posterior.
- **Ausencia de app móvil mantenida** (Actual Budget descontinuó su app nativa): mitigado con PWA
  (F-24) desde el principio en vez de prometer apps nativas que luego no se mantienen.
- **Exceso de notificaciones comerciales y venta cruzada** (Fintonic): cualquier notificación debe
  ser accionable y financiera (sobregasto, subida de precio), nunca promocional.
- **Reportes bonitos pero no accionables** ("vanity metrics" en varias apps con muchos gráficos pero
  ninguna alerta clara): priorizar alertas concretas (F-20, F-30, F-48) sobre añadir más gráficos
  decorativos.
- **Parsing de factura que exige corrección manual sistemática sin aprender del error**: si el OCR
  falla siempre igual con un proveedor, debe poder guardarse una plantilla (F-40) para no repetir la
  corrección cada mes.
- **Setup técnico como barrera de entrada** (Firefly III): mantener el despliegue en un único
  contenedor Docker sobre EasyPanel como ventaja competitiva frente a stacks multi-contenedor.

## Fuentes

- [Support YNAB — Reconciliación](https://support.ynab.com/en_us/reconciling-accounts-a-guide-BJFE3fHys)
- [Support YNAB — Split Transactions](https://support.ynab.com/en_us/split-transactions-a-guide-SJLEKwY0q)
- [Support YNAB — Multi-divisa](https://support.ynab.com/en_us/using-multiple-currencies-in-ynab-a-guide-SyBF6PHno)
- [Support YNAB — Keyboard Shortcuts](https://support.ynab.com/en_us/keyboard-shortcuts-Skw9Xp9A9)
- [Support YNAB — Dark Mode](https://support.ynab.com/en_us/how-to-enable-dark-mode-rJQOmvYA9)
- [Support YNAB — Widget móvil](https://support.ynab.com/en_us/ynab-widget-for-mobile-a-guide-HJPEEQYR9)
- [YNAB — Keyboard Shortcuts (blog)](https://www.ynab.com/whats-new/keyboard-shortcuts-the-fastest-way-to-ynab)
- [Productive with Chris — YNAB review 2025 (quejas)](https://productivewithchris.com/app-reviews/ynab-review-2025/)
- [Trustpilot — Reviews YNAB](https://www.trustpilot.com/review/ynab.com)
- [Monarch Help — Splitting Transactions](https://help.monarch.com/hc/en-us/articles/360050178492-Splitting-Transactions)
- [Monarch Help — Creating Your Budget](https://help.monarch.com/hc/en-us/articles/360048883631-Creating-Your-Budget-in-Monarch)
- [Monarch — Track recurring bills and subscriptions](https://www.monarch.com/blog/track-recurring-bills-and-subscriptions)
- [Monarch Help — Using Reports](https://help.monarch.com/hc/en-us/articles/21846787088916-Using-Reports)
- [Monarch Help — Cash Flow](https://help.monarch.com/hc/en-us/articles/20504904768020-Cash-Flow)
- [Monarch — Expense & Net Worth Tracking](https://www.monarchmoney.com/features/spending)
- [Monarch Help — Receipt and Image Imports with Receipt Scanning](https://help.monarch.com/hc/en-us/articles/44244210547860-Receipt-and-Image-Imports-with-Receipt-Scanning)
- [Monarch Help — Retail Sync Extension](https://help.monarch.com/hc/en-us/articles/36463599367188-Using-the-Retail-Sync-Extension)
- [Monarch — Your Amazon orders, perfectly categorized](https://www.monarch.com/blog/monarch-extension-and-more)
- [Sacra Chat — Monarch merchant-level receipt parsing](https://sacra.com/chat/h/fa871fa4-1efc-4d62-bf70-137ba55e524f/)
- [Actual Budget Docs — Categories](https://actualbudget.org/docs/budgeting/categories/)
- [Actual Budget Docs — Rules](https://actualbudget.org/docs/budgeting/rules/)
- [Actual Budget Docs — Merging Duplicate Transactions](https://actualbudget.org/docs/transactions/merging/)
- [Actual Budget Docs — Sankey Report](https://actualbudget.org/docs/experimental/sankey-report/)
- [Actual Budget Docs — Reports](https://actualbudget.org/docs/reports/)
- [Actual Budget — Release 26.5.0](https://actualbudget.org/blog/release-26.5.0/)
- [ExpenseSorted — Actual Budget review 2026](https://www.expensesorted.com/blog/144_actual_budget)
- [GitHub — actual-budget](https://github.com/actual-budget)
- [Firefly III Docs — Introduction and features](https://docs.firefly-iii.org/explanation/firefly-iii/about/introduction/)
- [Firefly III Docs — Piggy banks how-to](https://docs.firefly-iii.org/how-to/firefly-iii/finances/piggy-banks/)
- [Firefly III Docs — Piggy banks concept](https://docs.firefly-iii.org/explanation/financial-concepts/piggy-banks/)
- [Firefly III Docs — Third-party apps](https://docs.firefly-iii.org/references/firefly-iii/third-parties/apps/)
- [GitHub — firefly-iii/firefly-iii](https://github.com/firefly-iii/firefly-iii)
- [ExpenseSorted — Firefly III review 2026](https://www.expensesorted.com/blog/147_firefly_iii)
- [AlternativeTo — Firefly III](https://alternativeto.net/software/firefly-iii/about/)
- [Fintonic — Descubriendo la app: Presupuestos](https://www.fintonic.com/blog/descubriendo-la-app-de-fintonic-presupuestos/)
- [Banktrack — Alternativas a Fintonic](https://banktrack.com/blog/alternativas-fintonic)
- [Opiniones España — Fintonic](https://opinionesespana.es/fintonic-opiniones)
- [Línea Legal — Opiniones negativas de Fintonic](https://linealegal.es/fintonic-opiniones-negativas/)
- [Roams — Opiniones Fintonic](https://roams.es/finanzas/entidades-financieras/fintonic/opiniones/)
- [Rocket Money — Mint app shutting down](https://www.rocketmoney.com/learn/personal-finance/mint-app-shutting-down)
- [AlternativeTo News — Intuit discontinúa Mint](https://alternativeto.net/news/2023/11/intuit-to-discontinue-mint-app-in-2024-merging-features-into-credit-karma/)
- [X1 Wealth — Mint alternatives](https://x1wealth.com/compare/mint-alternatives)
- [Money Manager EX — sitio oficial](https://moneymanagerex.org/)
- [Money Manager EX — Manual de usuario Android](http://android.moneymanagerex.org/usermanual/)
- [MoneyWiz Help — Generating reports](https://help.wiz.money/en/articles/4440626-generating-reports)
- [BudgetBakers — Wallet Features](https://budgetbakers.com/en/products/wallet/features/)
- [BudgetBakers — Introducing Labels](https://budgetbakers.com/introducing-labels-wallet/)
- [Tiller — Features](https://tiller.com/features/)
- [Tiller — Budget Spreadsheet Templates](https://tiller.com/resources/personal-finance-spreadsheet-templates/budget-spreadsheet-templates/)
- [Copilot Money — sitio oficial](https://www.copilot.money/)
- [Copilot Help — Quick Start Guide](https://help.copilot.money/en/articles/11157550-quick-start-guide)
- [Forbes Advisor — Copilot budget app review](https://www.forbes.com/advisor/banking/copilot-budget-app-review/)
- [Rocket Money — Tracking expenses](https://www.rocketmoney.com/learn/personal-finance/tracking-expenses-with-rocket-money)
- [Rocket Money Help — Bill Negotiation](https://help.rocketmoney.com/en/articles/9744564-how-to-submit-a-bill-negotiation)
- [Rocket Money — vs Monarch Money](https://www.rocketmoney.com/learn/personal-finance/monarch-money-vs-rocket-money)
- [PocketSmith — Cash Flow Forecasts](https://www.pocketsmith.com/tour/cash-flow-forecasts/)
- [PocketSmith Learn Center — Calendar & forecasting](https://learn.pocketsmith.com/article/506-calendar-forecasting)
- [Ramsey Solutions — Goodbudget vs EveryDollar](https://www.ramseysolutions.com/budgeting/goodbudget-vs-everydollar)
- [PocketGuard — Best free budget apps 2026](https://pocketguard.com/blog/best-free-budget-apps/)
- [FinCompareLab — Goodbudget review](https://www.fincomparelab.com/reviews/goodbudget-review/)
- [Groceries Tracker — sitio oficial](https://groceriestracker.com/)
- [Groceries Tracker — Best grocery price comparison apps 2026](https://groceriestracker.com/blog/best-grocery-price-comparison-apps-2026)
- [Google Play — Grocery Budget: Receipt Scan](https://play.google.com/store/apps/details?id=grocery.tracker.pro&hl=en_US)
- [App Store — Grocery Prices History](https://apps.apple.com/us/app/id1474544565)
- [ADSLZone — Top apps control de gastos](https://www.adslzone.net/noticias/moviles/top-apps-control-gastos/)
- [Generation Wealth — Apps controlar gastos y digitalizar tickets](https://www.generationwealth.es/credito-prestamos/mejores-apps-controlar-gastos-digitalizar-tickets)
- [GitHub — invoice-x/invoice2data](https://github.com/invoice-x/invoice2data)
- [invoice2data docs — How it works](https://invoice2data.readthedocs.io/latest/how-it-works.html)
- [invoicedataextraction.com — Open Source OCR for Invoice Extraction](https://invoicedataextraction.com/blog/open-source-ocr-invoice-extraction)
