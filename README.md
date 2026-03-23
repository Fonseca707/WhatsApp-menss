# WhatsApp-menss

Ahora el proyecto tiene dos caminos complementarios:

1. **Automático desde base de datos**: lee mensajes `pending` desde SQLite y los envía por WhatsApp Web en Chrome.
2. **Captura manual + inserción + ejecución**: desde una ventana de Windows puedes capturar los datos manualmente, insertarlos en la base y lanzar el proceso de envío en el momento.

## Flujo manual que pediste

La funcionalidad nueva permite esto desde `whatsapp_sender_windows.py`:

1. Escribes manualmente el **número**.
2. Escribes manualmente el **mensaje**.
3. Presionas **Insertar en cola** o **Insertar y ejecutar**.
4. El dato se inserta en la tabla `outbound_messages`.
5. La aplicación lanza `whatsapp_db_sender.py` para procesar los pendientes y abrir WhatsApp Web en Chrome.

También puedes pegar varias filas con formato:

```text
numero|mensaje
5215512345678|Hola Ana
5213312345678|Hola Carlos
```

## Archivos principales

- `whatsapp_db_sender.py`: lógica de base de datos y automatización de WhatsApp Web.
- `whatsapp_sender_windows.py`: interfaz para captura manual, inserción en DB y ejecución del envío.
- `launch_windows.bat`: abre la interfaz manual en Windows.
- `requirements.txt`: dependencia de Selenium.
- `contactos_ejemplo.txt`: ejemplo para carga manual por lote.

## Requisitos

- Windows 10 o Windows 11.
- Python 3.10 o superior.
- Google Chrome instalado.
- Una sesión válida de WhatsApp Web.

Instalación:

```powershell
py -3 -m pip install -r requirements.txt
```

## Cómo usar la captura manual

Ejecuta:

```powershell
py -3 whatsapp_sender_windows.py
```

O con doble clic en:

```text
launch_windows.bat
```

### Qué puedes hacer desde la ventana

- indicar la ruta de la base SQLite;
- indicar la carpeta de perfil de Chrome;
- capturar un registro manualmente;
- insertar un lote de registros con `numero|mensaje`;
- ver los últimos registros guardados;
- ejecutar el envío pendiente sin salir de la interfaz.

## Base de datos

Tabla usada:

```sql
CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    error_message TEXT
);
```

Estados:

- `pending`
- `processing`
- `sent`
- `failed`

## Línea de comandos del proceso automático

Para procesar manualmente los pendientes sin abrir la interfaz:

```powershell
py -3 whatsapp_db_sender.py --db whatsapp_messages.db --profile-dir chrome-profile
```

Opciones útiles:

- `--db`: ruta del archivo SQLite.
- `--profile-dir`: carpeta del perfil de Chrome.
- `--limit`: cantidad máxima de mensajes por ejecución.
- `--wait-seconds`: espera máxima para login/carga.
- `--chrome-binary`: ruta manual a `chrome.exe`.
- `--init-db`: crea o valida la tabla.
- `--seed-example`: inserta mensajes de ejemplo.

## Ejemplos de inserción manual por lote

Puedes pegar el contenido de `contactos_ejemplo.txt` en la interfaz:

```text
5215512345678|Hola Ana, este mensaje salió desde la base de datos.
5213312345678|Hola Carlos, tu recordatorio fue tomado desde SQLite.
15559876543|Hola John, este mensaje se enviará por WhatsApp Web.
```

## ¿En qué ayuda Codex?

Sí, Codex te puede ayudar a extender esta base para:

- usar SQL Server, MySQL o PostgreSQL;
- conectar la carga manual con tu sistema interno;
- empaquetar la app como `.exe`;
- programar envíos por lotes o por horarios.

## Limitaciones

- El primer login de WhatsApp Web requiere escanear QR.
- La automatización depende de la interfaz de WhatsApp Web.
- Si un dato manual se captura mal, el registro puede quedar en `failed`.
