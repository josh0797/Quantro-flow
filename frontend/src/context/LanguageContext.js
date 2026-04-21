import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { authFetch } from '../lib/authFetch';
import {
  translations,
  SUPPORTED_LANGUAGES,
  DEFAULT_LANGUAGE,
  FALLBACK_LANGUAGE,
} from '../i18n/translations';

/**
 * LanguageContext — Global i18n state for Quantro OS.
 *
 * Provides:
 *   - lang:    current language code ('es' | 'en')
 *   - setLang: setter with localStorage + backend persistence
 *   - t(key, vars?): resolve a dot-addressable key with optional interpolation
 *                    Self-healing: falls back to EN, then to the key itself.
 *
 * Initial resolution order:
 *   1. Business profile from backend (profile.language)
 *   2. localStorage  ('quantro_lang')
 *   3. DEFAULT_LANGUAGE
 */

const STORAGE_KEY = 'quantro_lang';
const SUPPORTED_CODES = SUPPORTED_LANGUAGES.map((l) => l.code);

const LanguageContext = createContext(null);

function readLocalLang() {
  try {
    const v = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
    return SUPPORTED_CODES.includes(v) ? v : null;
  } catch {
    return null;
  }
}

function writeLocalLang(v) {
  try {
    if (typeof window !== 'undefined') localStorage.setItem(STORAGE_KEY, v);
  } catch {
    /* ignore quota / privacy mode */
  }
}

/**
 * Resolve dot-addressable key (e.g. "settings.profile.saving") inside a given tree.
 * Returns undefined when not found.
 */
function resolveKey(tree, key) {
  if (!tree || typeof tree !== 'object' || typeof key !== 'string') return undefined;
  const parts = key.split('.');
  let node = tree;
  for (let i = 0; i < parts.length; i += 1) {
    if (node == null || typeof node !== 'object') return undefined;
    node = node[parts[i]];
  }
  return node;
}

/**
 * Replace {{var}} placeholders with values from the vars object.
 * Unknown vars are left untouched rather than crashing.
 */
function interpolate(str, vars) {
  if (typeof str !== 'string' || !vars) return str;
  return str.replace(/\{\{\s*([\w.-]+)\s*\}\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match
  );
}

export function LanguageProvider({ children }) {
  const [lang, setLangState] = useState(() => readLocalLang() || DEFAULT_LANGUAGE);
  const [hydrated, setHydrated] = useState(false);

  // ── Hydrate from backend business_profile (if available) on mount
  useEffect(() => {
    let cancelled = false;
    const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
    (async () => {
      try {
        const res = await authFetch(`${backendUrl}/api/business-profile`, { credentials: 'include' });
        if (!res.ok) return;
        const profile = await res.json();
        const remote = profile?.language;
        if (!cancelled && remote && SUPPORTED_CODES.includes(remote)) {
          // Backend wins on first hydration ONLY if user hasn't explicitly chosen locally.
          // We prefer a local override because the user just clicked the switcher.
          const local = readLocalLang();
          if (!local || local === DEFAULT_LANGUAGE) {
            setLangState(remote);
            writeLocalLang(remote);
          }
        }
      } catch {
        /* silent — offline fallback to local/default */
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── Persist to backend when lang changes (after hydration completed)
  const persistRemote = useCallback(async (nextLang) => {
    const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
    try {
      // Fetch current profile and merge language (avoid wiping other fields)
      const getRes = await authFetch(`${backendUrl}/api/business-profile`, { credentials: 'include' });
      if (!getRes.ok) return;
      const current = await getRes.json();
      const payload = { ...current, language: nextLang };
      delete payload.profile_id;
      delete payload.created_at;
      delete payload.updated_at;
      await authFetch(`${backendUrl}/api/business-profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch {
      /* silent — local storage still persists the choice */
    }
  }, []);

  const setLang = useCallback(
    (next) => {
      if (!SUPPORTED_CODES.includes(next)) return;
      setLangState(next);
      writeLocalLang(next);
      // Only push to backend once the app has hydrated — avoids overwriting the
      // backend-preferred value on the very first render.
      if (hydrated) {
        persistRemote(next);
      }
    },
    [hydrated, persistRemote]
  );

  // ── The t() function — memoized per (lang).
  const t = useMemo(() => {
    const primary = translations[lang] || {};
    const fallback = translations[FALLBACK_LANGUAGE] || {};
    return (key, vars) => {
      let value = resolveKey(primary, key);
      if (value === undefined) value = resolveKey(fallback, key);
      if (typeof value !== 'string') return key; // last-ditch fallback
      return interpolate(value, vars);
    };
  }, [lang]);

  const value = useMemo(
    () => ({ lang, setLang, t, supported: SUPPORTED_LANGUAGES, hydrated }),
    [lang, setLang, t, hydrated]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error('useLanguage must be used within <LanguageProvider>');
  }
  return ctx;
}

/**
 * Convenience hook for components that only need the `t()` function.
 * Equivalent to `const { t } = useLanguage()`.
 */
export function useT() {
  return useLanguage().t;
}
