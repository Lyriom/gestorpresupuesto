# Estado de las funcionalidades

Estado real de las 60 funcionalidades del [catálogo priorizado](competencia.md), con
la evidencia de dónde está cada una. Se actualiza a mano cuando se cierra una.

**Leyenda**: ✅ terminada y probada · 🟡 el backend está, la pantalla no (o al
revés) · ⬜ pendiente.

## Resumen

| Prioridad | Total | ✅ | 🟡 | ⬜ |
| --- | --- | --- | --- | --- |
| P0 (imprescindible) | 25 | 24 | 1 | 0 |
| P1 (alto valor) | 25 | 18 | 6 | 1 |
| P2 (nice-to-have) | 10 | 2 | 1 | 7 |
| **Total** | **60** | **44** | **8** | **8** |

Del MVP (los 25 P0) está todo terminado salvo la pantalla de importación de
CSV, cuyo backend sí está completo y probado. Las cifras se actualizan cuando
el trabajo en curso queda verificado.

## P0 — imprescindibles

| ID | Funcionalidad | Estado | Dónde está |
| --- | --- | --- | --- |
| F-01 | Ingreso mensual editable | ✅ | `GET/PUT /budgets/{periodo}`, `GET /budgets/{periodo}/incomes` |
| F-02 | Barra de presupuesto por temática | ✅ | `services/presupuesto.py`, `components/presupuesto/BarraPresupuesto.vue` |
| F-03 | Temáticas anidables multinivel | ✅ | `GET /categories/tree`, `POST /categories/{id}/move`, `TematicasVista.vue` |
| F-04 | Fusión de temáticas con reasignación | ✅ | `services/fusion.py`, `POST /categories/merge` (+ `preview` y `undo`) |
| F-05 | Renombrado sin romper histórico | ✅ | `PATCH /categories/{id}` |
| F-06 | Archivar en vez de borrar | ✅ | `POST /categories/{id}/archive` y `/unarchive` |
| F-07 | Registro rápido de gasto | ✅ | Modal de alta en `MovimientosVista.vue` |
| F-08 | Splits de una transacción | ✅ | `PUT /transactions/{id}/splits`, con la suma validada al céntimo |
| F-09 | Transferencias entre cuentas | ✅ | `/transfers`, con sus dos patas y fuera de los informes de gasto |
| F-10 | Tipos de cuenta | ✅ | `POST /accounts`, seis tipos |
| F-11 | Patrimonio neto | ✅ | `GET /accounts/summary`, `GET /reports/net-worth` |
| F-12 | Subida de factura PDF | ✅ | `POST /invoices`, validando por firma del fichero |
| F-13 | Extracción de líneas de producto | ✅ | `services/extraccion_pdf.py`: tablas, texto y OCR |
| F-14 | Revisión y corrección manual | ✅ | `RevisionFacturaVista.vue`, con la confianza por línea |
| F-15 | Historial de precio por producto | ✅ | `GET /products/{id}/prices`, `services/precios.py` |
| F-16 | Detección de subida de precio | ✅ | `GET /reports/price-increases`, con alerta |
| F-17 | Línea de factura → temática | ✅ | `PATCH /invoices/{id}/lines/{id}`, recuerda la última asignación |
| F-18 | Desglose de gasto por temática | ✅ | `GET /reports/spending-by-category` |
| F-19 | Comparativa mes a mes | ✅ | `GET /reports/monthly-comparison` |
| F-20 | Aviso de sobrepaso de presupuesto | ✅ | Estado `sobrepasado` en la barra + alerta |
| F-21 | Adjuntos en transacciones | ✅ | `/transactions/{id}/attachments`, validados por firma |
| F-22 | Login propio | ✅ | `/auth/*`, cookies httpOnly con CSRF |
| F-23 | Modo oscuro | ✅ | `styles/tema.css`, es el tema por defecto |
| F-24 | PWA instalable | ✅ | `public/manifest.webmanifest`, `public/sw.js` con los datos nunca cacheados, iconos y atajos |
| F-25 | Importación CSV de movimientos | 🟡 | `services/importacion.py` y `/imports/*` terminados y probados; la pantalla de revisión, en curso |

## P1 — alto valor

| ID | Funcionalidad | Estado | Dónde está / qué falta |
| --- | --- | --- | --- |
| F-26 | Rollover del saldo no gastado | ✅ | `calcular_arrastre()`, `GET /budgets/{periodo}/rollover` |
| F-27 | Reglas de auto-categorización | ✅ | `services/reglas.py`, `/rules/*` con probar y aplicar en seco |
| F-28 | Transacciones recurrentes | ✅ | `services/recurrencia.py`, `/recurring/*` |
| F-29 | Detección de suscripciones | ✅ | `GET /recurring/detected`, `GET /reports/subscriptions` |
| F-30 | Alerta de subida en recurrente | ✅ | `GET /recurring/{id}/price-history` |
| F-31 | Fondos objetivo | ✅ | `/goals/*` con aportar y retirar |
| F-32 | Reconciliación de cuenta | ✅ | `POST /accounts/{id}/reconcile` |
| F-33 | Importación OFX/QIF | 🟡 | El backend los acepta; la pantalla solo guía el CSV |
| F-34 | Detección de duplicados | ✅ | `GET /invoices/{id}/duplicates`, `GET /transactions/duplicates` |
| F-35 | Etiquetas libres | ✅ | `/tags/*`, `POST /transactions/bulk-tag` |
| F-36 | Informe de cash flow | ✅ | `GET /reports/cash-flow` |
| F-37 | Top comercios | ✅ | `GET /reports/top-payees` |
| F-38 | Comparador entre proveedores | ✅ | `GET /products/{id}/comparison` |
| F-39 | Fuzzy-matching de producto | ✅ | `services/normalizacion.py`, cascada con `pg_trgm` y RapidFuzz |
| F-40 | Plantillas de extracción | 🟡 | En curso |
| F-41 | Deuda con calendario | ✅ | `GET /accounts/{id}/amortization` |
| F-42 | Búsqueda y filtros combinables | ✅ | `GET /transactions` con filtros, orden y paginación en la URL |
| F-43 | Exportación de datos | 🟡 | `/exports/*` en JSON y CSV; el ZIP con los PDF originales no está |
| F-44 | Notas en transacciones | ✅ | Campo de nota en el alta y la edición |
| F-45 | Resumen periódico | 🟡 | `GET /alerts/digest` lo calcula; no hay envío por correo |
| F-46 | Atajos de teclado | ✅ | `composables/useAtajos.ts` |
| F-47 | Saldo proyectado a fin de mes | ✅ | `GET /reports/projected-balance` |
| F-48 | Detección de gasto inusual | 🟡 | En curso; hoy `GET /reports/anomalies` devuelve lista vacía a propósito |
| F-49 | Recordatorio de vencimiento | ✅ | `GET /recurring/upcoming`, con alerta |
| F-50 | Onboarding guiado | ✅ | `OnboardingVista.vue`, tres pasos |

## P2 — nice-to-have

| ID | Funcionalidad | Estado | Qué falta |
| --- | --- | --- | --- |
| F-51 | Facturas por email | ⬜ | Requiere un buzón y un proceso que lo vigile |
| F-52 | Multi-divisa con tipo de cambio | ⬜ | El esquema guarda la divisa; falta la conversión y una fuente de tipos |
| F-53 | Informe Sankey | ⬜ | Necesita una librería de diagramas de flujo |
| F-54 | Forecast a largo plazo | ⬜ | `projected-balance` cubre el mes; no hay vista de calendario a años |
| F-55 | «Disponible para gastar hoy» | 🟡 | El dato sale de la barra; falta el indicador dedicado |
| F-56 | Métrica «age of money» | ⬜ | |
| F-57 | Multiusuario con roles | 🟡 | Modelado y con permisos aplicados (`owner`/`editor`/`viewer`); faltan las invitaciones |
| F-58 | API REST documentada | ✅ | `/api/docs`, 209 operaciones |
| F-59 | Reglas editables en texto | ⬜ | Las reglas se editan por formulario |
| F-60 | Comparativa de cesta | ✅ | `GET /baskets/comparison`, `GET /reports/basket` |

## Aislamiento entre hogares

Tres capas, todas activas y comprobadas:

1. **Filtros de la aplicación**: todo endpoint que toca datos depende de
   `AlcanceHogar`, que resuelve usuario, hogar y rol.
2. **Claves ajenas compuestas** `(household_id, id)`: 44 en el esquema, que hacen
   imposible que una fila apunte a datos de otro hogar. Las dos columnas que por
   diseño no pueden llevarla se validan a mano en el endpoint.
3. **Row level security con `FORCE`**: 34 tablas y las 3 vistas (con
   `security_invoker`), y un rol `app_rw` sin `LOGIN`, sin `SUPERUSER` y sin
   `BYPASSRLS` al que se cambia con `SET LOCAL ROLE` en cada transacción.

Comprobado sobre una base con 421.874 categorías de muchos hogares: como
propietario se ven todas; con el rol puesto y sin hogar fijado se ven **0**; con
un hogar fijado, solo las 102 de ese hogar.

## Pendientes técnicos

No son funcionalidades, pero conviene tenerlos a la vista. El detalle está en
[auditoria-backend.md](auditoria-backend.md) y [auditoria-ui.md](auditoria-ui.md).

- `mv_product_price_monthly` (vista materializada de precios) se queda **sin
  permiso de lectura a propósito**: una vista materializada no admite
  `security_invoker` ni política de seguridad, así que hoy nadie la usa. El día
  que se necesite habrá que filtrarla antes de concederla.

- Deshacer una fusión de temáticas **pisa las ediciones hechas después**: la
  comprobación silenciosa de RN-20 está a medias.
- La pantalla de importación **lee el CSV también en el navegador**, con un
  espejo de la detección de `services/importacion.py` (alias de cabecera,
  delimitador, codificación). No es por gusto: ningún endpoint publica la
  cabecera del fichero, y sin ella no se puede pedir al usuario que asigne
  columnas por nombre. Está verificado contra el servicio real con cinco
  extractos distintos, pero son dos implementaciones que pueden desincronizarse.
  **El arreglo de fondo es que `GET /imports/{id}/preview` devuelva la cabecera y
  la muestra**, y que el cliente deje de adivinar.
- Reasignar presupuesto **arrastrando** en la barra no está; la alternativa
  accesible («Cambiar asignación») sí, así que se puede usar con teclado.
- Quedan dos consultas N+1 pequeñas en presupuestos y usuarios.
- Restablecer la contraseña por correo, OAuth y 2FA no están: la pantalla de
  recuperación lo dice en vez de fingir que funciona.
