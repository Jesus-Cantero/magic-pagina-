"""
database.py

Funciones de acceso a la base de datos SQLite (mtg_cards.db).
Toda la lógica de consultas SQL vive aquí para mantener app.py limpio.

El esquema (tablas, índices y versión) también se define aquí, para que
app.py y download_cards.py usen exactamente la misma estructura.
"""

import os
import sqlite3
from contextlib import contextmanager

# Ruta ABSOLUTA a la base de datos, calculada a partir de la carpeta donde
# está este archivo. Así funciona igual aunque ejecutes `python app.py`
# desde otra carpeta.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "mtg_cards.db")

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
    if tabla_existe(conn, "mazo_cartas"):
        col_mc = [f[1] for f in conn.execute("PRAGMA table_info(mazo_cartas)").fetchall()]
        if "imagen_personalizada" not in col_mc:
            conn.execute("ALTER TABLE mazo_cartas ADD COLUMN imagen_personalizada TEXT")
    conn.commit()


def estado_bd():
    """
    Devuelve el estado de la base de datos para que app.py pueda avisar al usuario:
      "falta"   -> no existe el archivo mtg_cards.db
      "antigua" -> existe pero tiene el esquema antiguo (hay que volver a descargar)
      "vacia"   -> el esquema es correcto pero no hay cartas
      "ok"      -> todo listo
    """
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
        return "ok" if hay_cartas else "vacia"


# ---------- Cartas ----------

def buscar_cartas(texto="", tipo="", color="", pagina=1, por_pagina=24, orden="nombre", solo_spoilers=False):
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
        return cur.lastrowid


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
            return conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario["id"],)).fetchone()

        cur = conn.execute(
            """
            INSERT INTO usuarios (nombre, email, google_id, avatar_url)
            VALUES (?, ?, ?, ?)
            """,
            (nombre.strip() or email_limpio.split("@")[0], email_limpio, google_id, avatar_url),
        )
        conn.commit()
        return conn.execute("SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)).fetchone()


# ---------- Mazos ----------

def crear_mazo(nombre, formato, usuario_id=None, comandante_id=None, bracket_objetivo=0):
    with conexion() as conn:
        if comandante_id and not conn.execute("SELECT 1 FROM cartas WHERE id = ?", (comandante_id,)).fetchone():
            comandante_id = None
        cur = conn.execute(
            "INSERT INTO mazos (nombre, formato, usuario_id, comandante_id, bracket_objetivo) VALUES (?, ?, ?, ?, ?)",
            (nombre, formato, usuario_id, comandante_id, int(bracket_objetivo or 0)),
        )
        conn.commit()
        return cur.lastrowid


def actualizar_bracket_mazo(mazo_id, bracket_objetivo):
    """Actualiza el Bracket objetivo (0 = automático, 1..5 = manual) de un mazo."""
    val = max(0, min(5, int(bracket_objetivo or 0)))
    with conexion() as conn:
        conn.execute("UPDATE mazos SET bracket_objetivo = ? WHERE id = ?", (val, mazo_id))
        conn.commit()


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


def actualizar_formato_mazo(mazo_id, formato):
    """Actualiza el formato de juego de un mazo existente."""
    with conexion() as conn:
        conn.execute("UPDATE mazos SET formato = ? WHERE id = ?", (formato.strip(), mazo_id))
        conn.commit()


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
    with conexion() as conn:
        if usuario_id is not None:
            return conn.execute(
                consulta_base.format(where="WHERE m.usuario_id = ? OR m.usuario_id IS NULL"),
                (usuario_id,),
            ).fetchall()
        return conn.execute(
            consulta_base.format(where="WHERE m.usuario_id IS NULL")
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
        return cantidad_carta_en_mazo(conn, mazo_id, carta_id), total_cartas_mazo(conn, mazo_id)


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
        return nueva, total_cartas_mazo(conn, mazo_id)


def quitar_carta_de_mazo(mazo_id, carta_id):
    """Elimina todas las copias de una carta. Devuelve el total de cartas del mazo."""
    with conexion() as conn:
        conn.execute("DELETE FROM mazo_cartas WHERE mazo_id = ? AND carta_id = ?", (mazo_id, carta_id))
        conn.commit()
        return total_cartas_mazo(conn, mazo_id)


def eliminar_mazo(mazo_id):
    # Las filas de mazo_cartas se borran solas gracias a ON DELETE CASCADE
    # (requiere PRAGMA foreign_keys = ON, que activamos en obtener_conexion).
    with conexion() as conn:
        conn.execute("DELETE FROM mazos WHERE id = ?", (mazo_id,))
        conn.commit()


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
