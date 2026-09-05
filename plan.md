# Plan de fixes (Quantro Flow | Business OS)

## Objetivos
- Eliminar vulnerabilidades IDOR (scope por `workspace_id`) en endpoints críticos.
- Arreglar el flujo de integraciones Google (Gmail/Calendar) evitando estados “connected” manuales y removiendo UI falsa.
- Reparar Modo Simulación para que genere/limpie datos al activar/desactivar, **y asegurar aislamiento multi-tenant** (toda data simulada con `workspace_id`).
- Asegurar que workspaces nuevos (y existentes) queden sembrados con `policies/escalations/templates` (idempotente) + backfill.
- Mejorar consistencia/claridad en UI (idioma, copy, estados vacíos, features duplicadas) y remover código muerto.
- **(NUEVO — PRIORIDAD PRODUCCIÓN/SEGURIDAD/MULTI-TENANT)** Cerrar definitivamente OAuth real de **Google + Microsoft** (dos providers, cuatro variantes de cuenta), con:
  - Authorization Code Flow **server-side**
  - refresh tokens **offline**
  - scopes mínimos
  - validación de scopes otorgados vs requeridos
  - almacenamiento cifrado de tokens
  - scheduler de sincronización real
  - multi-tenant estricto por `workspace_id`

> **Estado global:** Prioridades P1–P5 **COMPLETADAS** (tests verdes). **Nueva Fase OAuth real (P6)** en progreso: **Google listo/configurado en este entorno**, **Microsoft bloqueado por credenciales**.

---

## Fase 1 — P0 Seguridad (IDOR) ✅ COMPLETADA

**User stories (mín. 5)**
1. Como líder, quiero actualizar una tarea de onboarding sin riesgo de modificar tareas de otro workspace.
2. Como líder, quiero borrar contenido solo dentro de mi workspace.
3. Como usuario, quiero que un ID externo/copypasteado no me deje ver/modificar recursos ajenos.
4. Como auditor, quiero pruebas automáticas que detecten regresiones de aislamiento por workspace.
5. Como devops, quiero deploy inmediato con cambios mínimos y tests verdes.

**Implementación (realizada)**
1) `backend/server.py`:
- `update_onboarding_task` (`PUT /api/onboarding/{task_id}`):
  - `update_one` y `find_one` ahora filtran por `{"task_id": task_id, "workspace_id": workspace_id}`.
  - Se mantiene `404` si no matchea.
- `delete_content` (`DELETE /api/content/{content_id}`):
  - `delete_one` ahora filtra por `{"content_id": content_id, "workspace_id": workspace_id}`.
- Auditoría endpoints `{id}`: confirmados ya correctos (scoping por `workspace_id`) para:
  - `/api/contacts/{id}`, `/api/calendar/{id}`, `/api/policies/{id}`, `/api/templates/{id}`, `/api/escalation-rules/{id}`.
- Salvaguarda: se reforzó que el seed coloque `workspace_id` en tasks/content de seed (defensivo).

**Tests (agregados y pasando)**
- Nuevo: `/app/backend_test_idor.py` (14/14 passing)
  - Crea recursos en Workspace A y valida que Workspace B reciba `404` en intentos de update/delete/read.
  - Incluye spot-check de calendar delete y contact read.

**Verificación manual (realizada vía smoke HTTP)**
- Confirmado con dos workspaces sintéticos que update/delete cross-workspace falla.

---

## Fase 2 — P2 Integración Gmail/Calendar rota (UI + hardening) ✅ COMPLETADA

**User stories (mín. 5)**
1. Como usuario, quiero conectar Gmail/Calendar desde un flujo real OAuth (sin formularios falsos).
2. Como usuario, quiero ver claramente dónde conectar la bandeja desde Configuración.
3. Como sistema, quiero impedir que alguien “marque conectado” Gmail/Calendar sin OAuth real.
4. Como usuario, no quiero botones de “Probar conexión” que solo simulen salud para OAuth.
5. Como soporte, quiero que el estado de conexión venga de `/api/integrations/google/status`.

**Implementación (realizada)**
4) `frontend/src/components/IntegrationsPanel.js` (Opción A):
- Removidas tarjetas falsas `gmail` y `google_calendar` del `INTEGRATION_MANIFEST`.
- Agregada `RealConnectCard` con CTA que navega a `/welcome/inbox` (flujo real OAuth).
- Tarjeta `webhook` marcada como `comingSoon`:
  - Badge “Próximamente/Coming Soon”
  - Oculta form/endpoint/botones para evitar prometer `/api/webhooks/*` que no existe.

4b) Backend hardening:
- `PUT /api/integrations/{provider}`:
  - Bloquea `status="connected"` para `provider in (gmail, google_calendar)` devolviendo `400` con mensaje claro.
  - Permite `status="disconnected"`.
  - Mantiene comportamiento normal para `crm`/otros.

5) `/api/integrations/{provider}/test`:
- Se mantiene simulado para providers no-OAuth. Gmail/calendar ya no dependen de este botón desde Settings.

6) Limpieza ws_e1bf...:
- N/A en este entorno (no existía el doc basura en esta DB).

**Tests (agregados y pasando)**
- Incluido en `/app/backend_test_priorities.py`:
  - Gmail/calendar connect manual → `400`.
  - Gmail disconnect → `200`.
  - CRM connect manual → `200`.

**Verificación manual**
- Validación de compilación frontend (esbuild) y comportamiento backend por HTTP.

---

## Fase 3 — P3 Modo Simulación (generación/limpieza + acceso) ✅ COMPLETADA

**User stories (mín. 5)**
1. Como usuario, al activar Simulación quiero que se generen datos de ejemplo automáticamente.
2. Como usuario, al volver a Live quiero que se limpien datos simulados.
3. Como usuario, quiero poder togglear Simulación desde un lugar siempre accesible.
4. Como usuario, quiero que las pantallas vacías me guíen correctamente a conectar o simular.
5. Como QA, quiero tests que validen generate/clear vía API al togglear.

**Implementación (realizada)**
7) Frontend:
- `LiveEmptyState.js`: tras activar `simulation_mode: true`, llama `POST /api/simulation/generate`.
- `SimulationModeToggle.js`:
  - ON: llama `POST /api/simulation/generate`.
  - OFF: llama `POST /api/simulation/clear`.
- `Sidebar.js`: re-montado `SimulationModeToggle` en footer (variant `compact`).

**Corrección crítica adicional (hallazgo de testing) — multi-tenant isolation**
- `backend/server.py`:
  - `generate_simulation_data(industry, workspace_id)` ahora:
    - Limpia solo simulación del workspace actual.
    - Inserta **toda** data simulada con `workspace_id`.
  - `POST /api/simulation/clear` y `GET /api/simulation/status` ahora están scopeados por `workspace_id`.
  - Se corrigieron 2 call sites adicionales:
    - Auto-regeneración en `PUT /api/business-profile`.
    - Seed en `/api/onboarding/welcome/complete`.

**Tests (agregados y pasando)**
- `/app/backend_test_priorities.py`: pruebas generate/clear.
- Verificación adicional manual con 2 workspaces sintéticos:
  - Generar en A no crea data en B.
  - Clear en B no borra data de A.

---

## Fase 4 — P4 Seed/backfill de automatizaciones para workspaces ✅ COMPLETADA

**User stories (mín. 5)**
1. Como cliente nuevo, quiero tener policies por defecto sin configurar nada.
2. Como cliente nuevo, quiero reglas de escalamiento listas para usar.
3. Como cliente nuevo, quiero templates disponibles al entrar.
4. Como admin, quiero que el seed sea idempotente (sin duplicados).
5. Como operador, quiero backfill automático para workspaces existentes con 0 policies.

**Implementación (realizada)**
10) `seed_workspace_config(workspace_id, ...)`:
- Ahora crea defaults por workspace:
  - `automation_policies`: 7 intents.
  - `escalation_rules`: 5 reglas.
  - `content_templates`: 5 templates.
- Idempotencia por item:
  - Policies: por `intent`.
  - Rules: por `name`.
  - Templates: por `name`.

11) Backfill:
- Añadido `backfill_workspace_automations()` al startup (`lifespan`).
- Aplica a cualquier workspace con `0` policies.
- Confirmado que workspaces huérfanos quedan sembrados.
- Se corrigió un caso de duplicados generados durante hot-reload (limpieza en el entorno de pruebas).

**Tests (agregados y pasando)**
- `/app/backend_test_priorities.py` valida:
  - Counts esperados (7/5/5).
  - Idempotencia (sin duplicados tras re-seed).

---

## Fase 5 — P5 UI/consistencia + limpieza ✅ COMPLETADA

**User stories (mín. 5)**
1. Como usuario, si elijo español manualmente, el backend no debe sobreescribir mi elección.
2. Como usuario, quiero copy consistente entre “Demo/Live” en banners/empty states.
3. Como usuario, en CRM quiero un mensaje distinto cuando hay contactos pero no seleccioné uno.
4. Como usuario, quiero fechas formateadas en mi locale real.
5. Como usuario, si no hay agentes en Onboarding quiero un empty state útil.

**Implementación (realizada)**
12) `LanguageContext.js`:
- Agregado flag explícito `quantro_lang_user_set='1'`.
- Solo se escribe cuando el usuario usa el selector.
- Hidratación desde backend solo sobreescribe si el usuario **no** eligió manualmente.

13) Copy Demo/Live:
- `simulation.live_empty_title` actualizado a texto neutral:
  - ES: “Sin datos reales todavía”
  - EN: “No real data yet”

14) `CRM.js`:
- Si hay contactos pero ninguno seleccionado → `crm.select_prompt`.

15) `Members.js`:
- `formatStepDate` ahora usa locale explícito: `es-ES` / `en-US` según `useLanguage()`.

16) `Onboarding.js`:
- Agregado empty state (`LiveEmptyState moduleKey="onboarding"`) si no hay agents.

17) Renombre de feature para evitar colisión:
- Sidebar: “Onboarding” → “Onboarding de Equipo” / “Team Onboarding”.
- Members tab mantiene “Onboarding” (people onboarding).

18) Webhook card:
- Marcada como “Próximamente” + sin endpoint/form activo.

19) Endpoint muerto `/api/usage`:
- Eliminado de `backend/server.py` (confirmado no usado por `PlanAndUsage.js`).

**Tests / checks**
- `GET /api/usage` ahora retorna `404`.
- Compilación frontend validada con esbuild.

---

## Fase 6 — OAuth REAL Google + Microsoft (Producción / Seguridad / Multi-tenant) 🚧 EN PROGRESO

### 0) Regla de trabajo (audit first) ✅ CUMPLIDA
**Inspección completa realizada** antes de modificar código (según tu Regla 0). Se revisaron:
- `backend/server.py`
- `backend/google_oauth.py`
- `backend/microsoft_oauth.py`
- `frontend/src/pages/welcome/StepInbox.js`
- `frontend/src/pages/welcome/components/ProviderConnectModal.js`
- `frontend/src/components/IntegrationsPanel.js`
- referencias a endpoints `/api/integrations/{provider}/{start,callback,status,sync,disconnect}`
- variables `.env`: `GOOGLE_CLIENT_ID/SECRET`, `MS_CLIENT_ID/SECRET`, redirect URIs

**Hallazgos del audit (estado real):**
- Ya existía una implementación madura y correcta para ambos providers:
  - Authorization Code Flow **server-side**
  - Tokens cifrados con Fernet
  - Validación CSRF por `state` con TTL
  - Scheduler de sync periódico (`_periodic_provider_sync_loop`)
  - Un consentimiento por provider conecta Mail + Calendar (Google: Gmail+Calendar, Microsoft: Outlook+Calendar)
  - Microsoft usa MSAL oficial con `tenant=common` (soporta MSA personal + Entra/365 con una sola App)
- **Gaps reales detectados** antes del fix:
  1) Redirect URIs no estaban centralizados para producción.
  2) No se verificaba “scopes otorgados vs requeridos” post-callback.

### 1) Progreso implementado ✅
**P6.1 Google — scope validation post-callback (artefacto patch) ✅**
- Patch aplicado: `0001-Google-OAuth-compare-granted-vs-required-scopes...patch`
  - `google_oauth.missing_required_scopes(granted_scopes)`
  - `GET /api/integrations/google/status` ahora expone:
    - `connected`, `status`, `reauthorization_required`, `missing_scopes`
    - backward-compat: re-deriva el estado si el doc es viejo.
  - `GET /api/integrations/google/callback` ahora guarda:
    - `connected`, `status`, `reauthorization_required`, `missing_scopes`
    - y hace bounce `google_connected=permission_missing` si aplica.
  - `POST /api/integrations/google/sync` devuelve `403` con `missing_scopes` si la conexión requiere reautorización.

**P6.2 Redirect URIs — single source of truth ✅**
- Introducido `BACKEND_PUBLIC_URL` como fuente única de dominio canónico.
- `google_oauth.resolve_redirect_uri` y `microsoft_oauth.resolve_redirect_uri` ahora usan prioridad:
  1) provider override (`GOOGLE_OAUTH_REDIRECT_URI` / `MS_OAUTH_REDIRECT_URI`)
  2) `BACKEND_PUBLIC_URL`
  3) request base URL (dev/preview fallback)
  4) `REACT_APP_BACKEND_URL` (legacy fallback)
- `backend/.env` actualizado:
  - `BACKEND_PUBLIC_URL=https://quantro-os.emergent.host`
  - `GOOGLE_OAUTH_REDIRECT_URI=https://quantro-os.emergent.host/api/integrations/google/callback`
  - `MS_OAUTH_REDIRECT_URI=https://quantro-os.emergent.host/api/integrations/microsoft/callback`

**P6.3 Google OAuth credentials (reales) ✅ (en este entorno)**
- Se cargaron `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` desde el JSON aportado por ti.
- El JSON confirma que el redirect URI registrado en Google Cloud Console es:
  - `https://quantro-os.emergent.host/api/integrations/google/callback`

### 2) Verificaciones ejecutadas ✅
- `GET /api/integrations/google/status` → `configured:true`.
- `GET /api/integrations/google/start` → URL real de Google con:
  - `client_id` correcto
  - `redirect_uri` EXACTO (match)
  - scopes mínimos
  - `access_type=offline`
  - `prompt=consent`
- Microsoft sigue `configured:false` porque faltan `MS_CLIENT_ID/SECRET`.
- No regressions:
  - `/app/backend_test_idor.py` → 14/14
  - `/app/backend_test_priorities.py` → 20/20

### 3) Pendiente / bloqueado (para cerrar producción) ⛔
**P6.4 Microsoft credentials (bloqueante)**
- Faltan:
  - `MS_CLIENT_ID`
  - `MS_CLIENT_SECRET`
- Requisito externo: App Registration con:
  - Supported account types: **AzureADandPersonalMicrosoftAccount**
  - Redirect URI (Web): `https://quantro-os.emergent.host/api/integrations/microsoft/callback`
  - Delegated permissions mínimas: `Mail.Read`, `Calendars.Read`, `offline_access`, `User.Read`

**P6.5 Pruebas E2E reales de los 4 escenarios (bloqueante operativo)**
- A) Gmail personal — listo para ejecutar cuando hagas login y completes el consentimiento.
- B) Google Workspace — requiere cuenta Workspace de prueba.
- C) Microsoft personal — requiere MS creds + cuenta MSA.
- D) Microsoft 365/Entra — requiere MS creds + cuenta org.

**P6.6 Deploy a producción (bloqueante operativo)**
- Estos cambios están aplicados en este repo/entorno; para que se reflejen en:
  - Frontend: https://quantroflow.online
  - Backend: https://quantro-os.emergent.host
  necesitas ejecutar tu proceso de deploy/redeploy.

---

## Próximas acciones (orden operativo)
1) ✅ (Hecho) Suites de tests y smoke HTTP:
   - `/app/backend_test_idor.py` (14/14)
   - `/app/backend_test_priorities.py` (20/20)
2) 🚧 (En curso) Completar Microsoft OAuth:
   - Recibir `MS_CLIENT_ID` + `MS_CLIENT_SECRET`.
   - Setearlos en `backend/.env` (gitignored) + reiniciar backend.
   - Validar `/api/integrations/microsoft/start` y callback.
3) 🚧 Pruebas E2E reales (obligatorias para cerrar):
   - Ejecutar A/B/C/D (o dejar preparado el checklist exacto de credenciales faltantes).
4) 🚧 Deploy a producción:
   - Confirmar que `BACKEND_PUBLIC_URL` y redirect URIs registrados coinciden **exactamente**.
   - Confirmar que `/api/integrations/{provider}/status` y `sync` funcionan desde producción.

---

## Criterios de éxito (actualizados)
- ✅ No existe update/delete cross-workspace en onboarding/content.
- ✅ Gmail/Calendar no se pueden marcar “connected” a mano.
- ✅ (P6) Google OAuth start/callback/scope-validation listos y con credenciales reales en este entorno.
- ⛔ (P6) Microsoft OAuth pendiente por credenciales.
- ⛔ (P6) No se considera “cerrado definitivamente” hasta ejecutar pruebas reales A–D (o dejar E2E preparado + especificar credenciales externas faltantes).
- ✅ Sin regresiones en suites (14/14 + 20/20).