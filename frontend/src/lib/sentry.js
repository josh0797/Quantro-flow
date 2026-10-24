// src/lib/sentry.js
// Error tracking for the Quantro Flow web app (Sentry project `quantro-flow-web`,
// org `quantro-tb`). Activated only when REACT_APP_SENTRY_DSN is set at build
// time (Vercel → Quantro-flow → Environment Variables). Without it this is a
// no-op and @sentry/react is never downloaded (dynamic import → own chunk).
//
// Privacy: sendDefaultPii false, no Session Replay, no tracing headers to the
// API, and beforeSend/beforeBreadcrumb strip tokens, JWTs, emails, RFC/CURP and
// card numbers. User context, if ever set, must be the user id only.
// NOTE: no regex lookbehind here — this module is in the entry chunk and CRA
// does not transpile lookbehind, which would be a SyntaxError on Safari < 16.4.

const FILTERED = '[Filtered]';

const SENSITIVE_KEY =
  /(authorization|cookie|passw(or)?d|secret|token|api[-_]?key|apikey|service[-_]?role|private[-_]?key|signature|session|credential|jwt|bearer|refresh|access[-_]?key|client[-_]?secret|dsn)/i;

const VALUE_PATTERNS = [
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, '[JWT]'],
  [/\b(bearer\s+)[A-Za-z0-9\-._~+/]{12,}=*/gi, '$1[TOKEN]'],
  [/\bsk-[A-Za-z0-9_-]{16,}/g, '[API_KEY]'],
  [/\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{8,}/g, '[API_KEY]'],
  [/\bAIza[A-Za-z0-9_-]{30,}/g, '[API_KEY]'],
  [/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g, '[EMAIL]'],
  [/\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b/gi, '[CURP]'],
  [/\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b/gi, '[RFC]'],
  [/\b\d{18}\b/g, '[CLABE]'],
];

function luhn(digits) {
  let sum = 0;
  let dbl = false;
  for (let i = digits.length - 1; i >= 0; i -= 1) {
    let n = digits.charCodeAt(i) - 48;
    if (dbl) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    dbl = !dbl;
  }
  return sum % 10 === 0;
}

export function scrubText(value) {
  if (typeof value !== 'string' || !value) return value;
  let out = value.slice(0, 8000);
  for (const [re, repl] of VALUE_PATTERNS) out = out.replace(re, repl);
  return out.replace(/\b(?:\d[ -]?){12,18}\d\b/g, (m) => {
    const d = m.replace(/\D/g, '');
    return d.length >= 13 && d.length <= 19 && luhn(d) ? '[CARD]' : m;
  });
}

function scrubUrl(url) {
  if (typeof url !== 'string') return url;
  try {
    const u = new URL(url, 'http://relative.invalid');
    u.hash = '';
    [...u.searchParams.keys()].forEach((k) => {
      if (SENSITIVE_KEY.test(k) || /^(code|state|key|email)$/i.test(k)) u.searchParams.set(k, FILTERED);
    });
    const abs = /^[a-z][a-z0-9+.-]*:\/\//i.test(url);
    return scrubText(decodeURI(abs ? u.toString() : `${u.pathname}${u.search}`));
  } catch (e) {
    return scrubText(url.split('#')[0]);
  }
}

function scrubValue(value, key = '', depth = 0) {
  if (key && SENSITIVE_KEY.test(key)) return FILTERED;
  if (key && /(^id$|_id$|Id$|^(stacktrace|frames|trace_id|span_id|event_id|release|environment)$)/.test(key)) return value;
  if (typeof value === 'string') return key === 'url' ? scrubUrl(value) : scrubText(value);
  if (!value || typeof value !== 'object' || depth > 10) return value;
  if (Array.isArray(value)) return value.map((v) => scrubValue(v, '', depth + 1));
  const out = {};
  Object.keys(value).forEach((k) => {
    out[k] = scrubValue(value[k], k, depth + 1);
  });
  return out;
}

export function scrubEvent(event) {
  try {
    const e = { ...event };
    if (typeof e.message === 'string') e.message = scrubText(e.message);
    if (e.exception && Array.isArray(e.exception.values)) {
      e.exception = {
        ...e.exception,
        values: e.exception.values.map((v) => ({ ...v, value: scrubText(v.value) })),
      };
    }
    if (e.request) {
      const r = { ...e.request };
      delete r.cookies;
      delete r.data;
      if (r.url) r.url = scrubUrl(r.url);
      if (r.headers) r.headers = scrubValue(r.headers);
      e.request = r;
    }
    if (e.user) e.user = e.user.id ? { id: e.user.id } : undefined;
    if (Array.isArray(e.breadcrumbs)) e.breadcrumbs = e.breadcrumbs.map(scrubBreadcrumb);
    ['extra', 'contexts', 'tags'].forEach((f) => {
      if (e[f]) e[f] = scrubValue(e[f]);
    });
    return e;
  } catch (err) {
    return { event_id: event && event.event_id, message: FILTERED };
  }
}

export function scrubBreadcrumb(crumb) {
  const out = { ...crumb };
  if (typeof out.message === 'string') out.message = scrubText(out.message);
  if (out.data) {
    const data = {};
    Object.keys(out.data).forEach((k) => {
      if (k === 'body' || k === 'arguments') return;
      data[k] = scrubValue(out.data[k], k);
    });
    out.data = data;
  }
  return out;
}

export const IGNORE_ERRORS = [
  'ResizeObserver loop limit exceeded',
  'ResizeObserver loop completed with undelivered notifications',
  /^Script error\.?$/,
  /ethereum/i,
  /MetaMask/i,
  /chrome-extension:\/\//i,
  /moz-extension:\/\//i,
  /AbortError/,
];

export const DENY_URLS = [/extensions\//i, /^chrome(-extension)?:\/\//i, /^moz-extension:\/\//i, /^safari(-web)?-extension:\/\//i];

let started = false;

export function initSentry() {
  const dsn = process.env.REACT_APP_SENTRY_DSN;
  if (!dsn || started) return;
  started = true;
  const environment =
    process.env.REACT_APP_SENTRY_ENVIRONMENT || process.env.REACT_APP_VERCEL_ENV || process.env.NODE_ENV || 'production';
  import('@sentry/react')
    .then((Sentry) => {
      Sentry.init({
        dsn,
        environment,
        release: process.env.REACT_APP_SENTRY_RELEASE || process.env.REACT_APP_VERCEL_GIT_COMMIT_SHA || undefined,
        sendDefaultPii: false,
        tracesSampleRate: 0,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
        ignoreErrors: IGNORE_ERRORS,
        denyUrls: DENY_URLS,
        maxBreadcrumbs: 50,
        beforeSend: (event) => scrubEvent(event),
        beforeBreadcrumb: (crumb) => scrubBreadcrumb(crumb),
      });
    })
    .catch(() => {
      // SDK blocked/offline: never break the app.
    });
}
