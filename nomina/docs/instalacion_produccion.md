# Instalación en producción (Docker)

Esta guía instala el sistema en un servidor propio con Docker: PostgreSQL 16, la aplicación (gunicorn),
respaldos cifrados diarios y Caddy, que obtiene y renueva el certificado HTTPS automáticamente.

## 1. Requisitos

- Un servidor Linux (2 CPU, 4 GB de RAM, 40 GB de disco bastan para varias compañías) con Docker y el
  complemento `docker compose`.
- Un nombre de dominio (por ejemplo `nomina.qualitygroup.com`) que apunte a la IP pública del servidor.
- Los puertos 80 y 443 abiertos hacia el servidor (Caddy los usa para el certificado y para HTTPS).
  **No** abra el puerto de PostgreSQL: la base de datos sólo es accesible dentro de Docker.

## 2. Copiar el sistema y crear la configuración

```bash
git clone <repositorio> nomina && cd nomina/nomina
python3 generar_env.py --docker --dominio nomina.qualitygroup.com
```

`generar_env.py` crea el archivo `.env` (permisos 600) con:

| Variable | Qué es |
|---|---|
| `DJANGO_SECRET_KEY` | Firma de sesiones y formularios |
| `NOMINA_LLAVES_CIFRADO`, `NOMINA_LLAVE_ACTIVA` | Llaves AES-256 de los SSN, cuentas bancarias y números patronales |
| `NOMINA_LLAVE_INDICE` | Llave para buscar por SSN sin descifrar |
| `NOMINA_LLAVE_RESPALDO` | Llave de los respaldos (distinta de las anteriores) |
| `POSTGRES_PASSWORD` | Contraseña de la base de datos |
| `NOMINA_DOMINIO`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | El dominio |

> **Antes de seguir, guarde una copia del `.env` fuera del servidor** (gestor de contraseñas de la empresa o
> un sobre sellado en la caja fuerte), **separada de los respaldos**. Sin estas llaves los datos cifrados y los
> respaldos no se pueden recuperar. Vea [operacion.md](operacion.md#custodia-de-las-llaves).

## 3. Arrancar

```bash
docker compose up -d --build
docker compose ps          # db, web, respaldos y caddy deben estar «Up»; web «healthy»
```

Al arrancar, el servicio `web` aplica las migraciones y verifica la integridad de la bitácora.

## 4. Crear el primer administrador

```bash
docker compose exec web python manage.py createsuperuser
```

Entre a `https://nomina.qualitygroup.com`. El sistema pide configurar la verificación en dos pasos (2FA) con
una aplicación como Google Authenticator o Microsoft Authenticator antes de permitir cualquier otra cosa.

## 5. Configuración inicial (en la aplicación)

1. **Configuración → año**: revise y marque como verificadas las tasas y tablas del año (vienen «POR VERIFICAR»).
2. **Compañías → Nueva**: datos, números patronales, frecuencia de pago y de depósitos; tasas del año
   (SUTA, aportación especial, SINOT); departamentos y clasificaciones de la CFSE con su tasa; logo (opcional).
3. **Usuarios**: cree las cuentas de los preparadores (rol *Preparador*) y de consulta (*Sólo lectura*) y
   asígneles las compañías.
4. **Nómina → Depósito directo → Datos del banco** (si aplica) y **Cuentas contables** para QuickBooks.
5. **Empleados**: impórtelos de Excel (plantilla en la pantalla) o créelos uno a uno; registre los balances
   iniciales de vacaciones y enfermedad.

## 6. Actualizar a una versión nueva

```bash
docker compose exec respaldos python manage.py respaldar   # respaldo antes de actualizar
git pull
docker compose up -d --build
```

## 7. Comprobaciones después de instalar

- `https://…/salud/` responde `ok`.
- `docker compose exec web python manage.py check --deploy` no muestra errores.
- `docker compose exec web python manage.py verificar_auditoria` indica «Bitácora íntegra».
- Haga un respaldo y **verifíquelo** (vea operacion.md).

## Instalación sin Docker

Es posible (Python 3.12, PostgreSQL 16, un proxy con HTTPS delante y `NOMINA_ENTORNO=produccion`,
`NOMINA_PROXIES_CONFIABLES=1`), pero la configuración de Docker ya trae el sistema de archivos de sólo lectura,
el usuario sin privilegios, la base de datos sin puertos expuestos y los respaldos programados.
