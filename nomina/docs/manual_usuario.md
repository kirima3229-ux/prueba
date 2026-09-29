# Manual de uso — preparación de nómina

## Entrar

1. Usuario y contraseña; luego el código de 6 dígitos de la aplicación de verificación del teléfono.
2. La sesión se cierra sola tras 15 minutos sin uso (el sistema avisa un minuto antes).
3. Arriba a la derecha se escoge la **compañía activa**: todo lo que se ve y se hace es de esa compañía.

Roles: **Administrador** (todo, incluidos usuarios, configuración y reversos), **Preparador** (nómina,
empleados, archivos) y **Sólo lectura** (consulta y reportes).

## Nómina de cada período

| Paso | Dónde | Qué hacer |
|---|---|---|
| 1 | *Nómina → Nuevo período* | Acepte las fechas sugeridas (o cámbielas). Entran los empleados activos con sus deducciones recurrentes |
| 2 | Tabla del período | Escriba las horas (regulares, extra, vacaciones, enfermedad…), propinas, comisiones y bonos. O *Importar horas de Excel* (plantilla con los empleados ya listados) |
| 3 | Nombre del empleado | Ingresos o deducciones de una sola vez (reembolsos, préstamos) |
| 4 | *Calcular pre-nómina* | Revise los resultados y las alertas (balances insuficientes, salario mínimo, parámetros POR VERIFICAR). Cada monto tiene su explicación |
| 5 | *Aprobar y cerrar* | Ya no se puede modificar. Se descuentan las licencias usadas |
| 6 | *Cheques y talonarios* | Escriba el número del primer cheque de la impresora, emita e imprima. Los de depósito directo reciben aviso de depósito |
| 7 | *Depósito directo* | Descargue el archivo NACHA y envíelo al banco **una sola vez** |
| 8 | *Asiento QuickBooks* | Descargue el CSV e impórtelo en QuickBooks (*Configuración → Importar datos → Asientos de diario*) |
| 9 | *Servicios prestados* | Pagos a contratistas del ciclo, con la retención del 10% calculada |

**¿Error en una nómina cerrada?** Un administrador la **reversa** con un motivo (se crea un reverso con los
montos en negativo, se devuelven las licencias y se anulan sus cheques) y se procesa una nómina nueva correcta.

**Cheque dañado o perdido:** en *Cheques y talonarios*, *Anular y reemitir* con el motivo; sale con el próximo
número. Un número usado no se vuelve a usar.

## Cada mes

- *Licencias → Acumulación*: *Traer horas de la nómina* → revisar → *Guardar acumulación*.
- *Nómina → Impuestos a pagar*: lo que hay que depositar y cuándo vence.
- *Servicios → Depósitos*: registrar el depósito de la retención de servicios prestados.

## Cada trimestre y cada año

- *Planillas*: calendario con cada planilla, su vencimiento y su estado. Abra la planilla, revise la hoja de
  trabajo, descargue el PDF/Excel (o el Excel para la agencia) y, al radicar, **registre el número de
  confirmación**.
- Diciembre: *Licencias → Bono de Navidad* → *Traer horas y salarios de la nómina* → calcular y guardar →
  *Crear nómina del bono* (a pagar no más tarde del 15 de diciembre).
- Enero: W-2PR, 499R-3 (debe cuadrar con los trimestres), 940 y 480.6SP.

## Terminación de un empleado

1. *Empleados → el empleado → Terminar empleo* (fecha y razón).
2. *Calcular mesada* (desde la ficha): revise la mesada y las vacaciones acumuladas; marque la licencia por
   enfermedad sólo si la compañía la paga.
3. *Crear nómina final*: desmarque la mesada si renunció o hubo justa causa. Añada allí las horas o el salario
   pendiente, calcule y cierre.

## Reportes

*Nómina → Reportes*, por mes, trimestre, año o fechas, en pantalla, Excel y PDF: resumen por concepto, acumulado
del año por empleado, costo patronal por empleado o departamento (con el % al lado de cada $) e impuestos a pagar.

## Buenas prácticas

- No comparta su usuario. Cada acción queda en la bitácora con su nombre.
- Los archivos con SSN completo (Excel para la agencia, NACHA) no se envían por correo sin cifrar; súbalos
  directamente al portal de la agencia o del banco y bórrelos de la computadora después.
- Si ve algo raro (un número que no cuadra, un aviso de «POR VERIFICAR»), avise al administrador antes de cerrar.
