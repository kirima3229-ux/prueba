import crypto from 'node:crypto';
import { config } from './config.js';

const COOKIE = 'org_session';
const MAX_AGE_DAYS = 30;

function sign(value) {
  return crypto.createHmac('sha256', config.sessionSecret).update(value).digest('base64url');
}

function serialize(payload) {
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${body}.${sign(body)}`;
}

function deserialize(raw) {
  if (typeof raw !== 'string') return null;
  const dot = raw.lastIndexOf('.');
  if (dot === -1) return null;
  const body = raw.slice(0, dot);
  const mac = raw.slice(dot + 1);
  const expected = sign(body);
  // Comparacion en tiempo constante: evita filtrar la firma byte a byte.
  if (mac.length !== expected.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(expected))) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (!payload?.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

function parseCookies(header = '') {
  const out = {};
  for (const part of header.split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    out[part.slice(0, eq).trim()] = decodeURIComponent(part.slice(eq + 1).trim());
  }
  return out;
}

export function sessionMiddleware(req, res, next) {
  const cookies = parseCookies(req.headers.cookie || '');
  req.session = deserialize(cookies[COOKIE]);
  req.userId = req.session?.userId || null;

  res.setSession = (payload) => {
    const exp = Date.now() + MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
    const parts = [
      `${COOKIE}=${encodeURIComponent(serialize({ ...payload, exp }))}`,
      'Path=/',
      'HttpOnly',
      'SameSite=Lax',
      `Max-Age=${MAX_AGE_DAYS * 24 * 60 * 60}`,
    ];
    if (config.secureCookies) parts.push('Secure');
    res.append('Set-Cookie', parts.join('; '));
  };

  res.clearSession = () => {
    const parts = [`${COOKIE}=`, 'Path=/', 'HttpOnly', 'SameSite=Lax', 'Max-Age=0'];
    if (config.secureCookies) parts.push('Secure');
    res.append('Set-Cookie', parts.join('; '));
  };

  next();
}

export function requireAuth(req, res, next) {
  if (!req.userId) return res.status(401).json({ error: 'no_autenticado' });
  next();
}
