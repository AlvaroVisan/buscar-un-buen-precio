/**
 * =======================================================================
 * GOOGLE APPS SCRIPT: SINCRONIZADOR TRADINGVIEW, FIBONACCI & CONFLUENCIA
 * Proyecto: "Buscar un buen precio" (v2.0)
 * =======================================================================
 *
 * INSTRUCCIONES DE INSTALACIÓN / ACTUALIZACIÓN:
 * 1. Abre tu Google Sheet "Fibonacci".
 * 2. Menú superior -> "Extensiones" -> "Apps Script".
 * 3. Borra todo lo que haya en el editor y pega este código completo.
 * 4. Haz clic en el botón de guardar (icono de disco 💾).
 * 5. Haz clic en "Implementar" -> "Gestionar implementaciones" -> Editar (✏️)
 *    -> Versión: "Nueva versión" -> "Implementar" (o "Nueva implementación" si es la primera vez).
 * =======================================================================
 */

function doPost(e) {
  try {
    var rawData = e.postData.contents;
    var payload = JSON.parse(rawData);
    var items = payload.data || [];
    var timestamp = payload.timestamp || Utilities.formatDate(new Date(), "GMT+1", "yyyy-MM-dd HH:mm:ss");
    var period = payload.period || "3mo";
    var sentiment = payload.market_sentiment || null;

    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // 1. Actualizar cada pestaña individual con análisis técnico y gestión de riesgo
    for (var i = 0; i < items.length; i++) {
      updateIndividualSheet(ss, items[i], timestamp, period);
    }

    // 2. Crear / Actualizar la pestaña "RESUMEN GENERAL" limpiando filas sobrantes
    updateSummarySheet(ss, items, timestamp, period, sentiment);

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

function getPriceNumberFormat(item) {
  var curr = item.currency || "$";
  var dec = item.decimals || 2;
  var zeros = dec >= 4 ? "0.0000" : "0.00";
  return '"' + curr + '"#,##' + zeros;
}

/**
 * Actualiza la pestaña individual de un activo con Fibonacci, Confluencia, Riesgo y Venta
 */
function updateIndividualSheet(ss, item, timestamp, period) {
  var sheet = ss.getSheetByName(item.tab);
  if (!sheet) {
    sheet = ss.insertSheet(item.tab);
  }

  var numFmt = getPriceNumberFormat(item);
  var fibs = item.fib_levels || {};
  var risk = item.risk_mgmt || {};
  var sell = item.sell_mgmt || {};

  // Limpiar contenido y formatos anteriores
  sheet.getRange("A1:B36").clear();

  // Bloque 1: Cotización y Estructura
  sheet.getRange("A1:B1").setValues([["Parámetro (" + (item.ticker || item.tab) + ")", "Valor"]])
    .setBackground("#1e293b").setFontColor("#ffffff").setFontWeight("bold");

  var params = [
    ["Nombre Activo", item.name || item.tab],
    ["Mínimo (" + period + ")", item.min || 0],
    ["Máximo (" + period + ")", item.max || 0],
    ["Rango", item.range || 0],
    ["PRECIO ACTUAL", item.current_price || 0],
    ["Caída desde Máximo", (item.drop_pct || 0) / 100],
    ["Estructura del Impulso", item.swing_label || "En rango"],
    ["Estado / Señal", item.signal || ""],
    ["Última Actualización", timestamp]
  ];
  sheet.getRange("A2:B10").setValues(params);
  sheet.getRange("B3:B6").setNumberFormat(numFmt);
  sheet.getRange("B7").setNumberFormat("0.00%");
  sheet.getRange("A6:B6").setBackground("#eff6ff").setFontWeight("bold");
  sheet.getRange("A9:B9").setBackground("#f0fdf4").setFontWeight("bold");

  // Bloque 2: Escalera de Retrocesos de Fibonacci
  sheet.getRange("A12:B12").setValues([["Nivel de Retroceso Fibonacci", "Precio Objetivo"]])
    .setBackground("#0f172a").setFontColor("#facc15").setFontWeight("bold");

  var fibLevels = [
    ["23,6%", fibs["23.6%"] || 0],
    ["38,2%", fibs["38.2%"] || 0],
    ["50,0% (Zona Compra)", fibs["50.0%"] || 0],
    ["61,8% (Zona Áurea)", fibs["61.8%"] || 0],
    ["78,6% (Soporte Extremo)", fibs["78.6%"] || 0]
  ];
  sheet.getRange("A13:B17").setValues(fibLevels);
  sheet.getRange("B13:B17").setNumberFormat(numFmt);
  sheet.getRange("A16:B16").setBackground("#fef9c3").setFontWeight("bold");

  // Bloque 3: Confluencia Técnica (Score, RSI, SMA 200)
  sheet.getRange("A19:B19").setValues([["Confluencia Técnica", "Lectura"]])
    .setBackground("#1e293b").setFontColor("#38bdf8").setFontWeight("bold");

  var techRows = [
    ["Score de Confluencia (0-100)", (item.score !== undefined ? item.score : 0) + " / 100 (" + (item.confluence_rating || "") + ")"],
    ["RSI (14 sesiones)", (item.rsi !== undefined ? item.rsi : 50) + " (" + (item.rsi_desc || "") + ")"],
    ["Media Móvil SMA 200", item.sma_200 || 0],
    ["Distancia a SMA 200", (item.sma_dist_pct || 0) / 100]
  ];
  sheet.getRange("A20:B23").setValues(techRows);
  sheet.getRange("B22").setNumberFormat(numFmt);
  sheet.getRange("B23").setNumberFormat("+0.00%;-0.00%;0.00%");

  // Bloque 4: Gestión de Riesgo y Extensiones de Venta
  sheet.getRange("A25:B25").setValues([["Plan de Riesgo & Toma de Beneficios", "Nivel"]])
    .setBackground("#0f172a").setFontColor("#34d399").setFontWeight("bold");

  var riskRows = [
    ["Entrada Sugerida", risk.entry_price || item.current_price || 0],
    ["Stop Loss Protector", risk.stop_loss || 0],
    ["Take Profit 1 (38.2%)", risk.take_profit_1 || 0],
    ["Take Profit 2 (Máximo)", risk.take_profit_2 || 0],
    ["Ratio Riesgo / Beneficio", "1:" + (risk.rr_ratio_2 || 2) + " (" + (risk.rr_rating || "") + ")"],
    ["Extensión Venta 127.2%", sell.ext_127 || 0],
    ["Extensión Venta 161.8%", sell.ext_161 || 0],
    ["Trailing Stop (-5.5%)", sell.trailing_stop || 0]
  ];
  sheet.getRange("A26:B33").setValues(riskRows);
  sheet.getRange("B26:B29").setNumberFormat(numFmt);
  sheet.getRange("B31:B33").setNumberFormat(numFmt);

  sheet.autoResizeColumns(1, 2);
}

/**
 * Crea o actualiza la pestaña principal "RESUMEN GENERAL" (13 columnas, sin filas huérfanas)
 */
function updateSummarySheet(ss, items, timestamp, period, sentiment) {
  var sheetName = "RESUMEN GENERAL";
  var sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName, 0);
  }

  var totalCols = 13;
  var prevLastRow = Math.max(sheet.getLastRow(), items.length + 10);
  if (prevLastRow >= 5) {
    sheet.getRange(5, 1, prevLastRow - 4, totalCols + 2).clear();
  }

  // Título Principal
  sheet.getRange(1, 1, 1, totalCols).merge();
  sheet.getRange("A1").setValue("📊 PANEL GENERAL DE SEGUIMIENTO, FIBONACCI & CONFLUENCIA TÉCNICA")
    .setBackground("#0f172a")
    .setFontColor("#38bdf8")
    .setFontSize(13)
    .setFontWeight("bold")
    .setHorizontalAlignment("center");

  var sentimentTxt = "";
  if (sentiment && sentiment.score !== undefined) {
    sentimentTxt = " | 🌡️ Sentimiento CNN Wall St: " + sentiment.score + "/100 (" + (sentiment.rating_es || "Neutral") + ")";
  }

  sheet.getRange(2, 1, 1, totalCols).merge();
  sheet.getRange("A2").setValue("Última sincronización: " + timestamp + " | Ventana Fibonacci: " + period + sentimentTxt)
    .setFontSize(9)
    .setFontColor("#64748b")
    .setHorizontalAlignment("center");

  // Cabeceras (A4:M4)
  var headers = [[
    "Activo", "Ticker", "Precio Actual", "Mínimo (" + period + ")", "Máximo (" + period + ")",
    "Caída %", "Score", "RSI (14)", "Dist. SMA200", "Impulso",
    "Zona Fibonacci", "Señal Técnica", "Progreso de Caída"
  ]];
  sheet.getRange(4, 1, 1, totalCols).setValues(headers)
    .setBackground("#1e293b")
    .setFontColor("#ffffff")
    .setFontWeight("bold")
    .setHorizontalAlignment("center");

  if (items.length === 0) {
    return;
  }

  var rows = [];
  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    rows.push([
      it.tab || it.ticker,
      it.ticker || "",
      it.current_price || 0,
      it.min || 0,
      it.max || 0,
      (it.drop_pct || 0) / 100,
      (it.score !== undefined ? it.score : 0),
      (it.rsi !== undefined ? it.rsi : 50),
      (it.sma_dist_pct || 0) / 100,
      it.swing_label || "En rango",
      it.zone_desc || "",
      it.signal || "",
      ""
    ]);
  }

  sheet.getRange(5, 1, rows.length, totalCols).setValues(rows);

  // Formatos por fila (divisa adaptativa y sparklines)
  for (var k = 0; k < items.length; k++) {
    var rIdx = 5 + k;
    var rowFmt = getPriceNumberFormat(items[k]);
    sheet.getRange(rIdx, 3, 1, 3).setNumberFormat(rowFmt);

    var formulaSpanish = '=SPARKLINE(E' + rIdx + ' - C' + rIdx + '; {"charttype" \\ "bar"; "max" \\ MAX(0,0001; E' + rIdx + ' - D' + rIdx + '); "color1" \\ "#ef4444"})';
    try {
      sheet.getRange(rIdx, totalCols).setFormulaLocal(formulaSpanish);
    } catch (err) {
      sheet.getRange(rIdx, totalCols).setFormula(
        '=SPARKLINE(E' + rIdx + ' - C' + rIdx + ', {"charttype", "bar"; "max", MAX(0.0001, E' + rIdx + ' - D' + rIdx + '); "color1", "#ef4444"})'
      );
    }

    // Semáforo en Score (columna G = 7)
    var scoreCell = sheet.getRange(rIdx, 7);
    var sc = items[k].score || 0;
    scoreCell.setNumberFormat('0"/100"').setFontWeight("bold");
    if (sc >= 80) {
      scoreCell.setBackground("#fef3c7").setFontColor("#b45309");
    } else if (sc >= 65) {
      scoreCell.setBackground("#dcfce7").setFontColor("#15803d");
    } else {
      scoreCell.setBackground("#f8fafc").setFontColor("#475569");
    }

    // Semáforo en Señal (columna L = 12)
    var sigCell = sheet.getRange(rIdx, 12);
    var sigVal = String(items[k].signal || "");
    if (sigVal.indexOf("🟢") !== -1) {
      sigCell.setBackground("#dcfce7").setFontColor("#15803d").setFontWeight("bold");
    } else if (sigVal.indexOf("🟡") !== -1) {
      sigCell.setBackground("#fef9c3").setFontColor("#854d0e").setFontWeight("bold");
    } else {
      sigCell.setBackground("#f1f5f9").setFontColor("#475569");
    }
  }

  sheet.getRange(5, 6, rows.length, 1).setNumberFormat("0.00%");
  sheet.getRange(5, 8, rows.length, 1).setNumberFormat("0.0");
  sheet.getRange(5, 9, rows.length, 1).setNumberFormat("+0.0%;-0.0%;0.0%");
  sheet.getRange(5, 1, rows.length, 2).setHorizontalAlignment("center");
  sheet.getRange(5, 6, rows.length, 7).setHorizontalAlignment("center");

  // Bordes limpios solo en el área activa
  sheet.getRange(4, 1, rows.length + 1, totalCols)
    .setBorder(true, true, true, true, true, true, "#cbd5e1", SpreadsheetApp.BorderStyle.SOLID);

  sheet.autoResizeColumns(1, totalCols);
}

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
    "1. Pulsa 'Actualizar Precios' en el Panel Web (http://localhost:5050),\n" +
    "2. Envía /sync a tu Bot de Telegram, o\n" +
    "3. Ejecuta 'Actualizar_Precios.bat' en tu ordenador.",
    SpreadsheetApp.getUi().ButtonSet.OK
  );
}
