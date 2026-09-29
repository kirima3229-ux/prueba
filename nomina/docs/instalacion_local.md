# Probar el sistema en su computadora (Windows o Mac)

Esta instalación es **para probar**: usa una base de datos en un archivo (SQLite) y funciona sólo en su
computadora. Para trabajar con datos reales use la [instalación en producción](instalacion_produccion.md).

Tiempo: 15 a 20 minutos. Necesita: conexión a internet, su teléfono con una aplicación de verificación
(Google Authenticator o Microsoft Authenticator) y acceso al repositorio en GitHub.

## 1. Instalar Python (una sola vez)

**Windows**
1. Vaya a <https://www.python.org/downloads/> y descargue **Python 3.12**.
2. Al instalar, **marque la casilla «Add python.exe to PATH»** (abajo en la primera pantalla) y pulse
   *Install Now*.

**Mac**
1. Vaya a <https://www.python.org/downloads/> y descargue **Python 3.12** para macOS.
2. Abra el instalador y siga los pasos. Al final, en la carpeta *Aplicaciones → Python 3.12*, haga doble clic en
   *Install Certificates.command*.

## 2. Descargar el sistema

1. En GitHub, abra el repositorio **kirima3229-ux/prueba**.
2. Cambie a la rama **ccr-42ce2f0a-lgautl** (botón con el nombre de la rama, arriba a la izquierda).
3. Botón verde **Code → Download ZIP**.
4. Descomprima el ZIP, por ejemplo en *Documentos*. Dentro hay una carpeta **nomina**.

## 3. Abrir la terminal en la carpeta `nomina`

- **Windows:** abra la carpeta `nomina` en el Explorador de archivos, haga clic en la barra de dirección,
  escriba `cmd` y pulse Enter.
- **Mac:** abra *Terminal*, escriba `cd ` (con un espacio), arrastre la carpeta `nomina` a la ventana y pulse
  Enter.

## 4. Instalar (una sola vez)

Copie y pegue cada línea y pulse Enter. Espere a que termine antes de la siguiente.

**Windows**
```
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python generar_env.py
python manage.py migrate
python manage.py createsuperuser
python manage.py cargar_demo
```

**Mac**
```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python generar_env.py
python manage.py migrate
python manage.py createsuperuser
python manage.py cargar_demo
```

- `generar_env.py` crea el archivo `.env` con las llaves de cifrado de esta prueba.
- `createsuperuser` pide un usuario, un correo (puede dejarlo vacío) y una contraseña de **12 caracteres o
  más** (no se ve mientras la escribe; es normal).
- `cargar_demo` es opcional: crea la compañía ficticia *Restaurante La Ceiba, LLC* con 6 empleados y 4 nóminas,
  la misma del preview. Si prefiere empezar vacío, no lo ejecute.

## 5. Abrir el sistema

```
python manage.py runserver
```

Deje esa ventana abierta y en el navegador vaya a **<http://127.0.0.1:8000>**.

1. Entre con el usuario y la contraseña que creó.
2. La primera vez le pide configurar la verificación en dos pasos: escanee el código QR con la aplicación del
   teléfono y escriba el código de 6 dígitos.
3. Arriba a la derecha escoja la compañía (*Restaurante La Ceiba, LLC* si cargó la demostración).

Para cerrar el sistema: en la terminal pulse **Ctrl + C**.

## Las próximas veces

Abra la terminal en la carpeta `nomina` (paso 3) y escriba:

- **Windows:** `.venv\Scripts\activate` y luego `python manage.py runserver`
- **Mac:** `source .venv/bin/activate` y luego `python manage.py runserver`

## Si algo falla

| Mensaje | Solución |
|---|---|
| `'py' no se reconoce…` / `python3.12: command not found` | Python no quedó instalado o, en Windows, faltó marcar *Add python.exe to PATH*. Reinstale |
| `Ya existe …/.env` | Ya estaba creado; siga con el próximo paso |
| `Los datos de demostración ya están cargados` | Ya estaban; siga con el próximo paso |
| El código de 6 dígitos no funciona | Revise que la hora del teléfono y de la computadora estén correctas (automáticas) |
| Cuenta bloqueada tras 5 intentos | `python manage.py axes_reset` |
| Quiere empezar de cero | Cierre el sistema y borre los archivos `db.sqlite3` y `.env` de la carpeta `nomina`; repita desde `python generar_env.py` |

**Importante:** esta instalación de prueba no es para datos reales de empleados. Para eso use la
[instalación en producción](instalacion_produccion.md), con respaldos y HTTPS.
