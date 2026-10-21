# Suso Demonic Consultation · MTG Wiki

Wiki de cartas de **Magic: The Gathering** y creador de mazos.
Los datos de las cartas vienen de la API pública de [Scryfall](https://scryfall.com/docs/api).

El proyecto tiene **dos versiones** de la misma web, que comparten diseño y funcionalidad:

| | **A. Versión Flask** (servidor) | **B. Versión estática** (GitHub Pages) |
|---|---|---|
| Lenguajes | Python + SQL (SQLite) + HTML/Jinja + CSS + JS | HTML + CSS + JavaScript |
| Archivos | `app.py`, `database.py`, `download_cards.py`, `templates/`, `static/` | `index.html`, `app.js`, `style.css` |
| De dónde salen las cartas | Base de datos local `mtg_cards.db` (descargada una vez) | Consultas en directo a la API de Scryfall |
| Dónde se guardan los mazos | En la base de datos SQLite | En el `localStorage` del navegador |
| Necesita instalar algo | Python 3 y Flask | Nada (solo un navegador) |
| Funciona sin internet | Sí (cuando ya se han descargado las cartas; las imágenes sí necesitan internet) | Solo con 8 cartas de muestra (modo offline) |
| Se puede publicar en GitHub Pages | No (necesita un servidor Python) | Sí |

> Puedes usar cualquiera de las dos, o las dos. Son independientes: los mazos de una **no** aparecen en la otra.

---

## Índice

1. [Qué puedes hacer](#1-qué-puedes-hacer)
2. [Estructura del proyecto](#2-estructura-del-proyecto)
3. [Versión A (Flask): instalación y uso paso a paso](#3-versión-a-flask-instalación-y-uso-paso-a-paso)
4. [Versión B (estática): uso y publicación paso a paso](#4-versión-b-estática-uso-y-publicación-paso-a-paso)
5. [Cómo buscar cartas](#5-cómo-buscar-cartas)
6. [Referencia técnica](#6-referencia-técnica)
7. [Actualizar desde la versión anterior del proyecto](#7-actualizar-desde-la-versión-anterior-del-proyecto)
8. [Solución de problemas](#8-solución-de-problemas)
9. [Seguridad y puesta en producción](#9-seguridad-y-puesta-en-producción)
10. [Créditos y normas de Scryfall](#10-créditos-y-normas-de-scryfall)

El historial detallado de cambios y correcciones está en [CHANGELOG.md](CHANGELOG.md).

---

## 1. Qué puedes hacer

- Buscar cartas por **nombre o texto**, **tipo** y **color**.
- Ver la **ficha completa** de cada carta: imagen, coste de maná, tipo, poder/resistencia, rareza, edición, texto de reglas.
  Las cartas de **doble cara** muestran el texto de las dos caras.
- Ver la **legalidad** de cada carta en los formatos principales (Standard, Pioneer, Modern, Legacy, Vintage, Commander, Pauper...). *(Solo en la versión Flask.)*
- Crear **mazos** con nombre y formato.
- Añadir cartas a un mazo desde su ficha, **sumar o restar copias** (+ / −) y quitarlas desde la vista del mazo.
- Paginación cómoda: `« 1 … 48 49 [50] 51 52 … 1300 »`.

---

## 2. Estructura del proyecto

```
magic-prueba--main/
│
├── README.md              ← este archivo
├── CHANGELOG.md           ← todos los cambios y correcciones, explicados
├── requirements.txt       ← dependencias de Python (Flask)
├── .gitignore             ← archivos que NO se suben a Git (base de datos, cachés...)
│
│   ── Versión A: Flask ──────────────────────────────────────────────
├── app.py                 ← servidor web: rutas, validación, CSRF, API JSON
├── database.py            ← esquema de la base de datos y todas las consultas SQL
├── download_cards.py      ← descarga las cartas de Scryfall a mtg_cards.db
├── mtg_cards.db           ← base de datos SQLite (se genera; no se sube a Git)
├── templates/             ← plantillas HTML (Jinja2)
│   ├── base.html          ←   esqueleto común: menú, mensajes, pie, token CSRF
│   ├── index.html         ←   buscador + rejilla de cartas + paginación
│   ├── card_detail.html   ←   ficha de una carta + legalidad + añadir a mazo
│   ├── my_decks.html      ←   lista de mazos + crear/eliminar
│   ├── deck_builder.html  ←   contenido de un mazo (+ / − / quitar)
│   └── error.html         ←   página de error (404, 500...)
├── static/
│   ├── css/style.css      ← estilos de la versión Flask
│   └── js/api.js          ← función enviarJSON() para llamar a la API con CSRF
│
│   ── Versión B: estática ───────────────────────────────────────────
├── index.html             ← página única (grimorio, mazos, detalle de mazo, modal)
├── app.js                 ← toda la lógica: búsqueda en Scryfall, mazos, modal...
└── style.css              ← estilos de la versión estática
```

> `mtg-wiki.zip` y `__pycache__/` son archivos sueltos o generados: no se usan y están en `.gitignore`.

---

## 3. Versión A (Flask): instalación y uso paso a paso

Los comandos están pensados para **Windows con PowerShell** (la terminal por defecto de Windows / VS Code).
Si usas macOS o Linux, mira la columna correspondiente cuando haya diferencias.

### Paso 1 · Instalar Python

1. Descarga Python 3.10 o superior desde <https://www.python.org/downloads/>.
2. Al instalar, **marca la casilla "Add python.exe to PATH"** (abajo del todo en la primera pantalla). Es muy importante.
3. Cierra y vuelve a abrir la terminal.
4. Comprueba que funciona:

   ```powershell
   python --version
   ```

   Debe mostrar algo como `Python 3.12.x`.

> **¿Te sale "Python was not found; run without arguments to install from the Microsoft Store"?**
> Es un acceso directo falso de Windows. Instala Python desde python.org (paso 1) y, si sigue saliendo, ve a
> *Configuración → Aplicaciones → Configuración avanzada de aplicaciones → Alias de ejecución de aplicaciones*
> y **desactiva** `python.exe` y `python3.exe` ("Instalador de aplicación").

### Paso 2 · Abrir una terminal en la carpeta del proyecto

```powershell
cd "C:\Users\TU_USUARIO\Desktop\pagina web de magic con varios lenguajes\magic-prueba--main"
```

(En VS Code: *Terminal → Nuevo terminal* ya se abre en la carpeta del proyecto.)

### Paso 3 · Crear y activar un entorno virtual (recomendado)

Un entorno virtual instala Flask solo para este proyecto, sin ensuciar el Python del sistema.

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `python -m venv venv` | `python3 -m venv venv` |
| `.\venv\Scripts\Activate.ps1` | `source venv/bin/activate` |

Si se activa bien, verás `(venv)` al principio de la línea de la terminal.

> **¿Error "la ejecución de scripts está deshabilitada en este sistema"?** Ejecuta una sola vez:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> y vuelve a activar el entorno.

### Paso 4 · Instalar las dependencias

```powershell
pip install -r requirements.txt
```

Esto instala **Flask** (versión 3.x).

### Paso 5 · Descargar las cartas (solo la primera vez)

```powershell
python download_cards.py
```

Qué hace:

1. Pregunta a Scryfall dónde está el archivo más reciente de *Oracle Cards* (una entrada por carta única).
2. Lo descarga mostrando el progreso (son más de 100 MB; tarda de unos segundos a pocos minutos según tu conexión).
3. Crea `mtg_cards.db` con las tablas necesarias y guarda unas 30.000 cartas.
4. Apunta la fecha de la descarga.

Salida esperada (aproximada):

```
Descargando cartas desde https://data.scryfall.io/oracle-cards/... ...
   160.2 / 160.2 MB
Descargadas 3xxxx cartas.
Insertadas/actualizadas 3xxxx cartas en la base de datos.
Listo en 45.3 segundos. Base de datos: C:\...\magic-prueba--main\mtg_cards.db
```

> **Límite de una descarga al día.** Scryfall pide no descargar el *bulk data* más de una vez al día.
> Si vuelves a ejecutar el script antes de 24 horas, te avisará y no descargará nada.
> Si de verdad lo necesitas: `python download_cards.py --forzar`

### Paso 6 · (Opcional) Configurar variables de entorno

| Variable | Para qué sirve | Valor por defecto |
|---|---|---|
| `SECRET_KEY` | Firma las cookies de sesión (y el token CSRF). | Una clave aleatoria nueva en cada arranque. |
| `FLASK_DEBUG` | `1` = modo depuración: recarga automática al guardar archivos y errores detallados. | Desactivado. |

Si **no** defines `SECRET_KEY`, todo funciona, pero cada vez que reinicies el servidor la sesión se invalida
y el primer formulario que envíes mostrará *"La sesión ha caducado..."* (basta con repetirlo).
Para evitarlo, genera una clave y defínela:

| Windows (PowerShell) | macOS / Linux |
|---|---|
| `python -c "import secrets; print(secrets.token_hex(32))"` | igual con `python3` |
| `$env:SECRET_KEY = "pega-aquí-la-clave"` | `export SECRET_KEY="pega-aquí-la-clave"` |
| `$env:FLASK_DEBUG = "1"` | `export FLASK_DEBUG=1` |

> Estas variables solo duran mientras esa terminal esté abierta. Tendrás que definirlas de nuevo cada vez que abras otra terminal.

### Paso 7 · Arrancar el servidor

```powershell
python app.py
```

Verás algo como:

```
 * Running on http://127.0.0.1:5000
```

Abre **<http://127.0.0.1:5000>** en el navegador.

Para pararlo: pulsa `Ctrl + C` en la terminal. Para salir del entorno virtual: `deactivate`.

### Paso 8 · Usar la web

1. **Cartas** (portada): escribe un nombre o texto, elige color y/o tipo y pulsa *Buscar*. *Limpiar* quita los filtros.
2. Haz clic en una carta para ver su **ficha** y su **legalidad** en cada formato.
3. Ve a **Mis mazos**, escribe un nombre (y opcionalmente un formato) y pulsa *Crear mazo*.
4. Vuelve a la ficha de una carta, elige el mazo, la cantidad y pulsa *Añadir*.
5. En la vista del mazo puedes usar **+** (añadir una copia), **−** (quitar una copia) y **Quitar** (eliminar todas las copias).
   El total de cartas se actualiza al momento.
6. Desde *Mis mazos* puedes **eliminar** un mazo entero (pide confirmación).

### Paso 9 · Actualizar las cartas más adelante

Cuando salgan cartas nuevas, vuelve a ejecutar:

```powershell
python download_cards.py
```

**Tus mazos se conservan**: las cartas se identifican por su `oracle_id`, que no cambia entre descargas;
los datos de cada carta se actualizan sin borrar la fila.

### Resumen rápido (cuando ya está todo instalado)

```powershell
cd "ruta\a\magic-prueba--main"
.\venv\Scripts\Activate.ps1
python app.py
```

---

## 4. Versión B (estática): uso y publicación paso a paso

### Opción 1 · Abrirla directamente

Haz doble clic en `index.html`. Se abre en el navegador y funciona: busca en Scryfall y guarda los mazos en el navegador.

### Opción 2 · Con un servidor local (recomendado)

Algunos navegadores limitan ciertas funciones en páginas abiertas como `file://`. Con un servidor local te evitas problemas:

```powershell
cd "ruta\a\magic-prueba--main"
python -m http.server 8000
```

Abre <http://localhost:8000> (sirve `index.html` automáticamente). Para parar: `Ctrl + C`.

> Alternativa sin Python: la extensión **Live Server** de VS Code (clic derecho en `index.html` → *Open with Live Server*).

### Opción 3 · Publicarla en GitHub Pages

1. Sube el proyecto a un repositorio de GitHub (gracias a `.gitignore`, `mtg_cards.db` **no** se sube).
2. En el repositorio: **Settings → Pages**.
3. En *Build and deployment → Source* elige **Deploy from a branch**.
4. En *Branch* elige `main` y la carpeta `/ (root)`. Pulsa **Save**.
5. Espera 1–2 minutos. La web estará en `https://TU_USUARIO.github.io/NOMBRE_DEL_REPO/`.

> **Si `mtg_cards.db` ya se había subido antes a Git**, `.gitignore` no lo borra del repositorio por sí solo. Ejecuta:
> ```powershell
> git rm --cached mtg_cards.db
> git rm -r --cached __pycache__
> git commit -m "Dejar de versionar la base de datos y cachés"
> git push
> ```
> (El archivo sigue en tu ordenador; solo deja de estar en el repositorio.)

### Cómo funciona por dentro

- **Al abrir la página** se muestran las cartas más populares (consulta `game:paper` ordenada por EDHREC).
- **Al buscar**, `app.js` traduce los filtros a la sintaxis de Scryfall y llama a `https://api.scryfall.com/cards/search`.
  Scryfall devuelve **175 cartas por página**.
- Si escribes rápido y lanzas varias búsquedas, la anterior se **cancela** (`AbortController`), así que nunca aparece un resultado antiguo.
- **Errores**:
  - *Sin conexión* o *Scryfall caído (5xx)* → **modo offline** con 8 cartas de muestra y un aviso.
  - *Búsqueda mal escrita (400/422)* → aviso con la explicación de Scryfall (no entra en modo offline).
  - *Demasiadas peticiones (429)* → aviso para esperar unos segundos.
  - *Sin resultados (404)* → "0 cartas encontradas".
- **Mazos**: se guardan en `localStorage` con la clave `suso_mtg_mazos_v1`. Son **propios de cada navegador y dispositivo**:
  si borras los datos del navegador, se pierden. La primera vez se crea un "Mazo de Prueba".
- El modal de una carta se cierra con la **X**, haciendo **clic fuera** o con la tecla **Escape**.
  Las cartas se pueden abrir también con el teclado (**Tab** + **Enter**).

---

## 5. Cómo buscar cartas

> Las cartas están en **inglés** (es el idioma de los datos de Scryfall). Busca por nombre y tipo en inglés:
> *Creature*, *Instant*, *Sorcery*, *Artifact*, *Enchantment*, *Land*, *Planeswalker*, *Legendary*...

| Campo | Versión Flask | Versión estática |
|---|---|---|
| Nombre o texto | Busca el texto dentro del nombre **o** del texto de reglas. | Se envía tal cual a Scryfall: admite su [sintaxis avanzada](https://scryfall.com/docs/syntax) (p. ej. `o:draw pow>=3`). |
| Tipo | Busca el texto dentro de la línea de tipo. | Cada palabra se convierte en `t:palabra` (p. ej. `legendary creature` → `t:legendary t:creature`). |
| Color | Cartas que **contienen** ese color (las multicolor también salen). *Incoloro* = sin color. | Igual: `c>=w`, etc. *Incoloro* = `c=c`. |

En la rejilla, el **borde izquierdo** de cada carta indica su color: blanco, azul, negro, rojo, verde,
**dorado** = multicolor, **gris** = incolora.

---

## 6. Referencia técnica

### 6.1 Base de datos (`mtg_cards.db`)

El esquema está definido en [database.py](database.py) (`ESQUEMA_SQL`) y su versión se guarda en `PRAGMA user_version` (actualmente **2**).

**`cartas`**

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | TEXT, PK | `oracle_id` de Scryfall: identifica la carta, **no cambia** entre descargas. |
| `scryfall_id` | TEXT | Id de la impresión concreta usada para la imagen y la edición. |
| `nombre`, `coste_mana`, `cmc`, `tipo`, `texto` | | Datos básicos. En cartas de doble cara: costes unidos con ` // ` y textos de ambas caras. |
| `poder`, `resistencia` | TEXT | Texto porque pueden ser `*`, `1+*`, etc. |
| `colores`, `identidad_color` | TEXT | Letras en orden WUBRG separadas por comas: `"W,U"`. Vacío = incolora. |
| `rareza`, `set_code`, `set_nombre`, `imagen_url` | TEXT | |
| `legalidades` | TEXT | JSON: `{"standard": "legal", "modern": "banned", ...}` |

**`mazos`**: `id` (autoincremental), `nombre`, `formato`, `creado_en`.

**`mazo_cartas`**: `mazo_id` → `mazos.id` (**ON DELETE CASCADE**: al borrar un mazo se borran sus cartas),
`carta_id` → `cartas.id`, `cantidad` (`CHECK cantidad > 0`), y **`UNIQUE(mazo_id, carta_id)`**
(una carta aparece una sola vez por mazo; las copias van en `cantidad`, máximo 99).

**`meta`**: pares clave/valor. Guarda `ultima_descarga` (fecha ISO en UTC).

### 6.2 Rutas web (versión Flask)

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/?q=&tipo=&color=&pagina=` | Buscador. `pagina` inválida → 1; mayor que la última → redirige a la última. |
| GET | `/carta/<id>` | Ficha de la carta. |
| GET | `/mazos` | Lista de mazos con su número de cartas. |
| POST | `/mazos/nuevo` | Crea un mazo (`nombre` ≤ 100 caracteres, `formato` ≤ 50). |
| GET | `/mazos/<id>` | Constructor del mazo. |
| POST | `/mazos/<id>/eliminar` | Elimina el mazo. |

### 6.3 API JSON (versión Flask)

Todas son `POST`, reciben JSON y requieren la cabecera `X-CSRFToken` (ver 6.4).

| Ruta | Cuerpo | Efecto |
|---|---|---|
| `/api/mazos/<id>/anadir` | `{"carta_id": "...", "cantidad": 1}` | Suma copias (1–99; el total por carta se limita a 99). |
| `/api/mazos/<id>/restar` | `{"carta_id": "...", "cantidad": 1}` | Resta copias; si llega a 0, la carta sale del mazo. |
| `/api/mazos/<id>/quitar` | `{"carta_id": "..."}` | Quita todas las copias de la carta. |

Respuestas:

```json
{"ok": true,  "cantidad": 3, "total": 42}
{"ok": false, "error": "Esa carta no existe."}
```

`cantidad` = copias de esa carta que quedan en el mazo; `total` = cartas totales del mazo.

| Código | Cuándo |
|---|---|
| 200 | Correcto. |
| 400 | JSON inválido, falta `carta_id`, `cantidad` no es un entero entre 1 y 99, o token CSRF incorrecto. |
| 404 | El mazo o la carta no existen. |
| 503 | La base de datos no está lista (hay que ejecutar `download_cards.py`). |

### 6.4 Protección CSRF

Evita que otra página web pueda enviar formularios a tu servidor en tu nombre (por ejemplo, borrar tus mazos).
Está implementada en [app.py](app.py) sin librerías extra:

1. Cada sesión recibe un token aleatorio (`session["csrf_token"]`).
2. Los formularios llevan `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`.
3. `base.html` incluye `<meta name="csrf-token">` y [static/js/api.js](static/js/api.js) lo envía en la cabecera `X-CSRFToken` en cada `fetch()`.
4. Antes de procesar cualquier `POST`, `comprobar_csrf()` compara el token con `secrets.compare_digest`. Si no coincide → error 400 (API) o mensaje + redirección (formularios).

### 6.5 Paginación

Las dos versiones usan el mismo algoritmo (`rango_paginas()` en Python, `rangoPaginas()` en JS):
se muestran la primera y la última página, 2 páginas a cada lado de la actual, y `…` en los huecos, además de `«` y `»`.

---

## 7. Actualizar desde la versión anterior del proyecto

Si ya tenías un `mtg_cards.db` creado con la versión anterior del script (la clave de las cartas era el id de la impresión):

1. La web mostrará el aviso *"La base de datos usa un formato antiguo..."* y solo dejará ver la portada.
2. Ejecuta `python download_cards.py` (si hace falta, con `--forzar`).
3. El script detecta el esquema antiguo y:
   - guarda las cartas de tus mazos **por nombre**,
   - recrea las tablas `cartas` y `mazo_cartas` con el esquema nuevo (la tabla `mazos` no se toca),
   - inserta las cartas nuevas y vuelve a meter las de tus mazos buscándolas por nombre.
4. Todo se hace en **una sola transacción**: si algo falla a mitad, se deshace y tu base de datos queda como estaba.
5. Si alguna carta no se encuentra por nombre, el script la lista al final.

> Consejo: antes de migrar, haz una copia de `mtg_cards.db` (por ejemplo `mtg_cards.backup.db`).

---

## 8. Solución de problemas

| Problema | Solución |
|---|---|
| `Python was not found...` | Ver [Paso 1](#paso-1--instalar-python): instala Python desde python.org y desactiva los alias de la Microsoft Store. |
| `la ejecución de scripts está deshabilitada` al activar el venv | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError: No module named 'flask'` | No has activado el entorno virtual o no has hecho `pip install -r requirements.txt`. |
| La web dice *"Todavía no hay base de datos de cartas"* | Ejecuta `python download_cards.py`. |
| La web dice *"La base de datos usa un formato antiguo"* | Ver [sección 7](#7-actualizar-desde-la-versión-anterior-del-proyecto). |
| `download_cards.py` dice que la última descarga fue hace menos de 24 h | Es intencionado (norma de Scryfall). Usa `--forzar` si lo necesitas. |
| `Error al descargar las cartas de Scryfall` | Revisa tu conexión a internet o espera un poco: puede que Scryfall esté en mantenimiento. |
| *"La sesión ha caducado o el formulario no es válido"* | Has reiniciado el servidor sin `SECRET_KEY` fija. Repite la acción, o define `SECRET_KEY` ([Paso 6](#paso-6--opcional-configurar-variables-de-entorno)). |
| `Address already in use` / el puerto 5000 está ocupado | Cierra el otro servidor, o cambia la última línea de `app.py` a `app.run(port=5001, ...)`. |
| Búsqueda por tipo "Criatura" no encuentra nada | Los datos están en inglés: usa *Creature*. |
| Versión estática siempre en "Modo Offline" | No hay conexión con `api.scryfall.com` (red, cortafuegos, bloqueador de anuncios). Mira la consola del navegador (F12). |
| Versión estática: han desaparecido mis mazos | Se guardan en el navegador. Se pierden si borras los datos de navegación o usas otro navegador/dispositivo/modo incógnito. |
| Las imágenes no cargan | Las imágenes siempre se cargan desde los servidores de Scryfall: necesitan internet. |

---

## 9. Seguridad y puesta en producción

`python app.py` usa el servidor de desarrollo de Flask: perfecto para tu ordenador, **no** para publicar en internet.
Si algún día quieres publicar la versión Flask:

- Define siempre una `SECRET_KEY` fija y secreta (nunca la subas a Git).
- **No** actives `FLASK_DEBUG=1` (permitiría ejecutar código desde el navegador si hay un error).
- Usa un servidor WSGI. En Windows, por ejemplo:
  ```powershell
  pip install waitress
  waitress-serve --port=8000 app:app
  ```
  En Linux: `pip install gunicorn` y `gunicorn -w 2 -b 0.0.0.0:8000 app:app`.
- La app **no tiene usuarios ni contraseñas**: cualquiera que acceda puede ver, crear y borrar mazos.
  Para un uso público habría que añadir autenticación.

Medidas que ya incluye el código:

- Todas las consultas SQL usan **parámetros** (`?`): no hay inyección SQL.
- Las plantillas Jinja **escapan** el HTML automáticamente y los valores que pasan a JavaScript usan `|tojson`.
- En la versión estática no se usa `innerHTML` con datos del usuario ni de la API: todo se crea con `textContent`.
- Protección **CSRF** en todos los `POST`.
- Validación de todos los datos que llegan a la API (tipos, rangos, existencia del mazo y de la carta).

---

## 10. Créditos y normas de Scryfall

- Datos e imágenes de cartas: [Scryfall](https://scryfall.com). Este proyecto respeta sus normas:
  - El *bulk data* se descarga **como mucho una vez al día** (lo controla `download_cards.py`).
  - Las peticiones del script incluyen `User-Agent` y `Accept`, como pide su API.
  - La versión estática solo hace una petición por cada búsqueda o cambio de página del usuario.
  - Las imágenes se muestran desde los servidores de Scryfall, sin modificarlas.
- *Magic: The Gathering* y todo su contenido son propiedad de **Wizards of the Coast**.
  Este es un proyecto personal y educativo sin ánimo de lucro, no afiliado a Wizards of the Coast ni a Scryfall.
