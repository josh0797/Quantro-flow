/**
 * Quantro OS — Single source of truth for all user-facing copy.
 *
 * Conventions:
 *   - Hierarchical, dot-addressable keys resolved via t('a.b.c')
 *   - Variable interpolation: "Hello {{name}}" → t('key', { name: 'Ana' })
 *   - Never hard-code user-facing strings in components. Add them here first.
 *   - If a key is missing in the active language, EN is used as fallback;
 *     if still missing, the key itself is returned (never breaks UI).
 *
 * Adding a new language:
 *   1. Duplicate the `en` tree at the bottom.
 *   2. Translate leaf values only — preserve the shape.
 *   3. Update SUPPORTED_LANGUAGES in LanguageContext.
 */

export const translations = {
  // ────────────────────────────────────────────────────────────
  // Español
  // ────────────────────────────────────────────────────────────
  es: {
    common: {
      loading: 'Cargando...',
      save: 'Guardar',
      cancel: 'Cancelar',
      confirm: 'Confirmar',
      delete: 'Eliminar',
      edit: 'Editar',
      create: 'Crear',
      connect: 'Conectar',
      disconnect: 'Desconectar',
      update: 'Actualizar',
      details: 'Detalles',
      close: 'Cerrar',
      back: 'Volver',
      next: 'Siguiente',
      previous: 'Anterior',
      search: 'Buscar',
      optional: 'opcional',
      required: 'requerido',
      yes: 'Sí',
      no: 'No',
      retry: 'Reintentar',
      copy: 'Copiar',
      copied: 'Copiado',
    },

    language: {
      label: 'Idioma',
      spanish: 'Español',
      english: 'English',
      switched_to: 'Idioma cambiado a {{language}}',
    },

    login: {
      title: 'Bienvenido a Quantro One',
      subtitle: 'Tu sistema operativo autónomo para el negocio.',
      sign_in_google: 'Iniciar sesión con Google',
      loading: 'Verificando credenciales...',
    },

    sidebar: {
      brand: 'Quantro One',
      brand_subtitle: 'BUSINESS OS',
      dashboard: 'Panel',
      smart_inbox: 'Bandeja Inteligente',
      schedule: 'Agenda',
      crm: 'CRM',
      onboarding: 'Onboarding',
      content_engine: 'Motor de Contenido',
      automation: 'Automatización',
      settings: 'Configuración',
      integrations_label: 'INTEGRACIONES',
      system_running: 'Sistema Operando',
      synced: 'Sincronizado {{time}}',
    },

    dashboard: {
      title: 'Panel',
      subtitle: 'Operaciones del negocio · Vista en tiempo real',
      live_mode: 'Datos en Vivo',
      simulation_mode: 'Modo Simulación Activo',
      kpi: {
        team: 'Equipo',
        team_active: '{{count}} activos',
        schedule: 'Reuniones Próximas',
        schedule_window: 'próximos 7 días',
        inbox: 'Solicitudes',
        inbox_processed: '{{count}} procesadas',
        crm: 'Contactos Sincronizados',
        crm_new: '{{count}} nuevos esta semana',
      },
      live_activity: 'Actividad en Vivo',
      real_time: 'Tiempo Real',
      ai_suggestions: 'Sugerencias IA',
      quick_actions: 'Acciones Rápidas',
      today_meetings: 'Reuniones de Hoy',
      no_meetings: 'Sin reuniones hoy',
      view_full_calendar: 'Ver Calendario Completo',
      integration_connected: '{{count}} Integración Conectada',
      integrations_connected: '{{count}} Integraciones Conectadas',
      integration_sync_status: 'Sincronización en tiempo real',
      manage: 'Gestionar',
    },

    system_health: {
      title: 'Estado del Sistema',
      tagline: 'Quantro OS detecta y resuelve problemas antes de que los notes.',
      status_healthy: 'Sistema Saludable',
      status_repaired: 'Sistema Auto-Reparado',
      status_degraded: 'Sistema Degradado',
      all_operational: 'Todos los sistemas operativos',
      last_check: 'Última verificación: {{time}}',
      subcopy_healthy:
        'Quantro OS mantiene activamente tus integraciones. Las inconsistencias se detectan y resuelven automáticamente.',
      subcopy_repaired:
        'Quantro OS detectó componentes faltantes y los reparó automáticamente.',
      subcopy_degraded:
        'Algunos componentes requieren atención. Quantro OS está trabajando en resolverlos.',
      checks: {
        integrations_stable: 'Integraciones estables',
        integrations_stable_ok: '{{have}}/{{total}} proveedores registrados',
        integrations_stable_fail: 'Faltan proveedores ({{missing}})',
        data_consistency: 'Consistencia de datos verificada',
        data_consistency_ok: 'Perfil de negocio presente',
        data_consistency_fail: 'Perfil de negocio ausente',
        no_issues: 'Sin problemas detectados',
        no_issues_ok: 'Todos los sistemas operativos',
        no_issues_repairs: '{{count}} reparación(es) en el último arranque',
        issues_detected: 'Problemas detectados',
      },
      auto_resolved_header: 'Resueltos automáticamente en el último arranque',
      repair_provider_restored:
        "Integración '{{name}}' faltante fue restaurada automáticamente.",
      repair_metadata_backfilled:
        "Metadata reparada para '{{name}}' ({{fields}}).",
      repair_toast_single: 'El sistema reparó una integración faltante automáticamente',
      repair_toast_multi: 'El sistema reparó {{count}} integraciones faltantes automáticamente',
    },

    settings: {
      title: 'Configuración',
      subtitle: 'Configura tu Business OS',
      tabs: {
        integrations: 'Integraciones',
        automation: 'Automatización',
        business_profile: 'Perfil del Negocio',
        workspace: 'Espacio de Trabajo',
      },
      automation: {
        heading: 'Automatización',
        description:
          'Configura tus políticas de automatización, umbrales de confianza y reglas de escalamiento.',
        manage_button: 'Gestionar Políticas de Automatización',
        overview_title: 'Resumen Rápido',
        overview_auto: 'Auto-ejecución habilitada para items de alta confianza',
        overview_manual: 'Aprobación manual requerida para confianza media',
        overview_escalation: 'Escalamiento activado para baja confianza o conflictos',
      },
      profile: {
        heading: 'Perfil del Negocio',
        description: 'Configura el tipo de negocio y personaliza la terminología del sistema',
        industry_label: 'Industria',
        industry_helper:
          'El sistema adaptará su lenguaje y sugerencias IA según tu industria',
        use_case_label: 'Caso de Uso (opcional)',
        use_case_placeholder: 'Describe cómo usas este Business OS...',
        naming_heading: 'Nombres Personalizados de Entidades',
        naming_helper:
          'Personaliza la terminología en todo el sistema. Deja en blanco para usar los valores por defecto de la industria.',
        label_contacts: 'Etiqueta de Contactos',
        label_team: 'Etiqueta de Miembros del Equipo',
        label_meetings: 'Etiqueta de Reuniones',
        label_events: 'Etiqueta de Eventos',
        label_services: 'Etiqueta de Servicios/Productos',
        simulation_heading: 'Modo Simulación',
        simulation_description:
          'Carga datos operativos de muestra realistas para tu industria. Ideal para probar flujos de trabajo, validar automatizaciones y hacer demos antes de conectar integraciones reales.',
        simulation_active: 'Activo: El sistema está poblado con datos simulados',
        save_button: 'Guardar Perfil del Negocio',
        saving: 'Guardando...',
        saved_toast: 'Perfil del Negocio actualizado correctamente',
        save_failed_toast: 'Error al actualizar el Perfil del Negocio',
      },
      workspace: {
        heading: 'Espacio de Trabajo',
        description: 'Configuración del workspace y gestión del equipo',
        name_label: 'Nombre del Workspace',
        name_placeholder: 'Mi Negocio',
        phase_note:
          'Las funciones de autenticación y workspace multi-tenant estarán disponibles en la Fase 6.',
      },
    },

    integrations: {
      groups: {
        ai: 'IA e Inteligencia',
        email: 'Correo y Calendario',
        crm: 'CRM',
        automation: 'Webhooks y Endpoints',
      },
      status: {
        connected: 'Conectado',
        not_connected: 'No Conectado',
        last_sync: 'Última sincronización: {{time}}',
      },
      actions: {
        save_and_connect: 'Guardar y Conectar',
        connect_google: 'Conectar con Google',
        enable_webhooks: 'Activar Webhooks',
        test_connection: 'Probar Conexión',
        update_config: 'Actualizar Configuración',
        disconnect: 'Desconectar',
      },
      openai: {
        name: 'Proveedor OpenAI / LLM',
        description:
          'Potencia la clasificación IA, redacción y auto-ejecución en todos tus flujos.',
        helper:
          'Este workspace está alimentado por la Clave Universal Emergent. Añade tu propia clave para sobrescribirla por workspace.',
        api_key: 'API Key',
        default_model: 'Modelo Predeterminado',
      },
      gmail: {
        name: 'Gmail',
        description:
          'Sincroniza el correo entrante hacia la Bandeja Inteligente y permite al sistema redactar respuestas.',
        account: 'Cuenta Conectada',
      },
      calendar: {
        name: 'Google Calendar',
        description:
          'Sincronización bidireccional de eventos, reservas y ventanas de disponibilidad.',
        calendar_id: 'ID del Calendario',
      },
      crm: {
        name: 'Sistema CRM',
        description:
          'Sincronización bidireccional con HubSpot, GoHighLevel, Pipedrive o cualquier CRM con API.',
        provider: 'Proveedor CRM',
        api_key: 'API Key',
        base_url: 'URL Base (opcional)',
      },
      webhook: {
        name: 'Webhooks Entrantes',
        description:
          'Reenvía eventos desde cualquier servicio hacia Business OS. Usa el endpoint a continuación en tus herramientas externas.',
        endpoint_label: 'TU ENDPOINT ENTRANTE',
        shared_secret: 'Secreto Compartido (opcional)',
        secret_placeholder: 'Genera una cadena aleatoria',
      },
      toasts: {
        connected: '{{provider}} conectado exitosamente',
        disconnected: '{{provider}} desconectado',
        test_ok: 'La conexión de {{provider}} está saludable',
        test_fail: '{{provider}} no está conectado',
        load_failed: 'Error al cargar integraciones',
        connect_failed: 'Error al conectar {{provider}}',
        endpoint_copied: 'Endpoint copiado al portapapeles',
        copy_failed: 'Copia no disponible en este navegador — selecciona y copia manualmente',
      },
    },

    smart_inbox: {
      title: 'Bandeja Inteligente',
      subtitle: 'Clasificación IA y triage automatizado',
      empty_state: 'No hay items en la bandeja',
      analyze: 'Analizar',
      analyze_all: 'Analizar todo',
      approve: 'Aprobar',
      escalate: 'Escalar',
    },

    // ────────────────────────────────────────────────────
    // Decisiones — patrón clave para el sistema de decisiones
    // ────────────────────────────────────────────────────
    decisions: {
      revenue: {
        raise_prices: {
          title: 'Subir precios un {{percent}}%',
          summary:
            'La demanda y márgenes actuales respaldan un ajuste de precios del {{percent}}%.',
          impact: 'Incremento estimado en ingresos de {{lift}}%.',
          action_label: 'Aplicar cambio de precios',
        },
        launch_campaign: {
          title: 'Lanzar campaña de retención',
          summary:
            '{{count}} clientes muestran señales de riesgo — una campaña dirigida puede recuperarlos.',
          action_label: 'Lanzar campaña',
        },
      },
      action_center: {
        no_pending: 'Sin decisiones pendientes',
        pending_count: '{{count}} decisión pendiente',
        pending_count_plural: '{{count}} decisiones pendientes',
      },
    },

    // ────────────────────────────────────────────────────
    // Agentes — etiquetas y descripciones
    // ────────────────────────────────────────────────────
    agents: {
      pricing: {
        label: 'Agente de Precios',
        description: 'Monitorea márgenes y recomienda ajustes de precios.',
      },
      retention: {
        label: 'Agente de Retención',
        description: 'Detecta clientes en riesgo y propone campañas.',
      },
      triage: {
        label: 'Agente de Triage',
        description: 'Clasifica y enruta items entrantes de la bandeja.',
      },
    },
  },

  // ────────────────────────────────────────────────────────────
  // English
  // ────────────────────────────────────────────────────────────
  en: {
    common: {
      loading: 'Loading...',
      save: 'Save',
      cancel: 'Cancel',
      confirm: 'Confirm',
      delete: 'Delete',
      edit: 'Edit',
      create: 'Create',
      connect: 'Connect',
      disconnect: 'Disconnect',
      update: 'Update',
      details: 'Details',
      close: 'Close',
      back: 'Back',
      next: 'Next',
      previous: 'Previous',
      search: 'Search',
      optional: 'optional',
      required: 'required',
      yes: 'Yes',
      no: 'No',
      retry: 'Retry',
      copy: 'Copy',
      copied: 'Copied',
    },

    language: {
      label: 'Language',
      spanish: 'Español',
      english: 'English',
      switched_to: 'Language switched to {{language}}',
    },

    login: {
      title: 'Welcome to Quantro One',
      subtitle: 'Your autonomous operating system for business.',
      sign_in_google: 'Sign in with Google',
      loading: 'Verifying credentials...',
    },

    sidebar: {
      brand: 'Quantro One',
      brand_subtitle: 'BUSINESS OS',
      dashboard: 'Dashboard',
      smart_inbox: 'Smart Inbox',
      schedule: 'Schedule',
      crm: 'CRM',
      onboarding: 'Onboarding',
      content_engine: 'Content Engine',
      automation: 'Automation',
      settings: 'Settings',
      integrations_label: 'INTEGRATIONS',
      system_running: 'System Running',
      synced: 'Synced {{time}}',
    },

    dashboard: {
      title: 'Dashboard',
      subtitle: 'Business operations · Real-time overview',
      live_mode: 'Live Data Mode',
      simulation_mode: 'Simulation Mode Active',
      kpi: {
        team: 'Team Members',
        team_active: '{{count}} active',
        schedule: 'Upcoming Meetings',
        schedule_window: 'next 7 days',
        inbox: 'Inbox Requests',
        inbox_processed: '{{count}} processed',
        crm: 'CRM Contacts Synced',
        crm_new: '{{count}} new this week',
      },
      live_activity: 'Live Activity',
      real_time: 'Real-time',
      ai_suggestions: 'AI Suggestions',
      quick_actions: 'Quick Actions',
      today_meetings: "Today's Meetings",
      no_meetings: 'No meetings scheduled today',
      view_full_calendar: 'View Full Calendar',
      integration_connected: '{{count}} Integration Connected',
      integrations_connected: '{{count}} Integrations Connected',
      integration_sync_status: 'Syncing in real-time',
      manage: 'Manage',
    },

    system_health: {
      title: 'System Health',
      tagline: 'Quantro OS detects and fixes issues before you notice them.',
      status_healthy: 'System Status: Healthy',
      status_repaired: 'System Status: Auto-Repaired',
      status_degraded: 'System Status: Degraded',
      all_operational: 'All systems operational',
      last_check: 'Last check: {{time}}',
      subcopy_healthy:
        'Quantro OS is actively maintaining your integrations. Any inconsistencies are detected and resolved automatically.',
      subcopy_repaired:
        'Quantro OS detected missing components and repaired them automatically.',
      subcopy_degraded:
        'Some components require attention. Quantro OS is working to resolve them.',
      checks: {
        integrations_stable: 'Integrations stable',
        integrations_stable_ok: '{{have}}/{{total}} providers registered',
        integrations_stable_fail: 'Missing providers ({{missing}})',
        data_consistency: 'Data consistency verified',
        data_consistency_ok: 'Business profile present',
        data_consistency_fail: 'Business profile missing',
        no_issues: 'No issues detected',
        no_issues_ok: 'All systems operational',
        no_issues_repairs: '{{count}} auto-repair(s) on last startup',
        issues_detected: 'Issues detected',
      },
      auto_resolved_header: 'Auto-resolved on last startup',
      repair_provider_restored:
        "Missing integration '{{name}}' was restored automatically.",
      repair_metadata_backfilled:
        "Metadata repaired for '{{name}}' ({{fields}}).",
      repair_toast_single: 'System repaired missing integrations automatically',
      repair_toast_multi: 'System repaired {{count}} missing integrations automatically',
    },

    settings: {
      title: 'Settings',
      subtitle: 'Configure your Business OS',
      tabs: {
        integrations: 'Integrations',
        automation: 'Automation',
        business_profile: 'Business Profile',
        workspace: 'Workspace',
      },
      automation: {
        heading: 'Automation Settings',
        description:
          'Configure your automation policies, confidence thresholds, and escalation rules.',
        manage_button: 'Manage Automation Policies',
        overview_title: 'Quick Overview',
        overview_auto: 'Auto-run enabled for high-confidence items',
        overview_manual: 'Manual approval required for medium confidence',
        overview_escalation: 'Escalation triggered for low confidence or conflicts',
      },
      profile: {
        heading: 'Business Profile',
        description: 'Configure your business type and customize system terminology',
        industry_label: 'Industry',
        industry_helper:
          'The system will adapt its language and AI suggestions based on your industry',
        use_case_label: 'Use Case (Optional)',
        use_case_placeholder: 'Describe how you use this Business OS...',
        naming_heading: 'Custom Entity Naming',
        naming_helper:
          'Customize terminology throughout the system. Leave blank to use industry defaults.',
        label_contacts: 'Contacts Label',
        label_team: 'Team Members Label',
        label_meetings: 'Meetings Label',
        label_events: 'Events Label',
        label_services: 'Services/Products Label',
        simulation_heading: 'Simulation Mode',
        simulation_description:
          'Load realistic sample operational data for your selected industry. Perfect for testing workflows, validating automations, and demoing the system before connecting live integrations.',
        simulation_active: 'Active: The system is populated with simulated data',
        save_button: 'Save Business Profile',
        saving: 'Saving...',
        saved_toast: 'Business Profile updated successfully',
        save_failed_toast: 'Failed to update Business Profile',
      },
      workspace: {
        heading: 'Workspace',
        description: 'Workspace settings and team management',
        name_label: 'Workspace Name',
        name_placeholder: 'My Business',
        phase_note:
          'Authentication and multi-tenant workspace features will be available in Phase 6.',
      },
    },

    integrations: {
      groups: {
        ai: 'AI & Intelligence',
        email: 'Email & Calendar',
        crm: 'CRM',
        automation: 'Webhooks & Endpoints',
      },
      status: {
        connected: 'Connected',
        not_connected: 'Not Connected',
        last_sync: 'Last sync: {{time}}',
      },
      actions: {
        save_and_connect: 'Save & Connect',
        connect_google: 'Connect with Google',
        enable_webhooks: 'Enable Webhooks',
        test_connection: 'Test Connection',
        update_config: 'Update Config',
        disconnect: 'Disconnect',
      },
      openai: {
        name: 'OpenAI / LLM Provider',
        description:
          'Powers AI classification, drafting, and auto-execution across your workflows.',
        helper:
          'This workspace is currently powered by the Emergent Universal Key. Add your own key to override it per workspace.',
        api_key: 'API Key',
        default_model: 'Default Model',
      },
      gmail: {
        name: 'Gmail',
        description: 'Sync incoming email into Smart Inbox and let the system draft replies.',
        account: 'Connected Account',
      },
      calendar: {
        name: 'Google Calendar',
        description: 'Two-way sync events, bookings, and availability windows.',
        calendar_id: 'Calendar ID',
      },
      crm: {
        name: 'CRM System',
        description:
          'Bi-directional sync with HubSpot, GoHighLevel, Pipedrive, or any CRM with an API.',
        provider: 'CRM Provider',
        api_key: 'API Key',
        base_url: 'Base URL (optional)',
      },
      webhook: {
        name: 'Inbound Webhooks',
        description:
          'Forward events from any service into Business OS. Use the endpoint below in your external tools.',
        endpoint_label: 'YOUR INBOUND ENDPOINT',
        shared_secret: 'Shared Secret (optional)',
        secret_placeholder: 'Generate a random string',
      },
      toasts: {
        connected: '{{provider}} connected successfully',
        disconnected: '{{provider}} disconnected',
        test_ok: '{{provider}} connection is healthy',
        test_fail: '{{provider}} is not connected',
        load_failed: 'Failed to load integrations',
        connect_failed: 'Failed to connect {{provider}}',
        endpoint_copied: 'Endpoint copied to clipboard',
        copy_failed: 'Copy unavailable in this browser — please select and copy manually',
      },
    },

    smart_inbox: {
      title: 'Smart Inbox',
      subtitle: 'AI classification and automated triage',
      empty_state: 'No inbox items',
      analyze: 'Analyze',
      analyze_all: 'Analyze All',
      approve: 'Approve',
      escalate: 'Escalate',
    },

    // ────────────────────────────────────────────────────
    // Decisions — key pattern for the decision system
    // ────────────────────────────────────────────────────
    decisions: {
      revenue: {
        raise_prices: {
          title: 'Raise prices by {{percent}}%',
          summary:
            'Current demand and margins support a {{percent}}% pricing adjustment.',
          impact: 'Estimated revenue lift of {{lift}}%.',
          action_label: 'Apply price change',
        },
        launch_campaign: {
          title: 'Launch retention campaign',
          summary:
            '{{count}} customers show risk signals — a targeted campaign can win them back.',
          action_label: 'Launch campaign',
        },
      },
      action_center: {
        no_pending: 'No pending decisions',
        pending_count: '{{count}} pending decision',
        pending_count_plural: '{{count}} pending decisions',
      },
    },

    // ────────────────────────────────────────────────────
    // Agents — labels and descriptions
    // ────────────────────────────────────────────────────
    agents: {
      pricing: {
        label: 'Pricing Agent',
        description: 'Monitors margins and recommends price adjustments.',
      },
      retention: {
        label: 'Retention Agent',
        description: 'Detects at-risk customers and proposes campaigns.',
      },
      triage: {
        label: 'Triage Agent',
        description: 'Classifies and routes incoming inbox items.',
      },
    },
  },
};

export const SUPPORTED_LANGUAGES = [
  { code: 'es', label: 'Español', englishLabel: 'Spanish' },
  { code: 'en', label: 'English', englishLabel: 'English' },
];

export const DEFAULT_LANGUAGE = 'es';
export const FALLBACK_LANGUAGE = 'en';
