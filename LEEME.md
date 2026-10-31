# 📈 Proyecto: "Buscar un buen precio"
### Monitor Inteligente de Retrocesos de Fibonacci y Oportunidades de Compra

Este proyecto automatiza la extracción de datos de mercado (acciones de Wall Street, Oro e Índices) y calcula automáticamente los retrocesos de Fibonacci para identificar puntos de entrada óptimos, sincronizando todo con tu hoja de cálculo de Google Sheets.

---

## 🎯 ¿Cómo usarlo en tu día a día?

Tienes **3 formas muy sencillas** de actualizar los precios:

### 1. Pidiéndoselo a tu Asistente AI
Siempre que estés en este chat, solo di:
> *"Actualiza el excel"* o *"Mira los precios hoy"*
Y se sincronizará automáticamente al instante.

### 2. Con un solo clic (Archivo .bat)
* Ve a la carpeta `e:\Proyectos\Buscar un buen precio\`
* Haz doble clic en **`Actualizar_Precios.bat`**
* En 3 segundos verás el reporte en pantalla y tu Google Sheet quedará actualizado.

### 3. Desde el Panel Web Visual
* Haz doble clic en **`Abrir_Panel_Web.bat`** (o abre `http://localhost:5050` en tu navegador).
* Verás las tarjetas interactivas de cada valor con:
  * Su precio actual y caída % desde máximos.
  * El termómetro visual del rango (suelo vs techo).
  * La escalera de Fibonacci con los niveles alcanzados.
  * Los enlaces directos a sus gráficos en **TradingView**.
* Pulsa el botón azul **"Actualizar Precios"** para refrescar todo.

---

## 📊 Estructura de tu Google Sheet

1. **Pestaña `RESUMEN GENERAL`**:
   * Vista consolidada de todos tus activos (`AMD`, `Meta`, `CEG`, `NVIDIA`, `Gold`, `SP500`).
   * Columnas: Precio actual, Mínimo y Máximo de 3 meses, Caída %, Zona de Fibonacci, Señal de compra y Posición en el rango.
   * Semáforos de color:
     * 🟢 **COMPRA ÓPTIMA / FUERTE**: Precios en la zona áurea del 61.8% o soporte del 78.6%.
     * 🟢 **ENTRADA BUENA**: Corrección del 50%.
     * 🟡 **EN OBSERVACIÓN**: Caídas iniciales (23.6% - 38.2%).
     * ⚪ **RESISTENCIA / CARO**: Cerca de máximos.

2. **Pestañas Individuales (`AMD`, `Meta`, `CEG`, `NVIDIA`, `Gold`, `SP500`)**:
   * Contienen tus parámetros detallados, fecha/hora exacta de sincronización y los precios objetivos calculados de cada retroceso.

---

## ⚙️ Configuración y Personalización

En el archivo **`config.json`**:
* **`webhook_url`**: La dirección de conexión con tu Google Sheet.
* **`period`**: Periodo de cálculo del Máximo y Mínimo (por defecto `"3mo"` = 3 meses). Puedes poner `"1mo"`, `"6mo"`, `"1y"`.
* **`assets`**: Puedes agregar o quitar cualquier acción o activo que quieras seguir en el futuro.
