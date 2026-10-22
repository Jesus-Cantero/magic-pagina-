"""
app.py

Aplicación Flask: wiki de cartas de Magic the Gathering + creador de mazos.
Ejecutar con:
    python app.py
y abrir http://127.0.0.1:5000 en el navegador.

Requiere que ya se haya ejecutado antes:
    python download_cards.py
para tener la base de datos mtg_cards.db poblada.

Variables de entorno opcionales:
    SECRET_KEY   Clave para firmar la sesión (cookies). Si no se define se
                 genera una aleatoria en cada arranque (válido en local).
    FLASK_DEBUG  Pon "1" para activar el modo depuración (recarga automática
                 y errores detallados). NUNCA en producción.
"""

import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash

import database as db

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

# Clave secreta persistente para que las sesiones no se borren al reiniciar ni entre workers de Gunicorn.
app.secret_key = (
    os.environ.get("SECRET_KEY")
    or db.obtener_meta("secret_key")
    or "suso-mtg-moxfield-secret-key-2026-permanent-9f8e7d6c5b4a"
)

POR_PAGINA = 24

# Formatos que mostramos en la ficha de la carta (clave de Scryfall -> nombre visible)
FORMATOS_LEGALIDAD = [
    ("standard", "Standard"),
    ("pioneer", "Pioneer"),
    ("modern", "Modern"),
    ("legacy", "Legacy"),
    ("vintage", "Vintage"),
    ("commander", "Commander"),
    ("pauper", "Pauper"),
    ("historic", "Historic"),
    ("brawl", "Brawl"),
    ("oathbreaker", "Oathbreaker"),
    ("duel", "Duel Commander"),
    ("premodern", "Premodern"),
]

# Catálogo completo de todos los modos de juego de Magic: The Gathering
# agrupados por categoría al estilo Moxfield, con sus reglas oficiales.
GRUPOS_FORMATOS_MTG = [
    {
        "categoria": "👑 Formatos con Comandante / Zona de Mando",
        "formatos": [
            {
                "id": "Commander",
                "etiqueta": "Commander / EDH (1 Comandante + 99 · Singleton)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "commander",
                "resumen": "1 Comandante + 99 cartas · Singleton (máx. 1 copia salvo tierras básicas)",
            },
            {
                "id": "cEDH",
                "etiqueta": "cEDH · Commander Competitivo (1 Comandante + 99)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "commander",
                "resumen": "1 Comandante + 99 cartas · Singleton competitivo de alto poder",
            },
            {
                "id": "Duel Commander",
                "etiqueta": "Duel Commander 1v1 (1 Comandante + 99)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "duel",
                "resumen": "1 Comandante + 99 cartas · Singleton competitivo 1 contra 1 (20 vidas)",
            },
            {
                "id": "Pauper Commander",
                "etiqueta": "Pauper Commander / PDH (1 Infrecuente + 99 Comunes)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "paupercommander",
                "resumen": "1 Comandante infrecuente + 99 cartas comunes · Singleton",
            },
            {
                "id": "PreDH",
                "etiqueta": "PreDH · Commander Pre-2011 (1 Comandante + 99)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "predh",
                "resumen": "1 Comandante + 99 cartas · Solo expansiones previas a New Phyrexia (2011)",
            },
            {
                "id": "Oathbreaker",
                "etiqueta": "Oathbreaker (Planeswalker + Conjuro Firma · 60 cartas)",
                "usa_comandante": True,
                "total_objetivo": 60,
                "max_copias": 1,
                "clave_scryfall": "oathbreaker",
                "resumen": "1 Planeswalker Oathbreaker + 59 cartas (incl. Conjuro Firma) · Singleton",
            },
            {
                "id": "Brawl",
                "etiqueta": "Standard Brawl (1 Comandante + 59 · 60 cartas)",
                "usa_comandante": True,
                "total_objetivo": 60,
                "max_copias": 1,
                "clave_scryfall": "standardbrawl",
                "resumen": "1 Comandante (criatura o planeswalker) + 59 cartas de Standard · Singleton",
            },
            {
                "id": "Historic Brawl",
                "etiqueta": "Historic Brawl (1 Comandante + 99 · MTG Arena)",
                "usa_comandante": True,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "brawl",
                "resumen": "1 Comandante + 99 cartas del pool de MTG Arena · Singleton",
            },
            {
                "id": "Tiny Leaders",
                "etiqueta": "Tiny Leaders (1 Comandante + 49 · CMC ≤ 3)",
                "usa_comandante": True,
                "total_objetivo": 50,
                "max_copias": 1,
                "clave_scryfall": "legacy",
                "resumen": "1 Comandante + 49 cartas · Singleton · Coste de maná (CMC) máximo de 3",
            },
        ],
    },
    {
        "categoria": "⚔️ Construido Competitivo (60 cartas · Máx. 4 copias)",
        "formatos": [
            {
                "id": "Standard",
                "etiqueta": "Standard (60 cartas · Rotación actual)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "standard",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias por carta · Expansiones recientes en rotación",
            },
            {
                "id": "Pioneer",
                "etiqueta": "Pioneer (60 cartas · Desde Return to Ravnica)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "pioneer",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias por carta · Expansiones desde 2012",
            },
            {
                "id": "Modern",
                "etiqueta": "Modern (60 cartas · Desde Octava Edición)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "modern",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias por carta · Marco moderno desde 2003",
            },
            {
                "id": "Legacy",
                "etiqueta": "Legacy (60 cartas · Eterno)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "legacy",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias por carta · Todas las expansiones de la historia",
            },
            {
                "id": "Vintage",
                "etiqueta": "Vintage (60 cartas · Eterno con Restringidas)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "vintage",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias (1 copia para cartas Restringidas como el Power Nine)",
            },
            {
                "id": "Pauper",
                "etiqueta": "Pauper (60 cartas · Solo Comunes)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "pauper",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias por carta · Exclusivamente cartas de rareza Común",
            },
            {
                "id": "Premodern",
                "etiqueta": "Premodern (60 cartas · 1995 a 2003)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "premodern",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Desde Cuarta Edición hasta Azote (Scourge)",
            },
            {
                "id": "Old School 93/94",
                "etiqueta": "Old School 93/94 (60 cartas · Alpha a Fallen Empires)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "oldschool",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Expansiones clásicas de 1993 y 1994",
            },
            {
                "id": "Penny Dreadful",
                "etiqueta": "Penny Dreadful (60 cartas · Económico MTGO)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "penny",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Cartas de coste ultrabajo en MTGO",
            },
        ],
    },
    {
        "categoria": "💻 Formatos Digitales (MTG Arena)",
        "formatos": [
            {
                "id": "Alchemy",
                "etiqueta": "Alchemy (60 cartas · MTG Arena)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "alchemy",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Rotación de Arena con cartas digitales",
            },
            {
                "id": "Explorer",
                "etiqueta": "Explorer (60 cartas · Rumbo a Pioneer en Arena)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "explorer",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Cartas de Pioneer disponibles en MTG Arena",
            },
            {
                "id": "Historic",
                "etiqueta": "Historic (60 cartas · Eterno de MTG Arena)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "historic",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias · Todas las cartas de MTG Arena (salvo baneadas)",
            },
            {
                "id": "Timeless",
                "etiqueta": "Timeless (60 cartas · Sin prohibiciones en Arena)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 4,
                "clave_scryfall": "timeless",
                "resumen": "Mínimo 60 cartas · Máx. 4 copias (1 para restringidas) · El Vintage de MTG Arena",
            },
        ],
    },
    {
        "categoria": "🛡️ Singleton 100 Cartas (Sin Comandante)",
        "formatos": [
            {
                "id": "Canadian Highlander",
                "etiqueta": "Canadian Highlander (100 cartas · Singleton con puntos)",
                "usa_comandante": False,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "vintage",
                "resumen": "Mínimo 100 cartas · Singleton sin Comandante · Sistema de 10 puntos para cartas potentes",
            },
            {
                "id": "Gladiator",
                "etiqueta": "Gladiator (100 cartas · Singleton en MTG Arena)",
                "usa_comandante": False,
                "total_objetivo": 100,
                "max_copias": 1,
                "clave_scryfall": "gladiator",
                "resumen": "Mínimo 100 cartas · Singleton sin Comandante con todo el pool de MTG Arena",
            },
        ],
    },
    {
        "categoria": "🎲 Limitado & Casual (40 o Libre)",
        "formatos": [
            {
                "id": "Draft",
                "etiqueta": "Booster Draft (40 cartas · Limitado)",
                "usa_comandante": False,
                "total_objetivo": 40,
                "max_copias": 99,
                "clave_scryfall": None,
                "resumen": "Mínimo 40 cartas · Sin límite de 4 copias · Mazo construido abriendo sobres en Draft",
            },
            {
                "id": "Sealed",
                "etiqueta": "Mazo Cerrado / Sealed / Presentación (40 cartas)",
                "usa_comandante": False,
                "total_objetivo": 40,
                "max_copias": 99,
                "clave_scryfall": None,
                "resumen": "Mínimo 40 cartas · Sin límite de 4 copias · Construido con 6 sobres de presentación",
            },
            {
                "id": "Cube",
                "etiqueta": "Cube Draft (40 cartas · Cubo personalizado)",
                "usa_comandante": False,
                "total_objetivo": 40,
                "max_copias": 99,
                "clave_scryfall": None,
                "resumen": "Mínimo 40 cartas · Diseñado para jugar o registrar mazos de Cube Draft",
            },
            {
                "id": "Casual",
                "etiqueta": "Casual / Cocina / Formato Libre (60 cartas)",
                "usa_comandante": False,
                "total_objetivo": 60,
                "max_copias": 99,
                "clave_scryfall": None,
                "resumen": "Construcción libre sin restricciones de formato · Meta orientativa de 60 cartas",
            },
        ],
    },
]

# Diccionario rápido por nombre de formato (insensible a mayúsculas)
MAPA_REGLAS_FORMATO = {}
for _grupo in GRUPOS_FORMATOS_MTG:
    for _fmt in _grupo["formatos"]:
        MAPA_REGLAS_FORMATO[_fmt["id"].lower()] = _fmt
MAPA_REGLAS_FORMATO["edh"] = MAPA_REGLAS_FORMATO["commander"]


def obtener_reglas_formato(nombre_formato):
    """Devuelve las reglas asociadas al formato del mazo (por defecto Commander)."""
    clave = (nombre_formato or "Commander").strip().lower()
    return MAPA_REGLAS_FORMATO.get(clave, MAPA_REGLAS_FORMATO["commander"])


TIERRAS_BASICAS_NOMBRES = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest", " snow-covered wastes",
}


def evaluar_carta_en_formato(carta, reglas):
    """
    Comprueba si una carta del mazo cumple las reglas del formato elegido
    (legalidad en Scryfall y límite de copias por carta).
    Devuelve (es_legal: bool, aviso: str | None).
    """
    clave_sf = reglas.get("clave_scryfall")
    if clave_sf:
        try:
            leg_dict = json.loads(carta["legalidades"] or "{}")
        except (TypeError, ValueError):
            leg_dict = {}
        estado = leg_dict.get(clave_sf, "not_legal")
        if estado == "banned":
            return False, f"Prohibida en {reglas['id']}"
        if estado == "not_legal":
            return False, f"No legal en {reglas['id']}"
        if estado == "restricted" and carta["cantidad"] > 1:
            return False, f"Restringida en {reglas['id']} (máx. 1)"

    es_tierra_basica = (
        "Basic" in (carta["tipo"] or "")
        or (carta["nombre"] or "").strip().lower() in TIERRAS_BASICAS_NOMBRES
    )
    max_copias = reglas.get("max_copias", 4)
    if not es_tierra_basica and carta["cantidad"] > max_copias:
        return False, f"Máx. {max_copias} copia(s) en {reglas['id']}"

    return True, None


# ---------- Sistema de Brackets (1 al 5) estilo Moxfield / Wizards of the Coast ----------

CATALOGO_BRACKETS = {
    1: {
        "numero": 1,
        "nombre": "Exhibition",
        "titulo": "Bracket 1 · Exhibition",
        "etiqueta_corta": "Bracket 1: Exhibition",
        "turnos": "9+ turnos",
        "color": "#38bdf8",
        "resumen": "Ultra-Casual / Temático · 0 Game Changers · 0 MLD · 0 Turnos Extra · Sin tutores de combo",
        "descripcion": (
            "Prioriza una temática, historia o concepto artístico por encima de la optimización. "
            "No usa Game Changers, destrucción masiva de tierras (MLD), turnos extra ni combos de 2 cartas."
        ),
    },
    2: {
        "numero": 2,
        "nombre": "Core",
        "titulo": "Bracket 2 · Core (Precon)",
        "etiqueta_corta": "Bracket 2: Core",
        "turnos": "8+ turnos",
        "color": "#22c55e",
        "resumen": "Nivel Precon / Casual Estándar · 0 Game Changers · 0 MLD · Sin encadenar turnos extra",
        "descripcion": (
            "Equivalente a un mazo preconstruido actual (Precon). Condiciones de victoria incrementales y "
            "telegrafiadas, 0 Game Changers, 0 destrucción masiva de tierras (MLD) y tutores escasos."
        ),
    },
    3: {
        "numero": 3,
        "nombre": "Upgraded",
        "titulo": "Bracket 3 · Upgraded",
        "etiqueta_corta": "Bracket 3: Upgraded",
        "turnos": "6+ turnos",
        "color": "#eab308",
        "resumen": "Mejorado / Sinergia Fuerte · Hasta 3 Game Changers · 0 MLD · Sin combos tempranos",
        "descripcion": (
            "Mazos afinados con alta sinergia y cartas de gran calidad. Permite hasta 3 cartas de la lista "
            "oficial de Game Changers, pero sigue sin permitir destrucción masiva de tierras (MLD)."
        ),
    },
    4: {
        "numero": 4,
        "nombre": "Optimized",
        "titulo": "Bracket 4 · Optimized",
        "etiqueta_corta": "Bracket 4: Optimized",
        "turnos": "4–6 turnos",
        "color": "#f97316",
        "resumen": "Alto Poder Optimizado · Game Changers ilimitados · MLD, Turnos Extra y Combos permitidos",
        "descripcion": (
            "Mazos de alto poder diseñados para ganar rápido o bloquear la mesa, sin restricciones de "
            "Game Changers, destrucción masiva de tierras (MLD), maná rápido ni combos de 2 cartas."
        ),
    },
    5: {
        "numero": 5,
        "nombre": "cEDH",
        "titulo": "Bracket 5 · cEDH",
        "etiqueta_corta": "Bracket 5: cEDH",
        "turnos": "1–4 turnos",
        "color": "#ef4444",
        "resumen": "Competitivo de Torneo (cEDH) · Máxima velocidad, maná rápido, interacción gratuita y tutores",
        "descripcion": (
            "La cúspide competitiva construida específicamente para el metajuego de torneo (cEDH). "
            "Usa maná rápido explosivo, interacción gratuita, tutores universales y líneas de victoria inmediatas."
        ),
    },
}

# Lista oficial de Game Changers de Wizards of the Coast / Moxfield (en minúsculas)
CARTAS_GAME_CHANGERS = {
    # Incoloras
    "chrome mox", "grim monolith", "lion's eye diamond", "mana vault", "mox diamond",
    "panoptic mirror", "the one ring",
    # Blancas
    "drannith magistrate", "enlightened tutor", "farewell", "humility", "serra's sanctum",
    "smothering tithe", "teferi's protection",
    # Azules
    "consecrated sphinx", "cyclonic rift", "fierce guardianship", "force of will",
    "gifts ungiven", "intuition", "mystical tutor", "narset, parter of veils",
    "rhystic study", "thassa's oracle", "expropriate", "jin-gitaxias, core augur",
    "sway of the stars", "urza, lord high artificer",
    # Negras
    "ad nauseam", "bolas's citadel", "braids, cabal minion", "demonic tutor",
    "imperial seal", "necropotence", "opposition agent", "orcish bowmasters",
    "tergrid, god of fright", "vampiric tutor",
    # Rojas
    "gamble", "jeska's will", "underworld breach", "deflecting swat",
    # Verdes
    "biorhythm", "crop rotation", "gaea's cradle", "natural order", "seedborn muse",
    "survival of the fittest", "worldly tutor", "vorinclex, voice of hunger", "food chain",
    # Multicolor y Tierras
    "ancient tomb", "aura shards", "coalition victory", "field of the dead",
    "glacial chasm", "grand arbiter augustin iv", "mishra's workshop", "notion thief",
    "the tabernacle at pendrell vale", "kinnan, bonder prodigy", "winota, joiner of forces",
    "yuriko, the tiger's shadow",
}

# Destrucción o Bloqueo Masivo de Tierras (Mass Land Denial - MLD)
CARTAS_MLD = {
    "armageddon", "ravages of war", "catastrophe", "decree of annihilation", "jokulhaups",
    "obliterate", "apocalypse", "worldfire", "sunder", "ruination", "blood moon",
    "magus of the moon", "back to basics", "winter orb", "static orb", "stasis",
    "hokori, dust drinker", "vorinclex, voice of hunger", "contamination", "infernal darkness",
    "hall of gemstone", "harbinger of the seas", "balance", "cataclysm", "impending disaster",
    "boil", "boiling seas", "tsunami", "wake of destruction", "destructive force",
    "wildfire", "burning of xinye", "thoughts of ruin", "epicenter", "global ruin",
    "razia's purification", "fall of the thran", "rising waters", "mana breach", "overburden",
}

# Maná rápido e interacción gratuita típica de Bracket 4 / Bracket 5 (cEDH)
CARTAS_MANA_RAPIDO_CEDH = {
    "sol ring", "mana vault", "chrome mox", "mox diamond", "mox opal", "mox amber",
    "lotus petal", "grim monolith", "lion's eye diamond", "ancient tomb", "gaea's cradle",
    "serra's sanctum", "mishra's workshop", "dark ritual", "cabal ritual", "jeska's will",
    "simian spirit guide", "elvish spirit guide", "rite of flame", "culling the weak",
    "force of will", "force of negation", "fierce guardianship", "deflecting swat",
    "pact of negation", "mental misstep", "mindbreak trap", "flusterstorm", "swan song",
    "mystic remora", "carpet of flowers", "silence",
}

PATRON_MLD_TEXTO = re.compile(
    r"destroy all lands|exile all lands|return all lands to their owners' hands|"
    r"lands don't untap during their controllers' untap steps|nonbasic lands are mountains",
    re.IGNORECASE,
)
PATRON_TURNO_EXTRA = re.compile(
    r"\btakes?\s+(?:an|two)\s+extra\s+turns?\b",
    re.IGNORECASE,
)
PATRON_BUSCAR_BIBLIOTECA = re.compile(
    r"search your library for (?:an?|up to [a-z0-9]+)\s+([^.,;]+)",
    re.IGNORECASE,
)
TERMINOS_SOLO_TIERRA = (
    "basic land", "land card", "plains", "island", "swamp", "mountain", "forest",
    "gate card", "cave card", "desert card", "sphere card", "locus",
)


def clasificar_barometros_carta(carta):
    """
    Evalúa una carta según los barómetros oficiales del sistema de Brackets de Moxfield:
      - es_game_changer: está en la lista de Game Changers
      - es_mld: destruye o bloquea tierras masivamente (Mass Land Denial)
      - es_turno_extra: otorga turnos adicionales
      - es_tutor: busca cartas no-tierra en la biblioteca
      - es_mana_rapido: acelerador o interacción gratuita de alto poder / cEDH
    """
    nombre_completo = (carta.get("nombre") or "").strip().lower()
    nombre_base = nombre_completo.split("//")[0].strip() if "//" in nombre_completo else nombre_completo
    texto = (carta.get("texto") or "").lower()

    es_gc = nombre_completo in CARTAS_GAME_CHANGERS or nombre_base in CARTAS_GAME_CHANGERS
    es_mld = (
        nombre_completo in CARTAS_MLD
        or nombre_base in CARTAS_MLD
        or bool(PATRON_MLD_TEXTO.search(texto))
    )
    es_extra = bool(PATRON_TURNO_EXTRA.search(texto)) and "can't take extra turns" not in texto

    es_tutor = False
    for m in PATRON_BUSCAR_BIBLIOTECA.finditer(texto):
        objetivo = m.group(1).strip().lower()
        if not any(t in objetivo for t in TERMINOS_SOLO_TIERRA):
            es_tutor = True
            break

    es_fast = nombre_completo in CARTAS_MANA_RAPIDO_CEDH or nombre_base in CARTAS_MANA_RAPIDO_CEDH

    etiquetas = []
    if es_gc:
        etiquetas.append(("gc", "🔥 Game Changer"))
    if es_mld:
        etiquetas.append(("mld", "🌋 MLD"))
    if es_extra:
        etiquetas.append(("extra", "⏳ Turno Extra"))
    if es_tutor:
        etiquetas.append(("tutor", "🔍 Tutor"))

    return {
        "es_game_changer": es_gc,
        "es_mld": es_mld,
        "es_turno_extra": es_extra,
        "es_tutor": es_tutor,
        "es_mana_rapido": es_fast,
        "etiquetas": etiquetas,
    }


def analizar_bracket_mazo(mazo, comandante, cartas_biblioteca, cmc_medio=0.0):
    """
    Calcula el Bracket estimado del 1 al 5 al estilo de Moxfield a partir de las
    cartas del mazo (Comandante + Biblioteca) y el modo de juego.
    """
    todas = []
    if comandante:
        todas.append({**dict(comandante), "cantidad": 1, "es_comandante": True})
    for c in cartas_biblioteca:
        todas.append({**dict(c), "es_comandante": False})

    game_changers = []
    mld = []
    turnos_extra = []
    tutores = []
    mana_rapido = []

    for c in todas:
        bar = clasificar_barometros_carta(c)
        if bar["es_game_changer"]:
            game_changers.append(c)
        if bar["es_mld"]:
            mld.append(c)
        if bar["es_turno_extra"]:
            turnos_extra.append(c)
        if bar["es_tutor"]:
            tutores.append(c)
        if bar["es_mana_rapido"]:
            mana_rapido.append(c)

    num_gc = len(game_changers)
    num_mld = len(mld)
    num_extra = len(turnos_extra)
    num_tutores = len(tutores)
    num_fast = len(mana_rapido)
    formato_str = ((mazo["formato"] if mazo else "") or "Commander").strip().lower()

    motivos = []

    # Lógica de estimación oficial (1 a 5) estilo Moxfield
    if formato_str == "cedh" or (
        num_gc >= 5 and num_fast >= 4 and num_tutores >= 4 and (0 < cmc_medio <= 2.35)
    ):
        estimado = 5
        if formato_str == "cedh":
            motivos.append("Modo configurado explícitamente como cEDH (Bracket 5 · Competitivo).")
        if num_gc > 0:
            motivos.append(f"Incluye {num_gc} carta(s) de la lista oficial de Game Changers.")
        if num_fast > 0:
            motivos.append(f"Cuenta con {num_fast} aceleradores de maná rápido / interacción gratuita de cEDH.")
        if num_tutores > 0:
            motivos.append(f"Dispone de {num_tutores} tutor(es) para buscar piezas clave en la biblioteca.")
        if 0 < cmc_medio <= 2.35:
            motivos.append(f"Curva de maná ultrabaja (CMC medio {cmc_medio}) orientada a velocidad de torneo.")
    elif num_gc > 3 or num_mld >= 1 or num_extra >= 3 or num_fast >= 6:
        estimado = 4
        if num_gc > 3:
            motivos.append(f"Supera el límite de 3 Game Changers de Bracket 3 ({num_gc} detectados → Bracket 4).")
        if num_mld >= 1:
            motivos.append(f"Incluye {num_mld} carta(s) de Destrucción/Bloqueo Masivo de Tierras (MLD → mínimo Bracket 4).")
        if num_extra >= 3:
            motivos.append(f"Incluye {num_extra} cartas de Turnos Extra (riesgo de encadenar turnos → Bracket 4).")
        if num_fast >= 6:
            motivos.append(f"Alta concentración de maná rápido e interacción gratuita ({num_fast} cartas → Bracket 4).")
    elif 1 <= num_gc <= 3 or num_tutores >= 3 or num_extra >= 1 or num_fast >= 3:
        estimado = 3
        if 1 <= num_gc <= 3:
            motivos.append(f"Incluye {num_gc} de hasta 3 Game Changers permitidos en Bracket 3 (Upgraded).")
        if num_tutores >= 3:
            motivos.append(f"Cuenta con {num_tutores} tutores no-tierra para dar consistencia al plan de juego.")
        if num_extra >= 1:
            motivos.append(f"Incluye {num_extra} carta(s) de turno extra y 0 destrucción masiva de tierras.")
        if not motivos:
            motivos.append(f"Incluye {num_fast} piezas de aceleración/interacción rápida con 0 MLD.")
    elif len(todas) > 0 and (num_tutores >= 1 or num_fast >= 1 or len(todas) >= 15):
        estimado = 2
        motivos.append("0 Game Changers y 0 Destrucción Masiva de Tierras (MLD): cumple las normas de Bracket 2 (Core / Nivel Precon).")
    else:
        estimado = 1
        motivos.append("0 Game Changers, 0 MLD, 0 Turnos Extra y 0 Tutores: encaja en Bracket 1 (Exhibition / Temático).")

    objetivo = int((mazo["bracket_objetivo"] if mazo and "bracket_objetivo" in mazo.keys() else 0) or 0)
    activo = objetivo if objetivo in (1, 2, 3, 4, 5) else estimado

    alerta_objetivo = None
    if objetivo in (1, 2, 3, 4, 5) and estimado > objetivo:
        alerta_objetivo = (
            f"Has fijado como meta {CATALOGO_BRACKETS[objetivo]['titulo']}, pero por las cartas incluidas "
            f"el analizador lo estima en {CATALOGO_BRACKETS[estimado]['titulo']}."
        )

    return {
        "estimado": estimado,
        "objetivo": objetivo,
        "activo": activo,
        "info_activo": CATALOGO_BRACKETS[activo],
        "info_estimado": CATALOGO_BRACKETS[estimado],
        "catalogo": [CATALOGO_BRACKETS[i] for i in (1, 2, 3, 4, 5)],
        "game_changers": game_changers,
        "mld": mld,
        "turnos_extra": turnos_extra,
        "tutores": tutores,
        "mana_rapido": mana_rapido,
        "motivos": motivos,
        "alerta_objetivo": alerta_objetivo,
    }

ESTADOS_LEGALIDAD = {
    "legal": "Legal",
    "not_legal": "No legal",
    "banned": "Prohibida",
    "restricted": "Restringida",
}

MENSAJES_ESTADO_BD = {
    "falta": "Todavía no hay base de datos de cartas. Ejecuta 'python download_cards.py' primero.",
    "vacia": "La base de datos no tiene cartas. Ejecuta 'python download_cards.py'.",
    "antigua": "La base de datos usa un formato antiguo. Ejecuta 'python download_cards.py' "
               "para actualizarla (tus mazos se conservan).",
}


# ---------- Protección CSRF (sin dependencias externas) ----------
#
# Cada sesión tiene un token aleatorio. Todos los formularios POST lo envían
# en un campo oculto "csrf_token" y las llamadas fetch() en la cabecera
# "X-CSRFToken". Si no coincide, la petición se rechaza. Así otra web no
# puede, por ejemplo, borrar tus mazos enviando un formulario a tu servidor.

def obtener_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def obtener_usuario_actual():
    uid = session.get("usuario_id")
    if not uid:
        return None
    if db.estado_bd() != "ok":
        return None
    return db.obtener_usuario_por_id(uid)


@app.context_processor
def inyectar_contexto():
    usuario = obtener_usuario_actual()
    albumes_ctx = db.listar_albumes(usuario["id"] if usuario else None) if db.estado_bd() == "ok" else []
    return {
        "csrf_token": obtener_csrf_token,
        "usuario_actual": usuario,
        "albumes_globales": albumes_ctx,
        "google_oauth_configurado": bool(
            os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")
        ),
        "grupos_formatos": GRUPOS_FORMATOS_MTG,
        "obtener_reglas_formato": obtener_reglas_formato,
        "catalogo_brackets": [CATALOGO_BRACKETS[i] for i in (1, 2, 3, 4, 5)],
    }


def es_peticion_api():
    return request.path.startswith("/api/")


@app.before_request
def comprobar_csrf():
    if request.method != "POST":
        return None
    enviado = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
    esperado = session.get("csrf_token", "")
    if not esperado or not secrets.compare_digest(enviado, esperado):
        if es_peticion_api():
            return jsonify({"ok": False, "error": "Token CSRF no válido. Recarga la página."}), 400
        flash("La sesión ha caducado o el formulario no es válido. Inténtalo de nuevo.")
        return redirect(request.referrer or url_for("index"))
    return None


@app.before_request
def comprobar_base_de_datos():
    """Si la base de datos no está lista, solo dejamos ver la portada (con el aviso)."""
    if request.endpoint in ("home", "index", "static") or request.endpoint is None:
        return None
    estado = db.estado_bd()
    if estado == "ok":
        return None
    if es_peticion_api():
        return jsonify({"ok": False, "error": MENSAJES_ESTADO_BD[estado]}), 503
    return redirect(url_for("home"))


# ---------- Utilidades y filtros de plantilla ----------

PATRON_SIMBOLO_MANA = re.compile(r"\{([^{}]+)\}")


def _clase_simbolo(simbolo):
    s = simbolo.upper()
    if s in ("W", "U", "B", "R", "G", "C"):
        return f"mana-{s}"
    if s == "T":
        return "mana-tap"
    if "/" in s:
        return "mana-hybrid"
    return "mana-generic"


@app.template_filter("simbolos_mana")
def filtro_simbolos_mana(texto):
    """
    Convierte símbolos como '{2}{U}{U}' o '{T}: Add {C}{C}.' en insignias
    circulares estilo Moxfield/MTG de forma segura (escapando antes el HTML).
    """
    if not texto:
        return ""
    escapado = str(escape(texto))

    def reemplazar(coincidencia):
        contenido = coincidencia.group(1).strip()
        clase = _clase_simbolo(contenido)
        mostrar = "⟳" if contenido.upper() == "T" else contenido
        return f'<span class="mana-pip {clase}" title="{{{contenido}}}">{mostrar}</span>'

    resultado = PATRON_SIMBOLO_MANA.sub(reemplazar, escapado)
    return Markup(resultado)


def rango_paginas(actual, total, alrededor=2):
    """
    Devuelve las páginas a mostrar en la paginación, con None donde va "…".
    Ej.: actual=50, total=1300 -> [1, None, 48, 49, 50, 51, 52, None, 1300]
    """
    candidatas = {1, total, *range(actual - alrededor, actual + alrededor + 1)}
    paginas = sorted(p for p in candidatas if 1 <= p <= total)
    resultado, anterior = [], 0
    for p in paginas:
        if p - anterior > 1:
            resultado.append(None)
        resultado.append(p)
        anterior = p
    return resultado


def parsear_legalidades(texto_json):
    try:
        datos = json.loads(texto_json or "{}")
    except (TypeError, ValueError):
        datos = {}
    return [
        {
            "formato": nombre,
            "estado": datos.get(clave, "not_legal"),
            "texto": ESTADOS_LEGALIDAD.get(datos.get(clave, "not_legal"), datos.get(clave, "")),
        }
        for clave, nombre in FORMATOS_LEGALIDAD
    ]


# ---------- Páginas ----------

@app.route("/")
def home():
    """Página principal de bienvenida al estilo de https://moxfield.com."""
    estado = db.estado_bd()
    if estado != "ok":
        flash(MENSAJES_ESTADO_BD[estado])
        return render_template(
            "home.html",
            mazos=[],
            spoilers=[],
            staples=[],
            total_cartas=0,
            total_spoilers=0,
        )

    resumen = db.resumen_portada_moxfield(limite_spoilers=8)
    usuario = obtener_usuario_actual()
    filas_mazos = db.listar_mazos(usuario["id"] if usuario else None)
    mazos = []
    for fila in filas_mazos:
        d = dict(fila)
        m_full, cmd_full, cartas_full = db.obtener_mazo(d["id"])
        d["bracket"] = analizar_bracket_mazo(m_full, cmd_full, cartas_full)
        mazos.append(d)

    return render_template(
        "home.html",
        mazos=mazos,
        spoilers=resumen["spoilers"],
        staples=resumen["staples"],
        total_cartas=resumen["total_cartas"],
        total_spoilers=resumen["total_spoilers"],
    )


@app.route("/explorar")
def index():
    texto = request.args.get("q", "").strip()
    tipo = request.args.get("tipo", "").strip()
    color = request.args.get("color", "")
    if color not in ("", "W", "U", "B", "R", "G", "C"):
        color = ""
    edicion = (request.args.get("edicion") or request.args.get("set") or "").strip().lower()
    solo_spoilers = request.args.get("spoilers") == "1"
    orden = request.args.get("orden", "").strip()
    if orden not in ("nombre", "recientes"):
        orden = "recientes" if solo_spoilers else "nombre"
    # type=int: si llega "abc" se usa 1 en vez de lanzar un error 500
    pagina = request.args.get("pagina", 1, type=int)

    estado = db.estado_bd()
    if estado != "ok":
        flash(MENSAJES_ESTADO_BD[estado])
        return render_template("index.html", cartas=[], total=0, texto=texto, tipo=tipo, color=color,
                               edicion="", edicion_actual=None, ediciones=[],
                               orden=orden, solo_spoilers=solo_spoilers, mazos=[],
                               pagina=1, total_paginas=1, paginas=[])

    ediciones = db.listar_ediciones()
    edicion_actual = next((e for e in ediciones if e["set_code"] == edicion), None) if edicion else None

    pagina = max(1, pagina)
    cartas, total = db.buscar_cartas(
        texto, tipo, color, pagina, POR_PAGINA, orden=orden, solo_spoilers=solo_spoilers, edicion=edicion
    )
    total_paginas = max(1, (total + POR_PAGINA - 1) // POR_PAGINA)

    # Si piden una página que no existe, redirigimos a la última
    if pagina > total_paginas:
        return redirect(url_for("index", q=texto, tipo=tipo, color=color, edicion=edicion or None,
                                orden=orden, spoilers="1" if solo_spoilers else None, pagina=total_paginas))

    usuario = obtener_usuario_actual()
    mazos = db.listar_mazos(usuario["id"] if usuario else None)
    return render_template(
        "index.html",
        cartas=cartas,
        total=total,
        texto=texto,
        tipo=tipo,
        color=color,
        edicion=edicion,
        edicion_actual=edicion_actual,
        ediciones=ediciones,
        orden=orden,
        solo_spoilers=solo_spoilers,
        mazos=mazos,
        pagina=pagina,
        total_paginas=total_paginas,
        paginas=rango_paginas(pagina, total_paginas),
    )


@app.route("/carta/<carta_id>")
def carta_detalle(carta_id):
    carta = db.obtener_carta(carta_id)
    if carta is None:
        flash("No se encontró esa carta.")
        return redirect(url_for("index"))
    usuario = obtener_usuario_actual()
    mazos = db.listar_mazos(usuario["id"] if usuario else None)
    legalidades = parsear_legalidades(carta["legalidades"])
    return render_template("card_detail.html", carta=carta, mazos=mazos, legalidades=legalidades)


@app.route("/mazos")
def listar_mazos():
    formato_pre = request.args.get("formato", "").strip()
    usuario = obtener_usuario_actual()
    filas_mazos = db.listar_mazos(usuario["id"] if usuario else None)
    mazos = []
    for fila in filas_mazos:
        d = dict(fila)
        m_full, cmd_full, cartas_full = db.obtener_mazo(d["id"])
        d["bracket"] = analizar_bracket_mazo(m_full, cmd_full, cartas_full)
        mazos.append(d)
    return render_template("my_decks.html", mazos=mazos, formato_pre=formato_pre,
                           max_nombre=db.MAX_LONGITUD_NOMBRE_MAZO, max_formato=db.MAX_LONGITUD_FORMATO)


CATEGORIAS_TIPO = [
    ("Criaturas", "Creature"),
    ("Planeswalkers", "Planeswalker"),
    ("Instantáneos", "Instant"),
    ("Conjuros", "Sorcery"),
    ("Artefactos", "Artifact"),
    ("Encantamientos", "Enchantment"),
    ("Tierras", "Land"),
]


def clasificar_tipo_carta(linea_tipo):
    """
    Clasifica una carta en su categoría principal al estilo Moxfield.
    (Por ejemplo, una 'Artifact Creature' va a 'Criaturas', y una 'Artifact Land' a 'Tierras'.)
    """
    t = linea_tipo or ""
    if "Land" in t:
        return "Tierras"
    if "Creature" in t:
        return "Criaturas"
    if "Planeswalker" in t:
        return "Planeswalkers"
    if "Instant" in t:
        return "Instantáneos"
    if "Sorcery" in t:
        return "Conjuros"
    if "Artifact" in t:
        return "Artefactos"
    if "Enchantment" in t:
        return "Encantamientos"
    return "Otros"


def calcular_analiticas_mazo(comandante, cartas_biblioteca):
    """
    Calcula las agrupaciones por tipo, la curva de maná (0 a 7+, excluyendo tierras)
    y la distribución por colores al estilo de Moxfield.
    """
    orden_grupos = [nombre for nombre, _ in CATEGORIAS_TIPO] + ["Otros"]
    grupos_dict = {nombre: [] for nombre in orden_grupos}

    for c in cartas_biblioteca:
        cat = clasificar_tipo_carta(c["tipo"])
        grupos_dict[cat].append(c)

    grupos = [
        {
            "nombre": nombre,
            "cartas": lista,
            "total": sum(x["cantidad"] for x in lista),
        }
        for nombre, lista in grupos_dict.items()
        if lista
    ]

    # Curva de maná (0, 1, 2, 3, 4, 5, 6, 7+) excluyendo tierras (como hace Moxfield)
    conteo_curva = {i: 0 for i in range(8)}
    todas_para_curva = list(cartas_biblioteca)
    if comandante:
        todas_para_curva.append({**dict(comandante), "cantidad": 1})

    cartas_no_tierra = 0
    suma_cmc_no_tierra = 0.0
    conteo_colores = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    for c in todas_para_curva:
        cant = c["cantidad"]
        es_tierra = "Land" in (c["tipo"] or "")
        if not es_tierra:
            cmc_val = float(c["cmc"] or 0)
            bucket = min(7, max(0, int(cmc_val)))
            conteo_curva[bucket] += cant
            cartas_no_tierra += cant
            suma_cmc_no_tierra += cmc_val * cant

        colores = [x for x in (c["colores"] or "").split(",") if x]
        if not colores and not es_tierra:
            conteo_colores["C"] += cant
        else:
            for col in colores:
                if col in conteo_colores:
                    conteo_colores[col] += cant

    max_curva = max(conteo_curva.values()) if conteo_curva else 0
    curva_mana = [
        {
            "etiqueta": "7+" if k == 7 else str(k),
            "cantidad": v,
            "porcentaje": round((v / max_curva) * 100) if max_curva > 0 else 0,
        }
        for k, v in conteo_curva.items()
    ]

    cmc_medio = round(suma_cmc_no_tierra / cartas_no_tierra, 2) if cartas_no_tierra else 0.0
    return grupos, curva_mana, conteo_colores, cmc_medio


@app.route("/mazos/nuevo", methods=["POST"])
def crear_mazo():
    usuario = obtener_usuario_actual()
    if not usuario:
        flash("Debes iniciar sesión con tu cuenta para crear y guardar mazos.")
        return redirect(url_for("login"))

    nombre = request.form.get("nombre", "").strip()
    formato = request.form.get("formato", "").strip() or "Commander"
    comandante_id = request.form.get("comandante_id", "").strip() or None
    bracket_objetivo = request.form.get("bracket_objetivo", 0, type=int) or 0
    reglas = obtener_reglas_formato(formato)
    if not reglas["usa_comandante"]:
        comandante_id = None
    if not nombre:
        flash("El mazo necesita un nombre.")
        return redirect(url_for("listar_mazos"))
    if len(nombre) > db.MAX_LONGITUD_NOMBRE_MAZO or len(formato) > db.MAX_LONGITUD_FORMATO:
        flash(f"El nombre admite como máximo {db.MAX_LONGITUD_NOMBRE_MAZO} caracteres "
              f"y el formato {db.MAX_LONGITUD_FORMATO}.")
        return redirect(url_for("listar_mazos"))
    mazo_id = db.crear_mazo(nombre, reglas["id"], usuario["id"], comandante_id, bracket_objetivo)
    flash(f"Mazo «{nombre}» ({reglas['id']}) guardado en tu cuenta.")
    return redirect(url_for("ver_mazo", mazo_id=mazo_id))


@app.route("/mazos/<int:mazo_id>")
def ver_mazo(mazo_id):
    usuario = obtener_usuario_actual()
    if not usuario:
        flash("Inicia sesión con tu cuenta para ver y editar tus mazos.")
        return redirect(url_for("login"))
    mazo, comandante, cartas_filas = db.obtener_mazo(mazo_id)
    if mazo is None or mazo["usuario_id"] != usuario["id"]:
        flash("No se encontró ese mazo en tu cuenta.")
        return redirect(url_for("listar_mazos"))

    reglas_formato = obtener_reglas_formato(mazo["formato"])
    es_commander = reglas_formato["usa_comandante"]
    objetivo_total = reglas_formato["total_objetivo"]
    objetivo_biblioteca = (objetivo_total - 1) if es_commander else objetivo_total

    # Evaluar legalidad y etiquetas de Bracket de cada carta
    cartas = []
    total_ilegales = 0
    if es_commander and comandante:
        cmd_dict = {**dict(comandante), "cantidad": 1}
        cmd_legal, cmd_aviso = evaluar_carta_en_formato(cmd_dict, reglas_formato)
        cmd_dict["es_legal"] = cmd_legal
        cmd_dict["aviso_legalidad"] = cmd_aviso
        cmd_dict["etiquetas_bracket"] = clasificar_barometros_carta(cmd_dict)["etiquetas"]
        if not cmd_legal:
            total_ilegales += 1
        comandante = cmd_dict

    for fila in cartas_filas:
        d = dict(fila)
        es_legal, aviso = evaluar_carta_en_formato(d, reglas_formato)
        d["es_legal"] = es_legal
        d["aviso_legalidad"] = aviso
        d["etiquetas_bracket"] = clasificar_barometros_carta(d)["etiquetas"]
        if not es_legal:
            total_ilegales += 1
        cartas.append(d)

    cartas_biblioteca = sum(c["cantidad"] for c in cartas)
    total_cartas = cartas_biblioteca + (1 if (comandante and es_commander) else 0)

    grupos, curva_mana, conteo_colores, cmc_medio = calcular_analiticas_mazo(
        comandante if es_commander else None, cartas
    )
    bracket = analizar_bracket_mazo(
        mazo, comandante if es_commander else None, cartas, cmc_medio
    )

    return render_template(
        "deck_builder.html",
        mazo=mazo,
        comandante=comandante,
        cartas=cartas,
        grupos=grupos,
        curva_mana=curva_mana,
        conteo_colores=conteo_colores,
        cartas_biblioteca=cartas_biblioteca,
        total_cartas=total_cartas,
        cartas_unicas=len(cartas) + (1 if (comandante and es_commander) else 0),
        cmc_medio=cmc_medio,
        es_commander=es_commander,
        reglas_formato=reglas_formato,
        objetivo_biblioteca=objetivo_biblioteca,
        objetivo_total=objetivo_total,
        total_ilegales=total_ilegales,
        bracket=bracket,
    )


@app.route("/mazos/<int:mazo_id>/eliminar", methods=["POST"])
def eliminar_mazo(mazo_id):
    usuario = obtener_usuario_actual()
    if not usuario:
        flash("Inicia sesión con tu cuenta para gestionar tus mazos.")
        return redirect(url_for("login"))
    mazo = db.obtener_mazo_simple(mazo_id)
    if mazo is None or mazo["usuario_id"] != usuario["id"]:
        flash("No se encontró ese mazo en tu cuenta.")
    else:
        db.eliminar_mazo(mazo_id)
        flash("Mazo eliminado.")
    return redirect(url_for("listar_mazos"))


# ---------- Álbumes Físicos (Estilo Ultimate Guard QuadRow 12-Pocket / 9-Pocket / 4-Pocket) ----------

@app.route("/albumes")
@app.route("/albunes")
def listar_albumes():
    usuario = obtener_usuario_actual()
    albumes = db.listar_albumes(usuario["id"] if usuario else None)
    return render_template("albums.html", albumes=albumes)


@app.route("/albumes/nuevo", methods=["POST"])
def crear_album():
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    color_cubierta = request.form.get("color_cubierta", "negro").strip()
    formato_hoja = request.form.get("formato_hoja", "4x3").strip()
    if not nombre:
        flash("El álbum necesita un nombre.")
        return redirect(url_for("listar_albumes"))
    if len(nombre) > 100:
        flash("El nombre del álbum admite como máximo 100 caracteres.")
        return redirect(url_for("listar_albumes"))

    mapa_hoja = {
        "4x3": (3, 4),  # 12 bolsillos QuadRow (Ultimate Guard)
        "3x3": (3, 3),  # 9 bolsillos estándar
        "2x2": (2, 2),  # 4 bolsillos compacto
    }
    filas, columnas = mapa_hoja.get(formato_hoja, (3, 4))
    usuario = obtener_usuario_actual()
    album_id = db.crear_album(
        nombre=nombre,
        descripcion=descripcion,
        color_cubierta=color_cubierta,
        filas=filas,
        columnas=columnas,
        usuario_id=usuario["id"] if usuario else None,
    )
    flash(f"Álbum físico «{nombre}» ({columnas}×{filas} · {filas * columnas} bolsillos por hoja) creado.")
    return redirect(url_for("ver_album", album_id=album_id))


@app.route("/albumes/<int:album_id>")
def ver_album(album_id):
    pagina = request.args.get("pagina", 1, type=int)
    pagina = max(1, pagina)
    album, bolsillos, total_paginas, total_cartas = db.obtener_album_pagina(album_id, pagina=pagina)
    if album is None:
        flash("No se encontró ese álbum.")
        return redirect(url_for("listar_albumes"))
    capacidad_hoja = int(album["filas"] or 3) * int(album["columnas"] or 4)
    return render_template(
        "album_detail.html",
        album=album,
        bolsillos=bolsillos,
        pagina=pagina,
        total_paginas=total_paginas,
        total_cartas=total_cartas,
        capacidad_hoja=capacidad_hoja,
    )


@app.route("/albumes/<int:album_id>/eliminar", methods=["POST"])
def eliminar_album(album_id):
    if db.obtener_album_simple(album_id) is None:
        flash("No se encontró ese álbum.")
    else:
        db.eliminar_album(album_id)
        flash("Álbum eliminado.")
    return redirect(url_for("listar_albumes"))


@app.route("/api/albumes/<int:album_id>/colocar", methods=["POST"])
def api_colocar_en_album(album_id):
    if db.obtener_album_simple(album_id) is None:
        return error_api("Ese álbum no existe.", 404)
    data = request.get_json(silent=True) or {}
    carta_id = (data.get("carta_id") or "").strip()
    if not carta_id or db.obtener_carta(carta_id) is None:
        return error_api("Esa carta no existe.", 404)
    pagina = data.get("pagina")
    posicion = data.get("posicion")
    imagen_url = (data.get("imagen_url") or data.get("imagen_custom") or "").strip() or None
    if imagen_url and not imagen_url.startswith("https://cards.scryfall.io/"):
        return error_api("La URL de la imagen debe pertenecer a Scryfall.")
    acabado_foil = 1 if (data.get("acabado_foil") or data.get("es_foil")) else 0

    pag_asig, pos_asig, total = db.colocar_carta_en_album(
        album_id=album_id,
        carta_id=carta_id,
        pagina=pagina,
        posicion=posicion,
        imagen_url=imagen_url,
        acabado_foil=acabado_foil,
    )
    return jsonify({"ok": True, "pagina": pag_asig, "posicion": pos_asig, "total": total})


@app.route("/api/albumes/<int:album_id>/mover", methods=["POST"])
def api_mover_en_album(album_id):
    if db.obtener_album_simple(album_id) is None:
        return error_api("Ese álbum no existe.", 404)
    data = request.get_json(silent=True) or {}
    try:
        pag_orig = int(data.get("pagina_origen", 1))
        pos_orig = int(data.get("pos_origen", 0))
        pag_dest = int(data.get("pagina_destino", pag_orig))
        pos_dest = int(data.get("pos_destino", 0))
    except (TypeError, ValueError):
        return error_api("Posiciones de bolsillo no válidas.")
    ok = db.mover_carta_en_album(album_id, pag_orig, pos_orig, pag_dest, pos_dest)
    if not ok:
        return error_api("No había carta en el bolsillo de origen.")
    return jsonify({"ok": True})


@app.route("/api/albumes/<int:album_id>/actualizar_bolsillo", methods=["POST"])
def api_actualizar_bolsillo_album(album_id):
    if db.obtener_album_simple(album_id) is None:
        return error_api("Ese álbum no existe.", 404)
    data = request.get_json(silent=True) or {}
    try:
        pagina = int(data.get("pagina", 1))
        posicion = int(data.get("posicion", 0))
    except (TypeError, ValueError):
        return error_api("Bolsillo no válido.")
    imagen_url = data.get("imagen_url")
    if imagen_url and not str(imagen_url).startswith("https://cards.scryfall.io/"):
        return error_api("La imagen debe pertenecer a Scryfall.")
    acabado_foil = data.get("acabado_foil")
    ok = db.actualizar_bolsillo_album(album_id, pagina, posicion, imagen_url=imagen_url, acabado_foil=acabado_foil)
    if not ok:
        return error_api("Bolsillo vacío.", 404)
    return jsonify({"ok": True})


@app.route("/api/albumes/<int:album_id>/quitar", methods=["POST"])
def api_quitar_de_album(album_id):
    if db.obtener_album_simple(album_id) is None:
        return error_api("Ese álbum no existe.", 404)
    data = request.get_json(silent=True) or {}
    try:
        pagina = int(data.get("pagina", 1))
        posicion = int(data.get("posicion", 0))
    except (TypeError, ValueError):
        return error_api("Bolsillo no válido.")
    total = db.quitar_carta_de_album(album_id, pagina, posicion)
    return jsonify({"ok": True, "total": total})


# ---------- Autenticación: Registro, Login, Cuenta y Google OAuth ----------

PATRON_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _credenciales_google():
    cid = (os.environ.get("GOOGLE_CLIENT_ID") or db.obtener_meta("google_client_id") or "").strip()
    csec = (os.environ.get("GOOGLE_CLIENT_SECRET") or db.obtener_meta("google_client_secret") or "").strip()
    return cid, csec


def _redirect_uri_google():
    uri = url_for("auth_google_callback", _external=True)
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https" or ".onrender.com" in request.host or ".trycloudflare.com" in request.host:
        uri = re.sub(r"^http://", "https://", uri)
    return uri


@app.route("/login", methods=["GET", "POST"])
def login():
    if obtener_usuario_actual():
        return redirect(url_for("cuenta"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        usuario = db.obtener_usuario_por_email(email)

        if usuario is not None and not usuario["password_hash"] and len(password) >= 6:
            # Cuenta creada previamente con Google sin contraseña: le asignamos esta contraseña
            db.actualizar_password_usuario(usuario["id"], generate_password_hash(password))
            usuario = db.obtener_usuario_por_email(email)

        if usuario is None or not usuario["password_hash"] or not check_password_hash(usuario["password_hash"], password):
            flash("Correo electrónico o contraseña incorrectos.")
            return render_template("login.html", email=email), 401

        session.permanent = True
        session["usuario_id"] = usuario["id"]
        flash(f"¡Bienvenido de nuevo, {usuario['nombre']}!")
        return redirect(url_for("home"))

    return render_template("login.html", email="")


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if obtener_usuario_actual():
        return redirect(url_for("cuenta"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmar = request.form.get("confirmar", "")

        if not nombre or len(nombre) > 60:
            flash("Introduce un nombre de usuario válido (máximo 60 caracteres).")
            return render_template("register.html", nombre=nombre, email=email), 400
        if not PATRON_EMAIL.match(email):
            flash("Introduce una dirección de correo electrónico válida.")
            return render_template("register.html", nombre=nombre, email=email), 400
        if len(password) < 6:
            flash("La contraseña debe tener al menos 6 caracteres.")
            return render_template("register.html", nombre=nombre, email=email), 400
        if password != confirmar:
            flash("Las contraseñas no coinciden.")
            return render_template("register.html", nombre=nombre, email=email), 400

        existente = db.obtener_usuario_por_email(email)
        if existente is not None:
            if not existente["password_hash"]:
                db.actualizar_password_usuario(existente["id"], generate_password_hash(password), nombre=nombre)
                session.permanent = True
                session["usuario_id"] = existente["id"]
                flash(f"¡Contraseña configurada y sesión iniciada como {nombre}!")
                return redirect(url_for("home"))
            flash("Ya existe una cuenta con ese correo electrónico. Inicia sesión.")
            return render_template("register.html", nombre=nombre, email=email), 409

        uid = db.crear_usuario(nombre, email, password_hash=generate_password_hash(password))
        session.permanent = True
        session["usuario_id"] = uid
        flash(f"¡Cuenta creada con éxito! Bienvenido, {nombre}.")
        return redirect(url_for("home"))

    return render_template("register.html", nombre="", email="")


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("usuario_id", None)
    flash("Has cerrado sesión correctamente.")
    return redirect(url_for("home"))


@app.route("/cuenta")
def cuenta():
    usuario = obtener_usuario_actual()
    if not usuario:
        flash("Inicia sesión para acceder a tu perfil.")
        return redirect(url_for("login"))
    mazos = db.listar_mazos(usuario["id"])
    return render_template("account.html", usuario=usuario, mazos=mazos)


@app.route("/auth/google")
def auth_google():
    """
    Inicia el flujo OAuth 2.0 real redirigiendo a https://accounts.google.com
    cuando GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET están configurados (por variables
    de entorno o guardados en la base de datos).
    """
    client_id, client_secret = _credenciales_google()
    if not client_id or not client_secret:
        return redirect(url_for("auth_google_demo"))

    estado_oauth = secrets.token_urlsafe(24)
    session.permanent = True
    session["google_oauth_state"] = estado_oauth
    redirect_uri = _redirect_uri_google()

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": estado_oauth,
        "prompt": "select_account",
    })
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@app.route("/auth/google/callback")
def auth_google_callback():
    estado_esperado = session.pop("google_oauth_state", None)
    estado_recibido = request.args.get("state", "")
    codigo = request.args.get("code", "")

    if not codigo or (estado_esperado and not secrets.compare_digest(estado_esperado, estado_recibido)):
        flash("No se pudo verificar la respuesta de Google. Inténtalo de nuevo.")
        return redirect(url_for("login"))

    client_id, client_secret = _credenciales_google()
    redirect_uri = _redirect_uri_google()

    try:
        datos_token = urllib.parse.urlencode({
            "code": codigo,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")

        req_token = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=datos_token,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req_token, timeout=15) as resp:
            token_json = json.loads(resp.read().decode("utf-8"))

        access_token = token_json.get("access_token", "")
        req_perfil = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req_perfil, timeout=15) as resp:
            perfil = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        flash("Error al comunicarse con Google OAuth. Revisa el Client ID, Client Secret y la Redirect URI en Google Cloud.")
        return redirect(url_for("auth_google_demo"))

    google_id = perfil.get("sub")
    email = perfil.get("email")
    nombre = perfil.get("name") or (email.split("@")[0] if email else "Planeswalker")
    avatar = perfil.get("picture")

    if not google_id or not email:
        flash("Tu cuenta de Google no devolvió un correo electrónico válido.")
        return redirect(url_for("login"))

    usuario = db.obtener_o_crear_usuario_google(google_id, email, nombre, avatar)
    session.permanent = True
    session["usuario_id"] = usuario["id"]
    flash(f"¡Sesión iniciada con Google como {usuario['nombre']} ({usuario['email']})!")
    return redirect(url_for("home"))


@app.route("/auth/google/configurar", methods=["POST"])
def auth_google_configurar():
    """Guarda GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en la BD y lanza el redirect real a Google."""
    cid = request.form.get("client_id", "").strip()
    csec = request.form.get("client_secret", "").strip()
    if not cid or not csec:
        flash("Debes introducir tanto el Client ID como el Client Secret de Google Cloud.")
        return redirect(url_for("auth_google_demo"))
    db.guardar_meta("google_client_id", cid)
    db.guardar_meta("google_client_secret", csec)
    flash("Credenciales de Google OAuth guardadas. Redirigiendo a Google...")
    return redirect(url_for("auth_google"))


@app.route("/auth/google/demo", methods=["GET", "POST"])
def auth_google_demo():
    """
    Selector de cuenta de Google y asistente para activar la redirección real
    a accounts.google.com con un clic.
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        if not PATRON_EMAIL.match(email):
            flash("Introduce un correo de Google válido.")
            return redirect(url_for("auth_google_demo"))
        exist = db.obtener_usuario_por_email(email)
        if not nombre:
            nombre = exist["nombre"] if exist else email.split("@")[0].capitalize()
        google_id = f"google-local-{email}"
        usuario = db.obtener_o_crear_usuario_google(google_id, email, nombre)
        if password and len(password) >= 6:
            db.actualizar_password_usuario(usuario["id"], generate_password_hash(password), nombre=nombre)
        session.permanent = True
        session["usuario_id"] = usuario["id"]
        flash(f"¡Sesión iniciada con Google como {usuario['nombre']} ({usuario['email']})!")
        return redirect(url_for("home"))

    redirect_uri_actual = _redirect_uri_google()
    cid_actual, _ = _credenciales_google()
    return render_template("google_demo.html", redirect_uri_actual=redirect_uri_actual, client_id_actual=cid_actual)


# ---------- Endpoints usados por JavaScript (AJAX) ----------
#
# Todos responden JSON con la forma:
#   éxito: {"ok": true, "cantidad": <copias de esa carta>, "total": <cartas del mazo>}
#   error: {"ok": false, "error": "<mensaje>"}  + código HTTP 400 / 404

def error_api(mensaje, codigo=400):
    return jsonify({"ok": False, "error": mensaje}), codigo


def leer_peticion_carta(mazo_id, con_cantidad=True):
    """
    Valida el cuerpo JSON de las peticiones de la API.
    Devuelve (carta_id, cantidad, None) si es correcto, o (None, None, respuesta_error).
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, None, error_api("El cuerpo de la petición debe ser JSON.")

    carta_id = data.get("carta_id")
    if not isinstance(carta_id, str) or not carta_id.strip():
        return None, None, error_api("Falta 'carta_id'.")

    cantidad = 1
    if con_cantidad:
        try:
            cantidad = int(data.get("cantidad", 1))
        except (TypeError, ValueError):
            return None, None, error_api("'cantidad' debe ser un número entero.")
        if not 1 <= cantidad <= db.MAX_COPIAS_POR_CARTA:
            return None, None, error_api(f"'cantidad' debe estar entre 1 y {db.MAX_COPIAS_POR_CARTA}.")

    if db.obtener_mazo_simple(mazo_id) is None:
        return None, None, error_api("Ese mazo no existe.", 404)
    if db.obtener_carta(carta_id) is None:
        return None, None, error_api("Esa carta no existe.", 404)

    return carta_id, cantidad, None


@app.route("/api/mazos/<int:mazo_id>/anadir", methods=["POST"])
def api_anadir_carta(mazo_id):
    carta_id, cantidad, error = leer_peticion_carta(mazo_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    imagen_url = (data.get("imagen_url") or "").strip() or None
    if imagen_url and not imagen_url.startswith("https://cards.scryfall.io/"):
        return error_api("La URL de la imagen debe pertenecer al dominio oficial de Scryfall.")
    nueva_cantidad, total = db.anadir_carta_a_mazo(mazo_id, carta_id, cantidad, imagen_url=imagen_url)
    return jsonify({"ok": True, "cantidad": nueva_cantidad, "total": total})


@app.route("/api/mazos/<int:mazo_id>/restar", methods=["POST"])
def api_restar_carta(mazo_id):
    carta_id, cantidad, error = leer_peticion_carta(mazo_id)
    if error:
        return error
    nueva_cantidad, total = db.restar_carta_de_mazo(mazo_id, carta_id, cantidad)
    return jsonify({"ok": True, "cantidad": nueva_cantidad, "total": total})


@app.route("/api/mazos/<int:mazo_id>/quitar", methods=["POST"])
def api_quitar_carta(mazo_id):
    carta_id, _, error = leer_peticion_carta(mazo_id, con_cantidad=False)
    if error:
        return error
    total = db.quitar_carta_de_mazo(mazo_id, carta_id)
    return jsonify({"ok": True, "cantidad": 0, "total": total})


@app.route("/api/mazos/<int:mazo_id>/comandante", methods=["POST"])
def api_asignar_comandante(mazo_id):
    """Asigna o quita el comandante de un mazo (opcionalmente con su alter oficial)."""
    if db.obtener_mazo_simple(mazo_id) is None:
        return error_api("Ese mazo no existe.", 404)
    data = request.get_json(silent=True) or {}
    carta_id = data.get("carta_id")
    imagen_url = (data.get("imagen_url") or "").strip() or None
    if imagen_url and not imagen_url.startswith("https://cards.scryfall.io/"):
        return error_api("La URL de la imagen debe pertenecer al dominio oficial de Scryfall.")
    if carta_id:
        if not isinstance(carta_id, str) or db.obtener_carta(carta_id) is None:
            return error_api("Esa carta no existe.", 404)
        db.asignar_comandante(mazo_id, carta_id, imagen_url=imagen_url)
    else:
        db.asignar_comandante(mazo_id, None)
    return jsonify({"ok": True})


@app.route("/api/mazos/<int:mazo_id>/imagen_carta", methods=["POST"])
def api_cambiar_imagen_carta_en_mazo(mazo_id):
    """Cambia el arte/alter oficial de una carta específica dentro de un mazo o del comandante."""
    if db.obtener_mazo_simple(mazo_id) is None:
        return error_api("Ese mazo no existe.", 404)
    data = request.get_json(silent=True) or {}
    carta_id = (data.get("carta_id") or "").strip()
    imagen_url = (data.get("imagen_url") or "").strip()
    es_comandante = bool(data.get("es_comandante"))
    if not carta_id or db.obtener_carta(carta_id) is None:
        return error_api("Esa carta no existe.", 404)
    if not imagen_url or not imagen_url.startswith("https://cards.scryfall.io/"):
        return error_api("La URL de la imagen debe pertenecer al dominio oficial de Scryfall.")
    db.actualizar_imagen_carta_en_mazo(mazo_id, carta_id, imagen_url, es_comandante=es_comandante)
    return jsonify({"ok": True, "imagen_url": imagen_url})


# Caché en memoria de alters oficiales por oracle_id para respuestas instantáneas
CACHE_ALTERS_SCRYFALL = {}


def clasificar_estilo_alter(impresion):
    """Clasifica el tipo de alter/edición oficial de Scryfall y su prioridad visual."""
    set_code = (impresion.get("set") or "").lower()
    set_name = (impresion.get("set_name") or "")
    efectos = set(impresion.get("frame_effects") or [])
    borde = (impresion.get("border_color") or "").lower()
    full_art = bool(impresion.get("full_art"))
    promo = bool(impresion.get("promo"))
    frame = str(impresion.get("frame") or "")

    if set_code == "sld" or "secret lair" in set_name.lower():
        return "✨ Secret Lair Alter", 1
    if "showcase" in efectos:
        return "🌟 Showcase / Alter Oficial", 2
    if borde == "borderless" or full_art or "inverted" in efectos:
        return "🖼️ Borderless / Arte Completo", 3
    if "extendedart" in efectos:
        return "📐 Extended Art", 4
    if promo or "promo" in set_name.lower() or "masterpiece" in (impresion.get("set_type") or ""):
        return "🏆 Promo / Edición Especial", 5
    if frame in ("1993", "1997"):
        return "📜 Marco Retro Clásico", 6
    return "🃏 Edición Oficial", 7


@app.route("/api/cartas/<carta_id>/alters")
def api_listar_alters_carta(carta_id):
    """
    Devuelve todas las impresiones, alters oficiales, Secret Lair, Borderless,
    Showcase y Extended Art de una carta en alta resolución (large 672x936 y png 745x1040).
    """
    carta = db.obtener_carta(carta_id)
    if carta is None:
        return error_api("No se encontró esa carta.", 404)

    if carta_id in CACHE_ALTERS_SCRYFALL:
        return jsonify({
            "ok": True,
            "carta_id": carta_id,
            "nombre": carta["nombre"],
            "imagen_actual": carta["imagen_url"],
            "alters": CACHE_ALTERS_SCRYFALL[carta_id],
        })

    url = (
        f"https://api.scryfall.com/cards/search?"
        f"order=released&q=oracleid%3A{urllib.parse.quote(carta_id)}&unique=prints"
    )
    impresiones_brutas = []
    paginas = 0
    while url and paginas < 2:
        paginas += 1
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SusoMTG-Alters/2.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                datos = json.loads(resp.read().decode("utf-8"))
            impresiones_brutas.extend(datos.get("data") or [])
            url = datos.get("next_page") if datos.get("has_more") else None
        except urllib.error.URLError:
            break

    alters = []
    urls_vistas = set()
    for imp in impresiones_brutas:
        uris = imp.get("image_uris")
        if not uris and imp.get("card_faces"):
            uris = (imp["card_faces"][0] or {}).get("image_uris")
        if not uris:
            continue
        img_hd = db.url_imagen_4k(uris.get("png") or uris.get("large") or uris.get("normal"))
        img_png = uris.get("png") or img_hd
        if not img_hd or img_hd in urls_vistas:
            continue
        urls_vistas.add(img_hd)
        etiqueta, prioridad = clasificar_estilo_alter(imp)
        alters.append({
            "scryfall_id": imp.get("id", ""),
            "set_code": (imp.get("set") or "").upper(),
            "set_nombre": imp.get("set_name") or "",
            "collector_number": imp.get("collector_number") or "",
            "artista": imp.get("artist") or "Artista oficial",
            "fecha": (imp.get("released_at") or "")[:4],
            "rareza": imp.get("rarity") or "",
            "etiqueta": etiqueta,
            "prioridad": prioridad,
            "es_alter_especial": prioridad <= 6,
            "imagen_url": img_hd,
            "imagen_png": img_png,
        })

    # Ordenamos poniendo primero los alters especiales (Secret Lair, Showcase, Borderless, etc.)
    alters.sort(key=lambda x: (x["prioridad"], x["set_nombre"]))
    CACHE_ALTERS_SCRYFALL[carta_id] = alters

    return jsonify({
        "ok": True,
        "carta_id": carta_id,
        "nombre": carta["nombre"],
        "imagen_actual": carta["imagen_url"],
        "alters": alters,
    })


@app.route("/api/cartas/<carta_id>/imagen", methods=["POST"])
def api_cambiar_imagen_carta_catalogo(carta_id):
    """Cambia la imagen principal de una carta en el catálogo por el alter oficial elegido."""
    if db.obtener_carta(carta_id) is None:
        return error_api("No se encontró esa carta.", 404)
    data = request.get_json(silent=True) or {}
    imagen_url = (data.get("imagen_url") or "").strip()
    if not imagen_url or not imagen_url.startswith("https://cards.scryfall.io/"):
        return error_api("La URL de la imagen debe pertenecer al dominio oficial de Scryfall.")
    db.actualizar_imagen_carta(carta_id, imagen_url)
    return jsonify({"ok": True, "imagen_url": imagen_url})


@app.route("/api/cartas/sincronizar_spoilers", methods=["POST"])
def api_sincronizar_spoilers():
    """Sincroniza en directo los últimos spoilers y expansiones desde Scryfall."""
    import download_cards as dc
    try:
        actualizadas = dc.sincronizar_spoilers_en_vivo()
    except Exception as exc:
        return error_api(f"No se pudo sincronizar con Scryfall: {exc}", 502)
    return jsonify({"ok": True, "actualizadas": actualizadas})


@app.route("/api/mazos/<int:mazo_id>/formato", methods=["POST"])
def api_cambiar_formato_mazo(mazo_id):
    """Permite cambiar el formato/modo de juego del mazo desde el constructor."""
    if db.obtener_mazo_simple(mazo_id) is None:
        return error_api("Ese mazo no existe.", 404)
    data = request.get_json(silent=True) or {}
    formato_req = (data.get("formato") or "").strip()
    if not formato_req:
        return error_api("Debes indicar un formato válido.")
    reglas = obtener_reglas_formato(formato_req)
    db.actualizar_formato_mazo(mazo_id, reglas["id"])
    return jsonify({"ok": True, "formato": reglas["id"]})


@app.route("/api/mazos/<int:mazo_id>/bracket", methods=["POST"])
def api_cambiar_bracket_mazo(mazo_id):
    """Permite fijar el Bracket objetivo (0 = automático, 1..5 = manual) de un mazo."""
    if db.obtener_mazo_simple(mazo_id) is None:
        return error_api("Ese mazo no existe.", 404)
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get("bracket_objetivo", 0))
    except (TypeError, ValueError):
        return error_api("Valor de Bracket no válido.")
    db.actualizar_bracket_mazo(mazo_id, val)
    return jsonify({"ok": True, "bracket_objetivo": max(0, min(5, val))})


@app.route("/api/cartas/autocompletar")
def api_autocompletar_cartas():
    """Búsqueda rápida JSON para elegir comandante o añadir cartas desde el constructor."""
    q = request.args.get("q", "").strip()
    solo_cmd = request.args.get("comandante") == "1"
    if len(q) < 2:
        return jsonify({"ok": True, "cartas": []})
    filas = db.buscar_cartas_autocompletar(q, solo_comandantes=solo_cmd, limite=10)
    return jsonify({
        "ok": True,
        "cartas": [
            {
                "id": f["id"],
                "nombre": f["nombre"],
                "coste_mana": f["coste_mana"] or "",
                "tipo": f["tipo"] or "",
                "identidad_color": f["identidad_color"] or "",
                "imagen_url": f["imagen_url"] or "",
            }
            for f in filas
        ],
    })


# ---------- Analizador de Combos (Estilo LoopLine + Commander Spellbook) ----------

SPELLBOOK_API_URL = "https://backend.commanderspellbook.com/find-my-combos"
PATRON_LINEA_MAZO = re.compile(r"^\s*(?:(\d+)\s*x?\s+)?(.+?)(?:\s+\([A-Za-z0-9]+\)\s*[\dA-Za-z★]*)?\s*$")
ENCABEZADOS_IGNORADOS = {
    "deck", "commander", "commanders", "sideboard", "maybeboard",
    "companion", "mainboard", "mazo", "comandante", "banquillo"
}


def parsear_lista_texto(texto):
    """
    Convierte una lista de cartas en formato Moxfield / MTG Arena / texto plano
    en una lista de tuplas (nombre_carta, cantidad).
    """
    resultado = []
    for linea in (texto or "").splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("//") or limpia.startswith("#"):
            continue
        if limpia.rstrip(":").lower() in ENCABEZADOS_IGNORADOS:
            continue
        m = PATRON_LINEA_MAZO.match(limpia)
        if not m:
            continue
        cantidad = int(m.group(1) or 1)
        nombre = m.group(2).strip()
        if nombre:
            resultado.append((nombre, max(1, min(cantidad, 99))))
    return resultado


def transformar_combo_spellbook(combo, nombres_en_mazo):
    """Normaliza un combo devuelto por Commander Spellbook para el frontend y el mapa."""
    cartas_combo = []
    for uso in combo.get("uses") or []:
        c = uso.get("card") or {}
        nombre = c.get("name") or ""
        local = db.obtener_carta_por_nombre(nombre)
        img = db.url_imagen_4k(
            (local["imagen_url"] if local and local["imagen_url"] else None)
            or c.get("imageUriFrontLarge")
            or c.get("imageUriFrontNormal")
            or ""
        )
        en_mazo = nombre.lower() in nombres_en_mazo
        if not en_mazo and "//" in nombre:
            primera_cara = nombre.split("//")[0].strip().lower()
            en_mazo = primera_cara in nombres_en_mazo

        cartas_combo.append({
            "nombre": nombre,
            "cantidad": uso.get("quantity", 1),
            "imagen_url": img,
            "tipo": c.get("typeLine") or (local["tipo"] if local else ""),
            "en_mazo": en_mazo,
            "local_id": local["id"] if local else None,
        })

    requisitos = [
        r.strip()
        for r in (combo.get("easyPrerequisites") or "", combo.get("notablePrerequisites") or "")
        if r and r.strip()
    ]
    pasos = [p.strip() for p in (combo.get("description") or "").splitlines() if p.strip()]
    produce = [
        (p.get("feature") or {}).get("name")
        for p in (combo.get("produces") or [])
        if (p.get("feature") or {}).get("name")
    ]

    return {
        "id": str(combo.get("id", "")),
        "identidad": combo.get("identity") or "C",
        "mana_necesario": combo.get("manaNeeded") or "",
        "requisitos": " · ".join(requisitos),
        "pasos": pasos,
        "produce": produce,
        "popularidad": combo.get("popularity") or 0,
        "cartas": cartas_combo,
        "url_spellbook": f"https://commanderspellbook.com/combo/{combo.get('id', '')}",
    }


@app.route("/combos")
def combos():
    mazos = db.listar_mazos(session.get("usuario_id"))
    mazo_seleccionado = request.args.get("mazo_id", type=int)
    if mazo_seleccionado is None and mazos:
        mazo_seleccionado = mazos[0]["id"]
    return render_template("combos.html", mazos=mazos, mazo_seleccionado=mazo_seleccionado)


@app.route("/api/combos/analizar", methods=["POST"])
def api_analizar_combos():
    data = request.get_json(silent=True) or {}
    mazo_id = data.get("mazo_id")
    lista_texto = (data.get("lista_texto") or "").strip()

    pares_cartas = []
    comandantes_lista = []
    nombre_mazo = "Lista personalizada"

    if lista_texto:
        pares_cartas = parsear_lista_texto(lista_texto)
    elif mazo_id:
        try:
            mazo_id = int(mazo_id)
        except (TypeError, ValueError):
            return error_api("Identificador de mazo no válido.")
        mazo, comandante, cartas_mazo = db.obtener_mazo(mazo_id)
        if mazo is None:
            return error_api("No se encontró ese mazo.", 404)
        nombre_mazo = mazo["nombre"]
        pares_cartas = [(c["nombre"], c["cantidad"]) for c in cartas_mazo]
        if comandante:
            comandantes_lista.append({"card": comandante["nombre"], "quantity": 1})
            pares_cartas.append((comandante["nombre"], 1))
    else:
        return error_api("Selecciona un mazo o pega una lista de cartas para analizar.")

    if not pares_cartas:
        return jsonify({
            "ok": True,
            "nombre_mazo": nombre_mazo,
            "total_cartas_analizadas": 0,
            "incluidos": [],
            "sugerencias": [],
        })

    nombres_en_mazo = set()
    for nombre, _ in pares_cartas:
        nombres_en_mazo.add(nombre.lower())
        if "//" in nombre:
            nombres_en_mazo.add(nombre.split("//")[0].strip().lower())

    payload = json.dumps({
        "main": [{"card": nombre, "quantity": cant} for nombre, cant in pares_cartas],
        "commanders": comandantes_lista,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            SPELLBOOK_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "SusoMTG-LoopLine/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            respuesta_sb = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return error_api(f"No se pudo conectar con Commander Spellbook: {exc}", 502)

    resultados = respuesta_sb.get("results") or {}
    brutos_incluidos = resultados.get("included") or []
    brutos_casi = resultados.get("almostIncluded") or []

    incluidos = [transformar_combo_spellbook(c, nombres_en_mazo) for c in brutos_incluidos[:40]]
    sugerencias = [transformar_combo_spellbook(c, nombres_en_mazo) for c in brutos_casi[:30]]

    return jsonify({
        "ok": True,
        "nombre_mazo": nombre_mazo,
        "total_cartas_analizadas": sum(cant for _, cant in pares_cartas),
        "incluidos": incluidos,
        "sugerencias": sugerencias,
    })


# ---------- Páginas de error ----------

@app.errorhandler(404)
def no_encontrado(_error):
    if es_peticion_api():
        return error_api("Recurso no encontrado.", 404)
    return render_template("error.html", codigo=404, mensaje="Esta página no existe."), 404


@app.errorhandler(405)
def metodo_no_permitido(_error):
    if es_peticion_api():
        return error_api("Método no permitido.", 405)
    return render_template("error.html", codigo=405, mensaje="Método no permitido."), 405


@app.errorhandler(500)
def error_interno(_error):
    if es_peticion_api():
        return error_api("Error interno del servidor.", 500)
    return render_template("error.html", codigo=500,
                           mensaje="Algo ha fallado en el servidor. Inténtalo de nuevo."), 500


if __name__ == "__main__":
    # Modo debug solo si se pide explícitamente con FLASK_DEBUG=1
    port = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
application = app
