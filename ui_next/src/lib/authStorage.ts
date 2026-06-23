import type { CommercialUser } from './api';

const USER_KEY = 'gis-agent-auth-user';
const LEGACY_SESSION_KEY = 'gis-agent-auth-session';

export function readStoredUser(): CommercialUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function writeStoredUser(user: CommercialUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearStoredAuth() {
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(LEGACY_SESSION_KEY);
}

export function clearLegacyAuthSession() {
  localStorage.removeItem(LEGACY_SESSION_KEY);
}
