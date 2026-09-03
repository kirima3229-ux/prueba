// Doble de pruebas de la API de Google (OAuth + Calendar).
// Implementa solo lo que usa la app, con el mismo contrato de respuestas.

import http from 'node:http';
import crypto from 'node:crypto';

export function createFakeGoogle() {
  const state = {
    accessTokens: new Set(),
    refreshToken: 'refresh-1',
    tokenRequests: [],
    calendars: [
      {
        id: 'primary@test',
        summary: 'Trabajo y personal',
        primary: true,
        accessRole: 'owner',
        backgroundColor: '#4285f4',
        timeZone: 'Europe/Madrid',
      },
    ],
    events: new Map(),      // eventId -> recurso de evento
    syncTokens: new Map(),  // syncToken -> calendarId
    failNextSyncToken: false,  // fuerza un 410 GONE en la próxima llamada incremental
    forceExpireAccessToken: false,
  };

  function issueAccessToken() {
    const token = 'access-' + crypto.randomBytes(6).toString('hex');
    state.accessTokens.add(token);
    return token;
  }

  /** Inserta un evento como si lo hubiera creado el propio Google Calendar. */
  state.seedEvent = (event) => {
    const id = event.id || 'ev-' + crypto.randomBytes(5).toString('hex');
    const resource = {
      id,
      status: 'confirmed',
      updated: new Date().toISOString(),
      htmlLink: `https://calendar.google.com/event?eid=${id}`,
      ...event,
    };
    state.events.set(id, resource);
    return resource;
  };

  const json = (res, code, body) => {
    res.writeHead(code, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
  };

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fake');
    const path = url.pathname;

    let body = '';
    for await (const chunk of req) body += chunk;

    // --- OAuth -------------------------------------------------------------
    if (path === '/oauth/token') {
      const params = new URLSearchParams(body);
      const grant = params.get('grant_type');
      state.tokenRequests.push(grant);

      if (grant === 'authorization_code') {
        return json(res, 200, {
          access_token: issueAccessToken(),
          refresh_token: state.refreshToken,
          expires_in: 3600,
          scope: 'calendar',
          token_type: 'Bearer',
        });
      }
      if (grant === 'refresh_token') {
        if (params.get('refresh_token') !== state.refreshToken) {
          return json(res, 400, { error: 'invalid_grant' });
        }
        state.forceExpireAccessToken = false;
        return json(res, 200, { access_token: issueAccessToken(), expires_in: 3600, token_type: 'Bearer' });
      }
      return json(res, 400, { error: 'unsupported_grant_type' });
    }

    // Pantalla de consentimiento: acepta siempre y vuelve con un code.
    if (path === '/oauth/auth') {
      const redirect = url.searchParams.get('redirect_uri');
      const oauthState = url.searchParams.get('state');
      res.writeHead(302, {
        Location: `${redirect}?code=codigo-falso&state=${encodeURIComponent(oauthState || '')}`,
      });
      return res.end();
    }

    if (path === '/oauth/revoke') return json(res, 200, {});

    if (path === '/userinfo') {
      return json(res, 200, {
        sub: 'user-123',
        email: 'prueba@example.com',
        name: 'Persona de Prueba',
        picture: 'https://example.com/avatar.png',
      });
    }

    // --- Calendar (requiere token válido) ----------------------------------
    const auth = (req.headers.authorization || '').replace('Bearer ', '');
    if (!state.accessTokens.has(auth) || state.forceExpireAccessToken) {
      return json(res, 401, { error: { code: 401, message: 'Invalid Credentials' } });
    }

    if (path === '/calendar/v3/users/me/calendarList') {
      return json(res, 200, { items: state.calendars });
    }

    const eventsMatch = /^\/calendar\/v3\/calendars\/([^/]+)\/events(?:\/([^/]+))?$/.exec(path);
    if (eventsMatch) {
      const calendarId = decodeURIComponent(eventsMatch[1]);
      const eventId = eventsMatch[2] ? decodeURIComponent(eventsMatch[2]) : null;

      if (req.method === 'GET' && !eventId) {
        if (url.searchParams.has('syncToken')) {
          if (state.failNextSyncToken) {
            state.failNextSyncToken = false;
            return json(res, 410, { error: { code: 410, message: 'Sync token is no longer valid' } });
          }
        }
        const token = 'sync-' + crypto.randomBytes(4).toString('hex');
        state.syncTokens.set(token, calendarId);
        return json(res, 200, { items: [...state.events.values()], nextSyncToken: token });
      }

      if (req.method === 'POST' && !eventId) {
        const payload = JSON.parse(body || '{}');
        return json(res, 200, state.seedEvent(payload));
      }

      if (req.method === 'PATCH' && eventId) {
        const existing = state.events.get(eventId);
        if (!existing) return json(res, 404, { error: { code: 404, message: 'Not Found' } });
        const merged = { ...existing, ...JSON.parse(body || '{}'), updated: new Date().toISOString() };
        state.events.set(eventId, merged);
        return json(res, 200, merged);
      }

      if (req.method === 'DELETE' && eventId) {
        if (!state.events.delete(eventId)) {
          return json(res, 404, { error: { code: 404, message: 'Not Found' } });
        }
        res.writeHead(204);
        return res.end();
      }
    }

    return json(res, 404, { error: { code: 404, message: `sin ruta: ${req.method} ${path}` } });
  });

  return {
    state,
    listen: () =>
      new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`));
      }),
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}
