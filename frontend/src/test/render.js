// Minimal render helpers for tests (no @testing-library in this project).
import { act } from 'react';
import { createRoot } from 'react-dom/client';

export async function render(ui) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(ui);
  });
  return {
    container,
    async unmount() {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

// Let pending promises / effects settle inside act().
export async function flush(times = 3) {
  for (let i = 0; i < times; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await Promise.resolve();
    });
  }
}

// Like flush(), but also lets zero-delay timers fire (retry backoff set
// to 0 in tests, setTimeout-based helpers).
export async function settle(times = 4) {
  for (let i = 0; i < times; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    });
  }
}

export async function click(el) {
  await act(async () => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

export function byTestId(testId, root = document.body) {
  return root.querySelector(`[data-testid="${testId}"]`);
}

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * Router spy: `const nav = createNavSpy(); <nav.Probe />` inside a router,
 * then read `nav.location` or call `await nav.go('/path')`.
 */
export function createNavSpy() {
  // Imported lazily so non-router tests don't need react-router.
  // eslint-disable-next-line global-require
  const { useLocation, useNavigate } = require('react-router-dom');
  const spy = { location: null, navigate: null };
  spy.Probe = function NavProbe() {
    spy.location = useLocation();
    spy.navigate = useNavigate();
    return null;
  };
  spy.go = async (to) => {
    await act(async () => {
      spy.navigate(to);
    });
  };
  return spy;
}
