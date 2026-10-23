/** Keep an invitation only for the current browser tab; storage may be unavailable. */
const key = 'voice-delegate.invitation';
export function readInvitation(): string {
  try {
    return sessionStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}
export function saveInvitation(value: string): void {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch {
    /* The input still works when browser storage is disabled. */
  }
}
