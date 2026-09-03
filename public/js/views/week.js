// Vista "Semana": siete columnas con eventos y tareas de cada día.

import { setState, state, visibleTasks } from '../state.js';
import { openDrawer } from '../drawer.js';
import {
  addDays, capitalize, clear, dayKey, el, fmtDayShort, fmtTime, isToday, startOfWeek,
} from '../util.js';

function itemsForDay(date) {
  const key = dayKey(date);
  const items = [];

  for (const event of state.events) {
    if (event.taskId || !event.start) continue;
    const eventKey = event.allDay ? event.start : dayKey(event.start);
    if (eventKey !== key) continue;
    items.push({
      kind: 'event',
      sort: event.allDay ? '' : event.start,
      title: event.summary,
      time: event.allDay ? 'Todo el día' : fmtTime(event.start),
      data: event,
    });
  }

  for (const task of visibleTasks()) {
    const scheduledHere = task.scheduledAt && dayKey(task.scheduledAt) === key;
    const dueHere = !task.scheduledAt && task.dueDate === key;
    if (!scheduledHere && !dueHere) continue;
    items.push({
      kind: 'task',
      sort: scheduledHere ? task.scheduledAt : 'zz',
      title: task.title,
      time: scheduledHere ? fmtTime(task.scheduledAt) : 'Sin hora',
      data: task,
    });
  }

  return items.sort((a, b) => String(a.sort).localeCompare(String(b.sort)));
}

function dayColumn(date) {
  const weekend = [0, 6].includes(date.getDay());
  const classes = ['day-col'];
  if (isToday(date)) classes.push('is-today');
  if (weekend) classes.push('is-weekend');

  const body = el('div', { class: 'day-body' });

  for (const item of itemsForDay(date)) {
    const classNames = ['chip'];
    if (item.kind === 'event') classNames.push('is-event');
    else {
      classNames.push(`is-task-${item.data.area}`);
      if (item.data.status === 'done') classNames.push('is-done');
    }

    body.append(
      el(
        'div',
        {
          class: classNames.join(' '),
          title: item.title,
          onClick: () => {
            if (item.kind === 'task') openDrawer(item.data);
            else if (item.data.htmlLink) window.open(item.data.htmlLink, '_blank', 'noopener');
          },
        },
        [
          el('div', { class: 'chip-time', text: item.time }),
          el('div', { class: 'chip-title', text: item.title }),
        ],
      ),
    );
  }

  body.append(
    el('button', {
      class: 'icon-btn',
      text: '+',
      title: 'Nueva tarea este día',
      style: { alignSelf: 'flex-start', marginTop: '2px' },
      onClick: () => {
        const at = new Date(date);
        at.setHours(state.settings?.dayStartHour ?? 9, 0, 0, 0);
        openDrawer(null, { scheduledAt: at.toISOString(), dueDate: dayKey(date) });
      },
    }),
  );

  return el('div', { class: classes.join(' ') }, [
    el(
      'div',
      {
        class: 'day-head',
        style: { cursor: 'pointer' },
        title: 'Ver este día',
        onClick: () => setState({ view: 'today', anchorDate: new Date(date) }),
      },
      [
        el('span', { class: 'day-name', text: fmtDayShort(date).replace('.', '') }),
        el('span', { class: 'day-num', text: String(date.getDate()) }),
      ],
    ),
    body,
  ]);
}

export function renderWeek(host) {
  clear(host);
  const monday = startOfWeek(state.anchorDate);
  const sunday = addDays(monday, 6);

  document.getElementById('view-title').textContent = 'Semana';
  const sameMonth = monday.getMonth() === sunday.getMonth();
  const fmt = new Intl.DateTimeFormat('es', { day: 'numeric', month: sameMonth ? undefined : 'short' });
  document.getElementById('view-subtitle').textContent = capitalize(
    `${fmt.format(monday)} – ${new Intl.DateTimeFormat('es', { day: 'numeric', month: 'long', year: 'numeric' }).format(sunday)}`,
  );

  const grid = el('div', { class: 'week' });
  for (let i = 0; i < 7; i++) grid.append(dayColumn(addDays(monday, i)));
  host.append(grid);
}
