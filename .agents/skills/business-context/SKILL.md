---
name: business-context
description: >-
  Mantener Ver negocio en Buscar un buen precio: lectura de solidez empresarial, valoración,
  estados financieros, fuentes y caché. Usar para sus reglas, datos o presentación específica.
---

# Ver negocio

## Componentes y consulta

- [business_context.py](../../../business_context.py): `build_context()` transforma datos contables en una lectura explicable; `get_business_context()` obtiene datos y gestiona caché.
- [business.js](../../../business.js): `addBusinessButton()` coloca Ver negocio bajo el nombre de la empresa, tanto en Compra como en Venta. Gestiona el modal, peticiones abortables, foco y detalle desplegable.
- [app.py](../../../app.py): `GET /api/business?ticker=AMD` solo permite candidatos empresariales de la lista configurada. El proveedor confirma `quoteType="EQUITY"`; no apliques la ficha a índices, futuros, cripto o fondos.

Se consulta al abrir la ficha, sin añadir descargas fundamentales al ciclo de precios. `.business_cache.json` es privado y tiene TTL de 24 horas. Un fallo conserva una lectura anterior marcada `is_stale` y su fecha original; sin lectura previa devuelve información insuficiente. Los fallos de descarga tienen espera de cinco minutos. Cambia `SCHEMA_VERSION` si modificas reglas/esquema de forma que invalide lecturas guardadas.

## Reglas que hay que conservar

La clasificación es `favorable`, `mixed`, `weak` o `insufficient`. Se basa en beneficios y caja libre durante tres ejercicios, crecimiento anual de ingresos, evolución del margen neto y deuda neta frente a caja operativa. No es un modelo de rentabilidad ni sustituye el score técnico.

Antes de cambiar umbrales, lee `build_context()`. Para emitir una conclusión requiere las cinco dimensiones, sector conocido, cierres alineados y estados recientes. Datos incompletos, fechas antiguas/no válidas y sectores financiero o inmobiliario se tratan como información insuficiente para estas reglas generales. No completes huecos mezclando ejercicios ni conviertas NaN/None en cero o en fortaleza.

El precio se contextualiza por separado, con PER de los últimos doce meses cuando sea útil; no afirmes que un múltiplo aislado demuestra que una empresa está barata o cara. Conserva fecha de consulta, cierre anual, divisa, fuentes y limitaciones. No atribuyas al cálculo ventajas competitivas, solvencia garantizada, análisis de dirección o riesgos cualitativos que no ha evaluado.

Los enlaces del proveedor se filtran antes de insertarse en la web y los textos se escapan. No publiques la caché ni vuelques datos completos del proveedor a la consola para diagnosticar una métrica puntual.

## Validación

`python -m unittest test_business_context test_local_server` cubre lectura, datos ausentes, cierres, caché y rutas. Usa fixtures de estados financieros y mocks de Yahoo. Para cambios visuales, revisa escritorio/móvil, carga, fallo, cierre, foco y ausencia de desbordamientos; consulta [web-panel-dev](../web-panel-dev/SKILL.md) si cambias el panel compartido.

Una prueba real de datos, cuando haga falta, debe limitarse a comprobar la consulta y no escribir cartera ni señales. Finaliza con [git-auto-sync](../git-auto-sync/SKILL.md).
