import path from 'node:path';
import express from 'express';
import { ROOT, config, googleConfigured } from './config.js';
import { sessionMiddleware } from './session.js';
import { authRouter } from './routes/auth.js';
import { tasksRouter } from './routes/tasks.js';
import { calendarRouter } from './routes/calendar.js';
import { settingsRouter } from './routes/settings.js';
import { getDb } from './store.js';
import { isConnected, syncAll } from './sync.js';
import { GoogleError } from './google.js';

const app = express();

app.disable('x-powered-by');
app.use(express.json({ limit: '1mb' }));
app.use(sessionMiddleware);

app.use(authRouter);
app.use('/api/tasks', tasksRouter);
app.use('/api/calendar', calendarRouter);
app.use('/api/settings', settingsRouter);

app.get('/api/health', (req, res) => {
  res.json({ ok: true, googleConfigured, version: 1 });
});

app.use(express.static(path.join(ROOT, 'public'), { extensions: ['html'] }));

// Cualquier ruta no-API cae en la SPA.
app.get(/^\/(?!api\/|auth\/).*/, (req, res) => {
  res.sendFile(path.join(ROOT, 'public', 'index.html'));
});

app.use((req, res) => res.status(404).json({ error: 'no_encontrado' }));

app.use((err, req, res, _next) => {
  const status = err instanceof GoogleError ? err.status || 502 : 500;
  if (status >= 500) console.error('[error]', err);
  res.status(status).json({ error: err.message || 'error_interno' });
});

app.listen(config.port, () => {
  console.log(`\n  Organizador escuchando en http://localhost:${config.port}`);
  console.log(
    googleConfigured
      ? '  Google Calendar: configurado. Conecta tu cuenta desde Ajustes.\n'
      : '  Google Calendar: sin configurar (modo local). Ver README.md paso 2.\n',
  );
});

// Sincronizacion periodica en segundo plano de todas las cuentas conectadas.
const SYNC_INTERVAL_MS = 5 * 60 * 1000;
setInterval(() => {
  for (const userId of Object.keys(getDb().users)) {
    if (!isConnected(userId)) continue;
    syncAll(userId).catch((err) => console.error(`[sync] ${userId}:`, err.message));
  }
}, SYNC_INTERVAL_MS).unref();
