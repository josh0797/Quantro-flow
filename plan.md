# Plan de fixes (Quantro Flow | Business OS)

## Objetivos
- Eliminar vulnerabilidades IDOR (scope por `workspace_id`) en endpoints críticos.
- Arreglar el flujo de integraciones Google (Gmail/Calendar) evitando estados “connected” manuales y removiendo UI falsa.
- Reparar Modo Simulación para que genere/limpie datos al activar/desactivar, **y asegurar aislamiento multi-tenant** (toda data simulada con `workspace_id`).
- Asegurar que workspaces nuevos (y existentes) queden sembrados con `policies/escalations/templates` (idempotente) + backfill.
- Mejorar consistencia/claridad en UI (idioma, copy, estados vacíos, features duplicadas) y remover código muerto.

> **Estado global:** Todas las prioridades (P1–P5) están **COMPLETADAS** y verificadas con tests automatizados + smoke tests HTTP.

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
- Nota: OAuth real requiere credenciales Google/Azure del usuario (fuera del scope de estos fixes).

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
- Confirmado que workspaces huérfanos (ej. `ws_6f20be48bd44` en esta DB) quedan sembrados.
- Se corrigió un caso de duplicados generados durante hot-reload (limpieza de duplicados en el entorno de pruebas).

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
  (evita choque semántico con `DataModeBanner` Demo/Real).

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
- `GET /api/usage` ahora retorna `404` (validado en `/app/backend_test_priorities.py`).
- Compilación frontend validada con esbuild.

---

## Próximas acciones (orden operativo)
1) ✅ (Hecho) Ejecutar suites de tests y confirmar verde:
   - `/app/backend_test_idor.py` (14/14)
   - `/app/backend_test_priorities.py` (20/20)
2) ✅ (Hecho) Smoke tests HTTP para endpoints críticos.
3) (Opcional, fuera de scope) QA con credenciales reales OAuth Google/Microsoft para validar el flujo completo en navegador.

---

## Criterios de éxito (cumplidos)
- ✅ No existe update/delete cross-workspace en onboarding/content (tests IDOR pasan).
- ✅ Gmail/Calendar solo conectan vía OAuth real; no se puede forzar `connected` por PUT.
- ✅ Simulación genera y limpia datos; toggle accesible; y **sin leak multi-tenant** (todo scopeado por `workspace_id`).
- ✅ Workspaces nuevos y existentes con 0 policies quedan sembrados (idempotente).
- ✅ UI consistente (idioma, copy, empty states) y sin endpoint `/api/usage` muerto.
