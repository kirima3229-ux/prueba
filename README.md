# Organizador

Aplicación para organizar el día a día —trabajo y vida personal en un mismo
sitio— con **sincronización bidireccional real con Google Calendar**: tus
reuniones aparecen junto a tus tareas, y las tareas que agendas se escriben como
eventos en tu calendario. Si mueves ese bloque en Google, la tarea se mueve aquí.

```
┌──────────────┐   tareas agendadas → eventos   ┌─────────────────┐
│  Organizador │ ────────────────────────────►  │ Google Calendar │
│  (esta app)  │ ◄────────────────────────────  │                 │
└──────────────┘   eventos → agenda del día     └─────────────────┘
```

## Qué hace

- **Hoy** — línea de tiempo del día con tus reuniones reales y tus bloques de
  trabajo mezclados, la hora actual marcada, y bandejas laterales con lo
  atrasado, lo que vence hoy y la bandeja de entrada.
- **Semana** — las siete columnas de la semana de un vistazo.
- **Tareas** — todo el backlog separado en dos columnas, Trabajo y Personal, con
  búsqueda por título, nota o etiqueta.
- **Áreas** — cada tarea es de trabajo o personal; el filtro de la barra lateral
  cambia toda la app a la vez. En Google Calendar cada área recibe un color
  distinto.
- **Sincronización** — automática cada pocos minutos, y a demanda con el botón
  «Sincronizar ahora».

## Puesta en marcha

Requisitos: **Node.js 20 o superior**. No hace falta base de datos ni compilar
nada; el frontend es HTML, CSS y JavaScript nativos.

### 1. Instalar y arrancar

```bash
npm install
npm start
```

La app queda en <http://localhost:3000>. Ya puedes usarla en modo local (tareas y
agenda, sin calendario). Para la sincronización con Google, sigue el paso 2.

### 2. Conectar Google Calendar

Necesitas credenciales OAuth propias. Son gratuitas y se sacan en unos minutos:

1. Entra en [Google Cloud Console](https://console.cloud.google.com/) y crea un
   proyecto (o usa uno que ya tengas).
2. En **APIs y servicios → Biblioteca**, busca **Google Calendar API** y pulsa
   *Habilitar*.
3. En **APIs y servicios → Pantalla de consentimiento de OAuth**, elige tipo
   *Externo*, rellena nombre y correo, y en *Usuarios de prueba* añade tu propia
   cuenta de Google. (Mientras la app esté en modo prueba solo podrán entrar los
   usuarios que añadas ahí; no hace falta verificarla para uso personal.)
4. En **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de
   OAuth**, tipo *Aplicación web*. En **URIs de redireccionamiento autorizados**
   añade exactamente:

   ```
   http://localhost:3000/auth/google/callback
   ```

5. Copia el **Client ID** y el **Client Secret** al archivo `.env`:

   ```bash
   cp .env.example .env
   ```

   ```ini
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:3000/auth/google/callback
   SESSION_SECRET=   # genera uno, ver abajo
   ```

   Para el secreto de sesión:

   ```bash
   node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
   ```

6. Reinicia con `npm start` y pulsa **Continuar con Google**.

Permisos que se piden: leer tus calendarios y crear/editar eventos. Nada más.

## Cómo funciona la sincronización

Cada vez que se sincroniza (a demanda, o sola cada 5 minutos):

1. **Se refresca la lista de calendarios.** La primera vez se marcan los tuyos y
   se fija el principal como destino de las tareas.
2. **Se bajan los eventos** de los calendarios marcados. Se usa el `syncToken` de
   Google para traer solo lo que cambió; si Google lo invalida (410) se rehace la
   descarga completa sola. Ventana: 30 días atrás, 180 adelante.
3. **Se traen los cambios hechos en Google** sobre los eventos espejo de tareas:
   si moviste o renombraste el bloque allí, la tarea lo adopta aquí.
4. **Se suben los cambios hechos en la app**: se crean, actualizan o borran los
   eventos correspondientes.

**Conflictos.** Cuando una tarea cambió en los dos sitios entre sincronizaciones,
manda la app y el evento se reescribe. La decisión no depende de relojes —que
entre Google y tu máquina no van a la par— sino de una huella de los campos que
se espejan: si la tarea cambió desde el último sync, gana la app; si no, gana
Google.

**Qué se espeja y qué no.** Solo las tareas con hora asignada se convierten en
eventos. Los eventos que ya tenías en Google se muestran en la agenda pero nunca
se convierten en tareas ni se modifican. Al borrar una tarea se borra su evento;
al quitarle la hora, también. Si borras el evento en Google, la tarea sigue
existiendo, solo se queda sin hora.

Todo esto está cubierto por la suite de pruebas.

## Pruebas

```bash
npm test
```

Levanta el servidor real contra un doble de la API de Google (`test/fake-google.mjs`)
y recorre el ciclo completo: OAuth, exportar una tarea, editarla, moverla desde
Google, refresco de token caducado, invalidación del `syncToken`, borrado y cierre
de sesión.

## Estructura

```
server/
  index.js      Servidor Express, rutas estáticas y SPA
  config.js     Carga de .env y configuración
  store.js      Persistencia en JSON con escritura atómica
  session.js    Cookies de sesión firmadas (HMAC)
  google.js     Cliente de OAuth y de la API de Calendar
  sync.js       Motor de sincronización bidireccional
  model.js      Modelo de tarea y saneado de entrada
  routes/       tasks · calendar · settings · auth
public/
  index.html    Estructura de la app
  styles.css    Estilos (modo claro y oscuro)
  js/           Vistas y lógica de cliente, sin framework
test/           Pruebas de extremo a extremo
data/db.json    Tus datos (se crea solo; ignorado por git)
```

## Atajos de teclado

| Tecla | Acción              |
|-------|---------------------|
| `n`   | Nueva tarea         |
| `t`   | Ir a Hoy            |
| `w`   | Ir a Semana         |
| `a`   | Ir a Tareas         |
| `r`   | Sincronizar ahora   |
| `Esc` | Cerrar el panel     |

## Notas de despliegue

Pensado para correr en tu máquina o en un servidor personal. Si lo publicas:

- Sirve la app por **HTTPS** y pon `SECURE_COOKIES=true`.
- Cambia `GOOGLE_REDIRECT_URI` a tu dominio y añádelo en Google Cloud Console.
- Define `SESSION_SECRET` como valor fijo: si falta, se genera uno nuevo en cada
  arranque y las sesiones se pierden.
- `data/db.json` guarda tareas y **tokens de Google**. Protégelo como protegerías
  una contraseña; ya está fuera de git.
