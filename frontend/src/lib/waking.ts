import { useSyncExternalStore } from "react";

// True while requests are being retried because the free host looks asleep (about a minute to wake).
let waking = false;
const listeners = new Set<() => void>();

export function setWaking(value: boolean) {
  if (waking === value) return;
  waking = value;
  listeners.forEach((l) => l());
}

export function useWaking(): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => waking,
  );
}
