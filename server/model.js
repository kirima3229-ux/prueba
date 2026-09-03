import crypto from 'node:crypto';

export const AREAS = ['work', 'personal'];
export const PRIORITIES = ['low', 'normal', 'high'];
export const STATUSES = ['todo', 'done'];

export function newId() {
  return crypto.randomUUID();
}

function clampString(value, max) {
  if (typeof value !== 'string') return '';
  return value.trim().slice(0, max);
}

function parseIsoOrNull(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function parseDateOnlyOrNull(value) {
  if (!value) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value).trim())) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : String(value).trim();
}

function oneOf(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback;
}

export function emptyTask() {
  const now = new Date().toISOString();
  return {
    id: newId(),
    title: '',
    notes: '',
    area: 'work',
    priority: 'normal',
    status: 'todo',
    tags: [],
    dueDate: null,
    scheduledAt: null,
    durationMin: 30,
    order: Date.now(),
    createdAt: now,
    updatedAt: now,
    completedAt: null,
    google: null,
  };
}

/**
 * Aplica un patch del cliente sobre una tarea, saneando cada campo.
 * Solo toca las claves presentes en el patch.
 */
export function applyTaskPatch(task, patch = {}) {
  const next = { ...task };

  if ('title' in patch) next.title = clampString(patch.title, 300);
  if ('notes' in patch) next.notes = clampString(patch.notes, 5000);
  if ('area' in patch) next.area = oneOf(patch.area, AREAS, next.area);
  if ('priority' in patch) next.priority = oneOf(patch.priority, PRIORITIES, next.priority);
  if ('dueDate' in patch) next.dueDate = parseDateOnlyOrNull(patch.dueDate);
  if ('scheduledAt' in patch) next.scheduledAt = parseIsoOrNull(patch.scheduledAt);
  if ('order' in patch && Number.isFinite(Number(patch.order))) next.order = Number(patch.order);

  if ('durationMin' in patch) {
    const minutes = Math.round(Number(patch.durationMin));
    next.durationMin = Number.isFinite(minutes) ? Math.min(Math.max(minutes, 5), 24 * 60) : next.durationMin;
  }

  if ('tags' in patch) {
    const tags = Array.isArray(patch.tags) ? patch.tags : [];
    next.tags = [...new Set(tags.map((tag) => clampString(tag, 40)).filter(Boolean))].slice(0, 12);
  }

  if ('status' in patch) {
    const status = oneOf(patch.status, STATUSES, next.status);
    if (status !== next.status) {
      next.completedAt = status === 'done' ? new Date().toISOString() : null;
    }
    next.status = status;
  }

  next.updatedAt = new Date().toISOString();
  return next;
}

/**
 * Huella de los campos que se reflejan en Google Calendar. Si no cambia,
 * no hace falta reescribir el evento.
 */
export function taskSignature(task) {
  return [
    task.title,
    task.scheduledAt || '',
    task.durationMin,
    task.status,
    task.area,
    task.notes,
  ].join('|');
}

export function taskEndsAt(task) {
  if (!task.scheduledAt) return null;
  return new Date(new Date(task.scheduledAt).getTime() + task.durationMin * 60000).toISOString();
}
