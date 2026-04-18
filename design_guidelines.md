{
  "product": {
    "name": "Quantro One | Realty OS",
    "positioning": "Premium internal operating system for real estate teams — unified, connected, always running.",
    "brand_attributes": ["intelligent", "calm", "powerful", "system-driven", "minimal", "futuristic"],
    "mode": "dark-only",
    "layout_mandates": ["left sidebar navigation", "no transparent backgrounds", "real-time feeling via polling + subtle animations"],
    "testing_requirement": {
      "data_testid": "All interactive and key informational elements MUST include data-testid in kebab-case describing role (not appearance)."
    }
  },

  "visual_personality": {
    "north_star": "Feels like an OS: the system runs in the background; user observes, approves, and steers.",
    "reference_fusion": [
      "Linear: crisp hierarchy + sidebar density + subtle motion",
      "Apple: calm materials + precise typography + restrained glow",
      "Stripe: token-driven color system + status semantics"
    ],
    "do_not": [
      "No light mode toggle",
      "No centered app container",
      "No transparent/glass backgrounds (solid dark surfaces only)",
      "No loud gradients; gradients limited to small decorative areas (<=20% viewport)"
    ]
  },

  "design_tokens": {
    "css_custom_properties": {
      "notes": "Implement by overriding :root and .dark tokens in /app/frontend/src/index.css. Keep dark-only by applying .dark on <html> or <body> at app boot.",
      "colors": {
        "background": "222 22% 6%",
        "foreground": "210 20% 96%",

        "surface_0": "222 22% 6%",
        "surface_1": "222 18% 9%",
        "surface_2": "222 16% 12%",
        "surface_3": "222 14% 16%",

        "card": "222 18% 9%",
        "card_foreground": "210 20% 96%",
        "popover": "222 18% 9%",
        "popover_foreground": "210 20% 96%",

        "border": "222 12% 18%",
        "input": "222 12% 18%",
        "ring": "186 92% 42%",

        "primary": "186 92% 42%",
        "primary_foreground": "222 22% 6%",

        "secondary": "222 14% 16%",
        "secondary_foreground": "210 20% 96%",

        "muted": "222 14% 14%",
        "muted_foreground": "215 14% 70%",

        "accent": "199 88% 52%",
        "accent_foreground": "222 22% 6%",

        "destructive": "0 72% 52%",
        "destructive_foreground": "210 20% 96%",

        "success": "152 62% 44%",
        "warning": "38 92% 56%",
        "info": "199 88% 52%",
        "critical": "0 72% 52%",

        "sidebar": "222 22% 6%",
        "sidebar_foreground": "210 20% 92%",
        "sidebar_active": "222 16% 12%",
        "sidebar_border": "222 12% 14%",

        "status_running": "152 62% 44%",
        "status_syncing": "199 88% 52%",
        "status_degraded": "38 92% 56%",
        "status_down": "0 72% 52%"
      },
      "radii": {
        "radius_sm": "10px",
        "radius_md": "14px",
        "radius_lg": "18px"
      },
      "shadows": {
        "shadow_1": "0 1px 0 hsl(0 0% 100% / 0.04), 0 10px 30px hsl(0 0% 0% / 0.35)",
        "shadow_2": "0 1px 0 hsl(0 0% 100% / 0.06), 0 18px 50px hsl(0 0% 0% / 0.45)"
      },
      "spacing": {
        "page_padding_x": "px-4 sm:px-6 lg:px-8",
        "page_padding_y": "py-5 sm:py-6",
        "section_gap": "gap-4 sm:gap-6",
        "card_padding": "p-4 sm:p-5"
      }
    },

    "tailwind_usage_notes": {
      "backgrounds": [
        "Use bg-background for app shell",
        "Use bg-card for cards",
        "Use bg-[hsl(var(--surface_2))] for elevated panels"
      ],
      "borders": ["Prefer border-border with 1px borders; avoid heavy outlines"],
      "focus": ["Use focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] focus-visible:ring-offset-0"]
    }
  },

  "typography": {
    "font_pairing": {
      "display": {
        "name": "Space Grotesk",
        "google_fonts": "https://fonts.google.com/specimen/Space+Grotesk",
        "usage": "H1/H2, KPI numbers, page titles"
      },
      "body": {
        "name": "IBM Plex Sans",
        "google_fonts": "https://fonts.google.com/specimen/IBM+Plex+Sans",
        "usage": "Body, tables, forms, helper text"
      },
      "mono": {
        "name": "IBM Plex Mono",
        "google_fonts": "https://fonts.google.com/specimen/IBM+Plex+Mono",
        "usage": "IDs, sync logs, timestamps, system events"
      }
    },
    "scale": {
      "h1": "text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight",
      "h2": "text-base md:text-lg font-medium text-muted-foreground",
      "page_title": "text-xl sm:text-2xl font-semibold tracking-tight",
      "section_title": "text-sm font-semibold tracking-wide text-foreground/90",
      "body": "text-sm sm:text-base text-foreground/90",
      "small": "text-xs text-muted-foreground",
      "kpi_value": "text-2xl sm:text-3xl font-semibold tabular-nums",
      "kpi_delta": "text-xs font-medium tabular-nums"
    },
    "typesetting_rules": [
      "Use tabular-nums for metrics and timestamps.",
      "Keep line-height relaxed in reading areas: leading-6 for body blocks.",
      "Avoid all-caps except tiny labels (text-xs + tracking-wide)."
    ]
  },

  "grid_and_layout": {
    "app_shell": {
      "desktop": "Sidebar (w-64) + main content (flex-1) + optional right rail (w-[360px]) for Live Activity Feed.",
      "mobile": "Sidebar collapses into Sheet/Drawer; top bar shows page title + global status + quick actions.",
      "main_container": "max-w-[1400px] w-full (do NOT center text; only constrain width)."
    },
    "dashboard_layout": {
      "top_row": "Metrics bento grid (2 cols mobile, 4 cols lg)",
      "middle": "Today’s Schedule (left) + AI Suggestions (right)",
      "right_rail": "Live Activity Feed + System Status panel"
    },
    "spacing_principle": "Use 2–3x more whitespace than typical dashboards; rely on separators and subtle borders instead of heavy shadows."
  },

  "color_system_usage": {
    "semantic_mapping": {
      "running": "success",
      "syncing": "info",
      "needs_attention": "warning",
      "failed": "critical"
    },
    "intent_badges_for_inbox": {
      "schedule_request": {"label": "Schedule", "tone": "info"},
      "lead_inquiry": {"label": "Lead", "tone": "accent"},
      "doc_request": {"label": "Docs", "tone": "secondary"},
      "complaint": {"label": "Risk", "tone": "warning"},
      "spam": {"label": "Spam", "tone": "destructive"}
    },
    "gradient_policy": {
      "allowed": [
        "Only as decorative background wash in hero/top header area (<=20% viewport)",
        "Only mild cool gradients (teal/cyan/blue-gray)"
      ],
      "recommended_gradients": [
        "radial-gradient(800px circle at 20% 0%, hsl(186 92% 42% / 0.18), transparent 55%)",
        "radial-gradient(700px circle at 80% 10%, hsl(199 88% 52% / 0.14), transparent 60%)"
      ],
      "prohibited": [
        "purple/pink combos",
        "dark saturated gradients",
        "gradients on cards, tables, reading areas",
        "gradients on small UI elements (<100px)"
      ]
    }
  },

  "components": {
    "component_path": {
      "shadcn_primary": "/app/frontend/src/components/ui",
      "use_components": [
        {"name": "button", "path": "src/components/ui/button.jsx"},
        {"name": "badge", "path": "src/components/ui/badge.jsx"},
        {"name": "card", "path": "src/components/ui/card.jsx"},
        {"name": "tabs", "path": "src/components/ui/tabs.jsx"},
        {"name": "table", "path": "src/components/ui/table.jsx"},
        {"name": "dialog", "path": "src/components/ui/dialog.jsx"},
        {"name": "sheet", "path": "src/components/ui/sheet.jsx"},
        {"name": "drawer", "path": "src/components/ui/drawer.jsx"},
        {"name": "scroll-area", "path": "src/components/ui/scroll-area.jsx"},
        {"name": "separator", "path": "src/components/ui/separator.jsx"},
        {"name": "tooltip", "path": "src/components/ui/tooltip.jsx"},
        {"name": "dropdown-menu", "path": "src/components/ui/dropdown-menu.jsx"},
        {"name": "command", "path": "src/components/ui/command.jsx"},
        {"name": "calendar", "path": "src/components/ui/calendar.jsx"},
        {"name": "progress", "path": "src/components/ui/progress.jsx"},
        {"name": "sonner", "path": "src/components/ui/sonner.jsx"},
        {"name": "skeleton", "path": "src/components/ui/skeleton.jsx"}
      ]
    },

    "navigation": {
      "sidebar": {
        "structure": [
          "Top: Workspace switcher (DropdownMenu) + global search (Command)",
          "Middle: Nav items with icons + unread dots",
          "Bottom: System status capsule + user menu"
        ],
        "nav_item_classes": "group flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-[hsl(var(--sidebar_active))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]",
        "active_state": "bg-[hsl(var(--sidebar_active))] text-foreground",
        "data_testids": {
          "sidebar": "app-sidebar",
          "nav_dashboard": "nav-dashboard",
          "nav_inbox": "nav-smart-inbox",
          "nav_schedule": "nav-schedule",
          "nav_crm": "nav-crm",
          "nav_onboarding": "nav-onboarding",
          "nav_content_engine": "nav-content-engine",
          "global_search": "global-command-search"
        }
      },
      "topbar_mobile": {
        "use": "Sheet for sidebar; keep a compact top bar with page title + status dot + quick action button",
        "data_testids": {
          "mobile_menu_button": "mobile-sidebar-open-button",
          "quick_action": "topbar-quick-action-button"
        }
      }
    },

    "dashboard": {
      "metrics_cards": {
        "component": "Card",
        "layout": "grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4",
        "card_classes": "rounded-[var(--radius_md)] border border-border bg-card p-4 sm:p-5",
        "content": ["label", "value", "delta badge", "sparkline (optional)", "mini status"],
        "data_testids": {
          "kpi_agents": "kpi-agents",
          "kpi_meetings": "kpi-meetings",
          "kpi_inbox": "kpi-inbox",
          "kpi_sync_health": "kpi-sync-health"
        }
      },
      "live_activity_feed": {
        "component": "ScrollArea + Card rows",
        "row_pattern": "Left: icon/status dot; Middle: event text; Right: timestamp (mono)",
        "new_item_animation": "Framer Motion: initial {opacity:0, y:6} animate {opacity:1, y:0} transition {duration:0.18, ease:'easeOut'}",
        "data_testids": {
          "activity_feed": "live-activity-feed",
          "activity_item": "activity-feed-item"
        }
      },
      "system_status": {
        "pattern": "Status capsule with pulsing dot + label + last sync time",
        "dot_classes": {
          "running": "bg-[hsl(var(--status_running))]",
          "syncing": "bg-[hsl(var(--status_syncing))]",
          "degraded": "bg-[hsl(var(--status_degraded))]",
          "down": "bg-[hsl(var(--status_down))]"
        },
        "pulse": "Use motion-safe:animate-pulse on dot only (not whole row)",
        "data_testids": {
          "system-status": "system-status",
          "system-status-last-sync": "system-status-last-sync"
        }
      }
    },

    "smart_inbox": {
      "layout": "Two-pane: left list (w-full lg:w-[420px]) + right detail (flex-1). On mobile: Tabs (List/Detail).",
      "list": {
        "component": "ScrollArea + Button/Collapsible rows",
        "row_classes": "w-full text-left rounded-md border border-border bg-[hsl(var(--surface_1))] px-3 py-3 hover:bg-[hsl(var(--surface_2))]",
        "intent_badge": "Badge variant=secondary with custom tones via className",
        "data_testids": {
          "inbox-list": "smart-inbox-list",
          "inbox-item": "smart-inbox-item",
          "inbox-filter": "smart-inbox-filter"
        }
      },
      "detail": {
        "component": "Card + Tabs (Summary / Audit Trail / Related CRM)",
        "primary_actions": ["Approve", "Decline", "Schedule"],
        "audit_trail": "Use Separator between events; timestamps in mono",
        "data_testids": {
          "inbox-detail": "smart-inbox-detail",
          "approve": "smart-inbox-approve-button",
          "decline": "smart-inbox-decline-button",
          "schedule": "smart-inbox-schedule-button"
        }
      }
    },

    "schedule": {
      "calendar": {
        "component": "shadcn Calendar",
        "views": ["Agenda list (default)", "Day detail panel"],
        "create_event": "Dialog with form inputs; include availability preview",
        "data_testids": {
          "schedule-calendar": "schedule-calendar",
          "create-event": "schedule-create-event-button",
          "event-modal": "schedule-event-dialog"
        }
      }
    },

    "crm": {
      "contacts_table": {
        "component": "Table",
        "pattern": "Sticky header + row hover + right-side profile panel",
        "sync_status": "Badge + small dot; show 'Last synced' in mono",
        "data_testids": {
          "crm-contacts-table": "crm-contacts-table",
          "crm-contact-row": "crm-contact-row",
          "crm-contact-profile": "crm-contact-profile"
        }
      },
      "activity_timeline": {
        "pattern": "Vertical timeline with left rail dots + event cards",
        "data_testids": {
          "crm-activity-timeline": "crm-activity-timeline",
          "crm-activity-item": "crm-activity-item"
        }
      }
    },

    "onboarding": {
      "tracker": {
        "component": "Progress + Checkbox + Collapsible",
        "pattern": "Agent list with progress bar; expand row to show checklist",
        "data_testids": {
          "onboarding-agent-list": "onboarding-agent-list",
          "onboarding-agent-row": "onboarding-agent-row",
          "onboarding-progress": "onboarding-progress"
        }
      }
    },

    "content_engine": {
      "prompt_interface": {
        "component": "Textarea + Tabs + Button",
        "pattern": "Left: prompt + tone controls; Right: generated output preview",
        "library": "Generated drafts grid with filters",
        "data_testids": {
          "content-prompt": "content-engine-prompt-textarea",
          "generate": "content-engine-generate-button",
          "drafts": "content-engine-drafts-grid",
          "draft-item": "content-engine-draft-item"
        }
      }
    }
  },

  "motion_and_microinteractions": {
    "principles": [
      "Motion should imply background automation: subtle, continuous, never distracting.",
      "Prefer opacity/translate micro-moves; avoid large scaling.",
      "Respect prefers-reduced-motion (wrap with motion-safe utilities)."
    ],
    "recommended_library": {
      "name": "framer-motion",
      "install": "npm i framer-motion",
      "usage": [
        "Animate activity feed insertions",
        "Sidebar active indicator slide",
        "Dialog/Sheet entrance easing"
      ]
    },
    "interaction_specs": {
      "buttons": {
        "hover": "hover:bg-[hsl(var(--surface_3))] (secondary) or hover:brightness-110 (primary)",
        "press": "active:scale-[0.98] transition-[transform,background-color,box-shadow] duration-150",
        "focus": "focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))]"
      },
      "rows": {
        "hover": "hover:bg-[hsl(var(--surface_2))]",
        "selected": "bg-[hsl(var(--surface_2))] border-[hsl(var(--ring))]/30"
      },
      "status_dot": {
        "syncing": "animate-pulse (dot only)",
        "running": "subtle glow via shadow-[0_0_0_3px_hsl(var(--status_running)/0.12)]"
      }
    }
  },

  "data_visualization": {
    "library": {
      "name": "recharts",
      "install": "npm i recharts",
      "use_cases": ["KPI sparklines", "inbox volume over time", "onboarding completion trend"],
      "styling": "Use stroke hsl(var(--primary)) with low-opacity gridlines; no chart backgrounds."
    },
    "empty_states": {
      "pattern": "Use Card with concise copy + single CTA; include Skeleton while loading.",
      "copy_tone": "System voice: calm, factual, reassuring (e.g., 'All caught up. The system is monitoring new messages.')"
    }
  },

  "accessibility": {
    "requirements": [
      "WCAG AA contrast for text and icons",
      "Visible focus states on all interactive elements",
      "Keyboard navigable sidebar + command palette",
      "Use aria-labels for icon-only buttons",
      "Respect prefers-reduced-motion"
    ]
  },

  "image_urls": {
    "notes": "This is a dashboard app; keep imagery minimal. Prefer abstract system textures and subtle real-estate context only in onboarding/help panels.",
    "categories": [
      {
        "category": "subtle-background-texture",
        "description": "Dark noise/grain overlay (CSS) instead of images to avoid performance hits.",
        "urls": []
      },
      {
        "category": "optional-empty-state-illustrations",
        "description": "If needed, use Lottie (monochrome) rather than photos.",
        "urls": [
          {
            "label": "LottieFiles search (monochrome system)",
            "url": "https://lottiefiles.com/search?q=loading%20dots%20minimal"
          }
        ]
      }
    ]
  },

  "instructions_to_main_agent": {
    "global_css_updates": [
      "Remove/ignore /app/frontend/src/App.css centering styles; do not use .App-header layout.",
      "In /app/frontend/src/index.css: override tokens to match dark-only palette above; ensure body uses bg-background text-foreground.",
      "Apply .dark class at root (index.js/App.js) permanently."
    ],
    "implementation_notes_js": [
      "Project uses .js/.jsx (not .tsx). Keep components in JSX and avoid TS types.",
      "Use shadcn components from src/components/ui; do not use raw HTML dropdown/calendar/toast.",
      "Use sonner for toasts (src/components/ui/sonner.jsx)."
    ],
    "real_time_feel": [
      "Use polling (e.g., setInterval) + optimistic UI updates.",
      "Animate new activity feed items with Framer Motion.",
      "Show 'Last sync' timestamps in mono and update every poll."
    ],
    "data_testids": [
      "Add data-testid to: sidebar nav items, primary buttons, filters, table rows, dialogs, status indicators, KPI cards, activity feed items.",
      "Use kebab-case role-based names (e.g., data-testid=\"crm-sync-status-badge\")."
    ]
  }
}

---

<General UI UX Design Guidelines>  
    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms
    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text
   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json

 **GRADIENT RESTRICTION RULE**
NEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc
NEVER use dark gradients for logo, testimonial, footer etc
NEVER let gradients cover more than 20% of the viewport.
NEVER apply gradients to text-heavy content or reading areas.
NEVER use gradients on small UI elements (<100px width).
NEVER stack multiple gradient layers in the same viewport.

**ENFORCEMENT RULE:**
    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors

**How and where to use:**
   • Section backgrounds (not content backgrounds)
   • Hero section header content. Eg: dark to light to dark color
   • Decorative overlays and accent elements only
   • Hero section with 2-3 mild color
   • Gradients creation can be done for any angle say horizontal, vertical or diagonal

- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**

</Font Guidelines>

- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. 
   
- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.

- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.
   
- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly
    Eg: - if it implies playful/energetic, choose a colorful scheme
           - if it implies monochrome/minimal, choose a black–white/neutral scheme

**Component Reuse:**
	- Prioritize using pre-existing components from src/components/ui when applicable
	- Create new components that match the style and conventions of existing components when needed
	- Examine existing components to understand the project's component patterns before creating new ones

**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component

**Best Practices:**
	- Use Shadcn/UI as the primary component library for consistency and accessibility
	- Import path: ./components/[component-name]

**Export Conventions:**
	- Components MUST use named exports (export const ComponentName = ...)
	- Pages MUST use default exports (export default function PageName() {...})

**Toasts:**
  - Use `sonner` for toasts"
  - Sonner component are located in `/app/src/components/ui/sonner.tsx`

Use 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.
</General UI UX Design Guidelines>
