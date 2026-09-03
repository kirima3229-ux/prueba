// Piezas de UI reutilizadas por varias vistas.

import { api } from './api.js';
import { openDrawer } from './drawer.js';
import { el, fmtTime, relativeDay, toast, fmtDuration } from './util.js';

export const AREA_LABEL = { work: 'Trabajo', personal: 'Personal' };

/** Logotipo oficial de Google para los botones de conexión. */
export const GOOGLE_MARK = `<svg viewBox="0 0 48 48" aria-hidden="true">
  <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.2 17.6 9.5 24 9.5z"/>
  <path fill="#4285F4" d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9.1h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.2 5.6c4.2-3.9 6.7-9.6 6.7-17z"/>
  <path fill="#FBBC05" d="M10.4 28.7c-.5-1.4-.8-2.9-.8-4.7s.3-3.3.8-4.7l-7.8-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.8-6.1z"/>
  <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.2-5.6c-2 1.4-4.7 2.3-8.7 2.3-6.4 0-11.7-3.7-13.6-9.2l-7.8 6.1C6.5 42.6 14.6 48 24 48z"/>
</svg>`;
const PRIORITY_LABEL = { high: 'Alta', normal: '', low: 'Baja' };

function isOverdue(task) {
  if (task.status === 'done' || !task.dueDate) return false;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return new Date(`${task.dueDate}T23:59:59`) < today;
}

function metaFor(task) {
  const pills = [];

  pills.push(el('span', { class: `pill pill-${task.area}`, text: AREA_LABEL[task.area] }));

  if (task.priority === 'high') pills.push(el('span', { class: 'pill pill-high', text: 'Alta' }));

  if (task.scheduledAt) {
    pills.push(el('span', { class: 'pill', text: `${fmtTime(task.scheduledAt)} · ${fmtDuration(task.durationMin)}` }));
  }

  if (task.dueDate) {
    pills.push(
      el('span', {
        class: `pill${isOverdue(task) ? ' pill-overdue' : ''}`,
        text: `Vence ${relativeDay(task.dueDate)}`,
      }),
    );
  }

  if (task.google?.eventId) pills.push(el('span', { class: 'pill pill-synced', text: 'En Calendar' }));

  for (const tag of task.tags || []) pills.push(el('span', { class: 'pill', text: `#${tag}` }));

  return pills;
}

/** Fila de tarea con casilla, título y metadatos. */
export function taskRow(task, refresh) {
  const check = el('button', {
    class: 'check',
    type: 'button',
    text: '✓',
    title: task.status === 'done' ? 'Marcar como pendiente' : 'Marcar como hecha',
    onClick: async (event) => {
      event.stopPropagation();
      try {
        await api.updateTask(task.id, { status: task.status === 'done' ? 'todo' : 'done' });
        await refresh();
      } catch (err) {
        toast(`No se pudo actualizar: ${err.message}`, { error: true });
      }
    },
  });

  return el(
    'div',
    {
      class: `task${task.status === 'done' ? ' is-done' : ''}`,
      onClick: () => openDrawer(task),
    },
    [
      check,
      el('div', { class: 'task-main' }, [
        el('div', { class: 'task-title', text: task.title }),
        el('div', { class: 'task-meta' }, metaFor(task)),
      ]),
    ],
  );
}

export function panel(title, count, body, action) {
  return el('section', { class: 'panel' }, [
    el('header', { class: 'panel-head' }, [
      el('h2', { text: title }),
      count === null || count === undefined ? null : el('span', { class: 'count', text: String(count) }),
      action || null,
    ]),
    el('div', { class: 'panel-body' }, [body]),
  ]);
}

export function emptyState(message) {
  return el('div', { class: 'empty', text: message });
}

export function taskList(tasks, refresh, emptyMessage) {
  if (!tasks.length) return emptyState(emptyMessage);
  return el('div', {}, tasks.map((task) => taskRow(task, refresh)));
}
