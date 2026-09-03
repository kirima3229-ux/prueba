import { config, googleConfigured } from './config.js';
import { getUser, upsertUser } from './store.js';

// Endpoints reales de Google. GOOGLE_API_BASE existe solo para poder
// apuntar los tests a un servidor de pruebas local.
const BASE = process.env.GOOGLE_API_BASE || '';
const OAUTH_AUTH = BASE ? `${BASE}/oauth/auth` : 'https://accounts.google.com/o/oauth2/v2/auth';
const OAUTH_TOKEN = BASE ? `${BASE}/oauth/token` : 'https://oauth2.googleapis.com/token';
const OAUTH_REVOKE = BASE ? `${BASE}/oauth/revoke` : 'https://oauth2.googleapis.com/revoke';
const USERINFO = BASE ? `${BASE}/userinfo` : 'https://openidconnect.googleapis.com/v1/userinfo';
const CAL_API = BASE ? `${BASE}/calendar/v3` : 'https://www.googleapis.com/calendar/v3';

export class GoogleError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = 'GoogleError';
    this.status = status;
    this.body = body;
  }
}

export function authUrl(state) {
  const params = new URLSearchParams({
    client_id: config.google.clientId,
    redirect_uri: config.google.redirectUri,
    response_type: 'code',
    scope: config.google.scopes.join(' '),
    access_type: 'offline',   // necesario para recibir refresh_token
    prompt: 'consent',        // fuerza refresh_token incluso si ya dio permiso antes
    include_granted_scopes: 'true',
    state,
  });
  return `${OAUTH_AUTH}?${params}`;
}

async function tokenRequest(body) {
  const res = await fetch(OAUTH_TOKEN, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new GoogleError(json.error_description || json.error || 'fallo al obtener token', res.status, json);
  }
  return json;
}

export async function exchangeCode(code) {
  return tokenRequest({
    code,
    client_id: config.google.clientId,
    client_secret: config.google.clientSecret,
    redirect_uri: config.google.redirectUri,
    grant_type: 'authorization_code',
  });
}

export async function fetchUserInfo(accessToken) {
  const res = await fetch(USERINFO, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (!res.ok) throw new GoogleError('no se pudo leer el perfil de Google', res.status, await res.text());
  return res.json();
}

export function tokensFromResponse(response, previous = {}) {
  return {
    accessToken: response.access_token,
    // Google solo devuelve refresh_token en el primer consentimiento: conservamos el anterior.
    refreshToken: response.refresh_token || previous.refreshToken || null,
    scope: response.scope || previous.scope || '',
    expiresAt: Date.now() + (Number(response.expires_in || 3600) - 60) * 1000,
  };
}

const refreshing = new Map(); // userId -> Promise, evita refrescos duplicados en paralelo

async function refreshAccessToken(userId) {
  if (refreshing.has(userId)) return refreshing.get(userId);

  const promise = (async () => {
    const user = getUser(userId);
    if (!user?.tokens?.refreshToken) {
      throw new GoogleError('sesion de Google caducada, vuelve a conectar la cuenta', 401);
    }
    const response = await tokenRequest({
      client_id: config.google.clientId,
      client_secret: config.google.clientSecret,
      refresh_token: user.tokens.refreshToken,
      grant_type: 'refresh_token',
    });
    const tokens = tokensFromResponse(response, user.tokens);
    upsertUser({ ...user, tokens });
    return tokens.accessToken;
  })().finally(() => refreshing.delete(userId));

  refreshing.set(userId, promise);
  return promise;
}

async function accessTokenFor(userId) {
  const user = getUser(userId);
  if (!user?.tokens?.accessToken) {
    throw new GoogleError('cuenta de Google no conectada', 401);
  }
  if (Date.now() >= (user.tokens.expiresAt || 0)) {
    return refreshAccessToken(userId);
  }
  return user.tokens.accessToken;
}

/**
 * Llamada autenticada a la API de Calendar. Reintenta una vez tras refrescar
 * el token si Google responde 401.
 */
export async function calendarApi(userId, pathname, { method = 'GET', query, body, retry = true } = {}) {
  if (!googleConfigured) throw new GoogleError('Google OAuth no esta configurado en el servidor', 503);

  const token = await accessTokenFor(userId);
  const url = new URL(CAL_API + pathname);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }

  const res = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && retry) {
    await refreshAccessToken(userId);
    return calendarApi(userId, pathname, { method, query, body, retry: false });
  }
  if (res.status === 204) return null;

  const text = await res.text();
  const json = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const message = json?.error?.message || `Google respondio ${res.status}`;
    throw new GoogleError(message, res.status, json);
  }
  return json;
}

export async function revokeToken(token) {
  if (!token) return;
  await fetch(OAUTH_REVOKE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ token }),
  }).catch(() => {});
}

export async function listCalendars(userId) {
  const data = await calendarApi(userId, '/users/me/calendarList', {
    query: { maxResults: 250, minAccessRole: 'reader' },
  });
  return (data?.items || []).map((cal) => ({
    id: cal.id,
    summary: cal.summaryOverride || cal.summary,
    description: cal.description || '',
    primary: Boolean(cal.primary),
    accessRole: cal.accessRole,
    color: cal.backgroundColor || '#4285f4',
    timeZone: cal.timeZone,
    writable: cal.accessRole === 'owner' || cal.accessRole === 'writer',
  }));
}
