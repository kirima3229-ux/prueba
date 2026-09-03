// Vista "Hoy": línea de tiempo del día + bandejas laterales.

import { state, visibleTasks } from '../state.js';
import { openDrawer } from '../drawer.js';
import { emptyState, panel, taskList } from '../components.js';
import {
  addDays, capitalize, clear, dayKey, el, endOfDay, fmtDayLong, fmtTime,
  fmtDuration, isToday, startOfDay,
} from '../util.js';

const HOUR_HEIGHT = 54; // px por hora en la línea de tiempo

/** Reparte en carriles los bloques que se solapan para que ninguno tape a otro. */
function assignLanes(blocks) {
  const sorted = [...blocks].sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);
  const clusters = [];
  let cluster = [];
  let clusterEnd = -Infinity;

  for (const block of sorted) {
    if (block.startMs >= clusterEnd && cluster.length) {
      clusters.push(cluster);
      cluster = [];
    }
    cluster.push(block);
    clusterEnd = Math.max(clusterEnd, block.endMs);
  }
  if (cluster.length) clusters.push(cluster);

  for (const group of clusters) {
    const lanes = []; // lanes[i] = fin del último bloque de ese carril
    for (const block of group) {
      let lane = lanes.findIndex((end) => end <= block.startMs);
      if (lane === -1) {
        lane = lanes.length;
        lanes.push(0);
      }
      lanes[lane] = block.endMs;
      block.lane = lane;
    }
    for (const block of group) block.lanes = lanes.length;
  }
  return sorted;
}

function blocksForDay(date) {
  const from = startOfDay(date).getTime();
  const to = endOfDay(date).getTime();
  const blocks = [];

  for (const event of state.events) {
    if (event.allDay || !event.start) continue;
    // Los eventos espejo de tareas ya se pintan como tarea: evitamos duplicarlos.
    if (event.taskId) continue;
    const startMs = new Date(event.start).getTime();
    const endMs = event.end ? new Date(event.end).getTime() : startMs + 3600000;
    if (endMs <= from || startMs >= to) continue;
    blocks.push({ kind: 'event', title: event.summary, startMs, endMs, data: event });
  }

  for (const task of visibleTasks()) {
    if (!task.scheduledAt) continue;
    const startMs = new Date(task.scheduledAt).getTime();
    const endMs = startMs + task.durationMin * 60000;
    if (endMs <= from || startMs >= to) continue;
    blocks.push({ kind: 'task', title: task.title, startMs, endMs, data: task });
  }

  return assignLanes(blocks);
}

function allDayEvents(date) {
  const key = dayKey(date);
  return state.events.filter((event) => event.allDay && event.start <= key && (event.end || event.start) > key);
}

function timeline(date) {
  const startHour = state.settings?.dayStartHour ?? 8;
  const endHour = Math.max(startHour + 1, state.settings?.dayEndHour ?? 20);

  const blocks = blocksForDay(date);

  // Amplía el rango si hay algo fuera del horario configurado. Los bloques que
  // empiezan antes o acaban después del día se recortan al propio día.
  const dayStart = startOfDay(date).getTime();
  const dayEnd = endOfDay(date).getTime();
  let firstHour = startHour;
  let lastHour = endHour;
  for (const block of blocks) {
    firstHour = Math.min(firstHour, new Date(Math.max(block.startMs, dayStart)).getHours());
    const endRef = Math.min(block.endMs, dayEnd);
    lastHour = Math.max(lastHour, endRef >= dayEnd ? 24 : new Date(endRef - 1).getHours() + 1);
  }
  lastHour = Math.min(24, lastHour);

  const grid = el('div', { class: 'timeline' });

  for (let hour = firstHour; hour < lastHour; hour++) {
    grid.append(
      el('div', { class: 'timeline-row', style: { height: `${HOUR_HEIGHT}px` } }, [
        el('span', { class: 'timeline-hour', text: `${String(hour).padStart(2, '0')}:00` }),
      ]),
    );
  }

  const originMs = dayStart + firstHour * 3600000;
  const gridHeight = (lastHour - firstHour) * HOUR_HEIGHT;
  const toY = (ms) => ((Math.min(Math.max(ms, dayStart), dayEnd) - originMs) / 3600000) * HOUR_HEIGHT;

  // Los bloques viven en su propia capa para no invadir la columna de horas.
  const lanes = el('div', { class: 'timeline-lanes' });
  grid.append(lanes);

  for (const block of blocks) {
    const top = Math.max(0, toY(block.startMs));
    const height = Math.max(20, Math.min(toY(block.endMs) - top, gridHeight - top) - 2);
    const laneWidth = 100 / (block.lanes || 1);
    const isTask = block.kind === 'task';

    const classes = ['block'];
    if (isTask) {
      classes.push(`is-task-${block.data.area}`);
      if (block.data.status === 'done') classes.push('is-done');
    } else {
      classes.push('is-event');
    }

    lanes.append(
      el(
        'div',
        {
          class: classes.join(' '),
          style: {
            top: `${top}px`,
            height: `${height}px`,
            left: `${block.lane * laneWidth}%`,
            width: `calc(${laneWidth}% - 4px)`,
          },
          title: block.title,
          onClick: () => {
            if (isTask) openDrawer(block.data);
            else if (block.data.htmlLink) window.open(block.data.htmlLink, '_blank', 'noopener');
          },
        },
        [
          el('div', { class: 'block-title', text: block.title }),
          height > 32
            ? el('div', {
                class: 'block-time',
                text: `${fmtTime(block.startMs)} – ${fmtTime(block.endMs)}${
                  block.data.location ? ` · ${block.data.location}` : ''
                }`,
              })
            : null,
        ],
      ),
    );
  }

  if (isToday(date)) {
    const nowY = toY(Date.now());
    if (nowY >= 0 && nowY <= gridHeight) {
      lanes.append(el('div', { class: 'now-line', style: { top: `${nowY}px` } }));
    }
  }

  if (!blocks.length) {
    return panel('Agenda del día', null, emptyState('Nada agendado. Crea una tarea con hora para bloquear tiempo.'));
  }
  return panel('Agenda del día', blocks.length, grid);
}

function stats(date) {
  const key = dayKey(date);
  const tasks = visibleTasks();

  const forDay = tasks.filter(
    (task) => (task.scheduledAt && dayKey(task.scheduledAt) === key) || task.dueDate === key,
  );
  const done = forDay.filter((task) => task.status === 'done').length;
  const meetings = state.events.filter(
    (event) => !event.allDay && !event.taskId && event.start && dayKey(event.start) === key,
  ).length;
  const focusMin = forDay
    .filter((task) => task.scheduledAt && task.status !== 'done')
    .reduce((total, task) => total + task.durationMin, 0);

  const cards = [
    ['Tareas hoy', forDay.length],
    ['Completadas', `${done}/${forDay.length || 0}`],
    ['Reuniones', meetings],
    ['Tiempo bloqueado', focusMin ? fmtDuration(focusMin) : '—'],
  ];

  return el(
    'div',
    { class: 'stats' },
    cards.map(([label, value]) =>
      el('div', { class: 'stat' }, [
        el('div', { class: 'stat-value', text: String(value) }),
        el('div', { class: 'stat-label', text: label }),
      ]),
    ),
  );
}

function sidePanels(date, refresh) {
  const key = dayKey(date);
  const tasks = visibleTasks();

  const dueToday = tasks.filter(
    (task) => task.status !== 'done' && !task.scheduledAt && task.dueDate === key,
  );

  const overdue = tasks.filter(
    (task) => task.status !== 'done' && task.dueDate && task.dueDate < dayKey(new Date()),
  );

  const inbox = tasks.filter((task) => task.status !== 'done' && !task.scheduledAt && !task.dueDate);

  const wrap = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '18px' } });

  if (overdue.length) {
    wrap.append(panel('Atrasadas', overdue.length, taskList(overdue, refresh, '')));
  }

  wrap.append(
    panel(
      'Sin hora asignada',
      dueToday.length,
      taskList(dueToday, refresh, 'Todo lo de hoy tiene su hueco.'),
    ),
  );

  const allDay = allDayEvents(date);
  if (allDay.length) {
    wrap.append(
      panel(
        'Todo el día',
        allDay.length,
        el(
          'div',
          {},
          allDay.map((event) =>
            el('div', { class: 'task', onClick: () => event.htmlLink && window.open(event.htmlLink, '_blank', 'noopener') }, [
              el('div', { class: 'task-main' }, [
                el('div', { class: 'task-title', text: event.summary }),
                el('div', { class: 'task-meta' }, [el('span', { class: 'pill', text: 'Google Calendar' })]),
              ]),
            ]),
          ),
        ),
      ),
    );
  }

  wrap.append(
    panel(
      'Bandeja de entrada',
      inbox.length,
      taskList(inbox.slice(0, 12), refresh, 'Bandeja vacía.'),
      el('button', {
        class: 'icon-btn',
        text: '+',
        title: 'Añadir a la bandeja',
        onClick: () => openDrawer(null),
      }),
    ),
  );

  return wrap;
}

export function renderToday(host, refresh) {
  const date = state.anchorDate;
  clear(host);

  document.getElementById('view-title').textContent = isToday(date) ? 'Hoy' : capitalize(fmtDayLong(date));
  document.getElementById('view-subtitle').textContent = isToday(date)
    ? capitalize(fmtDayLong(date))
    : '';

  host.append(stats(date));
  host.append(
    el('div', { class: 'today-grid' }, [timeline(date), sidePanels(date, refresh)]),
  );
}

export function shiftToday(days) {
  return addDays(state.anchorDate, days);
}
