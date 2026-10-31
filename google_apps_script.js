/**
 * =======================================================================
 * GOOGLE APPS SCRIPT: SINCRONIZADOR TRADINGVIEW & FIBONACCI
 * Proyecto: "Buscar un buen precio"
 * =======================================================================
 * 
 * INSTRUCCIONES DE INSTALACIÓN:
 * 1. Abre tu Google Sheet "Fibonacci".
 * 2. Menú superior -> "Extensiones" -> "Apps Script".
 * 3. Borra todo lo que haya en el editor y pega este código completo.
 * 4. Haz clic en el botón de guardar (icono de disco 💾).
 * 5. Haz clic en "Implementar" (arriba a la derecha) -> "Nueva implementación".
 * 6. En el engranaje ⚙️ (Seleccionar tipo), elige "Aplicación web".
 * 7. Configura:
 *    - Descripción: Sincronizador de Mercado
 *    - Ejecutar como: "Yo" (tu cuenta)
 *    - Quién tiene acceso: "Cualquier usuario" (Anyone)
 * 8. Haz clic en "Implementar", autoriza los permisos si te los pide.
 * 9. Copia la URL que te proporciona (termina en /exec) y pégasela a tu asistente.
 * =======================================================================
 */

function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var payload = JSON.parse(rawData);
    var items = payload.data;
    var timestamp = payload.timestamp || Utilities.formatDate(new Date(), "GMT+1", "yyyy-MM-dd HH:mm:ss");
    var period = payload.period || "3 meses";

    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // 1. Actualizar cada pestaña individual
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      updateIndividualSheet(ss, item, timestamp, period);
    }

    // 2. Crear / Actualizar la pestaña "RESUMEN GENERAL"
    updateSummarySheet(ss, items, timestamp, period);

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      message: "Actualizado con éxito " + items.length + " valores.",
      timestamp: timestamp
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Actualiza una pestaña específica (AMD, Meta, CEG, NVIDIA, Gold, SP500)
 */
function updateIndividualSheet(ss, item, timestamp, period) {
  var sheet = ss.getSheetByName(item.tab);
  if (!sheet) {
    sheet = ss.insertSheet(item.tab);
  }

  // Limpiar contenido anterior para no dejar filas residuales
  sheet.getRange("A1:B25").clearContent();

  // Estilo y contenido
  sheet.getRange("A1:B1").setValues([["Parámetro", "Valor"]]);
  sheet.getRange("A1:B1").setBackground("#1e293b").setFontColor("#ffffff").setFontWeight("bold");

  var params = [
    ["Mínimo (" + period + ")", item.min],
    ["Máximo (" + period + ")", item.max],
    ["Rango", item.range],
    ["PRECIO ACTUAL", item.current_price],
    ["Caída desde Máximo", (item.drop_pct / 100)],
    ["Estado / Señal", item.signal],
    ["Última Actualización", timestamp]
  ];
  sheet.getRange("A2:B8").setValues(params);

  // Formatear precios como moneda
  sheet.getRange("B2:B5").setNumberFormat("$#,##0.00");
  sheet.getRange("B6").setNumberFormat("0.00%");

  // Resaltar Precio Actual y Señal
  sheet.getRange("A5:B5").setBackground("#eff6ff").setFontWeight("bold");
  sheet.getRange("A7:B7").setBackground("#f0fdf4").setFontWeight("bold");

  // Sección de Retrocesos de Fibonacci
  sheet.getRange("A10:B10").setValues([["Nivel de Retroceso", "Precio Objetivo"]]);
  sheet.getRange("A10:B10").setBackground("#0f172a").setFontColor("#facc15").setFontWeight("bold");

  var fibLevels = [
    ["23,6%", item.fib_levels["23.6%"]],
    ["38,2%", item.fib_levels["38.2%"]],
    ["50,0%", item.fib_levels["50.0%"]],
    ["61,8% (Áureo)", item.fib_levels["61.8%"]],
    ["78,6%", item.fib_levels["78.6%"]]
  ];
  sheet.getRange("A11:B15").setValues(fibLevels);
  sheet.getRange("B11:B15").setNumberFormat("$#,##0.00");

  // Destacar el 61.8%
  sheet.getRange("A14:B14").setBackground("#fef9c3").setFontWeight("bold");

  sheet.autoResizeColumns(1, 2);
}

/**
 * Crea o actualiza la pestaña principal "RESUMEN GENERAL"
 */
function updateSummarySheet(ss, items, timestamp, period) {
  var sheetName = "RESUMEN GENERAL";
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName, 0); // La ponemos en la primera posición
  }

  // Título
  sheet.getRange("A1:I1").merge();
  sheet.getRange("A1").setValue("📊 PANEL GENERAL DE SEGUIMIENTO Y COMPRA (FIBONACCI)")
    .setBackground("#0f172a")
    .setFontColor("#38bdf8")
    .setFontSize(14)
    .setFontWeight("bold")
    .setHorizontalAlignment("center");

  sheet.getRange("A2:I2").merge();
  sheet.getRange("A2").setValue("Última sincronización: " + timestamp + " | Periodo de cálculo: " + period)
    .setFontSize(9)
    .setFontColor("#64748b")
    .setHorizontalAlignment("center");

  // Cabeceras
  var headers = [
    ["Activo", "Ticker", "Precio Actual", "Mínimo (" + period + ")", "Máximo (" + period + ")", "Caída %", "Zona Fibonacci", "Señal de Compra", "Progreso de Caída"]
  ];
  sheet.getRange("A4:I4").setValues(headers)
    .setBackground("#1e293b")
    .setFontColor("#ffffff")
    .setFontWeight("bold")
    .setHorizontalAlignment("center");

  // Filas de datos (columnas A hasta H, la I la asignamos con setFormulaLocal)
  var rows = [];

  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    var rowIdx = 5 + i;

    rows.push([
      it.tab,
      it.ticker,
      it.current_price,
      it.min,
      it.max,
      it.drop_pct / 100,
      it.zone_desc,
      it.signal,
      "" // Dejamos la columna I para setFormulas
    ]);
  }

  var dataRange = sheet.getRange(5, 1, rows.length, 9);
  dataRange.setValues(rows);

  // Asignar la fórmula SPARKLINE en español directamente con setFormulaLocal
  for (var k = 0; k < items.length; k++) {
    var rIdx = 5 + k;
    var formulaSpanish = '=SPARKLINE(E' + rIdx + ' - C' + rIdx + '; {"charttype" \\ "bar"; "max" \\ (E' + rIdx + ' - D' + rIdx + '); "color1" \\ "#ef4444"})';
    try {
      sheet.getRange(rIdx, 9).setFormulaLocal(formulaSpanish);
    } catch (err) {
      sheet.getRange(rIdx, 9).setFormula(
        '=SPARKLINE(E' + rIdx + ' - C' + rIdx + ', {"charttype", "bar"; "max", (E' + rIdx + ' - D' + rIdx + '); "color1", "#ef4444"})'
      );
    }
  }

  // Formatos numéricos
  sheet.getRange(5, 3, rows.length, 3).setNumberFormat("$#,##0.00"); // Precios
  sheet.getRange(5, 6, rows.length, 1).setNumberFormat("0.00%");     // Caída %
  sheet.getRange(5, 1, rows.length, 2).setHorizontalAlignment("center");
  sheet.getRange(5, 6, rows.length, 3).setHorizontalAlignment("center");

  // Bordes elegantes
  sheet.getRange(4, 1, rows.length + 1, 9).setBorder(true, true, true, true, true, true, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);

  // Coloreado condicional en señales
  for (var r = 0; r < rows.length; r++) {
    var cell = sheet.getRange(5 + r, 8);
    var val = cell.getValue();
    if (val.indexOf("🟢") !== -1) {
      cell.setBackground("#dcfce7").setFontColor("#15803d").setFontWeight("bold");
    } else if (val.indexOf("🟡") !== -1) {
      cell.setBackground("#fef9c3").setFontColor("#854d0e").setFontWeight("bold");
    } else {
      cell.setBackground("#f1f5f9").setFontColor("#475569");
    }
  }

  sheet.autoResizeColumns(1, 9);
}

/**
 * Menú personalizado en Google Sheets
 */
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu("🚀 TradingView")
    .addItem("ℹ️ Cómo Actualizar", "showUpdateHelp")
    .addToUi();
}

function showUpdateHelp() {
  SpreadsheetApp.getUi().alert(
    "Actualización de Precios",
    "Para actualizar los precios:\n\n" +
    "1. Ejecuta el archivo 'Actualizar_Precios.bat' en tu ordenador, o\n" +
    "2. Pídeselo a tu asistente AI diciendo 'Actualiza el excel'.",
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}

/**
 * Función de prueba para ejecutar directamente desde el editor de Apps Script
 * (Permite verificar que la fórmula SPARKLINE funciona sin desplegar versión)
 */
function testUpdate() {
  var dummy = {
    postData: {
      contents: JSON.stringify({
        timestamp: Utilities.formatDate(new Date(), "GMT+1", "yyyy-MM-dd HH:mm:ss"),
        period: "3mo",
        data: [
          {
            tab: "AMD",
            ticker: "AMD",
            current_price: 504.80,
            min: 424.03,
            max: 658.52,
            range: 234.49,
            drop_pct: 23.34,
            zone_desc: "Zona Áurea 61.8%",
            signal: "🟢 COMPRA ÓPTIMA (61.8%)",
            fib_levels: {
              "23.6%": 603.18, "38.2%": 568.95, "50.0%": 541.28, "61.8%": 513.60, "78.6%": 474.21
            }
          }
        ]
      })
    }
  };
  doPost(dummy);
}

