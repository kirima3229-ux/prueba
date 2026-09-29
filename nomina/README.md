# Nómina PR — Quality Group

Sistema de nómina para Puerto Rico, multi-compañía, construido con Django + PostgreSQL.

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura, entrada y seguridad, roles, compañías, empleados, proveedores de servicios prestados, bitácora | **Completada** |
| 2 | Configuración de tasas y tablas por año, motor de cálculo con pruebas | **En curso** (2a completada) |
| 3 | Flujo de nómina, talonarios, reportes | Pendiente |
| 4 | Archivos de Hacienda, DTRH, IRS y CFSE | Pendiente |
| 5 | Revisión de seguridad, backups, Docker y documentación final | Pendiente |

---

## Instalación para desarrollo (en su computadora)

Requisitos: Python 3.11 o superior. PostgreSQL 14 o superior es opcional en desarrollo (se puede usar SQLite).

```bash
cd nomina
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python generar_env.py              # crea .env con llaves nuevas (SQLite)
# o: python generar_env.py --postgres

python manage.py migrate
python manage.py createsuperuser   # queda como Administrador
python manage.py runserver
```

Abra http://127.0.0.1:8000. Al entrar por primera vez como administrador, el sistema le pide configurar la
autenticación de dos pasos (escanear un código QR con Google Authenticator).

### Con PostgreSQL

```sql
CREATE USER nomina WITH PASSWORD '...';
CREATE DATABASE nomina OWNER nomina;
```

Ponga la misma contraseña en `POSTGRES_PASSWORD` del `.env` y ejecute `python manage.py migrate`.

### Pruebas automatizadas

```bash
pytest                                   # con SQLite (rápido)
NOMINA_DB_MOTOR=postgres POSTGRES_PASSWORD=... pytest   # con PostgreSQL
```

---

## Las llaves de cifrado (MUY IMPORTANTE)

El SSN, las cuentas bancarias y los números patronales (EIN, registro de comerciante, cuenta DTRH, póliza CFSE)
se guardan **cifrados con AES-256-GCM**. Las llaves están en el archivo `.env`, nunca en el código ni en la base de datos.

- **Si pierde `NOMINA_LLAVES_CIFRADO`, los datos cifrados no se pueden recuperar.** Guarde una copia del `.env`
  en un lugar seguro fuera del servidor (por ejemplo, un gestor de contraseñas o una memoria USB en la caja fuerte).
- Un backup de la base de datos sin el `.env` no sirve para leer los SSN. Esto es intencional.
- **Rotación de llaves:** añada una llave nueva (`1:...,2:...`) y cambie `NOMINA_LLAVE_ACTIVA=2`. Los valores
  viejos se siguen leyendo con la llave 1. En la Fase 5 se añade un comando para volver a cifrar todo con la llave nueva.

---

## Seguridad implementada (Fase 1)

| Requisito | Cómo se cumple |
|---|---|
| Entrada obligatoria | Todas las páginas exigen sesión (`LoginRequiredMiddleware`); una prueba recorre **todas** las rutas y lo verifica. |
| Contraseñas | Hash **Argon2**; mínimo 12 caracteres; se rechazan las contraseñas comunes, las solo numéricas y las parecidas al usuario. |
| 2FA (TOTP) | Opcional para Preparador y Solo lectura; **obligatorio para administradores** (no pueden usar el sistema sin configurarlo). |
| Bloqueo | 5 intentos fallidos (contraseña **o** código 2FA) bloquean la cuenta. Se bloquea por usuario y no por IP, para no bloquear a toda la oficina, que comparte la misma IP. Solo un administrador desbloquea (o configure `NOMINA_MINUTOS_BLOQUEO`). |
| Sesión | Expira a los 15 minutos de inactividad; aviso un minuto antes. |
| Roles | Administrador: todo. Preparador: empleados y catálogos de sus compañías. Solo lectura: consultar. Cada usuario ve **solo** sus compañías asignadas (los administradores ven todas). |
| Cifrado | AES-256-GCM por campo, con llave fuera de la base de datos. En pantalla solo aparecen los últimos 4 dígitos. El valor completo solo se obtiene llamando `.revelar()` en el código, algo reservado para los archivos de agencias. |
| Bitácora | Registra entradas, salidas, intentos fallidos, bloqueos, cambios de usuarios, compañías, tasas y empleados (antes → después), con usuario, fecha e IP. Los datos sensibles se anotan como "modificado", nunca con su valor. |
| Bitácora inmutable | (1) el modelo rechaza editar o borrar; (2) triggers de PostgreSQL rechazan UPDATE, DELETE y TRUNCATE; (3) cadena de hashes SHA-256: el botón "Verificar integridad" (o `python manage.py verificar_auditoria`) detecta cualquier alteración hecha directamente en la base de datos. |
| Cabeceras | CSP estricta (sin scripts de terceros ni scripts en línea), X-Frame-Options DENY, nosniff, Referrer-Policy y `Cache-Control: no-store` en páginas con datos. En producción: HTTPS forzado, HSTS y cookies seguras. |
| CSRF | Activo en todos los formularios y en las peticiones HTMX. |
| Secretos | `.env` excluido de git; `generar_env.py` crea llaves aleatorias. |

### Si un administrador queda bloqueado

```bash
python manage.py axes_reset_username <usuario>
```

### Si un administrador pierde su teléfono (2FA)

Otro administrador entra en **Usuarios → Reiniciar 2FA**. Si no hay otro administrador:

```bash
python manage.py shell -c "from django_otp.plugins.otp_totp.models import TOTPDevice; TOTPDevice.objects.filter(user__username='<usuario>').delete()"
```

---

## Uso (Fase 1)

1. **Compañías** → *Nueva compañía* (solo administradores). Los números patronales se escriben una vez y quedan cifrados.
2. En la compañía: **Tasas por año** (SUTA, aportación especial, SINOT). Quedan **POR VERIFICAR** hasta que un
   administrador marque la confirmación. Si cambia una tasa sin confirmarla, vuelve a POR VERIFICAR.
3. **Departamentos** y **Clasificaciones CFSE** de la compañía.
4. **Usuarios** → crear preparadores y asignarles compañías. Reciben una contraseña temporal que deben cambiar al entrar.
5. **Empleados** → crear uno por uno o **Importar Excel/CSV** (descargue la plantilla). La importación es
   "todo o nada": si una fila tiene error no se importa ninguna, y se muestra la fila, la columna y el motivo.
6. **Servicios** (servicios prestados) → proveedores que no son empleados: individuos con SSN o entidades con EIN
   (cifrados), con su relevo de retención (parcial con porcentaje, total, o exento por declaración jurada de la
   Sección 1062.03(b)) y la fecha de vencimiento. Se pueden importar desde Excel/CSV.
   - **Pagos:** se registran uno por uno (con vista previa del cálculo) o se importan desde Excel/CSV. La
     retención se calcula sola: **10% sobre el exceso de los primeros $500 pagados en el año a cada proveedor**,
     según el relevo vigente **en la fecha del pago**. Tasa y exención se configuran por año en
     *Servicios → Tasa y exención* (cargadas POR VERIFICAR para 2025 y 2026).
   - Un pago registrado no se edita: se **anula** con motivo y se registra de nuevo. El resumen anual recalcula
     la retención de cada proveedor y marca "Revisar" si un pago anulado cambió lo que se debió retener.
   - **Depósitos:** cada compañía tiene su frecuencia de depósito de retenciones (mensual o bisemanal). El
     sistema sugiere el período siguiente, muestra la retención pendiente y, al registrar el depósito (fecha y
     número de confirmación de SURI), marca esos pagos como depositados. El inicio avisa si hay retención
     pendiente. Un depósito registrado por error se anula y sus pagos vuelven a quedar pendientes.
   - **Informe trimestral** por proveedor (ingresos pagados y retenciones, con lo ya depositado y lo pendiente),
     exportable a Excel. El archivo oficial que se sube cada trimestre se genera en la Fase 4.
   - **Resumen anual** por proveedor (pagado, exención, sujeto, retenido), exportable a Excel: es la base para
     la 480.6SP, que se genera en la Fase 4. En la Fase 3 los pagos también se podrán incluir en el ciclo de nómina.
7. El selector de la barra superior cambia la compañía activa sin volver a entrar.

### Régimen laboral (Ley 4-2017)

Cada empleado tiene un campo **Régimen laboral**. En blanco, se calcula automáticamente según la fecha de empleo
(antes del 26 de enero de 2017 → régimen anterior; desde esa fecha → Ley 4-2017). Se puede fijar manualmente, y
la ficha lo indica con la etiqueta "Asignado manualmente".

---

## Fase 2a — configuración por año y motor de cálculo

**Configuración** (menú *Configuración*, solo administradores). Todo queda **POR VERIFICAR** hasta que se confirma:

- **Parámetros por año:** Seguro Social (tasas y tope), Medicare (y el adicional de 0.9% sobre $200,000), FUTA,
  topes de desempleo estatal y SINOT, Seguro Choferil semanal, exenciones del 499 R-4, **tabla de retención de PR
  por tramos** y **multiplicadores de horas extra** por régimen (antes de Ley 4-2017 / Ley 4-2017).
  *Crear año copiando* prepara el año siguiente a partir del anterior.
- **Salario mínimo** con fecha de vigencia ($9.50 desde 7/1/2023 y $10.50 desde 7/1/2024) y, opcional, el mínimo
  en efectivo para **empleados con propinas** (meseros). A estos empleados se les puede pagar menos del mínimo, pero
  sus **vacaciones y licencias por enfermedad se pagan al salario mínimo**. Según la Opinión del Secretario del DTRH
  2024-01 (Ley 47-2021): mínimo en efectivo **$2.13** (crédito máximo = salario mínimo − $2.13), y las **horas extra**
  se calculan sobre el salario mínimo completo menos el mismo crédito (1.5 × $10.50 − $8.37 = $7.38). El sistema avisa
  si las propinas no cubren el crédito tomado y cuánto debe completar el patrono.
- **Conceptos de ingreso** (a qué contribuciones está sujeto cada uno) y **de deducción** (antes o después de la
  retención de PR, federal y Seguro Social/Medicare/desempleo).
- **Tasas CFSE** por clasificación y año, en la ficha de la compañía.

Valores iniciales cargados: topes del Seguro Social confirmados con la SSA ($176,100 en 2025; $184,500 en 2026) y salario
mínimo según la Ley 47-2021. **Sin confirmar** (verificar antes de usar): la tabla de retención de PR (se cargaron los
tramos de contribución de individuos de la Ley 52-2022), las exenciones, el Seguro Choferil, los multiplicadores
de horas extra y la tributabilidad de propinas y del bono de Navidad.

**Motor de cálculo** (`apps/calculo/motor.py`, Python puro): salario regular, horas extra según el régimen, licencias
pagadas, otros ingresos, salarios tributables distintos para cada contribución, retención de PR anualizada con
exenciones y concesión del 499 R-4, Seguro Social con tope, Medicare y Medicare adicional, SINOT, Seguro Choferil,
FUTA, SUTA, aportación especial y provisión de CFSE; alertas de salario mínimo, neto negativo y valores POR VERIFICAR.
Cada línea trae su explicación.

**Simulador** (menú *Simulador*): calcula un período para un empleado sin guardar nada, para comparar con casos reales.

Pendiente en la Fase 2: acumulación de vacaciones y enfermedad, bono de Navidad, calculadora de mesada (Ley 80) y
retención federal (W-4). Pendiente en la Fase 4: archivo trimestral de servicios prestados (en espera del formato).

## Estructura

```
nomina/
  config/            configuración (settings.py lee todo del .env)
  apps/core/         cifrado, campos cifrados, validadores, permisos, cabeceras
  apps/auditoria/    bitácora inmutable (modelo, triggers, verificación)
  apps/cuentas/      usuarios, roles, entrada con 2FA, administración de usuarios
  apps/companias/    compañías, tasas por año, departamentos, clasificaciones CFSE
  apps/empleados/    empleados, importación Excel/CSV
  apps/servicios/    proveedores de servicios prestados, pagos, depósitos, informes
  apps/parametros/   configuración por año (tasas, topes, tablas, conceptos)
  apps/calculo/      motor de cálculo (Python puro) y simulador
  templates/, static/  interfaz (HTMX servido localmente, sin CDN)
  tests/             pruebas automatizadas (pytest)
```

## Backups

Los backups automáticos cifrados, la restauración paso a paso y la instalación con Docker se documentan en la Fase 5.
Mientras tanto, en desarrollo:

```bash
pg_dump -Fc nomina > nomina_$(date +%F).dump     # respaldo
pg_restore -d nomina --clean nomina_2026-09-29.dump   # restauración
```

Recuerde: el respaldo solo sirve junto con el `.env` que contiene las llaves.
