# Nómina PR — Quality Group

Sistema de nómina para Puerto Rico, multi-compañía, construido con Django + PostgreSQL.

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Estructura, entrada y seguridad, roles, compañías, empleados, proveedores de servicios prestados, bitácora | Completada |
| 2 | Configuración de tasas y tablas por año, motor de cálculo (PR y federal W-4), licencias, bono y mesada | Completada |
| 3 | Flujo de nómina, talonarios y cheques, reportes, NACHA, QuickBooks, pagos especiales | Completada |
| 4 | Planillas de Hacienda, DTRH, IRS y CFSE | Hojas de trabajo completadas; archivos electrónicos pendientes de las especificaciones |
| 5 | Revisión de seguridad, respaldos cifrados, rotación de llaves, Docker y documentación | Completada |

**Documentación:** [instalación en producción](docs/instalacion_produccion.md) ·
[operación: respaldos, restauración y llaves](docs/operacion.md) · [seguridad](docs/seguridad.md) ·
[manual de uso](docs/manual_usuario.md)

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

### Retención federal (W-4)

Sólo para empleados con *aplica retención federal (W-4)* (por ejemplo, quienes no son residentes de Puerto Rico).
Método de porcentaje para sistemas automatizados de la **Publicación 15-T, Hoja 1A**:

- **W-4 de 2020 o posterior**: salario federal del período × períodos + otros ingresos (4a) − deducciones (4b) −
  ajuste de la línea 1g ($12,900 casados, $8,600 los demás; $0 si el paso 2 está marcado) → tabla anual
  (estándar o «paso 2 marcado») ÷ períodos − dependientes (paso 3) ÷ períodos + adicional (4c).
- **W-4 de 2019 o anterior**: resta $4,300 por exención y usa la tabla estándar de soltero o de casado.
- El salario federal excluye los conceptos marcados como no tributables federales (reembolsos) y las deducciones
  «antes de la retención federal».
- *Configuración → año* trae las tablas de 2025 y 2026 (**POR VERIFICAR**), generadas con los tramos y deducciones
  estándar del año; la de casados de 2026 coincide con la publicada por el IRS. Se pueden editar.
- La retención federal va a la línea 3 del 941 y a su cuenta en el asiento de QuickBooks. Para estos empleados
  corresponde además el W-2 federal (no se genera todavía).

## Fase 2b — vacaciones, enfermedad y bono de Navidad

Rige la **Ley 4-2017** (la Ley 41-2022 fue declarada nula por el Tribunal Federal el 3 de marzo de 2023). Las
reglas están en *Configuración → año* y se cargaron POR VERIFICAR:

| Régimen | Horas mín./mes | Vacaciones por mes | Enfermedad |
|---|---|---|---|
| Antes de Ley 4-2017 | 115 | 1.25 días (patrono de ≤12: ½ día) | 1 día |
| Ley 4-2017, patrono de más de 12 | 130 | ½ (1er año), ¾ (1–5), 1 (5–15), 1.25 (15+) | 1 día |
| Ley 4-2017, patrono de ≤12 | 130 | ½ día | 1 día |

Cada tramo de antigüedad empieza "a partir del año más un día". Días de 8 horas; topes: 24 meses de
vacaciones y 15 días de enfermedad (configurables).

- **Licencias y bono → Acumular mes:** se entran las horas trabajadas del mes por empleado, se ve la vista previa
  con la explicación de cada acumulación y se guarda. Un mes no se acumula dos veces.
- **Balances** por empleado (en horas y días), exportables a Excel. Los movimientos (saldo inicial, acumulación, uso,
  ajuste, liquidación) no se editan: las correcciones se hacen con un ajuste con motivo. Use *Saldo inicial* para
  cargar los balances del sistema anterior.
- **Bono de Navidad** (Ley 148): período del 1 de octubre al 30 de septiembre. Antes de Ley 4: 700 h; más de 15
  empleados 6% sobre un salario máximo de $10,000 (hasta $600), si no 3% (hasta $300). Ley 4: 1,350 h; 2%, hasta
  $600 con más de 20 empleados o $300 con 20 o menos. Se calcula por compañía, se guarda y se exporta a Excel.

Las horas (acumulación mensual) y las horas y salarios (bono) se traen de las nóminas cerradas con el botón *Traer … de la nómina*, y se pueden corregir antes de calcular.

**Calculadora de mesada (Ley 80)** (menú *Simulador → Calculadora de mesada*, o desde la ficha del empleado):
antes de Ley 4-2017, hasta 5 años 2 meses + 1 semana por año, de 5 a 15 años 3 meses + 2 semanas por año, más de
15 años 6 meses + 3 semanas por año, sin tope; Ley 4-2017, 3 meses + 2 semanas por año hasta un máximo de 9 meses.
Semana = salario mensual × 12 ÷ 52. No aplica en el período probatorio. Reglas editables por año (POR VERIFICAR).
La pantalla calcula la **liquidación**: mesada + vacaciones acumuladas (balance del empleado × su tarifa por hora,
nunca menos del salario mínimo). Para empleados por hora, el salario base se puede calcular con las horas regulares
de los 30 días de más horas × la tarifa. La licencia por enfermedad no se paga por defecto (no es lo usual); hay una
opción para incluirla cuando la compañía la paga.

Pendiente en la Fase 2: retención federal (W-4). Pendiente en la Fase 4: archivo
trimestral de servicios prestados (en espera del formato).

## Fase 3a — flujo de nómina, talonarios y registro

Menú **Nómina**:

1. **Nuevo período**: el sistema sugiere las fechas según la frecuencia de pago de la compañía. Se crean las
   entradas de todos los empleados activos y se copian sus **deducciones recurrentes** vigentes (plan médico,
   préstamos, etc.; se configuran desde la ficha del empleado → *Deducciones recurrentes*).
2. **Horas**: en la rejilla del período se entran horas regulares, extra, séptimo día, período de alimentos,
   vacaciones y enfermedad, y propinas, comisiones y bonos. Cada empleado tiene su pantalla para ingresos y deducciones
   adicionales. Un empleado se puede excluir del período.
3. **Calcular (pre-nómina)**: usa el motor de la Fase 2 con los acumulados del año (topes de Seguro Social, FUTA, SUTA)
   y avisa si una licencia excede el balance. Cualquier cambio posterior marca el período para recalcular.
4. **Cerrar**: sólo si está calculado, al día y sin errores. Al cerrar se descuentan las horas de vacaciones y
   enfermedad usadas. Un período cerrado **no se puede editar**.
5. **Reversar** (sólo administrador, con motivo): crea un período de reverso con los montos negativos y devuelve las
   licencias. El período original queda como *Reversada* y todo queda en la bitácora.

**Talonarios** en PDF (SSN enmascarado, período actual y acumulado del año por concepto, balances de licencias) y
**registro de nómina** en Excel.

### Cheques y talonarios para imprimir

En una nómina cerrada, **Cheques y talonarios** emite e imprime los cheques en papel de cheque **tipo voucher**
tamaño carta (cheque y dos talonarios: uno para el empleado y otra copia para el patrono, el mismo papel que usa
QuickBooks). El papel debe traer preimpresos el banco, la línea MICR y el número.

- **Formato de cheques** (por compañía): posición del cheque (arriba, medio o abajo), monto en letras en español o
  inglés, próximo número, ajustes de alineación en pulgadas y si se imprime el nombre de la compañía. La **prueba de
  alineación** se imprime en papel blanco para ponerla sobre una hoja de cheques y calibrar.
- **Emitir**: se marcan los empleados (por defecto los que no tienen depósito directo) y se indica el número del
  primer cheque que está en la impresora; se numeran en orden alfabético.
- Un cheque emitido **no se modifica ni se borra**. Si se daña o se pierde se **anula con motivo** y se reemite con
  el próximo número. Un número usado no se vuelve a usar. Al reversar una nómina sus cheques quedan anulados.
- Los empleados con depósito directo reciben un **aviso de depósito** (no negociable) en el mismo formato.
- Imprimir cheques requiere rol de preparador o administrador; todo queda en la bitácora.

### Reportes e impuestos a pagar

Menú *Nómina → Reportes* (por mes, trimestre, año o fechas; en pantalla, Excel y PDF). Sólo cuentan las
nóminas cerradas, por fecha de pago; los reversos restan.

- **Resumen por concepto**: ingresos, retenciones, deducciones y aportaciones, cada una con su % del bruto.
- **Acumulado por empleado**: con el año completo es el acumulado del año (YTD) de cada empleado.
- **Costo patronal** por empleado o departamento: cada aportación con su **% al lado del $**, total y % del costo.
- **Impuestos a pagar** con la fecha de vencimiento: Hacienda (retención; mensual o bisemanal según la compañía),
  IRS 941 (mensual o bisemanal según *frecuencia de depósito federal* de la compañía), FUTA, DTRH trimestral
  (desempleo, aportación especial, SINOT, Choferil), CFSE (provisión) y la retención de servicios prestados.
  Fechas **POR VERIFICAR**; se corren al próximo día laborable (feriados federales).

### Importar horas

En la nómina, *Importar horas de Excel* acepta .xlsx o .csv (por ejemplo, lo exportado del reloj ponchador) con
`numero_empleado` y las columnas de horas, propinas, comisiones y bono. La plantilla trae ya los empleados del
período. Primero se valida; si hay un error no se cambia nada. Las columnas del archivo reemplazan lo entrado para
los empleados que aparecen; lo demás no se toca.

### Pagos especiales

Un período **especial** (bono, nómina final) no paga el salario fijo de los asalariados ni cobra semanas de
Seguro Choferil: sólo lo que se entre. Conceptos nuevos: mesada, vacaciones liquidadas y enfermedad liquidada
(tratamiento contributivo POR VERIFICAR).

- **Bono de Navidad por nómina**: en *Licencias → Bono*, con el bono guardado, *Crear nómina del bono* hace una
  nómina especial con el bono de cada empleado con derecho. Al cerrarla el bono queda *Pagado*; si se reversa, vuelve
  a *Calculado*. Mientras está en una nómina no se recalcula.
- **Nómina final (liquidación)**: en *Simulador → Calculadora de mesada*, después de calcular, *Crear nómina final*
  hace una nómina especial con la mesada (opcional: se desmarca si renunció o hubo justa causa), las vacaciones y,
  si se eligió, la enfermedad. Allí se añaden las horas o el salario pendiente. Al cerrarla se descuentan del
  balance las horas liquidadas; al reversarla se devuelven.

### Depósito directo (NACHA)

Un administrador configura el banco de la compañía (*Nómina → nómina cerrada → Depósito directo → Datos del banco*):
ruta del banco, *Immediate Origin*, *Company ID* y, si el banco lo pide, archivo balanceado con la cuenta de la
compañía (cifrada). En una nómina cerrada, *Depósito directo* genera el archivo **NACHA PPD** (registros de 94
caracteres en bloques de 10) con los empleados que tienen depósito directo y no cobraron con cheque. La fecha
efectiva debe ser día laborable. Es el único lugar, además de la base de datos cifrada, donde van los números de
cuenta completos. Cada archivo queda en el historial (con su huella SHA-256) y en la bitácora, y se avisa si ya se
generó uno para esa nómina. Antes del primer envío real, pida al banco que valide un archivo de prueba.

### Asiento para QuickBooks Online

En una nómina cerrada, *Asiento QuickBooks* muestra y descarga (CSV o Excel) el asiento de diario: débito a
salarios y a aportaciones patronales; crédito a cada retención y aportación por pagar, a las deducciones y al neto
(«Nómina por pagar»). Siempre cuadra; un reverso produce el asiento inverso. Un administrador asigna en
*Cuentas contables* el nombre de la cuenta de QuickBooks para cada concepto (o para el grupo); lo que no se asigna
usa la cuenta sugerida. En QuickBooks: *Configuración → Importar datos → Asientos de diario*.

### Servicios prestados en el ciclo de nómina

En cada nómina, *Servicios prestados* permite pagar a varios proveedores con la fecha de pago del ciclo: se
escriben los montos, *Ver retenciones* muestra la retención (10% después de los primeros $500, o el relevo) y
*Registrar pagos* los guarda como pagos de servicios (origen «Ciclo de nómina»). Quedan en el informe trimestral,
en los depósitos de retención y en *Impuestos a pagar*.

### Logo de la compañía (opcional)

En la ficha de la compañía, un administrador puede subir el logo (PNG o JPG, hasta 2 MB). Sale en los talonarios
PDF, en los talonarios de los cheques, en los avisos de depósito directo y en el encabezado del cheque cuando se
imprime el nombre de la compañía. El sistema valida la imagen, la reduce si es muy grande y guarda una copia PNG
generada por él (sin metadatos), en la base de datos, así que entra en los respaldos. Se puede cambiar o quitar en
cualquier momento; queda en la bitácora.

## Fase 4 — planillas de gobierno

Menú **Planillas**: calendario del año con cada planilla, su vencimiento y su estado (radicada, pendiente, vencida
sin registrar o sin nóminas). Cada planilla es una hoja de trabajo calculada de las nóminas cerradas (por fecha de
pago; los reversos restan), en pantalla, PDF y Excel:

| Planilla | Agencia | Contenido |
|---|---|---|
| 499 R-1B | Hacienda | Por mes: salarios pagados, sujeto a retención, contribución retenida |
| 941 | IRS | Líneas 1–12 y obligación mensual (línea 16) o por día (Anejo B si deposita bisemanal) |
| Desempleo e incapacidad | DTRH | Por empleado: salarios, tributable de desempleo y SINOT (con topes), aportaciones; empleados al día 12 |
| Seguro Choferil | DTRH | Por empleado: semanas y aportaciones |
| 499R-2/W-2PR | Hacienda / SSA | Por empleado: sueldos, comisiones, propinas, reembolsos, exentos, aportaciones, retenido, SS y Medicare |
| 499R-3 | Hacienda | Reconciliación: suma de los trimestres contra los W-2PR (avisa si no cuadran) |
| 940 | IRS | Líneas 3–8 y obligación por trimestre |
| 480.6SP | Hacienda | Por proveedor de servicios: pagado y retenido en el año |
| CFSE | CFSE | Nómina y prima por clasificación en el año de la póliza (julio–junio) |

- En pantalla y en PDF el SSN sale enmascarado. El **Excel para la agencia** (W-2PR, DTRH, Choferil, 480.6SP) trae
  el SSN o la identificación completa; sólo lo descargan administradores y preparadores y queda en la bitácora.
- **Registro de radicación**: en cada planilla se anota la fecha, el número de confirmación y el monto pagado.
- La clasificación CFSE se guarda con cada resultado de nómina (la que tenía el empleado al pagarse).
- Líneas, casillas y fechas **POR VERIFICAR** con los formularios del año.

**Pendiente**: los archivos electrónicos con formato oficial — EFW2PR del W-2PR (Publicación 25-01 de Hacienda), el
archivo de salarios del DTRH y el trimestral de servicios prestados — se generan cuando se incorporen las
especificaciones o las muestras.

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

## Respaldos, llaves y despliegue (Fase 5)

| Comando | Qué hace |
|---|---|
| `python manage.py respaldar` | Respaldo cifrado (AES-256-GCM, llave `NOMINA_LLAVE_RESPALDO`) de toda la base de datos |
| `python manage.py verificar_respaldo ARCHIVO` | Comprueba que un respaldo se descifra y es válido |
| `python manage.py restaurar ARCHIVO --confirmar` | Reemplaza la base de datos con el respaldo |
| `python manage.py rotar_llaves --inventario` / `--confirmar` | Vuelve a cifrar con la llave activa; `--llave-indice-nueva` rota el índice ciego |
| `python manage.py generar_llave` | Llave nueva para el `.env` |
| `docker compose up -d --build` | Producción: PostgreSQL + aplicación + respaldos diarios + Caddy (HTTPS) |

Detalles en [docs/operacion.md](docs/operacion.md) e [docs/instalacion_produccion.md](docs/instalacion_produccion.md).
Recuerde: un respaldo sólo sirve junto con el `.env` que contiene las llaves.
