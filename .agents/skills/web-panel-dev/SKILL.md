---
name: web-panel-dev
description: >-
  Use this skill when the user asks to modify, redesign, style, or add features to the
  web panel UI (HTML, CSS, JS, Flask) of "Buscar un buen precio".
---

# Procedimiento para Desarrollo y Modificación del Panel Web

Esta skill describe la arquitectura, diseño visual y procedimientos para extender el panel de control web.

## 1. Arquitectura de la Aplicación Web

- **Servidor Backend**: [app.py](file:///e:/Proyectos/Buscar%20un%20buen%20precio/app.py) (Flask en puerto `5050`).
  - `GET /`: Sirve `index.html`.
  - `GET /api/data`: Devuelve el contenido de `latest_data.json`.
  - `POST /api/update`: Ejecuta `market_updater.py` y devuelve los datos frescos.
  - `GET /api/config`: Devuelve la configuración de `config.json`.
- **Estructura HTML**: [index.html](file:///e:/Proyectos/Buscar%20un%20buen%20precio/index.html).
  - Header con resumen general (total activos, oportunidades activas, hora de sync).
  - Barra de acciones (botón "Actualizar Precios", estado de carga con spinner).
  - Contenedor de cuadrícula (#cardsGrid).
- **Estilos CSS**: [style.css](file:///e:/Proyectos/Buscar%20un%20buen%20precio/style.css).
  - Paleta oscura moderna basada en tokens CSS (`--bg-primary: #0b0f19`, `--card-bg: rgba(18, 24, 38, 0.8)`).
  - Efectos de Glassmorphism (`backdrop-filter: blur(16px)`).
  - Indicadores semafóricos (verde esmeralda, dorado ámbar, azul eléctrico).
  - Termómetro de posición en rango y escalera de Fibonacci.
- **Lógica Frontend**: [app.js](file:///e:/Proyectos/Buscar%20un%20buen%20precio/app.js).
  - Carga asíncrona mediante `fetch('/api/data')`.
  - Construcción dinámica de cada tarjeta de activo con sus enlaces a TradingView.
  - Animaciones de actualización y toast notifications.

## 2. Cómo Levantar o Reiniciar el Servidor Web

- **En Windows**:
  Haz doble clic en [Abrir_Panel_Web.bat](file:///e:/Proyectos/Buscar%20un%20buen%20precio/Abrir_Panel_Web.bat) o ejecuta:
  ```powershell
  python app.py
  ```
- **URL**: `http://localhost:5050`

## 3. Pautas de Diseño y Nuevas Características

Al agregar nuevas funcionalidades al panel:
1. **Mantener la coherencia estética**:
   - Usar las variables de color de `:root` en `style.css`.
   - Mantener las microanimaciones suaves (`transition: all 0.25s ease`).
2. **Enlaces a TradingView**:
   - Cada tarjeta genera el enlace a TradingView usando el ticker base:
     `https://www.tradingview.com/chart/?symbol={ticker_limpio}`
   - Para futuros o índices, limpiar prefijos si es necesario (ej: `GC=F` -> `COMEX:GC1!`).
3. **Responsive**:
   - Mantener el diseño adaptativo en móviles (`grid-template-columns: repeat(auto-fill, minmax(360px, 1fr))`).
