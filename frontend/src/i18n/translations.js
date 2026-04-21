/**
 * Quantro Flow — Single source of truth for all user-facing copy.
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

    simulation: {
      label: 'Modo Simulación',
      badge_simulation: 'SIMULACIÓN',
      badge_live: 'EN VIVO',
      tooltip_on: 'Estás viendo datos de muestra. Desactiva para usar tus integraciones reales.',
      tooltip_off: 'Usando datos reales de tus integraciones conectadas.',
      banner_title: 'Modo Simulación',
      banner_description_on:
        'Estás explorando Quantro Flow con un conjunto de datos de muestra realista. Tus integraciones reales no están en uso todavía.',
      banner_description_off:
        'Quantro Flow está operando con tus integraciones reales y datos en vivo.',
      confirm_title: 'Cambiar a Modo Live',
      confirm_body:
        'Vas a cambiar a Modo Live. Tus integraciones reales y los datos del workspace serán utilizados. Los datos de muestra se ocultarán.',
      confirm_go_live: 'Activar Live',
      confirm_stay: 'Permanecer en Simulación',
      toast_on: 'Modo Simulación activado',
      toast_off: 'Modo Live activado',
      toast_failed: 'No se pudo cambiar el modo',
    },

    login: {
      title: 'Bienvenido a Quantro Flow',
      subtitle: 'Tu sistema operativo autónomo para el negocio.',
      sign_in_google: 'Iniciar sesión con Google',
      loading: 'Verificando credenciales...',
    },

    sidebar: {
      brand: 'Quantro Flow',
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
      ai_engine: 'Motor IA',
      running: 'Operando',
      active: 'Activo',
      no_recent_activity: 'Sin actividad reciente',
      activity_hint: 'La actividad aparecerá aquí cuando el sistema procese items',
      no_suggestions: 'Sin sugerencias aún',
      integration_connected: '{{count}} Integración Conectada',
      integrations_connected: '{{count}} Integraciones Conectadas',
      integration_sync_status: 'Sincronización en tiempo real',
      manage: 'Gestionar',
    },

    system_health: {
      title: 'Estado del Sistema',
      tagline: 'Quantro Flow detecta y resuelve problemas antes de que los notes.',
      status_healthy: 'Sistema Saludable',
      status_repaired: 'Sistema Auto-Reparado',
      status_degraded: 'Sistema Degradado',
      all_operational: 'Todos los sistemas operativos',
      last_check: 'Última verificación: {{time}}',
      subcopy_healthy:
        'Quantro Flow mantiene activamente tus integraciones. Las inconsistencias se detectan y resuelven automáticamente.',
      subcopy_repaired:
        'Quantro Flow detectó componentes faltantes y los reparó automáticamente.',
      subcopy_degraded:
        'Algunos componentes requieren atención. Quantro Flow está trabajando en resolverlos.',
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
      empty_hint: 'Tus solicitudes entrantes aparecerán aquí',
      analyze: 'Analizar',
      analyze_all: 'Analizar todo',
      approve: 'Aprobar',
      escalate: 'Escalar',
      filters: {
        all: 'Todas',
        unread: 'Sin leer',
        needs_review: 'Requieren revisión',
        auto_actioned: 'Auto-ejecutadas',
        escalated: 'Escaladas',
        processed: 'Procesadas',
      },
      intent: {
        booking: 'Reserva',
        onboarding: 'Onboarding',
        follow_up: 'Seguimiento',
        inquiry: 'Consulta',
        escalation: 'Escalamiento',
        spam: 'Spam',
        needs_review: 'Requiere revisión',
      },
      status: {
        new: 'Nueva',
        analyzed: 'Analizada',
        needs_review: 'Requiere revisión',
        auto_actioned: 'Auto-ejecutada',
        escalated: 'Escalada',
        processed: 'Procesada',
      },
      confidence_label: 'Confianza',
      suggested_action: 'Acción sugerida',
      execution_trail: 'Registro de Ejecución',
      analyzing: 'Analizando...',
      batch_selected: '{{count}} seleccionada(s)',
      batch_analyze: 'Analizar seleccionadas',
      clear_selection: 'Limpiar selección',
      process_inbox: 'Procesar Bandeja',
      view_details: 'Ver detalles',
      mark_processed: 'Marcar procesada',
      escalation_reason: 'Razón del escalamiento',
      toasts: {
        analyzed: 'Item analizado correctamente',
        analyze_failed: 'Error al analizar',
        batch_done: '{{count}} items analizados',
        batch_failed: 'Error en análisis por lote',
        marked_processed: 'Item marcado como procesado',
        mark_failed: 'Error al marcar item',
        escalated: 'Item escalado',
      },
    },

    crm: {
      title: 'CRM',
      subtitle: 'Contactos y relaciones',
      empty_state: 'Sin contactos aún',
      empty_hint: 'Tus contactos sincronizados aparecerán aquí',
      search_placeholder: 'Buscar contactos...',
      add_contact: 'Añadir Contacto',
      new_contact: 'Nuevo Contacto',
      table: {
        name: 'Nombre',
        email: 'Correo',
        phone: 'Teléfono',
        status: 'Estado',
        source: 'Origen',
        created: 'Creado',
        last_contact: 'Último contacto',
        actions: 'Acciones',
      },
      status: {
        lead: 'Lead',
        contacted: 'Contactado',
        qualified: 'Calificado',
        customer: 'Cliente',
        churned: 'Inactivo',
        active: 'Activo',
      },
      details: {
        title: 'Detalles del Contacto',
        edit: 'Editar',
        delete: 'Eliminar',
        activities: 'Actividades',
        notes: 'Notas',
      },
      form: {
        name_label: 'Nombre completo',
        email_label: 'Correo electrónico',
        phone_label: 'Teléfono',
        status_label: 'Estado',
        source_label: 'Origen',
        notes_label: 'Notas',
      },
      toasts: {
        created: 'Contacto creado',
        updated: 'Contacto actualizado',
        deleted: 'Contacto eliminado',
        save_failed: 'Error al guardar contacto',
      },
    },

    schedule: {
      title: 'Agenda',
      subtitle: 'Reuniones y eventos',
      empty_state: 'Sin eventos programados',
      empty_hint: 'Tus próximas reuniones aparecerán aquí',
      add_event: 'Añadir Evento',
      today: 'Hoy',
      tomorrow: 'Mañana',
      this_week: 'Esta semana',
      upcoming: 'Próximas',
      past: 'Pasadas',
      duration: '{{minutes}} min',
      attendees: '{{count}} asistentes',
      with: 'con {{person}}',
      status: {
        scheduled: 'Programada',
        completed: 'Completada',
        cancelled: 'Cancelada',
        no_show: 'No asistió',
      },
      form: {
        title_label: 'Título',
        date_label: 'Fecha',
        time_label: 'Hora',
        duration_label: 'Duración (minutos)',
        location_label: 'Ubicación',
        attendees_label: 'Asistentes',
        notes_label: 'Notas',
      },
      toasts: {
        created: 'Evento creado',
        updated: 'Evento actualizado',
        cancelled: 'Evento cancelado',
        save_failed: 'Error al guardar evento',
      },
    },

    content_engine: {
      title: 'Motor de Contenido',
      subtitle: 'Generación de contenido con IA',
      tabs: {
        generate: 'Generar',
        templates: 'Plantillas',
        history: 'Historial',
      },
      generate: {
        topic_label: 'Tema',
        topic_placeholder: 'Ej: lanzamiento de nuevo producto...',
        tone_label: 'Tono',
        type_label: 'Tipo de contenido',
        generate_button: 'Generar Contenido',
        regenerate: 'Regenerar',
        copy_button: 'Copiar',
        generating: 'Generando contenido...',
        social_post: 'Post Social',
        email_draft: 'Borrador de Correo',
        hashtags: 'Hashtags',
        subject: 'Asunto',
        body: 'Cuerpo',
        call_to_action: 'Call to Action',
      },
      tone: {
        professional: 'Profesional',
        friendly: 'Amigable',
        warm: 'Cálido',
        urgent: 'Urgente',
        playful: 'Divertido',
      },
      templates: {
        heading: 'Plantillas',
        new_template: 'Nueva Plantilla',
        edit: 'Editar',
        delete: 'Eliminar',
        use: 'Usar',
        empty: 'Sin plantillas aún',
        variables: 'Variables',
        category_label: 'Categoría',
        type_label: 'Tipo',
        name_label: 'Nombre',
        content_label: 'Contenido',
        save: 'Guardar Plantilla',
      },
      history: {
        heading: 'Historial de Generación',
        empty: 'Sin generaciones aún',
        empty_hint: 'Tu contenido generado aparecerá aquí',
      },
      toasts: {
        generated: 'Contenido generado',
        generate_failed: 'Error al generar contenido',
        copied: 'Copiado al portapapeles',
        copy_failed: 'Error al copiar',
        template_saved: 'Plantilla guardada',
        template_deleted: 'Plantilla eliminada',
        save_failed: 'Error al guardar',
      },
    },

    onboarding: {
      title: 'Onboarding',
      subtitle: 'Flujos de incorporación de clientes',
      empty_state: 'Sin flujos de onboarding activos',
      empty_hint: 'Los onboardings creados aparecerán aquí',
      new_flow: 'Nuevo Flujo',
      progress: 'Progreso',
      steps: 'Pasos',
      step_completed: 'Completado',
      step_pending: 'Pendiente',
      step_in_progress: 'En progreso',
      start: 'Iniciar',
      complete: 'Completar',
      resume: 'Continuar',
      cancel: 'Cancelar',
      form: {
        client_label: 'Cliente',
        type_label: 'Tipo de onboarding',
        start_date_label: 'Fecha de inicio',
      },
      toasts: {
        created: 'Flujo de onboarding creado',
        updated: 'Flujo actualizado',
        completed: 'Flujo completado',
        step_completed: 'Paso completado',
        save_failed: 'Error al guardar',
      },
    },

    automation: {
      title: 'Políticas de Automatización',
      subtitle: 'Reglas de auto-ejecución y escalamiento',
      tabs: {
        policies: 'Políticas',
        escalations: 'Escalamientos',
      },
      policies: {
        heading: 'Políticas de Confianza',
        description:
          'Define qué ocurre según el nivel de confianza del análisis IA.',
        high_confidence: 'Alta Confianza',
        medium_confidence: 'Confianza Media',
        low_confidence: 'Baja Confianza',
        threshold_label: 'Umbral',
        action_label: 'Acción',
        enabled_label: 'Habilitada',
        new_policy: 'Nueva Política',
        save: 'Guardar Política',
        action_auto: 'Auto-ejecutar',
        action_manual: 'Aprobación manual',
        action_review: 'Requiere revisión',
        action_escalate: 'Escalar',
      },
      escalations: {
        heading: 'Reglas de Escalamiento',
        description:
          'Condiciones avanzadas que fuerzan revisión o notificación del equipo.',
        new_rule: 'Nueva Regla',
        rule_type: 'Tipo de Regla',
        condition: 'Condición',
        priority: 'Prioridad',
        notify_team: 'Notificar al equipo',
        types: {
          intent: 'Intención',
          keyword: 'Palabra clave',
          calendar_conflict: 'Conflicto de calendario',
          incomplete_entities: 'Entidades incompletas',
          urgency: 'Urgencia',
          contact_type: 'Tipo de contacto',
        },
        priority_levels: {
          low: 'Baja',
          medium: 'Media',
          high: 'Alta',
          critical: 'Crítica',
        },
      },
      toasts: {
        policy_saved: 'Política guardada',
        policy_deleted: 'Política eliminada',
        rule_saved: 'Regla guardada',
        rule_deleted: 'Regla eliminada',
        save_failed: 'Error al guardar',
      },
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

    simulation: {
      label: 'Simulation Mode',
      badge_simulation: 'SIMULATION',
      badge_live: 'LIVE',
      tooltip_on: 'You are viewing sample data. Turn off to use your real integrations.',
      tooltip_off: 'Using real data from your connected integrations.',
      banner_title: 'Simulation Mode',
      banner_description_on:
        'You are exploring Quantro Flow with a realistic sample dataset. Your real integrations are not being used yet.',
      banner_description_off:
        'Quantro Flow is operating with your real integrations and live data.',
      confirm_title: 'Switch to Live Mode',
      confirm_body:
        "You're switching to Live Mode. Your real integrations and workspace data will be used. Sample data will be hidden.",
      confirm_go_live: 'Go Live',
      confirm_stay: 'Stay in Simulation',
      toast_on: 'Simulation Mode activated',
      toast_off: 'Live Mode activated',
      toast_failed: 'Failed to switch mode',
    },

    login: {
      title: 'Welcome to Quantro Flow',
      subtitle: 'Your autonomous operating system for business.',
      sign_in_google: 'Sign in with Google',
      loading: 'Verifying credentials...',
    },

    sidebar: {
      brand: 'Quantro Flow',
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
      ai_engine: 'AI Engine',
      running: 'Running',
      active: 'Active',
      no_recent_activity: 'No recent activity',
      activity_hint: 'Activity will appear here as your system processes items',
      no_suggestions: 'No suggestions yet',
      integration_connected: '{{count}} Integration Connected',
      integrations_connected: '{{count}} Integrations Connected',
      integration_sync_status: 'Syncing in real-time',
      manage: 'Manage',
    },

    system_health: {
      title: 'System Health',
      tagline: 'Quantro Flow detects and fixes issues before you notice them.',
      status_healthy: 'System Status: Healthy',
      status_repaired: 'System Status: Auto-Repaired',
      status_degraded: 'System Status: Degraded',
      all_operational: 'All systems operational',
      last_check: 'Last check: {{time}}',
      subcopy_healthy:
        'Quantro Flow is actively maintaining your integrations. Any inconsistencies are detected and resolved automatically.',
      subcopy_repaired:
        'Quantro Flow detected missing components and repaired them automatically.',
      subcopy_degraded:
        'Some components require attention. Quantro Flow is working to resolve them.',
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
      empty_hint: 'Your incoming requests will appear here',
      analyze: 'Analyze',
      analyze_all: 'Analyze All',
      approve: 'Approve',
      escalate: 'Escalate',
      filters: {
        all: 'All',
        unread: 'Unread',
        needs_review: 'Needs review',
        auto_actioned: 'Auto-actioned',
        escalated: 'Escalated',
        processed: 'Processed',
      },
      intent: {
        booking: 'Booking',
        onboarding: 'Onboarding',
        follow_up: 'Follow-up',
        inquiry: 'Inquiry',
        escalation: 'Escalation',
        spam: 'Spam',
        needs_review: 'Needs review',
      },
      status: {
        new: 'New',
        analyzed: 'Analyzed',
        needs_review: 'Needs review',
        auto_actioned: 'Auto-actioned',
        escalated: 'Escalated',
        processed: 'Processed',
      },
      confidence_label: 'Confidence',
      suggested_action: 'Suggested action',
      execution_trail: 'Execution Trail',
      analyzing: 'Analyzing...',
      batch_selected: '{{count}} selected',
      batch_analyze: 'Analyze selected',
      clear_selection: 'Clear selection',
      process_inbox: 'Process Inbox',
      view_details: 'View details',
      mark_processed: 'Mark processed',
      escalation_reason: 'Escalation reason',
      toasts: {
        analyzed: 'Item analyzed successfully',
        analyze_failed: 'Failed to analyze',
        batch_done: '{{count}} items analyzed',
        batch_failed: 'Batch analysis failed',
        marked_processed: 'Item marked as processed',
        mark_failed: 'Failed to mark item',
        escalated: 'Item escalated',
      },
    },

    crm: {
      title: 'CRM',
      subtitle: 'Contacts and relationships',
      empty_state: 'No contacts yet',
      empty_hint: 'Your synced contacts will appear here',
      search_placeholder: 'Search contacts...',
      add_contact: 'Add Contact',
      new_contact: 'New Contact',
      table: {
        name: 'Name',
        email: 'Email',
        phone: 'Phone',
        status: 'Status',
        source: 'Source',
        created: 'Created',
        last_contact: 'Last contact',
        actions: 'Actions',
      },
      status: {
        lead: 'Lead',
        contacted: 'Contacted',
        qualified: 'Qualified',
        customer: 'Customer',
        churned: 'Churned',
        active: 'Active',
      },
      details: {
        title: 'Contact Details',
        edit: 'Edit',
        delete: 'Delete',
        activities: 'Activities',
        notes: 'Notes',
      },
      form: {
        name_label: 'Full name',
        email_label: 'Email',
        phone_label: 'Phone',
        status_label: 'Status',
        source_label: 'Source',
        notes_label: 'Notes',
      },
      toasts: {
        created: 'Contact created',
        updated: 'Contact updated',
        deleted: 'Contact deleted',
        save_failed: 'Failed to save contact',
      },
    },

    schedule: {
      title: 'Schedule',
      subtitle: 'Meetings and events',
      empty_state: 'No events scheduled',
      empty_hint: 'Your upcoming meetings will appear here',
      add_event: 'Add Event',
      today: 'Today',
      tomorrow: 'Tomorrow',
      this_week: 'This week',
      upcoming: 'Upcoming',
      past: 'Past',
      duration: '{{minutes}} min',
      attendees: '{{count}} attendees',
      with: 'with {{person}}',
      status: {
        scheduled: 'Scheduled',
        completed: 'Completed',
        cancelled: 'Cancelled',
        no_show: 'No show',
      },
      form: {
        title_label: 'Title',
        date_label: 'Date',
        time_label: 'Time',
        duration_label: 'Duration (minutes)',
        location_label: 'Location',
        attendees_label: 'Attendees',
        notes_label: 'Notes',
      },
      toasts: {
        created: 'Event created',
        updated: 'Event updated',
        cancelled: 'Event cancelled',
        save_failed: 'Failed to save event',
      },
    },

    content_engine: {
      title: 'Content Engine',
      subtitle: 'AI-powered content generation',
      tabs: {
        generate: 'Generate',
        templates: 'Templates',
        history: 'History',
      },
      generate: {
        topic_label: 'Topic',
        topic_placeholder: 'E.g. new product launch...',
        tone_label: 'Tone',
        type_label: 'Content type',
        generate_button: 'Generate Content',
        regenerate: 'Regenerate',
        copy_button: 'Copy',
        generating: 'Generating content...',
        social_post: 'Social Post',
        email_draft: 'Email Draft',
        hashtags: 'Hashtags',
        subject: 'Subject',
        body: 'Body',
        call_to_action: 'Call to Action',
      },
      tone: {
        professional: 'Professional',
        friendly: 'Friendly',
        warm: 'Warm',
        urgent: 'Urgent',
        playful: 'Playful',
      },
      templates: {
        heading: 'Templates',
        new_template: 'New Template',
        edit: 'Edit',
        delete: 'Delete',
        use: 'Use',
        empty: 'No templates yet',
        variables: 'Variables',
        category_label: 'Category',
        type_label: 'Type',
        name_label: 'Name',
        content_label: 'Content',
        save: 'Save Template',
      },
      history: {
        heading: 'Generation History',
        empty: 'No generations yet',
        empty_hint: 'Your generated content will appear here',
      },
      toasts: {
        generated: 'Content generated',
        generate_failed: 'Failed to generate content',
        copied: 'Copied to clipboard',
        copy_failed: 'Failed to copy',
        template_saved: 'Template saved',
        template_deleted: 'Template deleted',
        save_failed: 'Failed to save',
      },
    },

    onboarding: {
      title: 'Onboarding',
      subtitle: 'Client onboarding flows',
      empty_state: 'No active onboarding flows',
      empty_hint: 'Onboarding flows you create will appear here',
      new_flow: 'New Flow',
      progress: 'Progress',
      steps: 'Steps',
      step_completed: 'Completed',
      step_pending: 'Pending',
      step_in_progress: 'In progress',
      start: 'Start',
      complete: 'Complete',
      resume: 'Resume',
      cancel: 'Cancel',
      form: {
        client_label: 'Client',
        type_label: 'Onboarding type',
        start_date_label: 'Start date',
      },
      toasts: {
        created: 'Onboarding flow created',
        updated: 'Flow updated',
        completed: 'Flow completed',
        step_completed: 'Step completed',
        save_failed: 'Failed to save',
      },
    },

    automation: {
      title: 'Automation Policies',
      subtitle: 'Auto-execution and escalation rules',
      tabs: {
        policies: 'Policies',
        escalations: 'Escalations',
      },
      policies: {
        heading: 'Confidence Policies',
        description: 'Define what happens based on the confidence level of AI analysis.',
        high_confidence: 'High Confidence',
        medium_confidence: 'Medium Confidence',
        low_confidence: 'Low Confidence',
        threshold_label: 'Threshold',
        action_label: 'Action',
        enabled_label: 'Enabled',
        new_policy: 'New Policy',
        save: 'Save Policy',
        action_auto: 'Auto-execute',
        action_manual: 'Manual approval',
        action_review: 'Needs review',
        action_escalate: 'Escalate',
      },
      escalations: {
        heading: 'Escalation Rules',
        description: 'Advanced conditions that force review or team notification.',
        new_rule: 'New Rule',
        rule_type: 'Rule Type',
        condition: 'Condition',
        priority: 'Priority',
        notify_team: 'Notify team',
        types: {
          intent: 'Intent',
          keyword: 'Keyword',
          calendar_conflict: 'Calendar conflict',
          incomplete_entities: 'Incomplete entities',
          urgency: 'Urgency',
          contact_type: 'Contact type',
        },
        priority_levels: {
          low: 'Low',
          medium: 'Medium',
          high: 'High',
          critical: 'Critical',
        },
      },
      toasts: {
        policy_saved: 'Policy saved',
        policy_deleted: 'Policy deleted',
        rule_saved: 'Rule saved',
        rule_deleted: 'Rule deleted',
        save_failed: 'Failed to save',
      },
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
