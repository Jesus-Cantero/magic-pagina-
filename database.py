"""
database.py

Funciones de acceso a la base de datos SQLite (mtg_cards.db).
Toda la lógica de consultas SQL vive aquí para mantener app.py limpio.

El esquema (tablas, índices y versión) también se define aquí, para que
app.py y download_cards.py usen exactamente la misma estructura.
"""

import base64
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

# Ruta ABSOLUTA a la base de datos, calculada a partir de la carpeta donde
# está este archivo. Así funciona igual aunque ejecutes `python app.py`
# desde otra carpeta.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "mtg_cards.db")
BACKUP_JSON_PATH = os.path.join(BASE_DIR, "datos_persistentes.json")
_RESTAURADO_EN_ARRANQUE = False

# Versión del esquema. Se guarda en `PRAGMA user_version`.
#   0 -> base de datos vacía o del esquema antiguo (clave = id de impresión)
#   2 -> esquema actual (clave = oracle_id, UNIQUE en mazo_cartas, tabla meta)
VERSION_ESQUEMA = 2

# Límites de validación compartidos con app.py
MAX_COPIAS_POR_CARTA = 99
MAX_LONGITUD_NOMBRE_MAZO = 100
MAX_LONGITUD_FORMATO = 50

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS cartas (
    id TEXT PRIMARY KEY,            -- oracle_id de Scryfall (estable entre descargas)
    scryfall_id TEXT,               -- id de la impresión concreta usada para imagen/edición
    nombre TEXT NOT NULL,
    coste_mana TEXT,
    cmc REAL,
    tipo TEXT,
    texto TEXT,
    poder TEXT,
    resistencia TEXT,
    colores TEXT,                   -- letras separadas por comas: "W,U"
    identidad_color TEXT,
    rareza TEXT,
    set_code TEXT,
    set_nombre TEXT,
    imagen_url TEXT,
    legalidades TEXT,               -- JSON: {"standard": "legal", ...}
    fecha_lanzamiento TEXT,
    es_spoiler INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nombre ON cartas (nombre);
CREATE INDEX IF NOT EXISTS idx_tipo ON cartas (tipo);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    google_id TEXT UNIQUE,
    avatar_url TEXT,
    creado_en TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mazos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER REFERENCES usuarios (id) ON DELETE CASCADE,
    comandante_id TEXT REFERENCES cartas (id),
    comandante_imagen_personalizada TEXT,
    nombre TEXT NOT NULL,
    formato TEXT,
    bracket_objetivo INTEGER DEFAULT 0,
    creado_en TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mazo_cartas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mazo_id INTEGER NOT NULL,
    carta_id TEXT NOT NULL,
    cantidad INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    imagen_personalizada TEXT,
    FOREIGN KEY (mazo_id) REFERENCES mazos (id) ON DELETE CASCADE,
    FOREIGN KEY (carta_id) REFERENCES cartas (id),
    UNIQUE (mazo_id, carta_id)
);

CREATE TABLE IF NOT EXISTS albumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER REFERENCES usuarios (id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    color_cubierta TEXT DEFAULT 'negro',
    filas INTEGER NOT NULL DEFAULT 3,
    columnas INTEGER NOT NULL DEFAULT 4,
    creado_en TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS album_cartas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id INTEGER NOT NULL,
    pagina INTEGER NOT NULL DEFAULT 1 CHECK (pagina >= 1),
    posicion INTEGER NOT NULL DEFAULT 0 CHECK (posicion >= 0),
    carta_id TEXT NOT NULL,
    imagen_personalizada TEXT,
    acabado_foil INTEGER NOT NULL DEFAULT 0,
    cantidad INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    agregado_en TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (album_id) REFERENCES albumes (id) ON DELETE CASCADE,
    FOREIGN KEY (carta_id) REFERENCES cartas (id),
    UNIQUE (album_id, pagina, posicion)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # nos permite acceder a columnas por nombre
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def conexion():
    """
    Abre una conexión y la cierra SIEMPRE, aunque haya una excepción.
    Uso:
        with conexion() as conn:
            conn.execute(...)
    """
    conn = obtener_conexion()
    try:
        yield conn
    finally:
        conn.close()


# ---------- Esquema / estado ----------

def crear_esquema(conn):
    """Crea todas las tablas (si no existen) y marca la versión del esquema."""
    conn.executescript(ESQUEMA_SQL)
    conn.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
    conn.commit()


def tabla_existe(conn, nombre):
    fila = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (nombre,)
    ).fetchone()
    return fila is not None


def asegurar_esquema_usuarios(conn):
    """
    Asegura que la tabla `usuarios` y la columna `mazos.usuario_id` existan
    en bases de datos ya creadas, sin necesidad de volver a descargar cartas.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            avatar_url TEXT,
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    if tabla_existe(conn, "cartas"):
        col_cartas = [f[1] for f in conn.execute("PRAGMA table_info(cartas)").fetchall()]
        if "fecha_lanzamiento" not in col_cartas:
            conn.execute("ALTER TABLE cartas ADD COLUMN fecha_lanzamiento TEXT")
        if "es_spoiler" not in col_cartas:
            conn.execute("ALTER TABLE cartas ADD COLUMN es_spoiler INTEGER DEFAULT 0")
    if tabla_existe(conn, "mazos"):
        columnas = [f[1] for f in conn.execute("PRAGMA table_info(mazos)").fetchall()]
        if "usuario_id" not in columnas:
            conn.execute("ALTER TABLE mazos ADD COLUMN usuario_id INTEGER REFERENCES usuarios (id) ON DELETE CASCADE")
        if "comandante_id" not in columnas:
            conn.execute("ALTER TABLE mazos ADD COLUMN comandante_id TEXT REFERENCES cartas (id)")
        if "bracket_objetivo" not in columnas:
            conn.execute("ALTER TABLE mazos ADD COLUMN bracket_objetivo INTEGER DEFAULT 0")
        if "comandante_imagen_personalizada" not in columnas:
            conn.execute("ALTER TABLE mazos ADD COLUMN comandante_imagen_personalizada TEXT")
        conn.execute("DELETE FROM mazos WHERE usuario_id IS NULL")
    if tabla_existe(conn, "mazo_cartas"):
        col_mc = [f[1] for f in conn.execute("PRAGMA table_info(mazo_cartas)").fetchall()]
        if "imagen_personalizada" not in col_mc:
            conn.execute("ALTER TABLE mazo_cartas ADD COLUMN imagen_personalizada TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS albumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER REFERENCES usuarios (id) ON DELETE CASCADE,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            color_cubierta TEXT DEFAULT 'negro',
            filas INTEGER NOT NULL DEFAULT 3,
            columnas INTEGER NOT NULL DEFAULT 4,
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS album_cartas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            pagina INTEGER NOT NULL DEFAULT 1 CHECK (pagina >= 1),
            posicion INTEGER NOT NULL DEFAULT 0 CHECK (posicion >= 0),
            carta_id TEXT NOT NULL,
            imagen_personalizada TEXT,
            acabado_foil INTEGER NOT NULL DEFAULT 0,
            cantidad INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
            agregado_en TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (album_id) REFERENCES albumes (id) ON DELETE CASCADE,
            FOREIGN KEY (carta_id) REFERENCES cartas (id),
            UNIQUE (album_id, pagina, posicion)
        )
    """)
    conn.commit()


def estado_bd():
    """
    Devuelve el estado de la base de datos para que app.py pueda avisar al usuario:
      "falta"   -> no existe el archivo mtg_cards.db
      "antigua" -> existe pero tiene el esquema antiguo (hay que volver a descargar)
      "vacia"   -> el esquema es correcto pero no hay cartas
      "ok"      -> todo listo
    """
    global _RESTAURADO_EN_ARRANQUE
    if not os.path.exists(DB_PATH):
        return "falta"
    with conexion() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if not tabla_existe(conn, "cartas"):
            return "vacia"
        if version < VERSION_ESQUEMA:
            return "antigua"
        asegurar_esquema_usuarios(conn)
        hay_cartas = conn.execute("SELECT 1 FROM cartas LIMIT 1").fetchone()
        estado = "ok" if hay_cartas else "vacia"
    if estado == "ok" and not _RESTAURADO_EN_ARRANQUE:
        _RESTAURADO_EN_ARRANQUE = True
        try:
            restaurar_estado_persistente()
        except Exception:
            pass
    return estado


def obtener_meta(clave, por_defecto=None):
    if not os.path.exists(DB_PATH):
        return por_defecto
    try:
        with conexion() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
            fila = conn.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
            return fila["valor"] if fila and fila["valor"] is not None else por_defecto
    except Exception:
        return por_defecto


def guardar_meta(clave, valor):
    if not os.path.exists(DB_PATH):
        return
    with conexion() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
        conn.execute(
            "INSERT INTO meta (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )
        conn.commit()
    guardar_estado_persistente()


def _exportar_snapshot_dict():
    with conexion() as conn:
        usuarios = [dict(r) for r in conn.execute("SELECT * FROM usuarios ORDER BY id").fetchall()]
        mazos = [dict(r) for r in conn.execute("SELECT * FROM mazos ORDER BY id").fetchall()]
        mazo_cartas = [dict(r) for r in conn.execute("SELECT * FROM mazo_cartas ORDER BY id").fetchall()]
        albumes = [dict(r) for r in conn.execute("SELECT * FROM albumes ORDER BY id").fetchall()] if tabla_existe(conn, "albumes") else []
        album_cartas = [dict(r) for r in conn.execute("SELECT * FROM album_cartas ORDER BY id").fetchall()] if tabla_existe(conn, "album_cartas") else []
        meta = {
            r["clave"]: r["valor"]
            for r in conn.execute("SELECT clave, valor FROM meta").fetchall()
            if r["clave"] not in ("gh_sync_token",)
        }
    return {
        "usuarios": usuarios,
        "mazos": mazos,
        "mazo_cartas": mazo_cartas,
        "albumes": albumes,
        "album_cartas": album_cartas,
        "meta": meta,
    }


def _subir_snapshot_github_async(contenido_json):
    token = os.environ.get("GITHUB_SYNC_TOKEN") or obtener_meta("gh_sync_token")
    repo = os.environ.get("GITHUB_SYNC_REPO", "Jesus-Cantero/magic-pagina-")
    if not token:
        return
    url = f"https://api.github.com/repos/{repo}/contents/datos_persistentes.json"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "SusoMTG-Persistence",
    }
    sha = None
    try:
        req_get = urllib.request.Request(f"{url}?ref=datos-persistentes", headers=headers)
        with urllib.request.urlopen(req_get, timeout=8) as resp:
            datos_actuales = json.loads(resp.read().decode("utf-8"))
            sha = datos_actuales.get("sha")
    except Exception:
        pass

    payload = {
        "message": "Sincronizar cuentas y mazos [skip render]",
        "content": base64.b64encode(contenido_json.encode("utf-8")).decode("ascii"),
        "branch": "datos-persistentes",
    }
    if sha:
        payload["sha"] = sha
    try:
        req_put = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        urllib.request.urlopen(req_put, timeout=10).read()
    except Exception:
        pass


def guardar_estado_persistente():
    """
    Guarda una copia ligera de `usuarios`, `mazos` y `mazo_cartas` en disco
    (`datos_persistentes.json`) y la sincroniza en segundo plano con la rama
    `datos-persistentes` para que en Render nunca se borren las cuentas ni los mazos.
    """
    try:
        datos = _exportar_snapshot_dict()
        texto = json.dumps(datos, ensure_ascii=False, indent=2)
        with open(BACKUP_JSON_PATH, "w", encoding="utf-8") as f:
            f.write(texto)
        threading.Thread(target=_subir_snapshot_github_async, args=(texto,), daemon=True).start()
    except Exception:
        pass


def restaurar_estado_persistente():
    """
    Restaura cuentas de usuario, mazos y cartas de mazos desde la rama `datos-persistentes`
    o desde `datos_persistentes.json` local sin perder ningún dato existente.
    """
    datos = None
    repo = os.environ.get("GITHUB_SYNC_REPO", "Jesus-Cantero/magic-pagina-")
    url_raw = f"https://raw.githubusercontent.com/{repo}/datos-persistentes/datos_persistentes.json"
    try:
        req = urllib.request.Request(url_raw, headers={"User-Agent": "SusoMTG-Persistence", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass

    if not datos and os.path.exists(BACKUP_JSON_PATH):
        try:
            with open(BACKUP_JSON_PATH, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception:
            datos = None

    if not isinstance(datos, dict):
        return

    with conexion() as conn:
        for k, v in (datos.get("meta") or {}).items():
            conn.execute(
                "INSERT INTO meta (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = COALESCE(meta.valor, excluded.valor)",
                (k, v),
            )
        for u in datos.get("usuarios") or []:
            conn.execute(
                """
                INSERT INTO usuarios (id, nombre, email, password_hash, google_id, avatar_url, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    nombre = COALESCE(excluded.nombre, usuarios.nombre),
                    password_hash = COALESCE(excluded.password_hash, usuarios.password_hash),
                    google_id = COALESCE(excluded.google_id, usuarios.google_id),
                    avatar_url = COALESCE(excluded.avatar_url, usuarios.avatar_url)
                """,
                (
                    u.get("id"),
                    u.get("nombre") or "Planeswalker",
                    (u.get("email") or "").strip().lower(),
                    u.get("password_hash"),
                    u.get("google_id"),
                    u.get("avatar_url"),
                    u.get("creado_en"),
                ),
            )
        for m in datos.get("mazos") or []:
            uid = m.get("usuario_id")
            if not uid or not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (uid,)).fetchone():
                continue
            cmd_id = m.get("comandante_id")
            if cmd_id and not conn.execute("SELECT 1 FROM cartas WHERE id = ?", (cmd_id,)).fetchone():
                cmd_id = None
            conn.execute(
                """
                INSERT OR IGNORE INTO mazos (id, usuario_id, comandante_id, comandante_imagen_personalizada, nombre, formato, bracket_objetivo, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.get("id"),
                    uid,
                    cmd_id,
                    m.get("comandante_imagen_personalizada"),
                    m.get("nombre") or "Mazo",
                    m.get("formato") or "Commander",
                    int(m.get("bracket_objetivo") or 0),
                    m.get("creado_en"),
                ),
            )
        for mc in datos.get("mazo_cartas") or []:
            if not conn.execute("SELECT 1 FROM mazos WHERE id = ?", (mc.get("mazo_id"),)).fetchone():
                continue
            if not conn.execute("SELECT 1 FROM cartas WHERE id = ?", (mc.get("carta_id"),)).fetchone():
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO mazo_cartas (id, mazo_id, carta_id, cantidad, imagen_personalizada)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    mc.get("id"),
                    mc.get("mazo_id"),
                    mc.get("carta_id"),
                    int(mc.get("cantidad") or 1),
                    mc.get("imagen_personalizada"),
                ),
            )
        for alb in datos.get("albumes") or []:
            uid = alb.get("usuario_id")
            if uid and not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (uid,)).fetchone():
                uid = None
            conn.execute(
                """
                INSERT OR IGNORE INTO albumes (id, usuario_id, nombre, descripcion, color_cubierta, filas, columnas, creado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alb.get("id"),
                    uid,
                    alb.get("nombre") or "Álbum",
                    alb.get("descripcion") or "",
                    alb.get("color_cubierta") or "negro",
                    int(alb.get("filas") or 3),
                    int(alb.get("columnas") or 4),
                    alb.get("creado_en"),
                ),
            )
        for ac in datos.get("album_cartas") or []:
            if not conn.execute("SELECT 1 FROM albumes WHERE id = ?", (ac.get("album_id"),)).fetchone():
                continue
            if not conn.execute("SELECT 1 FROM cartas WHERE id = ?", (ac.get("carta_id"),)).fetchone():
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO album_cartas (id, album_id, pagina, posicion, carta_id, imagen_personalizada, acabado_foil, cantidad, agregado_en)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ac.get("id"),
                    ac.get("album_id"),
                    int(ac.get("pagina") or 1),
                    int(ac.get("posicion") or 0),
                    ac.get("carta_id"),
                    ac.get("imagen_personalizada"),
                    int(ac.get("acabado_foil") or 0),
                    int(ac.get("cantidad") or 1),
                    ac.get("agregado_en"),
                ),
            )
        conn.commit()


# ---------- Cartas ----------

def buscar_cartas(texto="", tipo="", color="", pagina=1, por_pagina=24, orden="nombre", solo_spoilers=False, edicion=""):
    condiciones = []
    parametros = []

    if texto:
        condiciones.append("(nombre LIKE ? OR texto LIKE ? OR set_nombre LIKE ?)")
        parametros.extend([f"%{texto}%", f"%{texto}%", f"%{texto}%"])
    if tipo:
        condiciones.append("tipo LIKE ?")
        parametros.append(f"%{tipo}%")
    if color:
        # color es una letra: W, U, B, R, G, o "C" para incoloras
        if color == "C":
            condiciones.append("(colores = '' OR colores IS NULL)")
        else:
            condiciones.append("colores LIKE ?")
            parametros.append(f"%{color}%")
    if edicion:
        condiciones.append("lower(set_code) = lower(?)")
        parametros.append(edicion.strip())
    if solo_spoilers:
        condiciones.append("es_spoiler = 1")

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    pagina = max(1, pagina)
    offset = (pagina - 1) * por_pagina

    if orden == "recientes":
        order_sql = "ORDER BY es_spoiler DESC, COALESCE(fecha_lanzamiento, '1993-01-01') DESC, nombre ASC"
    else:
        order_sql = "ORDER BY nombre ASC"

    with conexion() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM cartas {where}", parametros).fetchone()[0]
        filas = conn.execute(
            f"SELECT * FROM cartas {where} {order_sql} LIMIT ? OFFSET ?",
            parametros + [por_pagina, offset]
        ).fetchall()
    return filas, total


def listar_ediciones():
    """
    Devuelve todas las ediciones de Magic ordenadas cronológicamente desde la más
    reciente hasta Alpha (1993), situando como última edición en cabeza el spoiler
    de Star Trek (TRK / TRC / SDS - 2026-11-13).
    """
    codigos_posteriores_star_trek = ("mdd", "mdc", "tmdd", "pf27", "pmei", "slp", "pw26", "prm")
    placeholders = ",".join("?" for _ in codigos_posteriores_star_trek)
    with conexion() as conn:
        filas = conn.execute(
            f"""
            SELECT lower(set_code) AS set_code,
                   MAX(set_nombre) AS set_nombre,
                   CASE
                       WHEN lower(set_code) IN ('trk', 'trc', 'sds') THEN '2026-11-13'
                       WHEN lower(set_code) = 'sld' THEN '2026-11-01'
                       ELSE COALESCE(MAX(fecha_lanzamiento), '1993-01-01')
                   END AS fecha,
                   MAX(es_spoiler) AS es_spoiler,
                   COUNT(*) AS total_cartas
            FROM cartas
            WHERE set_code IS NOT NULL
              AND set_code != ''
              AND lower(set_code) NOT IN ({placeholders})
            GROUP BY lower(set_code)
            ORDER BY
                CASE WHEN lower(set_code) = 'trk' THEN 0
                     WHEN lower(set_code) = 'trc' THEN 1
                     WHEN lower(set_code) = 'sds' THEN 2
                     ELSE 3
                END ASC,
                fecha DESC,
                total_cartas DESC,
                set_nombre ASC
            """,
            codigos_posteriores_star_trek,
        ).fetchall()
    return [dict(r) for r in filas]


def actualizar_imagen_carta(carta_id, imagen_url):
    """Actualiza la imagen oficial por defecto de una carta en el catálogo."""
    with conexion() as conn:
        conn.execute("UPDATE cartas SET imagen_url = ? WHERE id = ?", (imagen_url, carta_id))
        conn.commit()


def obtener_carta(carta_id):
    with conexion() as conn:
        return conn.execute("SELECT * FROM cartas WHERE id = ?", (carta_id,)).fetchone()


def obtener_carta_por_nombre(nombre):
    """Busca una carta por su nombre exacto (o la primera cara en cartas dobles)."""
    nombre_limpio = (nombre or "").strip()
    if not nombre_limpio:
        return None
    with conexion() as conn:
        fila = conn.execute(
            "SELECT id, nombre, imagen_url, coste_mana, tipo FROM cartas WHERE lower(nombre) = lower(?) LIMIT 1",
            (nombre_limpio,),
        ).fetchone()
        if fila:
            return fila
        return conn.execute(
            "SELECT id, nombre, imagen_url, coste_mana, tipo FROM cartas WHERE lower(nombre) LIKE lower(?) LIMIT 1",
            (f"{nombre_limpio} //%",),
        ).fetchone()


# ---------- Usuarios ----------

def crear_usuario(nombre, email, password_hash=None, google_id=None, avatar_url=None):
    email_limpio = email.strip().lower()
    with conexion() as conn:
        cur = conn.execute(
            """
            INSERT INTO usuarios (nombre, email, password_hash, google_id, avatar_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nombre.strip(), email_limpio, password_hash, google_id, avatar_url),
        )
        conn.commit()
        uid = cur.lastrowid
    guardar_estado_persistente()
    return uid


def actualizar_password_usuario(usuario_id, password_hash, nombre=None):
    with conexion() as conn:
        if nombre:
            conn.execute(
                "UPDATE usuarios SET password_hash = ?, nombre = ? WHERE id = ?",
                (password_hash, nombre.strip(), usuario_id),
            )
        else:
            conn.execute(
                "UPDATE usuarios SET password_hash = ? WHERE id = ?",
                (password_hash, usuario_id),
            )
        conn.commit()
    guardar_estado_persistente()


def obtener_usuario_por_id(usuario_id):
    with conexion() as conn:
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()


def obtener_usuario_por_email(email):
    with conexion() as conn:
        return conn.execute(
            "SELECT * FROM usuarios WHERE lower(email) = ?", (email.strip().lower(),)
        ).fetchone()


def obtener_o_crear_usuario_google(google_id, email, nombre, avatar_url=None):
    """
    Busca al usuario por su `google_id` o por su `email`. Si ya existe, vincula
    el `google_id` y actualiza el avatar; si no existe, crea la cuenta.
    Devuelve la fila completa del usuario.
    """
    email_limpio = email.strip().lower()
    with conexion() as conn:
        usuario = conn.execute(
            "SELECT * FROM usuarios WHERE google_id = ? OR lower(email) = ?",
            (google_id, email_limpio),
        ).fetchone()
        if usuario:
            conn.execute(
                """
                UPDATE usuarios
                SET google_id = COALESCE(google_id, ?),
                    avatar_url = COALESCE(?, avatar_url),
                    nombre = COALESCE(NULLIF(nombre, ''), ?)
                WHERE id = ?
                """,
                (google_id, avatar_url, nombre, usuario["id"]),
            )
            conn.commit()
            res = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario["id"],)).fetchone()
        else:
            cur = conn.execute(
                """
                INSERT INTO usuarios (nombre, email, google_id, avatar_url)
                VALUES (?, ?, ?, ?)
                """,
                (nombre.strip() or email_limpio.split("@")[0], email_limpio, google_id, avatar_url),
            )
            conn.commit()
            res = conn.execute("SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)).fetchone()
    guardar_estado_persistente()
    return res


# ---------- Mazos ----------

def crear_mazo(nombre, formato, usuario_id=None, comandante_id=None, bracket_objetivo=0):
    with conexion() as conn:
        if usuario_id and not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone():
            usuario_id = None
        if comandante_id and not conn.execute("SELECT 1 FROM cartas WHERE id = ?", (comandante_id,)).fetchone():
            comandante_id = None
        cur = conn.execute(
            "INSERT INTO mazos (nombre, formato, usuario_id, comandante_id, bracket_objetivo) VALUES (?, ?, ?, ?, ?)",
            (nombre, formato, usuario_id, comandante_id, int(bracket_objetivo or 0)),
        )
        conn.commit()
        mid = cur.lastrowid
    guardar_estado_persistente()
    return mid


def actualizar_bracket_mazo(mazo_id, bracket_objetivo):
    """Actualiza el Bracket objetivo (0 = automático, 1..5 = manual) de un mazo."""
    val = max(0, min(5, int(bracket_objetivo or 0)))
    with conexion() as conn:
        conn.execute("UPDATE mazos SET bracket_objetivo = ? WHERE id = ?", (val, mazo_id))
        conn.commit()
    guardar_estado_persistente()


def asignar_comandante(mazo_id, carta_id=None, imagen_url=None):
    """
    Asigna (o quita si carta_id es None) la carta comandante del mazo.
    Si esa misma carta estaba en la biblioteca de 99 cartas (mazo_cartas),
    la retira de las 99 para que el comandante quede separado.
    """
    with conexion() as conn:
        conn.execute(
            "UPDATE mazos SET comandante_id = ?, comandante_imagen_personalizada = ? WHERE id = ?",
            (carta_id, imagen_url if carta_id else None, mazo_id),
        )
        if carta_id:
            conn.execute("DELETE FROM mazo_cartas WHERE mazo_id = ? AND carta_id = ?", (mazo_id, carta_id))
        conn.commit()
    guardar_estado_persistente()


def actualizar_formato_mazo(mazo_id, formato):
    """Actualiza el formato de juego de un mazo existente."""
    with conexion() as conn:
        conn.execute("UPDATE mazos SET formato = ? WHERE id = ?", (formato.strip(), mazo_id))
        conn.commit()
    guardar_estado_persistente()


def buscar_cartas_autocompletar(texto="", solo_comandantes=False, limite=12):
    """Búsqueda rápida para el selector de comandante y el buscador rápido del constructor."""
    q = (texto or "").strip()
    if not q:
        return []
    condiciones = ["nombre LIKE ?"]
    params = [f"%{q}%"]
    if solo_comandantes:
        condiciones.append(
            "(tipo LIKE '%Legendary%Creature%' OR tipo LIKE '%Legendary%Planeswalker%' "
            "OR tipo LIKE '%Legendary%Artifact%' OR texto LIKE '%can be your commander%')"
        )
    where = " AND ".join(condiciones)
    with conexion() as conn:
        return conn.execute(
            f"SELECT id, nombre, coste_mana, cmc, tipo, colores, identidad_color, imagen_url "
            f"FROM cartas WHERE {where} ORDER BY CASE WHEN lower(nombre) LIKE lower(?) THEN 0 ELSE 1 END, nombre LIMIT ?",
            params + [f"{q}%", limite],
        ).fetchall()


def listar_mazos(usuario_id=None):
    """
    Lista los mazos junto con el número de cartas en la biblioteca y los datos
    de su comandante (si tiene comandante asignado).
    """
    consulta_base = """
        SELECT m.*,
               COALESCE(SUM(mc.cantidad), 0) AS cartas_biblioteca,
               COALESCE(SUM(mc.cantidad), 0) + CASE WHEN m.comandante_id IS NOT NULL THEN 1 ELSE 0 END AS total_cartas,
               cmd.nombre AS comandante_nombre,
               COALESCE(m.comandante_imagen_personalizada, cmd.imagen_url) AS comandante_imagen,
               cmd.identidad_color AS comandante_identidad
        FROM mazos m
        LEFT JOIN mazo_cartas mc ON mc.mazo_id = m.id
        LEFT JOIN cartas cmd ON cmd.id = m.comandante_id
        {where}
        GROUP BY m.id
        ORDER BY m.creado_en DESC, m.id DESC
    """
    if usuario_id is None:
        return []
    with conexion() as conn:
        return conn.execute(
            consulta_base.format(where="WHERE m.usuario_id = ?"),
            (usuario_id,),
        ).fetchall()


def obtener_mazo_simple(mazo_id):
    with conexion() as conn:
        return conn.execute("SELECT * FROM mazos WHERE id = ?", (mazo_id,)).fetchone()


def obtener_mazo(mazo_id):
    """Devuelve (mazo, comandante, cartas_biblioteca)."""
    with conexion() as conn:
        mazo = conn.execute("SELECT * FROM mazos WHERE id = ?", (mazo_id,)).fetchone()
        comandante = None
        if mazo and mazo["comandante_id"]:
            fila_cmd = conn.execute(
                "SELECT * FROM cartas WHERE id = ?", (mazo["comandante_id"],)
            ).fetchone()
            if fila_cmd:
                d_cmd = dict(fila_cmd)
                if mazo["comandante_imagen_personalizada"]:
                    d_cmd["imagen_url"] = mazo["comandante_imagen_personalizada"]
                comandante = d_cmd
        cartas = conn.execute("""
            SELECT c.id, c.scryfall_id, c.nombre, c.coste_mana, c.cmc, c.tipo, c.texto,
                   c.poder, c.resistencia, c.colores, c.identidad_color, c.rareza,
                   c.set_code, c.set_nombre,
                   COALESCE(mc.imagen_personalizada, c.imagen_url) AS imagen_url,
                   c.legalidades, c.fecha_lanzamiento, c.es_spoiler,
                   mc.cantidad, mc.imagen_personalizada
            FROM mazo_cartas mc
            JOIN cartas c ON c.id = mc.carta_id
            WHERE mc.mazo_id = ?
            ORDER BY c.cmc, c.nombre
        """, (mazo_id,)).fetchall()
    return mazo, comandante, cartas


def total_cartas_mazo(conn, mazo_id):
    return conn.execute(
        "SELECT COALESCE(SUM(cantidad), 0) FROM mazo_cartas WHERE mazo_id = ?", (mazo_id,)
    ).fetchone()[0]


def cantidad_carta_en_mazo(conn, mazo_id, carta_id):
    fila = conn.execute(
        "SELECT cantidad FROM mazo_cartas WHERE mazo_id = ? AND carta_id = ?", (mazo_id, carta_id)
    ).fetchone()
    return fila["cantidad"] if fila else 0


def anadir_carta_a_mazo(mazo_id, carta_id, cantidad=1, imagen_url=None):
    """
    Suma `cantidad` copias de la carta al mazo (o la inserta si no estaba).
    Permite opcionalmente especificar `imagen_url` (alter oficial elegido).
    Devuelve (cantidad_de_esa_carta, total_de_cartas_del_mazo).
    """
    with conexion() as conn:
        conn.execute("""
            INSERT INTO mazo_cartas (mazo_id, carta_id, cantidad, imagen_personalizada)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (mazo_id, carta_id)
            DO UPDATE SET
                cantidad = MIN(cantidad + excluded.cantidad, ?),
                imagen_personalizada = COALESCE(excluded.imagen_personalizada, mazo_cartas.imagen_personalizada)
        """, (mazo_id, carta_id, cantidad, imagen_url, MAX_COPIAS_POR_CARTA))
        conn.commit()
        res = (cantidad_carta_en_mazo(conn, mazo_id, carta_id), total_cartas_mazo(conn, mazo_id))
    guardar_estado_persistente()
    return res


def actualizar_imagen_carta_en_mazo(mazo_id, carta_id, imagen_url, es_comandante=False):
    """Cambia el arte/alter oficial de una carta específica dentro de un mazo o del comandante."""
    with conexion() as conn:
        if es_comandante:
            conn.execute(
                "UPDATE mazos SET comandante_imagen_personalizada = ? WHERE id = ?",
                (imagen_url, mazo_id),
            )
        else:
            conn.execute(
                "UPDATE mazo_cartas SET imagen_personalizada = ? WHERE mazo_id = ? AND carta_id = ?",
                (imagen_url, mazo_id, carta_id),
            )
        conn.commit()
    guardar_estado_persistente()


def restar_carta_de_mazo(mazo_id, carta_id, cantidad=1):
    """
    Resta `cantidad` copias. Si llega a 0 o menos, elimina la carta del mazo.
    Devuelve (cantidad_restante, total_de_cartas_del_mazo).
    """
    with conexion() as conn:
        actual = cantidad_carta_en_mazo(conn, mazo_id, carta_id)
        nueva = actual - cantidad
        if nueva > 0:
            conn.execute(
                "UPDATE mazo_cartas SET cantidad = ? WHERE mazo_id = ? AND carta_id = ?",
                (nueva, mazo_id, carta_id)
            )
        else:
            conn.execute(
                "DELETE FROM mazo_cartas WHERE mazo_id = ? AND carta_id = ?", (mazo_id, carta_id)
            )
            nueva = 0
        conn.commit()
        res = (nueva, total_cartas_mazo(conn, mazo_id))
    guardar_estado_persistente()
    return res


def quitar_carta_de_mazo(mazo_id, carta_id):
    """Elimina todas las copias de una carta. Devuelve el total de cartas del mazo."""
    with conexion() as conn:
        conn.execute("DELETE FROM mazo_cartas WHERE mazo_id = ? AND carta_id = ?", (mazo_id, carta_id))
        conn.commit()
        res = total_cartas_mazo(conn, mazo_id)
    guardar_estado_persistente()
    return res


def eliminar_mazo(mazo_id):
    # Las filas de mazo_cartas se borran solas gracias a ON DELETE CASCADE
    # (requiere PRAGMA foreign_keys = ON, que activamos en obtener_conexion).
    with conexion() as conn:
        conn.execute("DELETE FROM mazos WHERE id = ?", (mazo_id,))
        conn.commit()
    guardar_estado_persistente()


def resumen_portada_moxfield(limite_spoilers=8):
    """
    Obtiene los contadores y cartas destacadas para la portada estilo Moxfield:
      - total_cartas, total_spoilers
      - spoilers_recientes: últimas cartas spoiler con imagen HD
      - staples_destacadas: cartas icónicas / Game Changers populares
    """
    nombres_staples = (
        "Cloud, Midgar Mercenary",
        "The One Ring",
        "Rhystic Study",
        "Cyclonic Rift",
        "Smothering Tithe",
        "Demonic Tutor",
        "Chrome Mox",
        "Force of Will",
    )
    with conexion() as conn:
        total_cartas = conn.execute("SELECT COUNT(*) FROM cartas").fetchone()[0]
        total_spoilers = conn.execute("SELECT COUNT(*) FROM cartas WHERE es_spoiler = 1").fetchone()[0]
        spoilers = conn.execute(
            """
            SELECT * FROM cartas
            WHERE es_spoiler = 1 AND imagen_url != ''
            ORDER BY COALESCE(fecha_lanzamiento, '2026-01-01') DESC, nombre ASC
            LIMIT ?
            """,
            (limite_spoilers,),
        ).fetchall()
        placeholders = ",".join("?" for _ in nombres_staples)
        staples = conn.execute(
            f"SELECT * FROM cartas WHERE nombre IN ({placeholders})",
            nombres_staples,
        ).fetchall()
    return {
        "total_cartas": total_cartas,
        "total_spoilers": total_spoilers,
        "spoilers": spoilers,
        "staples": staples,
    }


# ---------- Álbumes Físicos (Estilo Ultimate Guard QuadRow / 9-Pocket / 4-Pocket) ----------

def crear_album(nombre, descripcion="", color_cubierta="negro", filas=3, columnas=4, usuario_id=None):
    filas = max(2, min(4, int(filas or 3)))
    columnas = max(2, min(4, int(columnas or 4)))
    with conexion() as conn:
        if usuario_id and not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone():
            usuario_id = None
        cur = conn.execute(
            """
            INSERT INTO albumes (usuario_id, nombre, descripcion, color_cubierta, filas, columnas)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (usuario_id, nombre.strip(), (descripcion or "").strip(), color_cubierta or "negro", filas, columnas),
        )
        conn.commit()
        aid = cur.lastrowid
    guardar_estado_persistente()
    return aid


def listar_albumes(usuario_id=None):
    """
    Lista los álbumes junto con el número total de cartas guardadas, páginas
    ocupadas y hasta 4 imágenes en miniatura para la portada del álbum.
    """
    with conexion() as conn:
        if usuario_id is not None:
            filas = conn.execute(
                """
                SELECT a.*,
                       COUNT(ac.id) AS total_bolsillos,
                       COALESCE(SUM(ac.cantidad), 0) AS total_cartas,
                       COALESCE(MAX(ac.pagina), 1) AS total_paginas,
                       u.nombre AS autor_nombre
                FROM albumes a
                LEFT JOIN album_cartas ac ON ac.album_id = a.id
                LEFT JOIN usuarios u ON u.id = a.usuario_id
                WHERE a.usuario_id = ? OR a.usuario_id IS NULL
                GROUP BY a.id
                ORDER BY a.creado_en DESC, a.id DESC
                """,
                (usuario_id,),
            ).fetchall()
        else:
            filas = conn.execute(
                """
                SELECT a.*,
                       COUNT(ac.id) AS total_bolsillos,
                       COALESCE(SUM(ac.cantidad), 0) AS total_cartas,
                       COALESCE(MAX(ac.pagina), 1) AS total_paginas,
                       u.nombre AS autor_nombre
                FROM albumes a
                LEFT JOIN album_cartas ac ON ac.album_id = a.id
                LEFT JOIN usuarios u ON u.id = a.usuario_id
                GROUP BY a.id
                ORDER BY a.creado_en DESC, a.id DESC
                """
            ).fetchall()

        resultado = []
        for f in filas:
            d = dict(f)
            previews = conn.execute(
                """
                SELECT COALESCE(ac.imagen_personalizada, c.imagen_url) AS imagen_url, c.nombre
                FROM album_cartas ac
                JOIN cartas c ON c.id = ac.carta_id
                WHERE ac.album_id = ?
                ORDER BY ac.pagina ASC, ac.posicion ASC
                LIMIT 4
                """,
                (d["id"],),
            ).fetchall()
            d["previews"] = [dict(p) for p in previews]
            resultado.append(d)
    return resultado


def obtener_album_simple(album_id):
    with conexion() as conn:
        return conn.execute("SELECT * FROM albumes WHERE id = ?", (album_id,)).fetchone()


def obtener_album_pagina(album_id, pagina=1):
    """
    Devuelve (album, diccionario_bolsillos, total_paginas, total_cartas)
    donde `diccionario_bolsillos` mapea `posicion` (0 .. filas*columnas - 1) -> datos de la carta.
    """
    pagina = max(1, int(pagina or 1))
    with conexion() as conn:
        album = conn.execute("SELECT * FROM albumes WHERE id = ?", (album_id,)).fetchone()
        if not album:
            return None, {}, 1, 0

        stats = conn.execute(
            "SELECT COALESCE(MAX(pagina), 1) AS max_pag, COALESCE(SUM(cantidad), 0) AS tot FROM album_cartas WHERE album_id = ?",
            (album_id,),
        ).fetchone()
        total_paginas = max(1, int(stats["max_pag"] or 1), pagina)
        total_cartas = int(stats["tot"] or 0)

        filas_pag = conn.execute(
            """
            SELECT ac.id AS slot_id, ac.pagina, ac.posicion, ac.carta_id,
                   ac.imagen_personalizada, ac.acabado_foil, ac.cantidad,
                   c.nombre, c.coste_mana, c.tipo, c.rareza, c.set_code, c.set_nombre,
                   COALESCE(ac.imagen_personalizada, c.imagen_url) AS imagen_url
            FROM album_cartas ac
            JOIN cartas c ON c.id = ac.carta_id
            WHERE ac.album_id = ? AND ac.pagina = ?
            ORDER BY ac.posicion ASC
            """,
            (album_id, pagina),
        ).fetchall()

        bolsillos = {int(r["posicion"]): dict(r) for r in filas_pag}
    return dict(album), bolsillos, total_paginas, total_cartas


def colocar_carta_en_album(album_id, carta_id, pagina=None, posicion=None, imagen_url=None, acabado_foil=0):
    """
    Coloca una carta en un bolsillo específico `(pagina, posicion)` del álbum.
    Si no se indica `posicion`, busca automáticamente el primer bolsillo libre
    empezando en la página indicada (o página 1).
    Devuelve (pagina_asignada, posicion_asignada, total_cartas_album).
    """
    with conexion() as conn:
        album = conn.execute("SELECT * FROM albumes WHERE id = ?", (album_id,)).fetchone()
        if not album:
            return 1, 0, 0
        capacidad_hoja = int(album["filas"] or 3) * int(album["columnas"] or 4)
        pag_destino = max(1, int(pagina or 1))

        if posicion is not None and 0 <= int(posicion) < capacidad_hoja:
            pos_destino = int(posicion)
        else:
            # Buscar el primer bolsillo vacío desde `pag_destino`
            while True:
                ocupados = {
                    int(r[0])
                    for r in conn.execute(
                        "SELECT posicion FROM album_cartas WHERE album_id = ? AND pagina = ?",
                        (album_id, pag_destino),
                    ).fetchall()
                }
                libres = [i for i in range(capacidad_hoja) if i not in ocupados]
                if libres:
                    pos_destino = libres[0]
                    break
                pag_destino += 1

        conn.execute(
            """
            INSERT INTO album_cartas (album_id, pagina, posicion, carta_id, imagen_personalizada, acabado_foil, cantidad)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(album_id, pagina, posicion) DO UPDATE SET
                carta_id = excluded.carta_id,
                imagen_personalizada = COALESCE(excluded.imagen_personalizada, album_cartas.imagen_personalizada),
                acabado_foil = excluded.acabado_foil
            """,
            (album_id, pag_destino, pos_destino, carta_id, imagen_url, int(bool(acabado_foil))),
        )
        conn.commit()
        tot = conn.execute(
            "SELECT COALESCE(SUM(cantidad), 0) FROM album_cartas WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
    guardar_estado_persistente()
    return pag_destino, pos_destino, int(tot or 0)


def mover_carta_en_album(album_id, pagina_origen, pos_origen, pagina_destino, pos_destino):
    """Intercambia o mueve una carta de un bolsillo a otro dentro del álbum físico."""
    with conexion() as conn:
        orig = conn.execute(
            "SELECT * FROM album_cartas WHERE album_id = ? AND pagina = ? AND posicion = ?",
            (album_id, pagina_origen, pos_origen),
        ).fetchone()
        if not orig:
            return False
        dest = conn.execute(
            "SELECT * FROM album_cartas WHERE album_id = ? AND pagina = ? AND posicion = ?",
            (album_id, pagina_destino, pos_destino),
        ).fetchone()

        if dest:
            # Intercambiar ambos bolsillos usando una posición temporal (-1)
            conn.execute("DELETE FROM album_cartas WHERE id IN (?, ?)", (orig["id"], dest["id"]))
            conn.execute(
                """
                INSERT INTO album_cartas (album_id, pagina, posicion, carta_id, imagen_personalizada, acabado_foil, cantidad)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (album_id, pagina_destino, pos_destino, orig["carta_id"], orig["imagen_personalizada"], orig["acabado_foil"], orig["cantidad"]),
            )
            conn.execute(
                """
                INSERT INTO album_cartas (album_id, pagina, posicion, carta_id, imagen_personalizada, acabado_foil, cantidad)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (album_id, pagina_origen, pos_origen, dest["carta_id"], dest["imagen_personalizada"], dest["acabado_foil"], dest["cantidad"]),
            )
        else:
            conn.execute(
                "UPDATE album_cartas SET pagina = ?, posicion = ? WHERE id = ?",
                (pagina_destino, pos_destino, orig["id"]),
            )
        conn.commit()
    guardar_estado_persistente()
    return True


def actualizar_bolsillo_album(album_id, pagina, posicion, imagen_url=None, acabado_foil=None):
    with conexion() as conn:
        actual = conn.execute(
            "SELECT * FROM album_cartas WHERE album_id = ? AND pagina = ? AND posicion = ?",
            (album_id, pagina, posicion),
        ).fetchone()
        if not actual:
            return False
        nueva_img = imagen_url if imagen_url is not None else actual["imagen_personalizada"]
        nuevo_foil = int(bool(acabado_foil)) if acabado_foil is not None else actual["acabado_foil"]
        conn.execute(
            "UPDATE album_cartas SET imagen_personalizada = ?, acabado_foil = ? WHERE id = ?",
            (nueva_img, nuevo_foil, actual["id"]),
        )
        conn.commit()
    guardar_estado_persistente()
    return True


def quitar_carta_de_album(album_id, pagina, posicion):
    with conexion() as conn:
        conn.execute(
            "DELETE FROM album_cartas WHERE album_id = ? AND pagina = ? AND posicion = ?",
            (album_id, int(pagina), int(posicion)),
        )
        conn.commit()
        tot = conn.execute(
            "SELECT COALESCE(SUM(cantidad), 0) FROM album_cartas WHERE album_id = ?", (album_id,)
        ).fetchone()[0]
    guardar_estado_persistente()
    return int(tot or 0)


def eliminar_album(album_id):
    with conexion() as conn:
        conn.execute("DELETE FROM albumes WHERE id = ?", (album_id,))
        conn.commit()
    guardar_estado_persistente()
