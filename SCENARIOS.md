# Escenarios del Diario

`scenario_engine.py` evalúa vigilancia y acumulación dentro de la actualización de
`journal_manager.py`. Usa las historias ya descargadas, sin nuevas llamadas de red.
Los escenarios se conservan en `journal.json` y se consultan en `/api/journal`.
No registran compras reales en Cartera ni reconstruyen entradas anteriores.

## Confirmación

Fibonacci 61,8 % o score >= 70 activan vigilancia. El techo local es el máximo de
las dos últimas velas horarias completas. Se descargan cinco días de velas de
60 minutos durante cada actualización y se guardan hasta 64 en `rebound_bars`,
con hora de cierre UTC. Una vela no cuenta hasta que transcurre su hora completa.
Mientras no haya un cierre por encima, el techo se actualiza con los picos recientes.
En cada vela nueva se compara su cierre contra el techo de las dos anteriores,
sin incluir la vela que intenta romperlo.
Si hay un hueco de más de dos horas entre velas horarias, el techo y la tendencia
corta usan las velas posteriores al hueco: no arrastran el máximo de ayer tras
una apertura con caída. Puede haber inicialmente una sola vela para formar el techo;
la entrada sigue exigiendo sus dos cierres posteriores de confirmación.

Tras el primer cierre por encima se fija el techo. Se exigen dos cierres
consecutivos de velas horarias distintas sobre ese mismo nivel, con cotización actual
todavía encima y cierre sobre la media de cuatro velas horarias. Un cierre en o bajo
el techo reinicia el contador y permite actualizarlo. Repetir sincronizaciones
con la misma vela no suma confirmaciones. Las velas de hoy pueden confirmar si
han terminado; una vela horaria aún en formación nunca cuenta. Sin datos horarios
la cotización diaria se conserva, pero se bloquean nuevas confirmaciones. El
fallback diario se mantiene solo para llamadas sin el contrato `rebound_bars`
(compatibilidad de funciones y fixtures); el actualizador siempre envía ese campo.
Ya no se exige al activo recuperar la media de veinte sesiones; el filtro general
del S&P 500 se mantiene. Las vigilancias antiguas migran prospectivamente a estas
reglas horarias (versión 3), con contador cero, sin cambiar operaciones ya registradas.

Para acciones, si está disponible el S&P 500, un cierre del índice bajo su media
de veinte sesiones bloquea compras. Sin ese índice se indica contexto sin confirmar;
no hay filtro sectorial. La clasificación de acciones usa el formato del ticker:
excluye índices, futuros y pares con guion de este filtro general.

La entrada se simula al precio observado, nunca al precio de un cierre pasado.
El stop conserva el nivel estructural si es más amplio y exige al menos 2 ATR.
TP1 corresponde al Fibonacci 38,2 % y TP2 al máximo de la ventana. Se exige
entrada < TP1 < TP2 y beneficio/riesgo hasta TP1 >= 1,5. Si faltan niveles o ATR
no se abre la señal. Se vende la mitad en TP1 y el resto en TP2 o entrada.

Un stop reinicia vigilancia y exige una sesión posterior con estructura nueva.
Las posiciones del historial anterior continúan evaluándose con sus niveles
originales y pueden convivir con una señal nueva del mismo ticker.

## Acumulación

Cada campaña reserva 1.000 unidades de la divisa del activo, sin conversión ni
suma entre divisas. El primer tercio requiere la misma confirmación de estructura;
esta simulación tiene sus propias reglas de riesgo y no depende del filtro de
beneficio/riesgo del escenario Confirmación. El objetivo inicial es Fibonacci
38,2 % y la invalidación es el mínimo de las cuatro sesiones cerradas menos 1 ATR.
Ambos quedan fijos y deben rodear el precio de entrada.

Hasta dos compras adicionales, cada una de un tercio del presupuesto, exigen:

- Precio observado al menos un 5 % inferior al de la compra anterior.
- Sesión cerrada posterior al día de esa compra.
- Cierre sobre el máximo de la sesión precedente y medias exigidas por tendencia.
- Ausencia de bloqueo por mercado y precio dentro de invalidación y objetivo.

Se recalculan unidades y precio medio ponderado. El resultado se muestra sobre
capital invertido y sobre presupuesto reservado. La caída máxima se calcula
sobre patrimonio de la campaña (presupuesto más P&L). Se cierra toda la posición
al alcanzar invalidación u objetivo; nunca se amplía después de invalidar.
Una campaña cerrada exige vigilancia nueva antes de comenzar otra.

## Interpretación y límites

Las entradas usan velas horarias completas y las salidas conservan velas diarias
y observaciones periódicas, sin garantía de capturar todos los movimientos intradía.
La última vela corta de una sesión puede retrasarse hasta completar una hora desde
su apertura. No se
aplican rangos del día de compra para evitar usar extremos anteriores a ella.
En sesiones posteriores se revisan rangos cerrados y precio observado. Si una
vela toca stop y objetivo, gana prioridad el stop. Acumulación refleja gaps por
debajo de invalidación al precio de apertura disponible o al observado.

La caída máxima es conservadora y dependiente de las observaciones disponibles;
no equivale a una reconstrucción intradía exacta. Para Confirmación se muestra
por señal, con capital ilustrativo de 1.000 unidades. No se simulan comisiones,
deslizamiento completo ni restricciones de fracciones de acciones. Los presupuestos
son independientes por activo; no existe un límite agregado de cartera simulada.
Estas reglas son hipótesis para comparar prospectivamente, no mejoras demostradas.

Validación: `python -m unittest` y `node --check app.js`. Las regresiones de los
escenarios viven en `test_scenario_engine.py`; las pruebas usan archivos temporales
y no envían mensajes ni modifican Cartera.

## Telegram

El bot consulta el mismo estado persistido. `/ver TICKER` y `/compra TICKER`
distinguen vigilancia, entrada confirmada y campaña de acumulación. No generan
entradas al consultar. El análisis técnico de venta y la calculadora de riesgo
son lecturas hipotéticas; no sustituyen los niveles congelados del Diario.

`/alertas` muestra vigilancia y escenarios activos. `/diario` y sus filtros
muestran Confirmación; `/diario anterior` conserva los registros previos y
`/acumulacion` muestra las campañas. Los botones mantienen el escenario elegido.

Los avisos automáticos se evalúan después de guardar el Diario. Solo notifican
entradas confirmadas y tramos registrados, no candidatos por score o Fibonacci.
Los identificadores de evento se conservan en la caché privada por destinatario:
no se repite un evento al reiniciar o superar cuatro horas; un tramo nuevo puede
avisarse inmediatamente. Un destinatario fallido se reintenta sin repetir el
aviso a los que ya lo recibieron. Se conservan horario inteligente, habilitación
de Telegram y opciones generales de notificación (ambas desactivadas silencian
avisos). El antiguo `min_score` del bot ya no valida compras ni filtra eventos
registrados: las condiciones de entrada pertenecen al motor de escenarios.

Las pruebas de Telegram usan envíos simulados y archivos temporales. Los mensajes
ya enviados no se reescriben al actualizar el bot.

La ficha de compra y venta usa lenguaje cotidiano: precio actual, esperar o entrar,
zona donde podría frenar, recuperación necesaria, techo y precio de salida.
«Entramos de una» solo aparece con una entrada confirmada activa y precio aún
cerca de la entrada registrada (hasta un ATR o un 1 % si falta ATR), sobre su stop.
No se usa con cotización obsoleta, tras perder la salida ni para perseguir un precio
alejado. Las posibilidades de caída o rebote no se presentan como certezas.

## Importes en euros en Telegram

`euro_display.py` convierte la presentación al enviar un mensaje, usando la misma
fuente ECB/Frankfurter que el conversor web. Un único cambio EUR/USD se aplica a
todos los importes del mensaje. Precios, niveles, capital y P&L en dólares se
expresan como equivalentes en euros, con formato decimal español y fecha del cambio.
Los índices se muestran en puntos. Tickers, unidades y porcentajes no se convierten.

El Diario, Cartera y motor de mercado conservan importes y cálculos originales.
La rentabilidad porcentual sigue siendo la de la divisa original; convertir P&L
histórico al cambio de hoy no reconstruye un resultado histórico real en euros.
En `/riesgo AMD 100`, el presupuesto es 100 EUR: se pasa a USD antes de calcular
unidades y el mensaje vuelve a euros. Un `$` explícito mantiene el presupuesto USD.

La caché privada `.exchange_cache.local.json` evita consultar el cambio en cada
mensaje y sobrevive a reinicios. Se comprueba cada seis horas y, ante un fallo,
se admite un cambio de referencia de hasta siete días (fines de semana y festivos).
Sin un cambio válido se mantienen las monedas originales con aviso; no se cambia
solo el símbolo. En ese caso tampoco se dimensiona una compra con presupuesto EUR
para un activo USD. Las pruebas usan respuestas y envíos simulados.
