// Utilidades compartidas: DOM, fechas y formato.

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'style') Object.assign(node.style, value);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

// --- Fechas ----------------------------------------------------------------

export const DAY_MS = 24 * 60 * 60 * 1000;

/** Clave local YYYY-MM-DD (no UTC: respeta la zona del navegador). */
export function dayKey(date) {
  const d = new Date(date);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function startOfDay(date) {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function endOfDay(date) {
  const d = startOfDay(date);
  d.setDate(d.getDate() + 1);
  return d;
}

/** Lunes de la semana que contiene `date`. */
export function startOfWeek(date) {
  const d = startOfDay(date);
  const offset = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - offset);
  return d;
}

export function addDays(date, days) {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

export function isSameDay(a, b) {
  return dayKey(a) === dayKey(b);
}

export function isToday(date) {
  return isSameDay(date, new Date());
}

/** Valor para <input type="datetime-local"> en hora local. */
export function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

const timeFmt = new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' });
const dayFmt = new Intl.DateTimeFormat('es', { weekday: 'long', day: 'numeric', month: 'long' });
const shortDayFmt = new Intl.DateTimeFormat('es', { weekday: 'short' });
const monthFmt = new Intl.DateTimeFormat('es', { month: 'long', year: 'numeric' });

export const fmtTime = (value) => timeFmt.format(new Date(value));
export const fmtDayLong = (value) => dayFmt.format(new Date(value));
export const fmtDayShort = (value) => shortDayFmt.format(new Date(value));
export const fmtMonth = (value) => monthFmt.format(new Date(value));

export function capitalize(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

export function fmtDuration(minutes) {
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** "hoy", "manana", "hace 2 dias"... a partir de una fecha YYYY-MM-DD. */
export function relativeDay(dateStr) {
  const target = startOfDay(new Date(`${dateStr}T12:00:00`));
  const diff = Math.round((target - startOfDay(new Date())) / DAY_MS);
  if (diff === 0) return 'hoy';
  if (diff === 1) return 'mañana';
  if (diff === -1) return 'ayer';
  if (diff < 0) return `hace ${Math.abs(diff)} días`;
  if (diff <= 7) return `en ${diff} días`;
  return new Intl.DateTimeFormat('es', { day: 'numeric', month: 'short' }).format(target);
}

export function debounce(fn, ms = 250) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function toast(message, { error = false, ms = 3000 } = {}) {
  const host = document.getElementById('toasts');
  const node = el('div', { class: `toast${error ? ' is-error' : ''}`, text: message });
  host.append(node);
  setTimeout(() => node.remove(), ms);
}
