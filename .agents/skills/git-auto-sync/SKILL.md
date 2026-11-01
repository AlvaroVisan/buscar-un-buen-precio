---
name: git-auto-sync
description: >-
  Use this skill automatically after completing any code, configuration, skill, or documentation
  change in "Buscar un buen precio", or when the user asks to sync with GitHub. Stages, commits,
  and pushes changes without asking for confirmation while protecting private files.
---

# Sincronización Automática con Git y GitHub (`git-auto-sync`)

Por regla expresa del usuario en [AGENTS.md](file:///e:/Proyectos/Buscar%20un%20buen%20precio/AGENTS.md), **nunca debes preguntar si desea subir los cambios a Git/GitHub**: tras completar y verificar cualquier modificación en el proyecto, debes hacer commit y push automáticamente.

## 1. Verificación de Seguridad Previa al Commit

Antes de ejecutar `git add -A`, comprueba con `git status --short` que **ninguno** de los siguientes archivos privados aparezca para subirse:
- `secrets.json` (credenciales de Telegram y URL del Webhook de Google Sheets)
- `portfolio.json` (posiciones financieras privadas del usuario)
- `.alerts_cache.json` y `.earnings_cache.json` (cachés operativas locales)

Además, verifica que [config.json](file:///e:/Proyectos/Buscar%20un%20buen%20precio/config.json) tenga `"webhook_url": ""`, `"bot_token": ""` y `"chat_id": ""`.

## 2. Procedimiento de Subida Automática

1. **Añadir archivos al stage**:
   ```powershell
   git add -A
   ```
2. **Crear commit descriptivo en español**:
   Usa prefijos semánticos claros (`feat:`, `fix:`, `chore:`, `docs:`):
   ```powershell
   git commit -m "feat: descripción concisa de la mejora implementada"
   ```
3. **Subir a la rama `main` en GitHub**:
   ```powershell
   git push
   ```
   *(Nota: En el entorno Windows de este proyecto, `.git/index.lock` y la salida de red de `git push` pueden requerir ejecutar el comando fuera del sandbox si el modo estándar devuelve `Permission denied` o `Failed to connect`).*
