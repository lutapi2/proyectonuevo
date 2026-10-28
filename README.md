# BETANA

Catálogo público de calzado. La página muestra productos guardados en SQLite y permite agregar productos sin iniciar sesión.

## Ejecutar en Windows

1. Instala Python 3 desde [python.org](https://www.python.org/downloads/) si aún no está instalado.
2. Abre PowerShell en esta carpeta y ejecuta:

   ```powershell
   .\run.ps1
   ```

3. Abre [http://localhost:8000](http://localhost:8000). Mantén abierta la ventana de PowerShell mientras uses la tienda; para detenerla, presiona `Ctrl+C`.

En el primer inicio se cargan cuatro productos de ejemplo. Usa el botón **+ Añadir** para guardar un producto con nombre, precio e imagen. El catálogo y las imágenes se conservan en `data\betana.sqlite3` y `data\uploads`; no borres la carpeta `data` si quieres conservarlos.

**Aviso:** como pediste que no haya inicio de sesión, cualquier persona que visite la página puede agregar productos. El servidor limita cada conexión a 10 productos por hora y las imágenes a 5 MB, pero no identifica quién envía cada alta. No publiques el formulario abierto si necesitas controlar quién administra el catálogo.

Si aparece un error `Forbidden` o la página no conecta con el catálogo, confirma que `.\run.ps1` siga ejecutándose y que abriste `http://localhost:8000`. Abrir `index.html` directamente no funciona porque las solicitudes del catálogo necesitan el servidor.

## Publicar en internet

El archivo `render.yaml` configura BETANA para Render con un disco persistente montado en `/var/data`. El disco persistente requiere un servicio de pago en Render; sin él, los datos pueden perderse cuando se reinicie el servicio.

1. Crea un repositorio privado de GitHub y sube dentro de él los archivos y carpetas que están en `BETANA` (incluido `render.yaml`).
2. En Render, crea un **Blueprint** y conecta ese repositorio.
3. Espera a que termine el despliegue y abre la URL que Render asigna al servicio.

La página no incluye opciones para eliminar ni editar productos.
