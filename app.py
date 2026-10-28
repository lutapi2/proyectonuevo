import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.cookies import CookieError, SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
STATIC_FILES = {
    "/index.html": ROOT / "index.html",
    "/css/estilos.css": ROOT / "css" / "estilos.css",
    "/js/script.js": ROOT / "js" / "script.js",
}
DATA_DIR = Path(os.environ.get("BETANA_DATA_DIR", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "betana.sqlite3"
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_REQUEST_SIZE = MAX_IMAGE_SIZE + 64 * 1024
UPLOAD_WINDOW_SECONDS = 60 * 60
UPLOAD_MAX_PER_WINDOW = 10
UPLOADS_BY_IP = defaultdict(deque)
UPLOADS_LOCK = threading.Lock()
ADMIN_PASSWORD = os.environ.get("BETANA_ADMIN_PASSWORD")
SESSION_COOKIE = "betana_admin"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPTS_BY_IP = defaultdict(deque)
LOGIN_ATTEMPTS_LOCK = threading.Lock()
ADMIN_SESSIONS = {}
ADMIN_SESSIONS_LOCK = threading.Lock()
COOKIE_SECURE = os.environ.get("BETANA_COOKIE_SECURE", "false").lower() == "true"
IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

SEED_PRODUCTS = (
    (
        "ZAPATO SALÓN TACÓN PIEL",
        259000,
        "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=800&q=80",
    ),
    (
        "MOCASÍN SUELA TRACK",
        359000,
        "https://images.unsplash.com/photo-1560343090-f0409e92791a?auto=format&fit=crop&w=800&q=80",
    ),
    (
        "BOTA PIEL TACÓN ANCHO",
        499000,
        "https://images.unsplash.com/photo-1608256246200-53e635b5b65f?auto=format&fit=crop&w=800&q=80",
    ),
    (
        "SANDALIA TIRAS TACÓN",
        199000,
        "https://images.unsplash.com/photo-1562183241-b937e95585b6?auto=format&fit=crop&w=800&q=80",
    ),
)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def connect_database():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def database():
    connection = connect_database()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    with database() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                img TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(products)")
        }
        if "sort_order" not in columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
            connection.execute("UPDATE products SET sort_order = id")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        seed_completed = connection.execute(
            "SELECT value FROM app_settings WHERE key = 'initial_seed_completed'"
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if seed_completed is None:
            if count == 0:
                connection.executemany(
                    "INSERT INTO products (name, price, img, sort_order) VALUES (?, ?, ?, ?)",
                    [
                        (name, price, image, position)
                        for position, (name, price, image) in enumerate(SEED_PRODUCTS)
                    ],
                )
            connection.execute(
                "INSERT INTO app_settings (key, value) VALUES ('initial_seed_completed', 'true')"
            )


def product_list():
    with database() as connection:
        rows = connection.execute(
            "SELECT id, name, price, img FROM products ORDER BY sort_order, id"
        ).fetchall()
    return [dict(row) for row in rows]


def parse_multipart_fields(content_type, body):
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("latin-1")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    if message.get_content_type() != "multipart/form-data":
        raise ApiError(HTTPStatus.BAD_REQUEST, "El formulario no tiene un formato válido.")

    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        value = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            fields[name] = value
        else:
            try:
                fields[name] = value.decode(part.get_content_charset() or "utf-8").strip()
            except (LookupError, UnicodeDecodeError) as error:
                raise ApiError(HTTPStatus.BAD_REQUEST, "El formulario contiene texto no válido.") from error
    return fields


def get_image_extension(image_data):
    for signature, extension in IMAGE_SIGNATURES:
        if image_data.startswith(signature):
            return extension
    if (
        len(image_data) >= 12
        and image_data.startswith(b"RIFF")
        and image_data[8:12] == b"WEBP"
    ):
        return ".webp"
    raise ApiError(HTTPStatus.BAD_REQUEST, "La imagen debe ser PNG, JPG, GIF o WEBP válida.")


class BetanaHandler(BaseHTTPRequestHandler):
    server_version = "BETANA"
    sys_version = ""

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://images.unsplash.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'",
        )
        super().end_headers()

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json_with_cookie(self, status, data, cookie):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/products":
                self.send_json(HTTPStatus.OK, product_list())
                return
            if path == "/api/session":
                self.send_json(HTTPStatus.OK, {"authenticated": self.has_admin_session()})
                return
            self.serve_file(path)
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except (OSError, sqlite3.Error):
            logging.exception("No se pudo procesar la solicitud GET %s", path)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "No se pudo leer el catálogo."})

    def do_POST(self):
        path = unquote(urlsplit(self.path).path)
        if path not in ("/api/products", "/api/login", "/api/logout"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada."})
            return

        try:
            if path == "/api/login":
                self.login()
            elif path == "/api/logout":
                self.logout()
            else:
                self.require_admin()
                self.add_product()
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except (OSError, sqlite3.Error):
            logging.exception("No se pudo procesar la solicitud POST %s", path)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "No se pudo procesar la solicitud."})

    def has_admin_session(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return False
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return False

        token = morsel.value
        now = time.time()
        with ADMIN_SESSIONS_LOCK:
            expires_at = ADMIN_SESSIONS.get(token)
            if expires_at is None:
                return False
            if expires_at <= now:
                del ADMIN_SESSIONS[token]
                return False
            return True

    def require_admin(self):
        if not self.has_admin_session():
            raise ApiError(HTTPStatus.UNAUTHORIZED, "Inicia sesión como administrador para añadir productos.")

    def login(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(HTTPStatus.BAD_REQUEST, "La solicitud de acceso no tiene un formato válido.")
        try:
            data = json.loads(self.read_body(4096))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "La solicitud de acceso no tiene un formato válido.") from error
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(password, str):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Escribe la clave de administrador.")

        client_ip = self.client_address[0]
        now = time.monotonic()
        with LOGIN_ATTEMPTS_LOCK:
            attempts = LOGIN_ATTEMPTS_BY_IP[client_ip]
            while attempts and now - attempts[0] >= LOGIN_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= LOGIN_MAX_ATTEMPTS:
                raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "Demasiados intentos. Espera 15 minutos para volver a intentar.")

        if ADMIN_PASSWORD is None or not secrets.compare_digest(password, ADMIN_PASSWORD):
            with LOGIN_ATTEMPTS_LOCK:
                LOGIN_ATTEMPTS_BY_IP[client_ip].append(now)
            raise ApiError(HTTPStatus.UNAUTHORIZED, "La clave de administrador es incorrecta.")

        with LOGIN_ATTEMPTS_LOCK:
            LOGIN_ATTEMPTS_BY_IP.pop(client_ip, None)
        token = secrets.token_urlsafe(32)
        with ADMIN_SESSIONS_LOCK:
            for existing_token, expires_at in list(ADMIN_SESSIONS.items()):
                if expires_at <= time.time():
                    del ADMIN_SESSIONS[existing_token]
            ADMIN_SESSIONS[token] = time.time() + SESSION_TTL_SECONDS
        cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}"
        if COOKIE_SECURE:
            cookie += "; Secure"
        self.send_json_with_cookie(HTTPStatus.OK, {"authenticated": True}, cookie)

    def logout(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookie = SimpleCookie()
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is not None:
            with ADMIN_SESSIONS_LOCK:
                ADMIN_SESSIONS.pop(morsel.value, None)
        expired_cookie = f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
        if COOKIE_SECURE:
            expired_cookie += "; Secure"
        self.send_json_with_cookie(HTTPStatus.OK, {"authenticated": False}, expired_cookie)

    def do_PUT(self):
        self.reject_catalog_write()

    def do_PATCH(self):
        self.reject_catalog_write()

    def do_DELETE(self):
        path = unquote(urlsplit(self.path).path)
        match = re.fullmatch(r"/api/products/([1-9][0-9]{0,18})", path)
        if match is None:
            self.reject_catalog_write()
            return

        product_id = int(match.group(1))
        if product_id > 9_223_372_036_854_775_807:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Artículo no encontrado."})
            return

        try:
            self.require_admin()
            self.delete_product(product_id)
        except ApiError as error:
            self.send_json(error.status, {"error": error.message})
        except (OSError, sqlite3.Error):
            logging.exception("No se pudo eliminar el artículo %s.", product_id)
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "No se pudo eliminar el artículo."})

    def reject_catalog_write(self):
        self.send_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Esta acción no está permitida."})

    def read_body(self, limit):
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ApiError(HTTPStatus.BAD_REQUEST, "La solicitud no tiene un tamaño válido.") from error
        if content_length < 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, "La solicitud no tiene un tamaño válido.")
        if content_length > limit:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "El archivo supera el límite permitido de 5 MB.")
        body = self.rfile.read(content_length)
        if len(body) != content_length:
            raise ApiError(HTTPStatus.BAD_REQUEST, "La solicitud llegó incompleta.")
        return body

    def check_upload_limit(self):
        client_ip = self.client_address[0]
        now = time.monotonic()
        with UPLOADS_LOCK:
            uploads = UPLOADS_BY_IP[client_ip]
            while uploads and now - uploads[0] >= UPLOAD_WINDOW_SECONDS:
                uploads.popleft()
            if len(uploads) >= UPLOAD_MAX_PER_WINDOW:
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Se alcanzó el límite de 10 productos por hora para esta conexión.",
                )
            uploads.append(now)

    def add_product(self):
        content_type = self.headers.get("Content-Type", "")
        fields = parse_multipart_fields(content_type, self.read_body(MAX_REQUEST_SIZE))
        name = fields.get("name", "")
        price_text = fields.get("price", "")
        image_data = fields.get("image", b"")

        if not isinstance(name, str) or not name or len(name) > 100:
            raise ApiError(HTTPStatus.BAD_REQUEST, "El nombre es obligatorio y debe tener máximo 100 caracteres.")
        if any(ord(character) < 32 for character in name):
            raise ApiError(HTTPStatus.BAD_REQUEST, "El nombre contiene caracteres no permitidos.")
        if not isinstance(price_text, str) or not re.fullmatch(r"[0-9]{1,10}", price_text):
            raise ApiError(HTTPStatus.BAD_REQUEST, "El precio debe ser un número entero en pesos colombianos.")
        price = int(price_text)
        if price < 1 or price > 1_000_000_000:
            raise ApiError(HTTPStatus.BAD_REQUEST, "El precio debe estar entre 1 y 1.000.000.000 COP.")
        if not isinstance(image_data, bytes) or not image_data:
            raise ApiError(HTTPStatus.BAD_REQUEST, "Selecciona una imagen para el artículo.")
        if len(image_data) > MAX_IMAGE_SIZE:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "La imagen supera el límite permitido de 5 MB.")

        extension = get_image_extension(image_data)
        self.check_upload_limit()
        filename = f"{uuid.uuid4().hex}{extension}"
        image_path = UPLOAD_DIR / filename
        image_path.write_bytes(image_data)

        try:
            with database() as connection:
                next_sort_order = connection.execute(
                    "SELECT COALESCE(MIN(sort_order), 0) - 1 FROM products"
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO products (name, price, img, sort_order) VALUES (?, ?, ?, ?)",
                    (name, price, f"/uploads/{filename}", next_sort_order),
                )
        except sqlite3.Error:
            image_path.unlink(missing_ok=True)
            raise

        self.send_json(HTTPStatus.CREATED, product_list())

    def delete_product(self, product_id):
        with database() as connection:
            product = connection.execute(
                "SELECT img FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if product is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Artículo no encontrado.")
            connection.execute("DELETE FROM products WHERE id = ?", (product_id,))

        warning = None
        image_url = product["img"]
        if image_url.startswith("/uploads/"):
            filename = image_url[len("/uploads/"):]
            if Path(filename).name == filename:
                try:
                    (UPLOAD_DIR / filename).unlink(missing_ok=True)
                except OSError:
                    logging.exception("El artículo %s se eliminó, pero no se pudo borrar su imagen.", product_id)
                    warning = "El artículo se eliminó, pero no se pudo borrar su archivo de imagen."

        self.send_json(HTTPStatus.OK, {"products": product_list(), "warning": warning})

    def serve_file(self, url_path):
        if url_path == "/":
            url_path = "/index.html"

        if url_path.startswith("/uploads/"):
            filename = url_path[len("/uploads/"):]
            if Path(filename).name != filename:
                raise ApiError(HTTPStatus.NOT_FOUND, "Archivo no encontrado.")
            file_path = UPLOAD_DIR / filename
        else:
            file_path = STATIC_FILES.get(url_path)
            if file_path is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "Archivo no encontrado.")

        if not file_path.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "Archivo no encontrado.")

        body = file_path.read_bytes()
        content_type, _ = mimetypes.guess_type(file_path.name)
        content_type = content_type or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        cache_control = (
            "public, max-age=3600"
            if url_path.startswith("/uploads/")
            else "no-cache"
        )
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)


def main():
    if not ADMIN_PASSWORD:
        raise RuntimeError("Configura BETANA_ADMIN_PASSWORD antes de iniciar BETANA.")
    initialize_database()
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), BetanaHandler)
    logging.info("BETANA está disponible en http://127.0.0.1:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Cerrando el servidor BETANA.")
    finally:
        server.server_close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
