import { useSyncExternalStore } from "react";

/**
 * Read a value from localStorage as an external store.
 *
 * `useSyncExternalStore` is the sanctioned way to subscribe React to a store
 * that lives outside it, localStorage here. It reads the server snapshot during
 * SSR and the real value after hydration without a `setState` inside an effect
 * (which schedules an extra render and is what the react-hooks lint flags), and
 * without a hydration mismatch: the hook is built to reconcile differing server
 * and client snapshots itself.
 */
const listeners = new Set<() => void>();

/** Write a value and notify every subscriber in this tab. */
export function writeStored(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private-mode storage refusal is not worth surfacing.
  }
  for (const notify of listeners) notify();
}

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  // `storage` fires for changes in *other* tabs; the listener set covers this one.
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

export function useStored(key: string, fallback: string): string {
  return useSyncExternalStore(
    subscribe,
    () => {
      try {
        return localStorage.getItem(key) ?? fallback;
      } catch {
        return fallback;
      }
    },
    () => fallback,
  );
}
