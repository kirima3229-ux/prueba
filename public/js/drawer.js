// Panel lateral para crear y editar tareas.

import { api } from './api.js';
import { state } from './state.js';
import { fromLocalInput, toLocalInput, toast } from './util.js';

const dom = {};
let current = null;      // tarea en edición, o null si es nueva
let onSaved = () => {};

function pickSegment(group, value) {
  for (const button of group.querySelectorAll('button')) {
    button.classList.toggle('is-active', button.dataset.value === value);
  }
}

function readSegment(group) {
  return group.querySelector('.is-active')?.dataset.value;
}

function bindSegment(group) {
  group.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) pickSegment(group, button.dataset.value);
  });
}

export function initDrawer(refresh) {
  onSaved = refresh;

  Object.assign(dom, {
    root: document.getElementById('drawer'),
    backdrop: document.getElementById('drawer-backdrop'),
    title: document.getElementById('drawer-title'),
    form: document.getElementById('task-form'),
    fTitle: document.getElementById('f-title'),
    area: document.getElementById('f-area'),
    priority: document.getElementById('f-priority'),
    due: document.getElementById('f-due'),
    duration: document.getElementById('f-duration'),
    scheduled: document.getElementById('f-scheduled'),
    scheduledHint: document.getElementById('f-scheduled-hint'),
    tags: document.getElementById('f-tags'),
    notes: document.getElementById('f-notes'),
    submit: document.getElementById('f-submit'),
    remove: document.getElementById('f-delete'),
    gcal: document.getElementById('f-gcal'),
  });

  bindSegment(dom.area);
  bindSegment(dom.priority);

  dom.backdrop.addEventListener('click', closeDrawer);
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('f-cancel').addEventListener('click', closeDrawer);
  dom.form.addEventListener('submit', save);
  dom.remove.addEventListener('click', remove);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !dom.root.hidden) closeDrawer();
  });
}

export function openDrawer(task = null, defaults = {}) {
  current = task;

  dom.title.textContent = task ? 'Editar tarea' : 'Nueva tarea';
  dom.submit.textContent = task ? 'Guardar cambios' : 'Crear tarea';
  dom.remove.hidden = !task;

  const source = task || {
    title: '',
    notes: '',
    area: state.area === 'personal' ? 'personal' : 'work',
    priority: 'normal',
    tags: [],
    dueDate: null,
    scheduledAt: null,
    durationMin: state.settings?.defaultDurationMin || 30,
    ...defaults,
  };

  dom.fTitle.value = source.title || '';
  dom.notes.value = source.notes || '';
  dom.due.value = source.dueDate || '';
  dom.duration.value = source.durationMin || 30;
  dom.scheduled.value = toLocalInput(source.scheduledAt);
  dom.tags.value = (source.tags || []).join(', ');
  pickSegment(dom.area, source.area || 'work');
  pickSegment(dom.priority, source.priority || 'normal');

  dom.scheduledHint.textContent = state.connected
    ? 'Al poner fecha y hora se crea un evento en tu Google Calendar.'
    : 'Conecta Google Calendar en Ajustes para que este bloque aparezca también allí.';

  const link = task?.google?.eventId
    ? `https://calendar.google.com/calendar/u/0/r/eventedit/${btoa(`${task.google.eventId} ${task.google.calendarId}`).replace(/=+$/, '')}`
    : null;
  dom.gcal.hidden = !link;
  if (link) dom.gcal.href = link;

  dom.root.hidden = false;
  dom.backdrop.hidden = false;
  setTimeout(() => dom.fTitle.focus(), 30);
}

export function closeDrawer() {
  dom.root.hidden = true;
  dom.backdrop.hidden = true;
  current = null;
}

function readForm() {
  return {
    title: dom.fTitle.value.trim(),
    notes: dom.notes.value.trim(),
    area: readSegment(dom.area),
    priority: readSegment(dom.priority),
    dueDate: dom.due.value || null,
    durationMin: Number(dom.duration.value) || 30,
    scheduledAt: fromLocalInput(dom.scheduled.value),
    tags: dom.tags.value.split(',').map((tag) => tag.trim()).filter(Boolean),
  };
}

async function save(event) {
  event.preventDefault();
  const payload = readForm();
  if (!payload.title) return dom.fTitle.focus();

  dom.submit.disabled = true;
  try {
    if (current) {
      await api.updateTask(current.id, payload);
      toast('Tarea actualizada');
    } else {
      await api.createTask(payload);
      toast(payload.scheduledAt ? 'Tarea creada y agendada' : 'Tarea creada');
    }
    closeDrawer();
    await onSaved();
  } catch (err) {
    toast(`No se pudo guardar: ${err.message}`, { error: true });
  } finally {
    dom.submit.disabled = false;
  }
}

async function remove() {
  if (!current) return;
  if (!confirm(`¿Eliminar "${current.title}"?`)) return;

  try {
    await api.deleteTask(current.id);
    toast('Tarea eliminada');
    closeDrawer();
    await onSaved();
  } catch (err) {
    toast(`No se pudo eliminar: ${err.message}`, { error: true });
  }
}
