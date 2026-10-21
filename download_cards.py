"""
download_cards.py

Descarga el "bulk data" de cartas de Scryfall (Oracle Cards: una entrada
por cada carta única, sin reimpresiones duplicadas) y las guarda en una
base de datos SQLite local (mtg_cards.db).

Ejecutar una sola vez para poblar la base de datos:
    python download_cards.py

Para actualizar las cartas más adelante, vuelve a ejecutarlo. Tus mazos
NO se borran: las cartas se identifican por su `oracle_id`, que es estable
entre descargas.

Scryfall pide que las descargas de bulk data se hagan como mucho una vez
al día, así que el script se niega a descargar de nuevo si la última
descarga fue hace menos de 24 horas. Si de verdad lo necesitas:
    python download_cards.py --forzar

Más info: https://scryfall.com/docs/api/bulk-data
"""

import argparse
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import database as db

DB_PATH = db.DB_PATH
BULK_DATA_INFO_URL = "https://api.scryfall.com/bulk-data/oracle-cards"
USER_AGENT = "MTGWikiApp/1.0 (proyecto personal educativo)"
CABECERAS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
TIMEOUT_SEGUNDOS = 60
HORAS_ENTRE_DESCARGAS = 24

# Layouts que no son cartas "normales" jugables
LAYOUTS_IGNORADOS = ("token", "double_faced_token", "emblem", "art_series")

# Orden canónico de los colores de Magic (blanco, azul, negro, rojo, verde)
ORDEN_COLORES = "WUBRG"

# Separador entre las caras de una carta de doble cara (mismo que en la versión estática)
SEPARADOR_CARAS = "\n—————\n"


# ---------- Descarga ----------

def obtener_url_descarga():
    """
    Pregunta a Scryfall dónde está el archivo actual de oracle-cards.
    Scryfall ofrece actualmente `jsonl_download_uri` (.jsonl.gz comprimido)
    y anteriormente ofrecía `download_uri` (.json). Soportamos ambos.
    """
    req = urllib.request.Request(BULK_DATA_INFO_URL, headers=CABECERAS)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp:
        info = json.loads(resp.read().decode("utf-8"))
    url = info.get("jsonl_download_uri") or info.get("download_uri")
    if not url:
        raise RuntimeError(f"Scryfall no devolvió ninguna URL de descarga en {BULK_DATA_INFO_URL}")
    return url


def cargar_cartas_de_archivo(ruta, url):
    """
    Lee las cartas desde el archivo descargado.
    Soporta:
      - .jsonl.gz (formato actual de Scryfall: una carta JSON por línea, comprimido con gzip)
      - .jsonl    (una carta JSON por línea, sin comprimir)
      - .json     (formato antiguo: un único array JSON)
    """
    url_limpia = url.split("?", 1)[0].lower()
    abrir = gzip.open if url_limpia.endswith(".gz") else open
    es_jsonl = ".jsonl" in url_limpia

    with abrir(ruta, "rt", encoding="utf-8") as f:
        if es_jsonl:
            return [json.loads(linea) for linea in f if linea.strip()]
        return json.load(f)


def descargar_cartas(url):
    """
    Descarga el archivo por trozos a un fichero temporal (mostrando el
    progreso) y luego lo carga en memoria.
    """
    print(f"Descargando cartas desde {url} ...")
    req = urllib.request.Request(url, headers=CABECERAS)

    fd, ruta_temporal = tempfile.mkstemp(suffix=".bulk")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEGUNDOS) as resp, os.fdopen(fd, "wb") as destino:
            total = int(resp.headers.get("Content-Length") or 0)
            descargado = 0
            while True:
                trozo = resp.read(1024 * 1024)  # 1 MB
                if not trozo:
                    break
                destino.write(trozo)
                descargado += len(trozo)
                if total:
                    print(f"\r  {descargado / 1e6:6.1f} / {total / 1e6:.1f} MB", end="", flush=True)
                else:
                    print(f"\r  {descargado / 1e6:6.1f} MB", end="", flush=True)
        print()

        data = cargar_cartas_de_archivo(ruta_temporal, url)
    finally:
        if os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)

    print(f"Descargadas {len(data)} cartas.")
    return data


# ---------- Transformación de cada carta ----------

def caras(carta):
    return carta.get("card_faces") or []


def extraer_imagen(carta):
    # Preferimos "large" (alta resolución 672x936) o "png" (745x1040) sobre "normal".
    if "image_uris" in carta:
        uris = carta["image_uris"]
        return uris.get("large") or uris.get("png") or uris.get("normal", "")
    for cara in caras(carta):
        if "image_uris" in cara:
            uris = cara["image_uris"]
            return uris.get("large") or uris.get("png") or uris.get("normal", "")
    return ""


def extraer_oracle_id(carta):
    # Las cartas "reversible_card" no tienen oracle_id arriba, solo en cada cara.
    if carta.get("oracle_id"):
        return carta["oracle_id"]
    for cara in caras(carta):
        if cara.get("oracle_id"):
            return cara["oracle_id"]
    return carta.get("id")


def extraer_coste(carta):
    if carta.get("mana_cost"):
        return carta["mana_cost"]
    costes = [c.get("mana_cost", "") for c in caras(carta) if c.get("mana_cost")]
    return " // ".join(costes)


def extraer_texto(carta):
    if carta.get("oracle_text"):
        return carta["oracle_text"]
    textos = []
    for cara in caras(carta):
        if cara.get("oracle_text"):
            textos.append(f"{cara.get('name', '')}\n{cara['oracle_text']}")
    return SEPARADOR_CARAS.join(textos)


def extraer_colores(carta):
    if "colors" in carta:
        colores = set(carta["colors"])
    else:
        colores = set()
        for cara in caras(carta):
            colores.update(cara.get("colors", []))
    return ",".join(c for c in ORDEN_COLORES if c in colores)


def extraer_poder_resistencia(carta):
    if carta.get("power") is not None or carta.get("toughness") is not None:
        return carta.get("power", ""), carta.get("toughness", "")
    for cara in caras(carta):
        if cara.get("power") is not None:
            return cara.get("power", ""), cara.get("toughness", "")
    return "", ""


def transformar_carta(c, forzar_spoiler=False):
    poder, resistencia = extraer_poder_resistencia(c)
    fecha = c.get("released_at") or ""
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    es_sp = 1 if (forzar_spoiler or (fecha and fecha > hoy) or bool(c.get("preview"))) else 0
    return (
        extraer_oracle_id(c),
        c.get("id"),
        c.get("name", ""),
        extraer_coste(c),
        c.get("cmc", 0),
        c.get("type_line", ""),
        extraer_texto(c),
        poder,
        resistencia,
        extraer_colores(c),
        ",".join(x for x in ORDEN_COLORES if x in c.get("color_identity", [])),
        c.get("rarity", ""),
        c.get("set", ""),
        c.get("set_name", ""),
        extraer_imagen(c),
        json.dumps(c.get("legalities", {})),
        fecha,
        es_sp,
    )


# ---------- Base de datos ----------

def crear_tablas(conn):
    """
    Crea las tablas definidas en database.ESQUEMA_SQL sentencia a sentencia.
    No usamos conn.executescript() porque hace un COMMIT implícito y
    rompería la transacción en curso.
    """
    for sentencia in db.ESQUEMA_SQL.split(";"):
        if sentencia.strip():
            conn.execute(sentencia)
    db.asegurar_esquema_usuarios(conn)


def insertar_cartas(conn, cartas, forzar_spoiler=False):
    filas = [
        transformar_carta(c, forzar_spoiler=forzar_spoiler)
        for c in cartas
        if c.get("layout") not in LAYOUTS_IGNORADOS
    ]

    # UPSERT: si la carta ya existe (mismo oracle_id) se actualizan sus datos,
    # pero la fila no se borra, así que las referencias desde mazo_cartas siguen siendo válidas.
    conn.executemany("""
        INSERT INTO cartas (
            id, scryfall_id, nombre, coste_mana, cmc, tipo, texto, poder, resistencia,
            colores, identidad_color, rareza, set_code, set_nombre, imagen_url, legalidades,
            fecha_lanzamiento, es_spoiler
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            scryfall_id = excluded.scryfall_id,
            nombre = excluded.nombre,
            coste_mana = excluded.coste_mana,
            cmc = excluded.cmc,
            tipo = excluded.tipo,
            texto = excluded.texto,
            poder = excluded.poder,
            resistencia = excluded.resistencia,
            colores = excluded.colores,
            identidad_color = excluded.identidad_color,
            rareza = excluded.rareza,
            set_code = excluded.set_code,
            set_nombre = excluded.set_nombre,
            imagen_url = excluded.imagen_url,
            legalidades = excluded.legalidades,
            fecha_lanzamiento = COALESCE(excluded.fecha_lanzamiento, cartas.fecha_lanzamiento),
            es_spoiler = MAX(excluded.es_spoiler, COALESCE(cartas.es_spoiler, 0))
    """, filas)
    print(f"Insertadas/actualizadas {len(filas)} cartas en la base de datos.")
    return len(filas)


def sincronizar_spoilers_en_vivo():
    """
    Descarga en directo desde la API de búsqueda de Scryfall todos los spoilers
    actuales (cartas con fecha futura `date>today` y los spoilers más recientes)
    y mejora todas las URLs de imágenes existentes a alta resolución (`/large/`).
    """
    consultas = [
        ("https://api.scryfall.com/cards/search?q=date%3Etoday&order=spoiled&unique=cards", True),
        ("https://api.scryfall.com/cards/search?q=year%3E%3D2025+not%3Areprint&order=spoiled&unique=cards", False),
    ]
    cartas_recibidas = []
    for url_inicial, marcar_sp in consultas:
        url = url_inicial
        paginas = 0
        while url and paginas < 4:
            paginas += 1
            req = urllib.request.Request(url, headers=CABECERAS)
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    datos = json.loads(resp.read().decode("utf-8"))
                lote = datos.get("data") or []
                for c in lote:
                    c["_forzar_sp"] = marcar_sp
                cartas_recibidas.extend(lote)
                url = datos.get("next_page") if datos.get("has_more") else None
                time.sleep(0.08)
            except urllib.error.URLError:
                break

    with db.conexion() as conn:
        db.asegurar_esquema_usuarios(conn)
        # Mejorar todas las imágenes existentes de /normal/ a /large/ (alta calidad 672x936)
        conn.execute(
            "UPDATE cartas SET imagen_url = REPLACE(imagen_url, '/normal/', '/large/') "
            "WHERE imagen_url LIKE '%/normal/%'"
        )
        total_up = 0
        if cartas_recibidas:
            spoilers = [c for c in cartas_recibidas if c.get("_forzar_sp")]
            recientes = [c for c in cartas_recibidas if not c.get("_forzar_sp")]
            if spoilers:
                total_up += insertar_cartas(conn, spoilers, forzar_spoiler=True)
            if recientes:
                total_up += insertar_cartas(conn, recientes, forzar_spoiler=False)
        conn.commit()
    return total_up


def es_esquema_antiguo(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    hay_tablas = db.tabla_existe(conn, "cartas") or db.tabla_existe(conn, "mazo_cartas")
    return version < db.VERSION_ESQUEMA and hay_tablas


def guardar_mazos_antiguos(conn):
    """
    En el esquema antiguo, mazo_cartas apunta al id de impresión. Guardamos
    las cartas de cada mazo POR NOMBRE para poder reconstruirlas después
    con los nuevos oracle_id.
    """
    if not (db.tabla_existe(conn, "mazo_cartas") and db.tabla_existe(conn, "cartas")):
        return []
    return conn.execute("""
        SELECT mc.mazo_id, c.nombre, mc.cantidad
        FROM mazo_cartas mc
        JOIN cartas c ON c.id = mc.carta_id
    """).fetchall()


def restaurar_mazos_antiguos(conn, filas):
    restauradas, perdidas = 0, []
    for mazo_id, nombre, cantidad in filas:
        carta = conn.execute("SELECT id FROM cartas WHERE nombre = ? LIMIT 1", (nombre,)).fetchone()
        if carta is None:
            perdidas.append(nombre)
            continue
        conn.execute("""
            INSERT INTO mazo_cartas (mazo_id, carta_id, cantidad) VALUES (?, ?, ?)
            ON CONFLICT (mazo_id, carta_id)
            DO UPDATE SET cantidad = MIN(cantidad + excluded.cantidad, ?)
        """, (mazo_id, carta[0], min(cantidad, db.MAX_COPIAS_POR_CARTA), db.MAX_COPIAS_POR_CARTA))
        restauradas += 1
    print(f"Migración: {restauradas} entradas de mazos restauradas.")
    if perdidas:
        print(f"  Aviso: no se encontraron {len(perdidas)} cartas por nombre: {', '.join(perdidas[:10])}")


def ultima_descarga(conn):
    if not db.tabla_existe(conn, "meta"):
        return None
    fila = conn.execute("SELECT valor FROM meta WHERE clave = 'ultima_descarga'").fetchone()
    if not fila:
        return None
    try:
        return datetime.fromisoformat(fila[0])
    except ValueError:
        return None


def registrar_descarga(conn):
    conn.execute(
        "INSERT INTO meta (clave, valor) VALUES ('ultima_descarga', ?) "
        "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
        (datetime.now(timezone.utc).isoformat(),)
    )


# ---------- Programa principal ----------

def parsear_argumentos():
    parser = argparse.ArgumentParser(description="Descarga las cartas de Scryfall a mtg_cards.db")
    parser.add_argument(
        "--forzar", action="store_true",
        help="Descarga aunque la última descarga sea de hace menos de 24 horas."
    )
    return parser.parse_args()


def main():
    args = parsear_argumentos()
    inicio = time.time()

    # isolation_level=None -> controlamos nosotros BEGIN/COMMIT/ROLLBACK.
    # (Con el modo por defecto, Python no mete los DROP/CREATE en la transacción.)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # 1) Respetar la política de Scryfall: como mucho una descarga al día
        anterior = ultima_descarga(conn)
        if anterior and not args.forzar:
            transcurrido = datetime.now(timezone.utc) - anterior
            if transcurrido < timedelta(hours=HORAS_ENTRE_DESCARGAS):
                horas = transcurrido.total_seconds() / 3600
                print(f"La última descarga fue hace {horas:.1f} horas. Scryfall pide no descargar")
                print("más de una vez al día. Usa --forzar si de verdad lo necesitas.")
                return 0

        # 2) Descargar
        try:
            url = obtener_url_descarga()
            cartas = descargar_cartas(url)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"\nError al descargar las cartas de Scryfall: {e}")
            print("Comprueba tu conexión a internet y vuelve a intentarlo.")
            return 1

        # 3) Guardar en la base de datos, TODO en una única transacción:
        #    si algo falla a mitad, se hace ROLLBACK y la base de datos queda como estaba.
        conn.execute("BEGIN")
        try:
            if es_esquema_antiguo(conn):
                print("Detectada base de datos con el esquema antiguo. Migrando...")
                filas_mazos = guardar_mazos_antiguos(conn)
                conn.execute("DROP TABLE IF EXISTS mazo_cartas")
                conn.execute("DROP TABLE IF EXISTS cartas")
                crear_tablas(conn)
                insertar_cartas(conn, cartas)
                restaurar_mazos_antiguos(conn, filas_mazos)
            else:
                crear_tablas(conn)
                insertar_cartas(conn, cartas)
            registrar_descarga(conn)
            conn.execute(f"PRAGMA user_version = {db.VERSION_ESQUEMA}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    print(f"Listo en {time.time() - inicio:.1f} segundos. Base de datos: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
