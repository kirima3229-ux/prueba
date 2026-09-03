// Prueba de extremo a extremo del ciclo completo con Google Calendar:
// OAuth -> exportar tarea -> editar en Google -> traer el cambio -> borrar.
// El servidor real arranca como proceso hijo apuntando al doble de Google.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createFakeGoogle } from './fake-google.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

let google;
let googleUrl;
let server;
let baseUrl;
let dataDir;
const cookies = new Map();

// --- Cliente HTTP con tarro de cookies --------------------------------------

function cookieHeader() {
  return [...cookies].map(([key, value]) => `${key}=${value}`).join('; ');
}

async function call(pathname, options = {}) {
  const res = await fetch(baseUrl + pathname, {
    redirect: 'manual',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(cookies.size ? { Cookie: cookieHeader() } : {}),
      ...options.headers,
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  for (const raw of res.headers.getSetCookie?.() || []) {
    const [pair] = raw.split(';');
    const eq = pair.indexOf('=');
    cookies.set(pair.slice(0, eq), pair.slice(eq + 1));
  }

  const text = await res.text();
  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  return { status: res.status, headers: res.headers, body: isJson && text ? JSON.parse(text) : null, text };
}

async function waitForServer(url, attempts = 60) {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url + '/api/health');
      if (res.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('el servidor no arrancó a tiempo');
}

before(async () => {
  google = createFakeGoogle();
  googleUrl = await google.listen();
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'organizador-test-'));

  const port = 3100 + Math.floor(Math.random() * 400);
  baseUrl = `http://127.0.0.1:${port}`;

  server = spawn(process.execPath, [path.join(ROOT, 'server', 'index.js')], {
    env: {
      ...process.env,
      PORT: String(port),
      DATA_DIR: dataDir,
      SESSION_SECRET: 'secreto-de-prueba',
      GOOGLE_API_BASE: googleUrl,
      GOOGLE_CLIENT_ID: 'client-id-de-prueba',
      GOOGLE_CLIENT_SECRET: 'client-secret-de-prueba',
      GOOGLE_REDIRECT_URI: `${baseUrl}/auth/google/callback`,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stderr.on('data', (chunk) => process.stderr.write(`[servidor] ${chunk}`));

  await waitForServer(baseUrl);
});

after(async () => {
  server?.kill();
  await google?.close();
  fs.rmSync(dataDir, { recursive: true, force: true });
});

// --- Pruebas ----------------------------------------------------------------

test('el flujo OAuth deja la cuenta conectada', async () => {
  const start = await call('/auth/google');
  assert.equal(start.status, 302);

  const state = new URL(start.headers.get('location')).searchParams.get('state');
  assert.ok(state, 'la URL de autorización debe llevar un state');

  const callback = await call(`/auth/google/callback?code=codigo-falso&state=${encodeURIComponent(state)}`);
  assert.equal(callback.status, 302);
  assert.equal(callback.headers.get('location'), '/?connected=1');

  const me = await call('/api/me');
  assert.equal(me.body.connected, true);
  assert.equal(me.body.user.email, 'prueba@example.com');
});

test('un state inválido no autentica', async () => {
  const jar = new Map(cookies);
  cookies.clear();
  const res = await call('/auth/google/callback?code=x&state=inventado');
  assert.match(res.headers.get('location'), /auth_error=estado_invalido/);
  cookies.clear();
  for (const [key, value] of jar) cookies.set(key, value);
});

let taskId;

test('una tarea agendada se exporta como evento a Google', async () => {
  const created = await call('/api/tasks', {
    method: 'POST',
    body: {
      title: 'Revisión de sprint',
      area: 'work',
      scheduledAt: '2026-09-10T09:00:00.000Z',
      durationMin: 60,
    },
  });
  assert.equal(created.status, 201);
  taskId = created.body.task.id;

  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal(sync.status, 200);
  assert.equal(sync.body.pushed.created, 1);

  const events = [...google.state.events.values()];
  assert.equal(events.length, 1);
  assert.equal(events[0].summary, 'Revisión de sprint');
  assert.equal(events[0].extendedProperties.private.appTaskId, taskId);
  assert.equal(events[0].start.dateTime, '2026-09-10T09:00:00.000Z');
  assert.equal(events[0].end.dateTime, '2026-09-10T10:00:00.000Z');
});

test('editar la tarea actualiza el evento sin duplicarlo', async () => {
  await call(`/api/tasks/${taskId}`, { method: 'PATCH', body: { title: 'Revisión de sprint (larga)', durationMin: 90 } });

  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal(sync.body.pushed.created, 0);
  assert.equal(sync.body.pushed.updated, 1);

  const events = [...google.state.events.values()];
  assert.equal(events.length, 1, 'no debe crear un evento nuevo');
  assert.equal(events[0].summary, 'Revisión de sprint (larga)');
  assert.equal(events[0].end.dateTime, '2026-09-10T10:30:00.000Z');
});

test('sincronizar sin cambios no reescribe nada en Google', async () => {
  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.deepEqual(sync.body.pushed, { created: 0, updated: 0, deleted: 0 });
});

test('mover el evento en Google mueve la tarea en la app', async () => {
  const [event] = [...google.state.events.values()];
  google.state.events.set(event.id, {
    ...event,
    start: { dateTime: '2026-09-11T15:00:00.000Z', timeZone: 'UTC' },
    end: { dateTime: '2026-09-11T16:00:00.000Z', timeZone: 'UTC' },
    updated: new Date(Date.now() + 1000).toISOString(),
  });

  await call('/api/calendar/sync', { method: 'POST', body: {} });

  const { body } = await call('/api/tasks');
  const task = body.tasks.find((item) => item.id === taskId);
  assert.equal(task.scheduledAt, '2026-09-11T15:00:00.000Z');
  assert.equal(task.durationMin, 60);
});

test('los eventos ajenos llegan a la app pero no se convierten en tareas', async () => {
  google.state.seedEvent({
    summary: 'Reunión con cliente',
    location: 'Sala 2',
    start: { dateTime: '2026-09-12T11:00:00.000Z' },
    end: { dateTime: '2026-09-12T12:00:00.000Z' },
  });

  await call('/api/calendar/sync', { method: 'POST', body: {} });

  const events = await call('/api/calendar/events?from=2026-09-01T00:00:00Z&to=2026-09-30T00:00:00Z');
  const ajeno = events.body.events.find((event) => event.summary === 'Reunión con cliente');
  assert.ok(ajeno, 'el evento externo debe aparecer en la agenda');
  assert.equal(ajeno.taskId, null);
  assert.equal(ajeno.location, 'Sala 2');

  const tasks = await call('/api/tasks');
  assert.equal(tasks.body.tasks.length, 1, 'un evento externo no crea tareas');
});

test('un syncToken caducado (410) fuerza una resincronización completa', async () => {
  google.state.failNextSyncToken = true;
  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal(sync.status, 200);
  assert.deepEqual(sync.body.errors, []);

  const events = await call('/api/calendar/events?from=2026-09-01T00:00:00Z&to=2026-09-30T00:00:00Z');
  assert.equal(events.body.events.length, 2, 'tras el 410 los eventos siguen ahí');
});

test('un access token caducado se refresca solo', async () => {
  const before = google.state.tokenRequests.filter((grant) => grant === 'refresh_token').length;
  google.state.forceExpireAccessToken = true;

  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal(sync.status, 200);

  const after = google.state.tokenRequests.filter((grant) => grant === 'refresh_token').length;
  assert.ok(after > before, 'debe haber pedido un token nuevo con el refresh_token');
});

test('desagendar la tarea borra su evento en Google', async () => {
  await call(`/api/tasks/${taskId}`, { method: 'PATCH', body: { scheduledAt: null } });
  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });

  assert.equal(sync.body.pushed.deleted, 1);
  const mirrored = [...google.state.events.values()].filter((event) => event.extendedProperties);
  assert.equal(mirrored.length, 0);
});

test('borrar la tarea no deja rastro y respeta los eventos ajenos', async () => {
  await call(`/api/tasks/${taskId}`, { method: 'PATCH', body: { scheduledAt: '2026-09-15T08:00:00.000Z' } });
  await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal([...google.state.events.values()].length, 2);

  const del = await call(`/api/tasks/${taskId}`, { method: 'DELETE' });
  assert.equal(del.status, 200);

  const remaining = [...google.state.events.values()];
  assert.equal(remaining.length, 1);
  assert.equal(remaining[0].summary, 'Reunión con cliente');
});

test('los ajustes cambian el calendario destino y las horas del día', async () => {
  const res = await call('/api/settings', {
    method: 'PATCH',
    body: { dayStartHour: 7, dayEndHour: 21, pushEnabled: false, dayStartHourInvalido: 99 },
  });
  assert.equal(res.body.settings.dayStartHour, 7);
  assert.equal(res.body.settings.dayEndHour, 21);
  assert.equal(res.body.settings.pushEnabled, false);
});

test('con la exportación desactivada las tareas no llegan a Google', async () => {
  await call('/api/tasks', {
    method: 'POST',
    body: { title: 'No debe exportarse', area: 'personal', scheduledAt: '2026-09-16T10:00:00.000Z' },
  });

  const sync = await call('/api/calendar/sync', { method: 'POST', body: {} });
  assert.equal(sync.body.pushed.created, 0);
  assert.equal([...google.state.events.values()].length, 1);
});

test('cerrar sesión desconecta la cuenta', async () => {
  const res = await call('/auth/logout', { method: 'POST' });
  assert.equal(res.status, 200);

  cookies.clear();
  const me = await call('/api/me');
  assert.equal(me.body.user, null);
  assert.equal(me.body.connected, false);
});
