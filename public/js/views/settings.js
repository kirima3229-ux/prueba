// Vista "Ajustes": conexión con Google, calendarios y preferencias del día.

import { api } from '../api.js';
import { setState, state } from '../state.js';
import { GOOGLE_MARK, panel } from '../components.js';
import { clear, el, toast } from '../util.js';

async function patchSettings(patch, refresh) {
  try {
    const { settings } = await api.updateSettings(patch);
    setState({ settings });
    await refresh();
  } catch (err) {
    toast(`No se pudo guardar: ${err.message}`, { error: true });
  }
}

function row(label, description, control) {
  return el('div', { class: 'setting-row' }, [
    el('div', {}, [
      el('div', { class: 'label', text: label }),
      description ? el('div', { class: 'desc', text: description }) : null,
    ]),
    el('div', { class: 'control' }, [control]),
  ]);
}

function connectionPanel(refresh) {
  if (!state.googleConfigured) {
    return panel(
      'Google Calendar',
      null,
      el('div', { style: { padding: '6px 4px', display: 'flex', flexDirection: 'column', gap: '12px' } }, [
        el('div', { class: 'desc', text: 'El servidor todavía no tiene credenciales de Google. Para activar la sincronización:' }),
        el('ol', { class: 'setup-steps' }, [
          el('li', { html: 'Crea un ID de cliente OAuth (aplicación web) en <code>console.cloud.google.com</code> y habilita la <b>Google Calendar API</b>.' }),
          el('li', { html: 'Añade <code>http://localhost:3000/auth/google/callback</code> como URI de redirección autorizado.' }),
          el('li', { html: 'Copia <code>.env.example</code> a <code>.env</code> y pega ahí el Client ID y el Client Secret.' }),
          el('li', { html: 'Reinicia el servidor con <code>npm start</code> y vuelve aquí.' }),
        ]),
      ]),
    );
  }

  if (!state.connected) {
    return panel(
      'Google Calendar',
      null,
      el('div', { style: { padding: '10px 4px', display: 'flex', flexDirection: 'column', gap: '12px' } }, [
        el('div', { class: 'desc', text: 'Conecta tu cuenta para ver tus eventos aquí y que tus tareas agendadas aparezcan en tu calendario.' }),
        el('a', { class: 'google-btn', href: '/auth/google' }, [
          el('span', { html: GOOGLE_MARK }),
          'Conectar Google Calendar',
        ]),
      ]),
    );
  }

  const body = el('div', { style: { padding: '4px' } });

  body.append(
    row(
      'Cuenta conectada',
      state.user?.email || '',
      el('button', {
        class: 'btn btn-block',
        text: 'Desconectar',
        onClick: async () => {
          if (!confirm('¿Desconectar la cuenta de Google? Tus tareas se conservan.')) return;
          await api.logout();
          location.href = '/';
        },
      }),
    ),
  );

  body.append(
    row(
      'Exportar tareas al calendario',
      'Cada tarea con hora crea un evento en Google Calendar.',
      el(
        'label',
        { style: { display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'flex-end' } },
        [
          el('input', {
            type: 'checkbox',
            checked: state.settings?.pushEnabled,
            onChange: (event) => patchSettings({ pushEnabled: event.target.checked }, refresh),
          }),
          el('span', { class: 'desc', text: state.settings?.pushEnabled ? 'Activado' : 'Desactivado' }),
        ],
      ),
    ),
  );

  const writable = state.calendars.filter((cal) => cal.writable);
  body.append(
    row(
      'Calendario destino',
      'Dónde se escriben los bloques de tus tareas.',
      el(
        'select',
        { onChange: (event) => patchSettings({ pushCalendarId: event.target.value }, refresh) },
        writable.map((cal) =>
          el('option', {
            value: cal.id,
            selected: cal.id === state.settings?.pushCalendarId,
            text: cal.summary + (cal.primary ? ' (principal)' : ''),
          }),
        ),
      ),
    ),
  );

  return panel('Google Calendar', null, body);
}

function calendarsPanel(refresh) {
  if (!state.connected) return null;

  const visible = new Set(state.settings?.visibleCalendars || []);
  const list = el('div', { class: 'cal-list' });

  for (const cal of state.calendars) {
    list.append(
      el('label', { class: 'cal-item' }, [
        el('input', {
          type: 'checkbox',
          checked: visible.has(cal.id),
          onChange: (event) => {
            const next = new Set(state.settings?.visibleCalendars || []);
            if (event.target.checked) next.add(cal.id);
            else next.delete(cal.id);
            patchSettings({ visibleCalendars: [...next] }, refresh);
          },
        }),
        el('span', { class: 'cal-swatch', style: { background: cal.color } }),
        el('span', { class: 'cal-name', text: cal.summary }),
        cal.writable ? null : el('span', { class: 'pill', text: 'solo lectura' }),
      ]),
    );
  }

  if (!state.calendars.length) {
    list.append(el('div', { class: 'empty', text: 'Sincroniza para cargar tus calendarios.' }));
  }

  return panel('Calendarios visibles', state.calendars.length, list);
}

function preferencesPanel(refresh) {
  const body = el('div', { style: { padding: '4px' } });
  const settings = state.settings || {};

  const hourSelect = (key) =>
    el(
      'select',
      { onChange: (event) => patchSettings({ [key]: Number(event.target.value) }, refresh) },
      Array.from({ length: 24 }, (_, hour) =>
        el('option', {
          value: hour,
          selected: settings[key] === hour,
          text: `${String(hour).padStart(2, '0')}:00`,
        }),
      ),
    );

  body.append(row('Empieza el día', 'Primera hora visible en la agenda.', hourSelect('dayStartHour')));
  body.append(row('Termina el día', 'Última hora visible en la agenda.', hourSelect('dayEndHour')));

  body.append(
    row(
      'Duración por defecto',
      'Minutos que ocupa una tarea nueva al agendarla.',
      el('input', {
        type: 'number',
        min: 5,
        max: 480,
        step: 5,
        value: settings.defaultDurationMin ?? 30,
        onChange: (event) => patchSettings({ defaultDurationMin: Number(event.target.value) }, refresh),
      }),
    ),
  );

  body.append(
    row('Zona horaria', 'Se usa al crear eventos en Google Calendar.', el('div', { class: 'desc', text: settings.timeZone || '—' })),
  );

  return panel('Tu día', null, body);
}

export function renderSettings(host, refresh) {
  clear(host);
  document.getElementById('view-title').textContent = 'Ajustes';
  document.getElementById('view-subtitle').textContent = '';

  const wrap = el('div', { class: 'settings' }, [
    connectionPanel(refresh),
    calendarsPanel(refresh),
    preferencesPanel(refresh),
  ]);

  host.append(wrap);
}
