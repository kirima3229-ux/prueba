import express from 'express';
import { applyTaskPatch, emptyTask } from '../model.js';
import { getTasks, setTasks } from '../store.js';
import { deleteTaskEvent, isConnected, schedulePush } from '../sync.js';
import { requireAuth } from '../session.js';

export const tasksRouter = express.Router();

tasksRouter.use(requireAuth);

function sortTasks(tasks) {
  const rank = { high: 0, normal: 1, low: 2 };
  return [...tasks].sort((a, b) => {
    if (a.status !== b.status) return a.status === 'done' ? 1 : -1;
    if (a.scheduledAt && b.scheduledAt) return a.scheduledAt.localeCompare(b.scheduledAt);
    if (a.scheduledAt) return -1;
    if (b.scheduledAt) return 1;
    if (a.dueDate !== b.dueDate) return (a.dueDate || '9999').localeCompare(b.dueDate || '9999');
    if (rank[a.priority] !== rank[b.priority]) return rank[a.priority] - rank[b.priority];
    return a.order - b.order;
  });
}

tasksRouter.get('/', (req, res) => {
  const { area, status, q, from, to } = req.query;
  let tasks = getTasks(req.userId);

  if (area && area !== 'all') tasks = tasks.filter((task) => task.area === area);
  if (status && status !== 'all') tasks = tasks.filter((task) => task.status === status);

  if (q) {
    const needle = String(q).toLowerCase();
    tasks = tasks.filter(
      (task) =>
        task.title.toLowerCase().includes(needle) ||
        task.notes.toLowerCase().includes(needle) ||
        task.tags.some((tag) => tag.toLowerCase().includes(needle)),
    );
  }

  // Rango sobre el momento agendado; las tareas sin agendar se filtran por fecha limite.
  if (from || to) {
    const fromMs = from ? new Date(String(from)).getTime() : -Infinity;
    const toMs = to ? new Date(String(to)).getTime() : Infinity;
    tasks = tasks.filter((task) => {
      const ref = task.scheduledAt || (task.dueDate ? `${task.dueDate}T12:00:00` : null);
      if (!ref) return false;
      const ms = new Date(ref).getTime();
      return ms >= fromMs && ms <= toMs;
    });
  }

  res.json({ tasks: sortTasks(tasks) });
});

tasksRouter.post('/', (req, res) => {
  const body = req.body || {};
  if (!String(body.title || '').trim()) {
    return res.status(400).json({ error: 'titulo_requerido' });
  }

  const task = applyTaskPatch(emptyTask(), body);
  const tasks = getTasks(req.userId);
  tasks.push(task);
  setTasks(req.userId, tasks);
  schedulePush(req.userId);

  res.status(201).json({ task });
});

tasksRouter.patch('/:id', (req, res) => {
  const tasks = getTasks(req.userId);
  const index = tasks.findIndex((task) => task.id === req.params.id);
  if (index === -1) return res.status(404).json({ error: 'tarea_no_encontrada' });

  tasks[index] = applyTaskPatch(tasks[index], req.body || {});
  setTasks(req.userId, tasks);
  schedulePush(req.userId);

  res.json({ task: tasks[index] });
});

tasksRouter.delete('/:id', async (req, res) => {
  const tasks = getTasks(req.userId);
  const index = tasks.findIndex((task) => task.id === req.params.id);
  if (index === -1) return res.status(404).json({ error: 'tarea_no_encontrada' });

  const [removed] = tasks.splice(index, 1);
  setTasks(req.userId, tasks);

  // Si tenia evento espejo hay que borrarlo en Google antes de olvidar la tarea.
  if (removed.google?.eventId && isConnected(req.userId)) {
    try {
      await deleteTaskEvent(req.userId, removed);
    } catch (err) {
      console.error('[tasks] no se pudo borrar el evento en Google:', err.message);
    }
  }

  res.json({ ok: true, id: removed.id });
});

/** Cambio de orden en bloque tras arrastrar y soltar. */
tasksRouter.post('/reorder', (req, res) => {
  const ids = Array.isArray(req.body?.ids) ? req.body.ids : [];
  const tasks = getTasks(req.userId);
  const position = new Map(ids.map((id, index) => [id, index]));

  for (const task of tasks) {
    if (position.has(task.id)) task.order = position.get(task.id);
  }
  setTasks(req.userId, tasks);
  res.json({ ok: true });
});
