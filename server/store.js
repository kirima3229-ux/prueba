import fs from 'node:fs';
import path from 'node:path';
import { config } from './config.js';

const FILE = path.join(config.dataDir, 'db.json');
const TMP = FILE + '.tmp';

const EMPTY = () => ({
  version: 1,
  users: {},      // userId -> perfil + tokens de Google
  tasks: {},      // userId -> [task]
  settings: {},   // userId -> preferencias
  sync: {},       // userId -> { calendars, events, lastPullAt }
});

function read() {
  try {
    if (!fs.existsSync(FILE)) return EMPTY();
    const parsed = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    return { ...EMPTY(), ...parsed };
  } catch (err) {
    console.error('[store] db.json ilegible, se parte de cero:', err.message);
    // No borramos el original: lo movemos para poder inspeccionarlo.
    try {
      fs.renameSync(FILE, FILE + '.corrupt-' + Date.now());
    } catch {}
    return EMPTY();
  }
}

let db = read();
let writeTimer = null;
let writing = false;
let dirtyWhileWriting = false;

function writeNow() {
  if (writing) {
    dirtyWhileWriting = true;
    return;
  }
  writing = true;
  try {
    fs.mkdirSync(config.dataDir, { recursive: true });
    fs.writeFileSync(TMP, JSON.stringify(db, null, 2));
    fs.renameSync(TMP, FILE); // rename atomico: nunca dejamos un db.json a medias
  } catch (err) {
    console.error('[store] fallo al guardar:', err.message);
  } finally {
    writing = false;
    if (dirtyWhileWriting) {
      dirtyWhileWriting = false;
      writeNow();
    }
  }
}

// Agrupa escrituras rapidas seguidas en una sola pasada a disco.
export function save() {
  if (writeTimer) return;
  writeTimer = setTimeout(() => {
    writeTimer = null;
    writeNow();
  }, 50);
}

export function flush() {
  if (writeTimer) {
    clearTimeout(writeTimer);
    writeTimer = null;
  }
  writeNow();
}

export function getDb() {
  return db;
}

export const DEFAULT_SETTINGS = {
  visibleCalendars: [],       // ids de calendarios de Google que se muestran
  pushCalendarId: 'primary',  // donde se escriben las tareas agendadas
  pushEnabled: true,          // exportar tareas agendadas a Google Calendar
  dayStartHour: 8,
  dayEndHour: 20,
  defaultDurationMin: 30,
  timeZone: 'UTC',
};

export function getUser(userId) {
  return db.users[userId] || null;
}

export function upsertUser(user) {
  const existing = db.users[user.id];
  db.users[user.id] = { ...existing, ...user, updatedAt: new Date().toISOString() };
  if (!existing) db.users[user.id].createdAt = db.users[user.id].updatedAt;
  save();
  return db.users[user.id];
}

export function getTasks(userId) {
  if (!db.tasks[userId]) db.tasks[userId] = [];
  return db.tasks[userId];
}

export function setTasks(userId, tasks) {
  db.tasks[userId] = tasks;
  save();
}

export function getSettings(userId) {
  return { ...DEFAULT_SETTINGS, ...(db.settings[userId] || {}) };
}

export function setSettings(userId, patch) {
  db.settings[userId] = { ...getSettings(userId), ...patch };
  save();
  return db.settings[userId];
}

export function getSync(userId) {
  if (!db.sync[userId]) db.sync[userId] = { calendars: {}, events: {}, lastPullAt: null };
  return db.sync[userId];
}

process.on('exit', flush);
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    flush();
    process.exit(0);
  });
}
