# Plan de fixes (Quantro Flow | Business OS)

## Objetivos
- Eliminar vulnerabilidades IDOR (scope por `workspace_id`) en endpoints críticos.
- Arreglar el flujo de integraciones Google (Gmail/Calendar) evitando estados “connected” manuales y removiendo UI falsa.
- Reparar Modo Simulación para que genere/limpie datos al activar/desactivar, **y asegurar aislamiento multi-tenant** (toda data simulada con `workspace_id`).
- Asegurar que workspaces nuevos (y existentes) queden sembrados con `policies/escalations/templates` (idempotente) + backfill.
- Mejorar consistencia/claridad en UI (idioma, copy, estados vacíos, features duplicadas) y remover código muerto.
- **(PRIORIDAD PRODUCCIÓN/SEGURIDAD/MULTI-TENANT)** Cerrar definitivamente OAuth real de **Google + Microsoft** (dos providers, cuatro variantes de cuenta), con:
  - Authorization Code Flow **server-side**
  - refresh tokens **offline**
  - scopes mínimos
  - validación de scopes otorgados vs requeridos
  - almacenamiento cifrado de tokens
  - scheduler de sincronización real
  - multi-tenant estricto por `workspace_id`
  - **redirects seguros** (sin confiar en Origin/Referer)

> **Estado global:** Prioridades P1–P5 **COMPLETADAS** (tests verdes). **Fase OAuth (P6)**: **Google endurecido y listo para producción tras deploy**, **Microsoft intencionalmente oculto ("Próximamente") hasta nuevo aviso**.

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

## Fase 6 — OAuth REAL (Producción / Seguridad / Multi-tenant) ✅ Hardening aplicado / ⛔ cierre final pendiente de deploy

### 0) Regla de trabajo (audit first) ✅ CUMPLIDA
**Inspección completa realizada** antes de modificar código. Revisados:
- `backend/server.py`, `backend/google_oauth.py`, `backend/microsoft_oauth.py`
- `frontend/src/pages/welcome/StepInbox.js`, `ProviderConnectModal.js`, `IntegrationsPanel.js`
- endpoints `/api/integrations/{provider}/{start,callback,status,sync,disconnect}`
- variables: `GOOGLE_CLIENT_ID/SECRET`, `GOOGLE_TOKENS_ENCRYPTION_KEY`, `MS_CLIENT_ID/SECRET`, `BACKEND_PUBLIC_URL`, `FRONTEND_PUBLIC_URL`

**Hallazgos del audit (estado real):**
- Ya existía una implementación correcta para ambos providers:
  - Authorization Code Flow server-side
  - Tokens cifrados (Fernet)
  - `state` con TTL (anti-CSRF)
  - Sync scheduler periódico
  - Microsoft con MSAL (`tenant=common`) para cuentas personales + empresariales en **una sola app**

### 1) Hardening aplicado (lista de 9 fixes) ✅ COMPLETADO

**P6.1 Microsoft “PENDIENTE” en UI (sin tocar backend) ✅**
- `ProviderConnectModal.js`:
  - Microsoft se muestra como **“Próximamente / Coming soon”**.
  - Visualmente deshabilitado + badge.
  - **Nunca llama** `startMicrosoftOAuth`.
- `microsoft_oauth.py` y endpoints se mantienen intactos (no borrados ni reescritos).

**P6.2 Diagnóstico granular seguro de configuración Google ✅**
- `google_oauth.config_status()` expone solo booleans:
  - `client_id_configured`
  - `client_secret_configured`
  - `encryption_key_configured`
  - `backend_public_url_configured`
  - `redirect_uri_configured`
- `google_oauth.is_oauth_configured()` ahora deriva de `config_status()` (una sola fuente de verdad).
- `/api/integrations/google/start` devuelve un error 503 con mensaje de “qué falta” **sin exponer valores**.

**P6.3 Secrets de producción (no asumir preview) ✅ (documentado)**
- Se documentó explícitamente: producción debe configurar secrets/env vars en el deployment (no depende de `backend/.env`).
- Producción debe tener:
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `GOOGLE_TOKENS_ENCRYPTION_KEY`
  - `BACKEND_PUBLIC_URL=https://quantro-os.emergent.host`
  - `FRONTEND_PUBLIC_URL=https://quantroflow.online`

**P6.4 FRONTEND_PUBLIC_URL como retorno canónico + open-redirect hardening ✅**
- Eliminado `_frontend_url_from()` (no confiar en `Origin/Referer`, ni usar `REACT_APP_BACKEND_URL` como fallback de frontend).
- Nuevo `_frontend_base_url()`:
  - Solo lee `FRONTEND_PUBLIC_URL`
  - **Fail-closed** (500) si no está configurado.
- Return path safe:
  - `ALLOWED_OAUTH_RETURN_PATHS = {"/welcome/inbox", "/welcome/calendar"}`
  - `_sanitize_return_to()` evita open redirect por `return_to`.

**P6.5 ProviderCallbackHandler: permission_missing ✅**
- `OnboardingShell.js` ahora maneja:
  - `google_connected=permission_missing`
  - muestra permisos faltantes
  - CTA “Autorizar nuevamente” que reinicia `/api/integrations/google/start`
  - **NO marca** inbox/calendar como “real” si faltan scopes.

**P6.6 Preservar refresh_token si Google no lo devuelve ✅**
- Callback Google ahora:
  - lee `refresh_token` cifrado existente
  - si `creds.refresh_token` viene vacío → conserva el anterior (nunca lo nulifica).

**P6.7 No filtrar excepciones internas a URLs/frontend ✅**
- Callback Google ya no incluye `str(exc)` en query params.
- Solo envía `reason` con códigos controlados.
- Detalles quedan solo en logs (server-side).

**P6.8 Diagnóstico adicional en /google/status ✅**
- `GET /api/integrations/google/status` ahora devuelve:
  - `configured`, `connected`, `status`, `missing_scopes`, etc.
  - + flags de `config_status()` (sin secretos).

**P6.9 Criterio de cierre: NO preview-only ✅ (documentado)**
- Se dejó explícito: **no se declara cerrado** hasta validar contra:
  - `https://quantro-os.emergent.host`

### 2) Verificaciones ejecutadas (preview, no cuentan como cierre final) ✅
- `GET /api/integrations/google/status` devuelve `configured:true` + flags de diagnóstico.
- `GET /api/integrations/google/start` genera `auth_url` real.
- `return_to` whitelist probado:
  - path permitido se preserva
  - URL externa se sanea a default
- `error` param sanitizado:
  - payload malicioso colapsa a `oauth_error`.
- Fail-closed probado:
  - sin `FRONTEND_PUBLIC_URL` el callback devuelve 500 y no redirige a dominio adivinado.
- No regressions:
  - `backend_test_idor.py` 14/14
  - `backend_test_priorities.py` 20/20
  - esbuild OK

> Nota operativa: se intentó login browser automatizado con credenciales aportadas para pruebas reales, pero el flujo no fue concluyente en este entorno (401 repetidos a `/api/business-profile` tras submit). No se trató como bug resuelto/introducido porque estos cambios no tocan Auth.

### 3) Pendiente para cierre definitivo (obligatorio) ⛔

**P6.10 Deploy de producción (bloqueante)**
- Configurar en el deployment **de producción** (Secrets/env vars):
  - `GOOGLE_CLIENT_ID`
  - `GOOGLE_CLIENT_SECRET`
  - `GOOGLE_TOKENS_ENCRYPTION_KEY`
  - `BACKEND_PUBLIC_URL=https://quantro-os.emergent.host`
  - `FRONTEND_PUBLIC_URL=https://quantroflow.online`

**P6.11 Prueba final obligatoria (post-deploy) — Google**
Validar contra **producción**:
- `GET https://quantro-os.emergent.host/api/integrations/google/status` → `configured:true`
- `GET https://quantro-os.emergent.host/api/integrations/google/start` → devuelve `auth_url` real
- Completar consentimiento en Google, volver al frontend y confirmar:
  - `connected:true` solo si no hay `missing_scopes`
  - si hay `permission_missing`, UI muestra faltantes + CTA reautorizar

**P6.12 Microsoft (intencionalmente PENDIENTE)**
- No se expone al usuario aún.
- No se modifica lógica Microsoft más allá de la seguridad del redirect base (ya no existe `_frontend_url_from`).

---

## Próximas acciones (orden operativo)
1) ✅ (Hecho) Hardening de OAuth Google + seguridad de redirects (9 puntos)
2) ⛔ Deploy producción con Secrets correctos (sin depender de `.env` local)
3) ⛔ Ejecutar pruebas reales contra `https://quantro-os.emergent.host`:
   - `/google/status` y `/google/start`
   - completar callback y verificar scopes
4) (Futuro) Re-habilitar Microsoft en UI cuando se autorice el rollout (sin crear apps duplicadas)

---

## Criterios de éxito (actualizados)
- ✅ No existe update/delete cross-workspace en onboarding/content.
- ✅ Gmail/Calendar no se pueden marcar “connected” a mano.
- ✅ Google OAuth endurecido:
  - diagnóstico granular sin secretos
  - return redirects seguros (sin Origin/Referer)
  - scopes validados (permission_missing)
  - refresh_token preservado si Google no lo devuelve
  - no se filtran excepciones a URLs
- ✅ Microsoft NO expuesto en UI (Próximamente) sin borrar endpoints.
- ⛔ **No se considera cerrado** hasta verificación real post-deploy en:
  - `https://quantro-os.emergent.host/api/integrations/google/status` → `configured:true`
  - `https://quantro-os.emergent.host/api/integrations/google/start` → `auth_url` real
- ✅ Sin regresiones en suites (14/14 + 20/20).