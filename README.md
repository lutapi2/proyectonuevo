# BETANA

Catálogo público de calzado. Los visitantes pueden ver los productos; solo el administrador puede añadirlos.

## Ejecutar en Windows

1. Instala Python 3 desde [python.org](https://www.python.org/downloads/) si aún no está instalado.
2. Abre PowerShell en esta carpeta y ejecuta:

   ```powershell
   .\run.ps1
   ```

3. Abre [http://localhost:8000](http://localhost:8000). Mantén abierta la ventana de PowerShell mientras uses la tienda; para detenerla, presiona `Ctrl+C`.

En el primer inicio se cargan cuatro productos de ejemplo. Para añadir o eliminar productos, pulsa **Administrar** e ingresa la clave. En cada artículo aparecerá **Eliminar artículo**; se pedirá confirmación antes de borrarlo. El botón **Salir** cierra la sesión. La clave local inicial es `1234567890`; puedes cambiarla antes de iniciar PowerShell con `$env:BETANA_ADMIN_PASSWORD = 'tu-clave-larga'`. El catálogo y las imágenes se conservan en `data\betana.sqlite3` y `data\uploads`; no borres la carpeta `data` si quieres conservarlos.

La administración usa una sesión temporal de 12 horas y limita a cinco los intentos fallidos por conexión cada 15 minutos. El servidor también conserva el límite de 10 productos por hora y de 5 MB por imagen. Las sesiones se invalidan al reiniciar el servidor.

**Seguridad:** `1234567890` es una clave débil y solo debe usarse para pruebas locales. Antes de publicar la tienda, configura una clave larga y única como variable secreta `BETANA_ADMIN_PASSWORD` en Render. El archivo `render.yaml` solicita esa variable durante la configuración y activa cookies seguras para HTTPS. No compartas ni subas la clave al repositorio.

Si aparece un error `Forbidden` o la página no conecta con el catálogo, confirma que `.\run.ps1` siga ejecutándose y que abriste `http://localhost:8000`. Abrir `index.html` directamente no funciona porque las solicitudes del catálogo necesitan el servidor.

## Publicar en internet

El archivo `render.yaml` configura BETANA para Render con un disco persistente montado en `/var/data`. El disco persistente requiere un servicio de pago en Render; sin él, los datos pueden perderse cuando se reinicie el servicio.

1. Crea un repositorio privado de GitHub y sube dentro de él los archivos y carpetas que están en `BETANA` (incluido `render.yaml`).
2. En Render, crea un **Blueprint** y conecta ese repositorio.
3. Espera a que termine el despliegue y abre la URL que Render asigna al servicio.

La administración permite añadir y eliminar productos; todavía no permite editar productos.
