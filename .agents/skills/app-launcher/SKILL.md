---
name: app-launcher
description: >-
  Arrancar, reiniciar o diagnosticar el panel y el bot de Buscar un buen precio en Windows.
  Usar para puertos ocupados, procesos duplicados, Python ausente o cambios que no se cargan.
---

# Arranque y versiones en ejecución

## Archivos y contrato

- [Iniciar_Aplicacion.bat](../../../Iniciar_Aplicacion.bat) es el único lanzador. Activa UTF-8, exige Python 3.10 o superior y prueba `py -3` antes de `python`.
- [launcher.py](../../../launcher.py) comprueba dependencias, identidad del panel y puerto antes de ejecutar `app.py` con el mismo intérprete. Reutiliza un panel existente; no recarga su código.
- [app.py](../../../app.py) reserva el puerto antes de arrancar scheduler y bot. En Windows usa `SO_EXCLUSIVEADDRUSE` para impedir instancias que compartan el puerto.
- `GET http://127.0.0.1:5050/api/health` devuelve `application="buscar-un-buen-precio"` y `status="ok"`. Un HTTP 200 solo confirma que responde el panel, no la versión de sus funciones ni el éxito de Telegram.

## Diagnóstico y reinicio

1. Comprueba salud, comando del proceso y cambios en disco. Un error al enumerar procesos desde el sandbox no demuestra que no existan; usa elevación si es necesaria para consultarlos.
2. Ante puerto ocupado, verifica el bind y la identidad del servicio. `_port_is_available()` comprueba si puede reservarlo: una conexión que agota su timeout no demuestra ocupación. No desactives la exclusividad ni cambies el puerto sin localizar la causa.
3. Abrir otra vez el `.bat` abre la instancia existente. Para aplicar Python nuevo, verifica que el proceso a reiniciar corresponde al `app.py` de esta ruta. Detén únicamente esa instancia cuando el reinicio esté autorizado; no mates todos los procesos Python ni otros ocupantes del puerto.
4. Ejecuta el lanzador desde el directorio del proyecto. Si lo inicias en segundo plano con PowerShell, usa `Start-Process -WindowStyle Hidden`, ruta de trabajo explícita y logs locales ignorados. Un arranque manual normal mantiene la consola abierta; el proceso debe seguir vivo para actualizar y atender el bot.
5. Verifica salud, carga de las rutas nuevas y arranque del listener/scheduler. Para cambios de mensajes, genera una respuesta con Telegram simulado antes del reinicio y pide una consulta nueva al usuario después. Reiniciar no modifica los mensajes ya enviados.

No reinstales dependencias ni abras varios listeners por defecto. Comprueba el intérprete real: en este entorno `py` puede no existir aunque `python` funcione y el ejecutable se llame `python3.10.exe`. No dependas únicamente de `Get-Process -Name python` para identificarlo.

Los logs de un proceso activo pueden requerir lectura compartida; `Get-Content -Encoding UTF8` permite inspección sin volcarlos completos. No expongas tokens ni IDs de chat.

## Validación

Para cambios de arranque: `python -m unittest test_launcher test_local_server test_auto_scheduler`. Prueba puerto libre, panel existente, servicio ajeno y ausencia de servicios duplicados; usa mocks para navegador, bot y scheduler en las pruebas automatizadas. No arranques el servicio real como efecto colateral de una revisión documental.

Después de una corrección de código usa [git-auto-sync](../git-auto-sync/SKILL.md). Una mera puesta en marcha no requiere fabricar un commit con cotizaciones o logs.
