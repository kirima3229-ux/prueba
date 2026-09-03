// Arranque de la aplicación: carga de datos, navegación y sincronización.

import { api } from './api.js';
import { setState, state, subscribe } from './state.js';
import { initDrawer, openDrawer } from './drawer.js';
import { renderToday } from './views/today.js';
import { renderWeek } from './views/week.js';
import { renderTasks } from './views/tasks.js';
import { renderSettings } from './views/settings.js';
import { GOOGLE_MARK } from './components.js';
import { addDays, el, startOfWeek, toast, DAY_MS } from './util.js';

const VIEWS = { today: renderToday, week: renderWeek, tasks: renderTasks, settings: renderSettings };
const SYNC_INTERVAL_MS = 3 * 60 * 1000;

// --- Carga de datos ---------------------------------------------------------

function eventWindow() {
  const anchor = state.view === 'week' ? startOfWeek(state.anchorDate) : state.anchorDate;
  return {
    from: new Date(addDays(anchor, -14).setHours(0, 0, 0, 0)).toISOString(),
    to: new Date(addDays(anchor, 45).setHours(23, 59, 59, 999)).toISOString(),
  };
}

async function loadData() {
  const { from, to } = eventWindow();

  const [tasksRes, eventsRes] = await Promise.all([
    api.listTasks(),
    api.listEvents(from, to).catch(() => ({ events: [], lastPullAt: null })),
  ]);

  setState({
    tasks: tasksRes.tasks,
    events: eventsRes.events || [],
    lastSyncAt: eventsRes.lastPullAt || state.lastSyncAt,
  });
}

async function loadCalendars() {
  if (!state.connected) return;
  try {
    const { calendars } = await api.listCalendars();
    setState({ calendars });
  } catch (err) {
    console.warn('No se pudieron cargar los calendarios:', err.message);
  }
}

/** Recarga usada por todas las vistas tras cualquier cambio. */
async function refresh() {
  await loadData();
  render();
}

// --- Sincronización ---------------------------------------------------------

async function runSync({ silent = false } = {}) {
  if (!state.connected || state.syncing) return;

  setState({ syncing: true, syncError: null });
  try {
    const result = await api.sync();
    setState({ lastSyncAt: result.at, syncError: null });
    await loadData();
    await loadCalendars();
    // La sincronización puede fijar ajustes por su cuenta (calendario destino,
    // calendarios visibles la primera vez), así que los releemos.
    const { settings } = await api.getSettings();
    setState({ settings });
    if (!silent) {
      const { created, updated, deleted } = result.pushed;
      const pushedTotal = created + updated + deleted;
      toast(pushedTotal ? `Sincronizado · ${pushedTotal} cambios enviados` : 'Sincronizado');
    }
  } catch (err) {
    setState({ syncError: err.message });
    if (!silent) toast(`Error de sincronización: ${err.message}`, { error: true });
  } finally {
    setState({ syncing: false });
    render();
  }
}

function renderSyncStatus() {
  const dot = document.getElementById('sync-dot');
  const text = document.getElementById('sync-text');
  const button = document.getElementById('sync-now');

  dot.className = 'sync-dot';
  button.disabled = !state.connected || state.syncing;

  if (!state.connected) {
    text.textContent = state.googleConfigured ? 'Google sin conectar' : 'Modo local';
    button.disabled = true;
    return;
  }
  if (state.syncing) {
    dot.classList.add('is-busy');
    text.textContent = 'Sincronizando…';
    return;
  }
  if (state.syncError) {
    dot.classList.add('is-error');
    text.textContent = 'Error al sincronizar';
    return;
  }

  dot.classList.add('is-ok');
  if (!state.lastSyncAt) {
    text.textContent = 'Conectado';
    return;
  }
  const minutes = Math.round((Date.now() - new Date(state.lastSyncAt)) / 60000);
  text.textContent = minutes < 1 ? 'Al día' : `Hace ${minutes} min`;
}

// --- Render -----------------------------------------------------------------

function render() {
  if (!state.ready) return;

  for (const item of document.querySelectorAll('#nav .nav-item')) {
    item.classList.toggle('is-active', item.dataset.view === state.view);
  }
  for (const item of document.querySelectorAll('#area-filter button')) {
    item.classList.toggle('is-active', item.dataset.area === state.area);
  }

  document.getElementById('date-nav').hidden = !['today', 'week'].includes(state.view);

  const host = document.getElementById('view-host');
  (VIEWS[state.view] || renderToday)(host, refresh);
  renderSyncStatus();

  const chip = document.getElementById('user-chip');
  if (state.user && state.user.provider === 'google') {
    chip.hidden = false;
    document.getElementById('user-avatar').src = state.user.picture || '';
    document.getElementById('user-name').textContent = state.user.name;
    document.getElementById('user-email').textContent = state.user.email;
  } else {
    chip.hidden = true;
  }
}

// --- Pantalla de bienvenida -------------------------------------------------

function showWelcome() {
  const welcome = document.getElementById('welcome');
  const actions = document.getElementById('welcome-actions');
  welcome.hidden = false;
  document.getElementById('app').hidden = true;

  const authError = new URLSearchParams(location.search).get('auth_error');
  if (authError) {
    const box = document.getElementById('welcome-error');
    box.hidden = false;
    box.textContent = `No se pudo conectar con Google: ${authError}`;
  }

  actions.replaceChildren();

  if (state.googleConfigured) {
    actions.append(
      el('a', { class: 'google-btn', href: '/auth/google' }, [
        el('span', { html: GOOGLE_MARK }),
        'Continuar con Google',
      ]),
      el('button', {
        class: 'btn btn-ghost btn-block',
        style: { marginTop: '10px' },
        text: 'Entrar sin conectar el calendario',
        onClick: startLocal,
      }),
    );
  } else {
    actions.append(
      el('button', { class: 'btn btn-primary btn-block', text: 'Empezar', onClick: startLocal }),
      el('ol', { class: 'setup-steps', style: { marginTop: '18px' } }, [
        el('li', { html: 'Para sincronizar con Google Calendar, copia <code>.env.example</code> a <code>.env</code> con tus credenciales OAuth.' }),
        el('li', { html: 'Reinicia con <code>npm start</code>: el botón de Google aparecerá aquí.' }),
      ]),
    );
  }
}

async function startLocal() {
  try {
    const { user, settings } = await api.loginLocal();
    setState({ user, settings });
    await boot();
  } catch (err) {
    toast(`No se pudo iniciar: ${err.message}`, { error: true });
  }
}

// --- Navegación y eventos ---------------------------------------------------

function bindChrome() {
  document.getElementById('nav').addEventListener('click', (event) => {
    const button = event.target.closest('.nav-item');
    if (button) setState({ view: button.dataset.view });
  });

  document.getElementById('area-filter').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) setState({ area: button.dataset.area });
  });

  document.getElementById('new-task').addEventListener('click', () => openDrawer(null));
  document.getElementById('sync-now').addEventListener('click', () => runSync());

  const step = () => (state.view === 'week' ? 7 : 1);
  document.getElementById('date-prev').addEventListener('click', () => shift(-step()));
  document.getElementById('date-next').addEventListener('click', () => shift(step()));
  document.getElementById('date-today').addEventListener('click', () => {
    setState({ anchorDate: new Date() });
    refresh();
  });

  document.addEventListener('keydown', (event) => {
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(event.target.tagName);
    if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

    if (event.key === 'n') {
      event.preventDefault();
      openDrawer(null);
    } else if (event.key === 't') {
      setState({ view: 'today', anchorDate: new Date() });
    } else if (event.key === 'w') {
      setState({ view: 'week' });
    } else if (event.key === 'a') {
      setState({ view: 'tasks' });
    } else if (event.key === 'r') {
      runSync();
    }
  });
}

async function shift(days) {
  const next = addDays(state.anchorDate, days);
  setState({ anchorDate: next });
  // Solo recargamos eventos si nos salimos de la ventana ya descargada.
  if (Math.abs(next - new Date()) > 30 * DAY_MS) await loadData();
  render();
}

// --- Arranque ---------------------------------------------------------------

async function boot() {
  const me = await api.me();

  setState({
    googleConfigured: me.googleConfigured,
    user: me.user,
    connected: me.connected,
    settings: me.settings,
  });

  if (!me.user) return showWelcome();

  document.getElementById('welcome').hidden = true;
  document.getElementById('app').hidden = false;

  // La zona horaria del navegador manda: es la que se usa al crear eventos.
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (browserTz && me.settings?.timeZone !== browserTz) {
    const { settings } = await api.updateSettings({ timeZone: browserTz });
    setState({ settings });
  }

  setState({ ready: true });
  await loadData();
  await loadCalendars();
  render();

  if (state.connected) {
    runSync({ silent: true });
    setInterval(() => runSync({ silent: true }), SYNC_INTERVAL_MS);
  }

  // La línea de "ahora" y el estado de sync se refrescan solos.
  setInterval(() => {
    if (state.view === 'today') render();
    else renderSyncStatus();
  }, 60 * 1000);

  if (new URLSearchParams(location.search).get('connected')) {
    history.replaceState(null, '', '/');
    toast(`Calendario conectado, ${state.user.name.split(' ')[0]}`);
  }
}

subscribe(() => {
  if (state.ready) render();
});

initDrawer(refresh);
bindChrome();
boot().catch((err) => {
  console.error(err);
  document.body.append(el('pre', { style: { padding: '20px', color: 'crimson' }, text: `Error al arrancar: ${err.message}` }));
});

// Acceso desde la consola del navegador para depurar.
window.__organizador = { state, refresh, runSync };
