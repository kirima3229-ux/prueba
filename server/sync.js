import { calendarApi, listCalendars, GoogleError } from './google.js';
import { getSettings, getSync, getTasks, getUser, save, setSettings } from './store.js';
import { taskEndsAt, taskSignature } from './model.js';

const DAY = 24 * 60 * 60 * 1000;
const WINDOW_PAST_DAYS = 30;
const WINDOW_FUTURE_DAYS = 180;
const FULL_RESYNC_EVERY_MS = 7 * DAY;

// Colores de Google Calendar usados para distinguir las dos areas de un vistazo.
const AREA_COLOR_ID = { work: '9', personal: '10' };

const inFlight = new Map(); // userId -> Promise, serializa sincronizaciones del mismo usuario

export function isConnected(userId) {
  return Boolean(getUser(userId)?.tokens?.refreshToken);
}

function eventKey(calendarId, eventId) {
  return `${calendarId}::${eventId}`;
}

function normalizeEvent(calendarId, event) {
  const allDay = Boolean(event.start?.date);
  const start = allDay ? event.start.date : event.start?.dateTime;
  const end = allDay ? event.end?.date : event.end?.dateTime;
  return {
    key: eventKey(calendarId, event.id),
    id: event.id,
    calendarId,
    summary: event.summary || '(sin titulo)',
    description: event.description || '',
    location: event.location || '',
    allDay,
    start: start || null,
    end: end || null,
    status: event.status || 'confirmed',
    updated: event.updated || null,
    htmlLink: event.htmlLink || '',
    hangoutLink: event.hangoutLink || '',
    attendeeCount: Array.isArray(event.attendees) ? event.attendees.length : 0,
    taskId: event.extendedProperties?.private?.appTaskId || null,
    recurring: Boolean(event.recurringEventId),
  };
}

function currentWindow(anchorMs = Date.now()) {
  return {
    timeMin: new Date(anchorMs - WINDOW_PAST_DAYS * DAY).toISOString(),
    timeMax: new Date(anchorMs + WINDOW_FUTURE_DAYS * DAY).toISOString(),
  };
}

/** Descarga la lista de calendarios y la cachea para el frontend. */
export async function refreshCalendarList(userId) {
  const calendars = await listCalendars(userId);
  const sync = getSync(userId);
  sync.calendarList = calendars;
  sync.calendarListAt = new Date().toISOString();

  // 'primary' es un alias; lo fijamos al id real para que el destino de los
  // eventos no cambie entre sincronizaciones.
  const settings = getSettings(userId);
  if (settings.pushCalendarId === 'primary') {
    const primary = calendars.find((cal) => cal.primary);
    if (primary) setSettings(userId, { pushCalendarId: primary.id });
  }

  // Al conectar por primera vez marcamos los calendarios propios, para que lo
  // que se ve en la agenda coincida con lo marcado en Ajustes.
  if (!settings.visibleCalendars?.length && calendars.length) {
    const own = calendars.filter((cal) => cal.writable || cal.primary);
    setSettings(userId, { visibleCalendars: (own.length ? own : calendars).map((cal) => cal.id) });
  }

  save();
  return calendars;
}

/** Calendario donde se escriben las tareas, con 'primary' ya resuelto. */
function targetCalendarId(userId) {
  const target = getSettings(userId).pushCalendarId || 'primary';
  if (target !== 'primary') return target;
  return getSync(userId).calendarList?.find((cal) => cal.primary)?.id || 'primary';
}

/**
 * Descarga eventos de un calendario. Usa syncToken incremental cuando es
 * posible y cae a sincronizacion completa si Google lo invalida (410).
 */
async function pullCalendar(userId, calendarId, { full = false } = {}) {
  const sync = getSync(userId);
  if (!sync.calendars[calendarId]) sync.calendars[calendarId] = {};
  const state = sync.calendars[calendarId];

  const stale = !state.fullSyncAt || Date.now() - new Date(state.fullSyncAt).getTime() > FULL_RESYNC_EVERY_MS;
  let incremental = Boolean(state.syncToken) && !full && !stale;

  let changed = 0;
  let removed = 0;

  for (let attempt = 0; attempt < 2; attempt++) {
    const window = currentWindow();
    let pageToken;
    let nextSyncToken = null;
    const seededFull = !incremental;

    try {
      do {
        const query = incremental
          ? { syncToken: state.syncToken, pageToken, maxResults: 250, showDeleted: true }
          : {
              timeMin: window.timeMin,
              timeMax: window.timeMax,
              singleEvents: true,      // expande recurrencias en instancias concretas
              showDeleted: false,
              maxResults: 250,
              orderBy: 'startTime',
              pageToken,
            };

        const page = await calendarApi(userId, `/calendars/${encodeURIComponent(calendarId)}/events`, { query });

        for (const raw of page?.items || []) {
          const key = eventKey(calendarId, raw.id);
          if (raw.status === 'cancelled') {
            if (sync.events[key]) {
              delete sync.events[key];
              removed++;
            }
            continue;
          }
          sync.events[key] = normalizeEvent(calendarId, raw);
          changed++;
        }

        pageToken = page?.nextPageToken;
        nextSyncToken = page?.nextSyncToken || nextSyncToken;
      } while (pageToken);
    } catch (err) {
      // 410 GONE: el syncToken caduco. Reintentamos una vez en modo completo.
      if (err instanceof GoogleError && err.status === 410 && incremental) {
        incremental = false;
        state.syncToken = null;
        continue;
      }
      throw err;
    }

    state.syncToken = nextSyncToken || state.syncToken;
    if (seededFull) {
      state.fullSyncAt = new Date().toISOString();
      // Al hacer sincronizacion completa purgamos lo que quedo fuera de ventana.
      for (const [key, event] of Object.entries(sync.events)) {
        if (event.calendarId !== calendarId) continue;
        const ref = event.start || '';
        if (ref && (ref < window.timeMin.slice(0, 10) || ref > window.timeMax)) {
          delete sync.events[key];
          removed++;
        }
      }
    }
    state.lastPullAt = new Date().toISOString();
    break;
  }

  save();
  return { changed, removed };
}

/** Trae de vuelta los cambios hechos en Google sobre eventos espejo de tareas. */
function reconcileMirroredEvents(userId) {
  const sync = getSync(userId);
  const tasks = getTasks(userId);
  const byId = new Map(tasks.map((task) => [task.id, task]));
  let updated = 0;

  for (const event of Object.values(sync.events)) {
    if (!event.taskId) continue;
    const task = byId.get(event.taskId);
    if (!task || event.allDay || !event.start) continue;

    const startIso = new Date(event.start).toISOString();
    const durationMin = event.end
      ? Math.max(5, Math.round((new Date(event.end) - new Date(event.start)) / 60000))
      : task.durationMin;
    const title = event.summary.replace(/^✔\s*/, '');

    const differs =
      task.scheduledAt !== startIso || task.durationMin !== durationMin || task.title !== title;

    // Quien gana no se decide por reloj (el de Google y el nuestro no van a la
    // par) sino por huella: si la tarea cambio desde el ultimo sync, manda la
    // app y el push posterior corrige el evento. Si no, manda Google.
    const appChanged = Boolean(task.google?.signature) && task.google.signature !== taskSignature(task);
    const adopt = differs && !appChanged;

    if (adopt) {
      task.scheduledAt = startIso;
      task.durationMin = durationMin;
      if (title) task.title = title;
      task.updatedAt = new Date().toISOString();
      updated++;
    }

    task.google = {
      ...(task.google || {}),
      calendarId: event.calendarId,
      eventId: event.id,
      lastSyncedAt: event.updated,
      // Al no adoptar dejamos la huella antigua a proposito: asi el push
      // detecta la diferencia y reescribe el evento.
      signature: adopt || !differs ? taskSignature(task) : task.google?.signature,
    };
  }

  // Un evento espejo borrado en Google desagenda la tarea (no la elimina).
  for (const task of tasks) {
    if (!task.google?.eventId) continue;
    const key = eventKey(task.google.calendarId, task.google.eventId);
    if (sync.events[key]) continue;
    const lastPullAt = sync.calendars[task.google.calendarId]?.lastPullAt;
    if (!lastPullAt) continue;
    // Si la tarea se edito despues del pull, el evento aun no existia: no la tocamos.
    if (new Date(task.updatedAt) > new Date(lastPullAt)) continue;
    task.scheduledAt = null;
    task.google = null;
    task.updatedAt = new Date().toISOString();
    updated++;
  }

  if (updated) save();
  return updated;
}

function eventBodyForTask(task, timeZone) {
  const descriptionParts = [];
  if (task.notes) descriptionParts.push(task.notes);
  descriptionParts.push(`Area: ${task.area === 'work' ? 'Trabajo' : 'Personal'}`);
  if (task.tags?.length) descriptionParts.push(`Etiquetas: ${task.tags.join(', ')}`);
  if (task.dueDate) descriptionParts.push(`Fecha limite: ${task.dueDate}`);
  descriptionParts.push('— Creado por Organizador');

  return {
    summary: (task.status === 'done' ? '✔ ' : '') + (task.title || 'Tarea sin titulo'),
    description: descriptionParts.join('\n'),
    start: { dateTime: task.scheduledAt, timeZone },
    end: { dateTime: taskEndsAt(task), timeZone },
    colorId: AREA_COLOR_ID[task.area] || undefined,
    extendedProperties: { private: { appTaskId: task.id, appArea: task.area, app: 'organizador' } },
  };
}

/** Borra el evento espejo de una tarea. Se usa tambien al eliminar la tarea. */
export async function deleteTaskEvent(userId, task) {
  if (!task?.google?.eventId) return false;
  const { calendarId, eventId } = task.google;
  try {
    await calendarApi(userId, `/calendars/${encodeURIComponent(calendarId)}/events/${encodeURIComponent(eventId)}`, {
      method: 'DELETE',
    });
  } catch (err) {
    // 404/410 = ya no existe en Google; cualquier otra cosa si es un fallo real.
    if (!(err instanceof GoogleError && (err.status === 404 || err.status === 410))) throw err;
  }
  const sync = getSync(userId);
  delete sync.events[eventKey(calendarId, eventId)];
  task.google = null;
  save();
  return true;
}

/** Empuja a Google las tareas agendadas (crear / actualizar / borrar espejo). */
export async function pushTasks(userId) {
  const settings = getSettings(userId);
  const tasks = getTasks(userId);
  const sync = getSync(userId);
  const timeZone = settings.timeZone || 'UTC';
  const target = targetCalendarId(userId);

  let created = 0;
  let updated = 0;
  let deleted = 0;

  for (const task of tasks) {
    const wantsEvent = settings.pushEnabled && Boolean(task.scheduledAt);
    const hasEvent = Boolean(task.google?.eventId);

    if (!wantsEvent) {
      if (hasEvent) {
        await deleteTaskEvent(userId, task);
        deleted++;
      }
      continue;
    }

    // Si cambio el calendario destino, movemos el evento borrando y recreando.
    if (hasEvent && task.google.calendarId !== target) {
      await deleteTaskEvent(userId, task);
      deleted++;
    }

    const body = eventBodyForTask(task, timeZone);

    if (!task.google?.eventId) {
      const event = await calendarApi(userId, `/calendars/${encodeURIComponent(target)}/events`, {
        method: 'POST',
        body,
      });
      task.google = {
        calendarId: target,
        eventId: event.id,
        lastSyncedAt: event.updated,
        signature: taskSignature(task),
      };
      sync.events[eventKey(target, event.id)] = normalizeEvent(target, event);
      created++;
      continue;
    }

    if (task.google.signature === taskSignature(task)) continue;

    const event = await calendarApi(
      userId,
      `/calendars/${encodeURIComponent(target)}/events/${encodeURIComponent(task.google.eventId)}`,
      { method: 'PATCH', body },
    );
    task.google = {
      calendarId: target,
      eventId: event.id,
      lastSyncedAt: event.updated,
      signature: taskSignature(task),
    };
    sync.events[eventKey(target, event.id)] = normalizeEvent(target, event);
    updated++;
  }

  save();
  return { created, updated, deleted };
}

/**
 * Sincronizacion completa en el orden correcto:
 *   1. refresca lista de calendarios
 *   2. baja eventos de los calendarios visibles
 *   3. aplica a las tareas los cambios hechos en Google
 *   4. sube a Google los cambios hechos en la app
 */
export async function syncAll(userId, { full = false } = {}) {
  if (inFlight.has(userId)) return inFlight.get(userId);

  const promise = (async () => {
    if (!isConnected(userId)) throw new GoogleError('cuenta de Google no conectada', 401);

    const calendars = await refreshCalendarList(userId);
    const settings = getSettings(userId);
    const selected = settings.visibleCalendars?.length
      ? calendars.filter((cal) => settings.visibleCalendars.includes(cal.id))
      : calendars.filter((cal) => cal.primary);

    // El calendario destino de las tareas siempre se sincroniza, aunque este oculto.
    const target = targetCalendarId(userId);
    const targetCal = calendars.find((cal) => cal.id === target || (target === 'primary' && cal.primary));
    if (targetCal && !selected.some((cal) => cal.id === targetCal.id)) selected.push(targetCal);

    const pulled = { changed: 0, removed: 0 };
    const errors = [];
    for (const cal of selected) {
      try {
        const result = await pullCalendar(userId, cal.id, { full });
        pulled.changed += result.changed;
        pulled.removed += result.removed;
      } catch (err) {
        errors.push({ calendarId: cal.id, message: err.message });
      }
    }

    // Limpia eventos cacheados de calendarios que ya no se muestran.
    const sync = getSync(userId);
    const activeIds = new Set(selected.map((cal) => cal.id));
    for (const [key, event] of Object.entries(sync.events)) {
      if (!activeIds.has(event.calendarId)) delete sync.events[key];
    }
    for (const id of Object.keys(sync.calendars)) {
      if (!activeIds.has(id)) delete sync.calendars[id];
    }

    const reconciled = reconcileMirroredEvents(userId);
    const pushed = await pushTasks(userId);

    sync.lastPullAt = new Date().toISOString();
    save();

    return { calendars: calendars.length, pulled, reconciled, pushed, errors, at: sync.lastPullAt };
  })().finally(() => inFlight.delete(userId));

  inFlight.set(userId, promise);
  return promise;
}

/** Eventos cacheados dentro de un rango, listos para el frontend. */
export function eventsInRange(userId, fromIso, toIso) {
  const sync = getSync(userId);
  const settings = getSettings(userId);
  const visible = new Set(settings.visibleCalendars || []);
  const from = new Date(fromIso).getTime();
  const to = new Date(toIso).getTime();

  return Object.values(sync.events)
    .filter((event) => {
      if (visible.size && !visible.has(event.calendarId)) return false;
      if (!event.start) return false;
      const startMs = new Date(event.allDay ? `${event.start}T00:00:00` : event.start).getTime();
      const endMs = event.end
        ? new Date(event.allDay ? `${event.end}T00:00:00` : event.end).getTime()
        : startMs + 3600000;
      return endMs > from && startMs < to;
    })
    .sort((a, b) => String(a.start).localeCompare(String(b.start)));
}

// --- Empuje diferido ----------------------------------------------------
// Tras cada cambio en una tarea el cliente responde al instante y el envio a
// Google ocurre en segundo plano, agrupando rafagas de ediciones.
const pushTimers = new Map();

export function schedulePush(userId, delayMs = 1500) {
  if (!isConnected(userId)) return;
  clearTimeout(pushTimers.get(userId));
  pushTimers.set(
    userId,
    setTimeout(() => {
      pushTimers.delete(userId);
      pushTasks(userId).catch((err) => console.error('[sync] push en segundo plano fallido:', err.message));
    }, delayMs),
  );
}
