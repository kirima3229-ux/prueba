// Cliente HTTP: una sola puerta de entrada al backend.

async function request(url, options = {}) {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const error = new Error(data?.error || `HTTP ${res.status}`);
    error.status = res.status;
    throw error;
  }
  return data;
}

const qs = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  }
  const str = search.toString();
  return str ? `?${str}` : '';
};

export const api = {
  me: () => request('/api/me'),
  loginLocal: () => request('/auth/local', { method: 'POST' }),
  logout: () => request('/auth/logout', { method: 'POST' }),

  listTasks: (params) => request(`/api/tasks${qs(params)}`),
  createTask: (task) => request('/api/tasks', { method: 'POST', body: task }),
  updateTask: (id, patch) => request(`/api/tasks/${id}`, { method: 'PATCH', body: patch }),
  deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),

  listCalendars: (refresh) => request(`/api/calendar/calendars${refresh ? '?refresh=1' : ''}`),
  listEvents: (from, to) => request(`/api/calendar/events${qs({ from, to })}`),
  freeSlots: (date, minMinutes) => request(`/api/calendar/free-slots${qs({ date, minMinutes })}`),
  sync: (full = false) => request('/api/calendar/sync', { method: 'POST', body: { full } }),

  getSettings: () => request('/api/settings'),
  updateSettings: (patch) => request('/api/settings', { method: 'PATCH', body: patch }),
};
