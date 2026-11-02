---
name: git-auto-sync
description: >-
  Sincronizar con GitHub después de cambios de código, configuración pública, skills o documentación
  de Buscar un buen precio, o cuando el usuario solicite sincronizar. Protege datos privados y cambios ajenos.
---

# Entrega automática en Git

[AGENTS.md](../../../AGENTS.md) autoriza y exige commit y push a `main` al terminar cambios del proyecto, sin preguntar si el usuario quiere sincronizarlos. Esa autorización no sustituye los permisos técnicos del entorno ni permite publicar secretos, descartar cambios ajenos o forzar el historial remoto.

## Antes de preparar el commit

- Comprueba `git status --short`, rama, diff y estado inicial observado. Identifica cambios del usuario o del proceso activo antes de agrupar archivos.
- No publiques `secrets.json`, `portfolio.json`, `.alerts_cache.json`, `.earnings_cache.json`, `.business_cache.json`, `.trade_plans.json`, `.env`, logs ni otros archivos privados/locales. Comprueba `.gitignore` y que ninguno esté ya preparado o se vaya a añadir por error.
- Verifica que `webhook_url`, `telegram.bot_token` y `telegram.chat_id` de `config.json` estén vacíos. El objeto devuelto por `load_config()` puede contener secretos y no debe volcarse directamente a Git.
- `journal.json` y `latest_data.json` están versionados pero pueden cambiar por el proceso activo. Si ya tenían modificaciones o no pertenecen a la tarea, conserva sus cambios locales fuera del commit; no los restaures en el directorio de trabajo.

## Preparar, comprobar y subir

```powershell
git add -A
git diff --cached --stat
git diff --cached --name-only
git diff --cached --check
```

Si los datos de ejecución ajenos a la tarea entraron en staging, retira solo esas rutas con `git restore --staged journal.json latest_data.json`; esto conserva los archivos locales. No retires cambios que el usuario ya hubiera preparado sin distinguir su estado inicial. Usa rutas concretas para cualquier exclusión adicional.

Revisa el diff preparado y las validaciones relevantes, crea un mensaje descriptivo en español y ejecuta `git push origin main`. No anuncies una subida antes de que termine correctamente.

Si Git detecta propiedad dudosa, verifica que sea este repositorio y usa `git -c safe.directory=...` con su ruta absoluta en cada comando necesario, en vez de añadir excepciones globales. Si el entorno bloquea `.git/index.lock` o la red, solicita la elevación técnica mediante la herramienta; no lo presentes como una nueva elección sobre hacer commit.

Comprueba el código de salida de cada operación dependiente. Si `add` falla, resuelve ese fallo antes de `commit`; si `commit` falla, no interpretes un push sin cambios como entrega realizada. Si el remoto ha avanzado, integra los cambios conservando trabajo ajeno; no uses force push ni reseteos destructivos para resolverlo.

La respuesta final debe distinguir implementación local, validación y sincronización realmente completadas. Si un bloqueo impide subir, indica qué falta sin afirmar que está publicado.
