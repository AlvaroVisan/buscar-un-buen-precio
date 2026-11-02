---
name: web-panel-dev
description: >-
  Modificar la interfaz HTML, CSS y JavaScript o las API HTTP del panel Buscar un buen precio.
  Usar para tarjetas, filtros, modales, periodos, Diario y Cartera en la web.
---

# Panel web

## Arquitectura vigente

- [app.py](../../../app.py) usa `http.server`, `ThreadingFibonacciServer` y `FibonacciHandler`; no usa Flask ni blueprints. Escucha en `127.0.0.1:5050`.
- [index.html](../../../index.html), [style.css](../../../style.css), [app.js](../../../app.js): HTML, tokens CSS oscuros y JavaScript sin framework. Conserva la estética actual; no restaures diseños históricos por una descripción antigua.
- [business.js](../../../business.js): botón Ver negocio, modal, carga, accesibilidad y cancelación de peticiones. Se carga junto a `app.js`.

## API de referencia

| Método | Ruta | Comportamiento |
|---|---|---|
| GET | `/api/health` | Identidad del panel para el lanzador |
| GET | `/api/data`, `/api/config` | Cotizaciones guardadas y configuración con secretos enmascarados |
| GET | `/api/scheduler/status` | Horario, intervalo efectivo y próxima consulta |
| POST | `/api/sync`, `/api/period` | Sincronización completa o proyección de periodo desde caché |
| POST | `/api/assets/validate`, `/api/assets/add`, `/api/assets/remove` | Gestión de tickers |
| GET | `/api/journal`, `/api/portfolio` | Diario automático y cartera enriquecida |
| POST | `/api/journal/reset` | Borra el Diario; no es un endpoint de diagnóstico |
| POST | `/api/portfolio/upsert`, `/api/portfolio/remove` | Compras/edición/DCA y bajas/ventas |
| POST | `/api/telegram/save`, `/api/telegram/test`, `/api/scheduler/save` | Configuración y prueba explícita de Telegram |
| GET | `/api/business?ticker=AMD` | Contexto empresarial bajo demanda |

Lee el cuerpo del handler antes de construir payloads. No sustituyas estas rutas por antiguos `/api/update`, `/api/portfolio/buy` o métodos DELETE inexistentes.

## Invariantes de interfaz

- `initApp()` carga configuración y cotizaciones; `startLivePolling()` sondea cada 20 segundos. `switchPeriod()` proyecta `timeframes` y guarda la preferencia en segundo plano. El cambio de ventana no altera los niveles históricos del Diario.
- El Diario es el único seguimiento simulado; no recrees la sección ni el botón de planes separados. Sus tarjetas distinguen entrada, stop original, stop actual, TP1, TP2 y periodo registrado. No inventes el periodo de entradas antiguas.
- Usa `escapeHtml()` para datos interpolados, atributos `data-*` y listeners/delegación. No añadas `onclick` inline con strings de datos. Comprueba desbordamientos con nombres largos y precios grandes o de muchos decimales.
- Para modales comprueba cerrar con Escape y backdrop, foco al abrir, restauración del foco y navegación por teclado. `business.js` tiene su propia gestión: no rompas su interacción con `closeAllModals()`.
- Conserva las comprobaciones de Host, Origin, Sec-Fetch-Site, el enlace exclusivo en loopback y el bloqueo de archivos internos. Las API de escritura requieren JSON cuando hay cuerpo; no abras el servidor a la red para arreglar un problema de acceso local.

## Verificación y carga de cambios

`node --check app.js` y, si se modifica, `node --check business.js`. Para handlers y protección local: `python -m unittest test_local_server`. Verifica escritorio y móvil cuando cambien componentes visibles; usa mocks para servicios y cartera en las pruebas de navegador.

Actualiza la versión de las referencias CSS/JS en `index.html` cuando sea necesario evitar caché antigua. Cambios de Python requieren reiniciar la instancia: ver [app-launcher](../app-launcher/SKILL.md). Para la lectura empresarial usa [business-context](../business-context/SKILL.md), y para entrega [git-auto-sync](../git-auto-sync/SKILL.md).
