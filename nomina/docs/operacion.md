# Operación: respaldos, restauración, llaves y recuperación

Todos los comandos se ejecutan dentro del contenedor, por ejemplo
`docker compose exec respaldos python manage.py respaldar`. Sin Docker, `python manage.py …`.

## Respaldos

**Automáticos.** El servicio `respaldos` crea uno cada día a las 2:00 a. m. (hora de Puerto Rico;
`NOMINA_HORA_RESPALDO`) en el volumen `respaldos` y borra los de más de 35 días (`NOMINA_DIAS_RESPALDO`).

**Manual:** `python manage.py respaldar [--destino CARPETA] [--conservar-dias N]`

Cada respaldo (`nomina-AAAAMMDD-HHMMSS.respaldo`):

- contiene **toda** la base de datos (`pg_dump`), cifrada con AES-256-GCM por bloques;
- usa la llave `NOMINA_LLAVE_RESPALDO`, distinta de las llaves de los campos: dentro del respaldo los SSN y las
  cuentas siguen cifrados con sus propias llaves;
- detecta cualquier alteración, un archivo cortado o de más;
- queda en la bitácora con su huella SHA-256.

**Copia fuera del servidor (obligatorio).** Un respaldo en el mismo servidor no protege contra la pérdida del
servidor. Copie diariamente la carpeta de respaldos a otro lugar (otro servidor, almacenamiento en la nube,
disco externo rotativo). Como están cifrados, pueden guardarse en un servicio externo.

```bash
docker compose cp respaldos:/app/respaldos ./copia-respaldos      # ejemplo: sacarlos del volumen
```

**Verificar (una vez al mes, como mínimo):**

```bash
python manage.py verificar_respaldo /app/respaldos/nomina-20261001-020000.respaldo
```

Descifra el archivo completo y comprueba que el volcado de la base de datos es válido, sin cambiar nada.

## Restauración

Reemplaza **todos** los datos actuales con los del respaldo.

1. Detenga la aplicación: `docker compose stop web caddy`
2. Si la base de datos actual todavía tiene algo útil, respáldela primero.
3. Restaure:
   ```bash
   docker compose run --rm respaldos python manage.py restaurar /app/respaldos/ARCHIVO.respaldo --confirmar
   ```
4. Verifique la bitácora: `docker compose run --rm respaldos python manage.py verificar_auditoria`
5. Arranque: `docker compose up -d`

Para restaurar en un servidor nuevo: instale según [instalacion_produccion.md](instalacion_produccion.md)
**usando el `.env` original** (mismas llaves), copie el respaldo al volumen y siga los pasos anteriores.

## Custodia de las llaves

| Llave | Si se pierde | Si se filtra |
|---|---|---|
| `NOMINA_LLAVES_CIFRADO` | Los SSN, cuentas y números patronales **no se recuperan** | Rote la llave (abajo) |
| `NOMINA_LLAVE_INDICE` | Se recalcula con `rotar_llaves --llave-indice-nueva` | Rote la llave |
| `NOMINA_LLAVE_RESPALDO` | Los respaldos hechos con ella **no se pueden restaurar** | Cree una nueva y haga un respaldo nuevo |
| `DJANGO_SECRET_KEY` | Se cambia; todos vuelven a entrar | Cámbiela |

- Guarde el `.env` en dos lugares seguros **fuera del servidor**, separados de los respaldos.
- Sólo el administrador del sistema debe tener acceso al `.env` y al servidor.

## Rotación de llaves

Recomendado una vez al año o si se sospecha que una llave se filtró.

**Llaves de los campos:**

1. Genere una llave: `python manage.py generar_llave`
2. En el `.env`, añádala sin quitar la anterior y hágala activa:
   `NOMINA_LLAVES_CIFRADO=1:<vieja>,2:<nueva>` y `NOMINA_LLAVE_ACTIVA=2`
3. Detenga la aplicación, haga un respaldo y reinicie los contenedores para que lean el `.env`.
4. `python manage.py rotar_llaves --inventario` (cuántos valores tiene cada llave)
5. `python manage.py rotar_llaves --confirmar` (vuelve a cifrar todo con la llave 2, en una sola transacción)
6. Conserve la llave vieja en el `.env` mientras existan respaldos hechos antes de la rotación (35 días); después
   puede quitarla.

**Llave del índice ciego:**

1. Detenga la aplicación y haga un respaldo.
2. `python manage.py rotar_llaves --confirmar --llave-indice-nueva=<llave nueva>`
3. Ponga esa llave en `NOMINA_LLAVE_INDICE` y arranque.

**Llave de respaldos:** ponga la nueva primero: `NOMINA_LLAVE_RESPALDO=<nueva>,<vieja>`. Los respaldos nuevos
usan la nueva y los viejos se siguen restaurando con la vieja.

## Tareas frecuentes

| Situación | Qué hacer |
|---|---|
| Usuario bloqueado por intentos fallidos | *Usuarios → Desbloquear* (administrador) |
| Usuario perdió el teléfono (2FA) | *Usuarios → Reiniciar 2FA*; configurará uno nuevo al entrar |
| Administrador bloqueado y no hay otro | `python manage.py axes_reset_username <usuario>` |
| Revisar la integridad de la bitácora | `python manage.py verificar_auditoria` |
| Ver los registros de la aplicación | `docker compose logs -f web` |

## Plan ante desastres

1. Servidor perdido: servidor nuevo → instalación con el `.env` guardado → restaurar el último respaldo copiado
   fuera → verificar la bitácora.
2. Datos dañados por error: restaurar el respaldo anterior al error (lo hecho después se vuelve a entrar).
3. Sospecha de acceso indebido: revisar *Auditoría* (entradas, accesos denegados, archivos generados), cambiar
   contraseñas, reiniciar 2FA, rotar llaves y `DJANGO_SECRET_KEY`.
