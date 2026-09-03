import crypto from 'node:crypto';
import express from 'express';
import { googleConfigured } from '../config.js';
import { authUrl, exchangeCode, fetchUserInfo, revokeToken, tokensFromResponse } from '../google.js';
import { getSettings, getUser, setSettings, upsertUser } from '../store.js';
import { isConnected } from '../sync.js';

export const authRouter = express.Router();

// Estados OAuth pendientes (proteccion CSRF). TTL corto, en memoria.
const pendingStates = new Map();
const STATE_TTL_MS = 10 * 60 * 1000;

function issueState() {
  const state = crypto.randomBytes(24).toString('base64url');
  pendingStates.set(state, Date.now() + STATE_TTL_MS);
  for (const [key, expiry] of pendingStates) {
    if (expiry < Date.now()) pendingStates.delete(key);
  }
  return state;
}

function consumeState(state) {
  const expiry = pendingStates.get(state);
  pendingStates.delete(state);
  return Boolean(expiry) && expiry >= Date.now();
}

function publicUser(userId) {
  const user = getUser(userId);
  if (!user) return null;
  return {
    id: user.id,
    email: user.email,
    name: user.name,
    picture: user.picture || null,
    provider: user.provider,
    connectedToGoogle: Boolean(user.tokens?.refreshToken),
  };
}

authRouter.get('/api/me', (req, res) => {
  const user = req.userId ? publicUser(req.userId) : null;
  res.json({
    googleConfigured,
    user,
    connected: req.userId ? isConnected(req.userId) : false,
    settings: req.userId ? getSettings(req.userId) : null,
  });
});

authRouter.get('/auth/google', (req, res) => {
  if (!googleConfigured) {
    return res.status(503).send(
      'Google OAuth no esta configurado. Copia .env.example a .env y rellena GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET.',
    );
  }
  res.redirect(authUrl(issueState()));
});

authRouter.get('/auth/google/callback', async (req, res) => {
  const { code, state, error } = req.query;

  if (error) return res.redirect(`/?auth_error=${encodeURIComponent(String(error))}`);
  if (!code || !consumeState(String(state || ''))) {
    return res.redirect('/?auth_error=estado_invalido');
  }

  try {
    const tokenResponse = await exchangeCode(String(code));
    const profile = await fetchUserInfo(tokenResponse.access_token);

    const userId = `google:${profile.sub}`;
    const previous = getUser(userId);

    upsertUser({
      id: userId,
      provider: 'google',
      email: profile.email || '',
      name: profile.name || profile.email || 'Usuario',
      picture: profile.picture || null,
      tokens: tokensFromResponse(tokenResponse, previous?.tokens),
    });

    // Guardamos la zona horaria del navegador si el cliente la mando antes.
    if (!previous) setSettings(userId, { timeZone: getSettings(userId).timeZone });

    res.setSession({ userId });
    res.redirect('/?connected=1');
  } catch (err) {
    console.error('[auth] callback fallido:', err.message);
    res.redirect(`/?auth_error=${encodeURIComponent(err.message)}`);
  }
});

/**
 * Modo local: permite usar la app (tareas, agenda) sin conectar Google.
 * Util para probar antes de tener credenciales o para uso puramente offline.
 */
authRouter.post('/auth/local', (req, res) => {
  const userId = 'local:default';
  if (!getUser(userId)) {
    upsertUser({ id: userId, provider: 'local', email: '', name: 'Local', picture: null, tokens: null });
  }
  res.setSession({ userId });
  res.json({ user: publicUser(userId), settings: getSettings(userId) });
});

authRouter.post('/auth/logout', async (req, res) => {
  const user = req.userId ? getUser(req.userId) : null;
  if (user?.tokens?.accessToken) await revokeToken(user.tokens.accessToken);
  if (user) upsertUser({ ...user, tokens: null });
  res.clearSession();
  res.json({ ok: true });
});

export { publicUser };
