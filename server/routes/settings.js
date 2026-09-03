import express from 'express';
import { requireAuth } from '../session.js';
import { DEFAULT_SETTINGS, getSettings, setSettings } from '../store.js';
import { schedulePush } from '../sync.js';

export const settingsRouter = express.Router();

settingsRouter.use(requireAuth);

settingsRouter.get('/', (req, res) => {
  res.json({ settings: getSettings(req.userId) });
});

settingsRouter.patch('/', (req, res) => {
  const body = req.body || {};
  const patch = {};

  if (Array.isArray(body.visibleCalendars)) {
    patch.visibleCalendars = body.visibleCalendars.filter((id) => typeof id === 'string').slice(0, 100);
  }
  if (typeof body.pushCalendarId === 'string' && body.pushCalendarId) {
    patch.pushCalendarId = body.pushCalendarId;
  }
  if (typeof body.pushEnabled === 'boolean') patch.pushEnabled = body.pushEnabled;
  if (typeof body.timeZone === 'string' && body.timeZone) patch.timeZone = body.timeZone;

  for (const key of ['dayStartHour', 'dayEndHour']) {
    if (key in body) {
      const hour = Number(body[key]);
      if (Number.isInteger(hour) && hour >= 0 && hour <= 23) patch[key] = hour;
    }
  }
  if ('defaultDurationMin' in body) {
    const minutes = Number(body.defaultDurationMin);
    if (Number.isFinite(minutes)) patch.defaultDurationMin = Math.min(Math.max(Math.round(minutes), 5), 480);
  }

  const previous = getSettings(req.userId);
  const settings = setSettings(req.userId, patch);

  // Cambiar el destino o reactivar el envio obliga a rehacer los eventos espejo.
  if (settings.pushCalendarId !== previous.pushCalendarId || settings.pushEnabled !== previous.pushEnabled) {
    schedulePush(req.userId, 200);
  }

  res.json({ settings, defaults: DEFAULT_SETTINGS });
});
