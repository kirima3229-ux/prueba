// Estado global mínimo con suscriptores. Sin framework: una sola fuente de verdad.

const listeners = new Set();

export const state = {
  ready: false,
  googleConfigured: false,
  connected: false,
  user: null,
  settings: null,

  view: 'today',
  area: 'all',          // 'all' | 'work' | 'personal'
  anchorDate: new Date(),  // día (vista Hoy) o semana (vista Semana) que se muestra

  tasks: [],
  events: [],
  calendars: [],

  search: '',
  showDone: false,
  syncing: false,
  lastSyncAt: null,
  syncError: null,
};

export function setState(patch) {
  Object.assign(state, patch);
  for (const listener of listeners) listener(state);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Tareas ya filtradas por el área activa. */
export function visibleTasks() {
  return state.area === 'all' ? state.tasks : state.tasks.filter((task) => task.area === state.area);
}
