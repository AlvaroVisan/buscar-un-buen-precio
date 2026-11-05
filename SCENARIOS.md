# Escenarios del Diario

`scenario_engine.py` evalúa vigilancia y acumulación dentro de la actualización de
`journal_manager.py`. Usa las historias ya descargadas, sin nuevas llamadas de red.
Los escenarios se conservan en `journal.json` y se consultan en `/api/journal`.
No registran compras reales en Cartera ni reconstruyen entradas anteriores.

## Confirmación

Fibonacci 61,8 % o score >= 70 activan vigilancia. Se fija el máximo de las tres
últimas sesiones cerradas como nivel de recuperación. Una sesión posterior al día
de vigilancia debe cerrar sobre ese nivel, con precio actual todavía sobre él y
cierre sobre la media de cuatro sesiones. Cuando hay veinte sesiones disponibles,
también se exige cerrar sobre su media. Las velas del día actual no confirman.

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

Los datos son velas diarias y observaciones periódicas, sin garantía de capturar
todos los movimientos intradía. Las confirmaciones se retrasan deliberadamente
hasta otra fecha de calendario, incluso si la sesión de hoy ya terminó. No se
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
