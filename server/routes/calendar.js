import express from 'express';
import { requireAuth } from '../session.js';
import { getSync, getSettings } from '../store.js';
import { eventsInRange, isConnected, refreshCalendarList, syncAll } from '../sync.js';

export const calendarRouter = express.Router();

calendarRouter.use(requireAuth);

calendarRouter.get('/calendars', async (req, res, next) => {
  if (!isConnected(req.userId)) return res.json({ calendars: [], connected: false });

  const sync = getSync(req.userId);
  const cached = sync.calendarList;
  const fresh = cached && sync.calendarListAt && Date.now() - new Date(sync.calendarListAt).getTime() < 10 * 60 * 1000;

  if (fresh && req.query.refresh !== '1') {
    return res.json({ calendars: cached, connected: true, cached: true });
  }

  try {
    res.json({ calendars: await refreshCalendarList(req.userId), connected: true, cached: false });
  } catch (err) {
    next(err);
  }
});

calendarRouter.get('/events', (req, res) => {
  const { from, to } = req.query;
  if (!from || !to) return res.status(400).json({ error: 'from_y_to_requeridos' });

  res.json({
    events: eventsInRange(req.userId, String(from), String(to)),
    lastPullAt: getSync(req.userId).lastPullAt,
    connected: isConnected(req.userId),
  });
});

calendarRouter.post('/sync', async (req, res, next) => {
  if (!isConnected(req.userId)) {
    return res.status(400).json({ error: 'google_no_conectado' });
  }
  try {
    res.json(await syncAll(req.userId, { full: req.body?.full === true }));
  } catch (err) {
    next(err);
  }
});

/** Huecos libres del dia dentro del horario de trabajo configurado. */
calendarRouter.get('/free-slots', (req, res) => {
  const date = String(req.query.date || new Date().toISOString().slice(0, 10));
  const settings = getSettings(req.userId);
  const minMinutes = Math.max(5, Number(req.query.minMinutes) || 30);

  const dayStart = new Date(`${date}T00:00:00`);
  dayStart.setHours(settings.dayStartHour, 0, 0, 0);
  const dayEnd = new Date(`${date}T00:00:00`);
  dayEnd.setHours(settings.dayEndHour, 0, 0, 0);

  const busy = eventsInRange(req.userId, dayStart.toISOString(), dayEnd.toISOString())
    .filter((event) => !event.allDay)
    .map((event) => [new Date(event.start).getTime(), new Date(event.end || event.start).getTime()])
    .sort((a, b) => a[0] - b[0]);

  const slots = [];
  let cursor = dayStart.getTime();
  for (const [start, end] of busy) {
    if (start - cursor >= minMinutes * 60000) {
      slots.push({ start: new Date(cursor).toISOString(), end: new Date(start).toISOString() });
    }
    cursor = Math.max(cursor, end);
  }
  if (dayEnd.getTime() - cursor >= minMinutes * 60000) {
    slots.push({ start: new Date(cursor).toISOString(), end: dayEnd.toISOString() });
  }

  res.json({ date, slots });
});
