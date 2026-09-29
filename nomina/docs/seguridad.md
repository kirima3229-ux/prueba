# Seguridad

## Controles implementados

**Acceso**
- Toda página requiere sesión (salvo entrada, verificación 2FA y `/salud/`, que no muestra datos).
- Verificación en dos pasos (TOTP) obligatoria; contraseñas de 12+ caracteres con Argon2; cambio obligatorio de
  la contraseña temporal.
- Bloqueo por usuario tras 5 intentos fallidos (contraseña o código); sólo un administrador desbloquea.
- Sesión de 15 minutos de inactividad, cookies `__Host-` con `Secure`, `HttpOnly` y `SameSite`.
- Roles: *Administrador*, *Preparador*, *Sólo lectura*; cada usuario ve sólo sus compañías. Cada vista filtra
  por la compañía activa (una nómina, empleado o archivo de otra compañía da 404).

**Datos sensibles**
- SSN, cuentas bancarias, EIN y números patronales cifrados con AES-256-GCM por campo (nonce aleatorio, contexto
  del campo como datos autenticados, rotación de llaves). Búsquedas por índice ciego HMAC-SHA256.
- En pantallas, PDF y reportes el SSN sale enmascarado (últimos 4). Completo sólo en archivos para agencias
  (Excel para la agencia, NACHA), que requieren rol de edición y quedan en la bitácora.
- Respaldos cifrados con una llave distinta.

**Integridad**
- Bitácora inmutable (triggers en la base de datos) con cadena de hash SHA-256 verificable.
- Nómina cerrada, cheques, pagos de servicios y movimientos de licencias no se modifican: se reversan o anulan
  con motivo.

**Web**
- CSP estricta sin JavaScript en línea, `X-Frame-Options: DENY`, HSTS, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy`, `Cache-Control: no-store` en páginas con sesión.
- CSRF en todos los formularios; redirecciones sólo a rutas propias.
- Excel exportado protegido contra inyección de fórmulas; Excel importado con `defusedxml`, límite de 5 MB,
  20,000 filas y 100 columnas; logo re-generado como PNG (sin SVG).
- Panel de administración de Django no publicado.

**Infraestructura (Docker)**
- Usuario sin privilegios, sistema de archivos de sólo lectura, sin capacidades, `no-new-privileges`.
- PostgreSQL sin puertos expuestos; HTTPS automático con Caddy; límite de 10 MB por petición.

## Revisión de la Fase 5 (septiembre de 2026)

| Herramienta | Resultado |
|---|---|
| `manage.py check --deploy` (producción) | Sin errores. HSTS *preload* queda opcional (`NOMINA_HSTS_PRELOAD`), decisión del dueño del dominio |
| `pip-audit` | Sin vulnerabilidades conocidas en las dependencias |
| `bandit` | Sin hallazgos pendientes (los de `subprocess` y SQL de la rotación revisados: argumentos en lista sin shell; identificadores de los modelos entre comillas y valores parametrizados) |
| Revisión manual | Vistas y permisos, aislamiento por compañía, redirecciones, `|safe` (sólo el QR generado por el servidor), SQL directo, subidas de archivos |
| Contenedor | Cabeceras, redirección a HTTPS, host no permitido (400), usuario 10001 y disco de sólo lectura comprobados |

**Corregido en esta revisión**
- `defusedxml` para leer Excel subidos (protege contra XXE y «billion laughs»).
- Límite de filas y columnas al importar (un .xlsx pequeño puede descomprimirse a cientos de MB).
- Chequeo de salud sin sesión ni datos para Docker, exento de la redirección HTTPS sólo en la red interna.

**Riesgos residuales y recomendaciones**
- Las llaves viven en el `.env` del servidor: quien controle el servidor puede leer los datos. Proteja el acceso
  al servidor (SSH con llaves, 2FA en el proveedor, actualizaciones automáticas del sistema).
- Envíe los respaldos fuera del servidor y pruebe una restauración completa al menos dos veces al año.
- Revise la bitácora periódicamente (accesos denegados, archivos con SSN completo generados).
- Considere un escaneo externo (por ejemplo, del proveedor de hospedaje) una vez instalado en el dominio real.
- Mantenga las dependencias al día: `pip-audit -r requirements.txt` antes de cada actualización.
