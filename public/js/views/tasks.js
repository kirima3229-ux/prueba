// Vista "Tareas": todo el backlog, dividido por área, con búsqueda y filtros.

import { setState, state, visibleTasks } from '../state.js';
import { panel, taskList } from '../components.js';
import { clear, debounce, el } from '../util.js';

function matchesSearch(task, needle) {
  if (!needle) return true;
  const haystack = `${task.title} ${task.notes} ${task.tags.join(' ')}`.toLowerCase();
  return haystack.includes(needle);
}

function toolbar() {
  const search = el('input', {
    class: 'search',
    type: 'text',
    placeholder: 'Buscar por título, nota o etiqueta…',
    value: state.search,
    onInput: debounce((event) => setState({ search: event.target.value.trim().toLowerCase() }), 200),
  });

  const doneToggle = el('button', {
    class: `btn${state.showDone ? ' btn-primary' : ''}`,
    text: state.showDone ? 'Ver solo pendientes' : 'Mostrar completadas',
    onClick: () => setState({ showDone: !state.showDone }),
  });

  return el('div', { class: 'toolbar' }, [search, doneToggle]);
}

function group(tasks, refresh, title) {
  const pending = tasks.filter((task) => task.status !== 'done');
  const done = tasks.filter((task) => task.status === 'done');
  const shown = state.showDone ? [...pending, ...done] : pending;
  return panel(title, pending.length, taskList(shown, refresh, 'Sin tareas aquí.'));
}

export function renderTasks(host, refresh) {
  clear(host);

  document.getElementById('view-title').textContent = 'Tareas';
  const all = visibleTasks().filter((task) => matchesSearch(task, state.search));
  const pendingCount = all.filter((task) => task.status !== 'done').length;
  document.getElementById('view-subtitle').textContent = `${pendingCount} pendientes de ${all.length}`;

  host.append(toolbar());

  if (state.area !== 'all') {
    host.append(group(all, refresh, state.area === 'work' ? 'Trabajo' : 'Personal'));
    return;
  }

  host.append(
    el('div', { class: 'task-columns' }, [
      group(all.filter((task) => task.area === 'work'), refresh, 'Trabajo'),
      group(all.filter((task) => task.area === 'personal'), refresh, 'Personal'),
    ]),
  );
}
