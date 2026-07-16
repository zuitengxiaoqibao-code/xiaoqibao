export function safeStorageGet(key: string, fallback: string): string {
  try { return window.localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

export function safeStorageSet(key: string, value: string): void {
  try { window.localStorage.setItem(key, value); } catch { /* Browser storage may be disabled. */ }
}

export function safeStorageRemove(key: string): void {
  try { window.localStorage.removeItem(key); } catch { /* Browser storage may be disabled. */ }
}
