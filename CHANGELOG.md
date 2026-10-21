# Registro de cambios y mejoras (`CHANGELOG.md`)

Documento detallado de la revisión completa del proyecto (**Versión A: Flask + SQLite** y **Versión B: Estática / GitHub Pages**).

---

## 1. Fallos críticos corregidos

### 1.1 La versión estática entraba siempre en "Modo Offline" al abrirse
- **Archivo afectado:** `index.html` → ahora en `app.js` (`ejecutarBusqueda`)
- **Causa:** Cuando no había filtros, se enviaba `q=order:edhrec` a `https://api.scryfall.com/cards/search`. Scryfall rechaza con **HTTP 400** las consultas que solo contienen directivas de ordenación sin ningún filtro de búsqueda, lo que disparaba el bloque `catch` y activaba siempre el modo offline de 8 cartas.
- **Solución:** Se separa el filtro (`q=game:paper` por defecto) del parámetro de ordenación (`order=edhrec` cuando no hay filtros, `order=name` cuando el usuario busca algo), construyendo la URL con `URLSearchParams`.

### 1.2 Cualquier error de búsqueda en Scryfall se mostraba como "Modo Offline"
- **Archivo afectado:** `app.js` (`ejecutarBusqueda`, `manejarErrorScryfall`)
- **Causa:** Un `throw new Error(...)` ante cualquier código HTTP distinto de 200/404 acababa en el mismo `catch` que los fallos de red.
- **Solución:** Se distingue cada caso:
  - **Fallo de red (`fetch` rechaza la promesa) o error 5xx de Scryfall:** activa el modo offline con las 8 cartas de muestra y muestra un aviso explicativo.
  - **HTTP 400 / 422 (consulta inválida):** muestra el mensaje devuelto por Scryfall (`data.details`) sin activar el modo offline.
  - **HTTP 404:** muestra `0 cartas encontradas`.
  - **HTTP 429 (demasiadas peticiones):** avisa al usuario para que espere unos segundos.
  - **Respuestas con `warnings`:** si Scryfall devuelve advertencias en la consulta, se muestran en el bloque `#aviso-busqueda`.
- **Extra:** Se añadió un `AbortController` (`peticionEnCurso`) para cancelar búsquedas anteriores si el usuario lanza una nueva antes de que termine la previa.

### 1.3 Paginación bloqueada o inmanejable
- **Archivos afectados:** `app.py` (`rango_paginas`), `templates/index.html`, `app.js` (`rangoPaginas`, `renderPaginacion`)
- **Causa:**
  - En la versión Flask se generaban **todos** los enlaces de página (`1` a `~1300`) de golpe en el HTML.
  - En la versión estática había un tope fijo `Math.min(totalPaginas, 10)` que impedía pasar de la página 10 y además calculaba mal `totalPaginasActual` cuando `has_more` era verdadero.
- **Solución:** Ambas versiones usan ahora el mismo algoritmo de ventana (`« 1 … 48 49 [50] 51 52 … 1300 »`), mostrando siempre la primera, la última y ±2 páginas alrededor de la actual, además de botones anterior (`«`) y siguiente (`»`).

### 1.4 Error 500 con parámetros `?pagina=` inválidos en Flask
- **Archivos afectados:** `app.py` (`index`), `database.py` (`buscar_cartas`)
- **Causa:** `int(request.args.get("pagina", 1))` lanzaba `ValueError` (HTTP 500) con `?pagina=abc`, y valores como `?pagina=0` o `?pagina=-3` generaban un `OFFSET` negativo en SQLite.
- **Solución:** Se usa `request.args.get("pagina", 1, type=int)`, se fuerza `pagina = max(1, pagina)` tanto en `app.py` como en `database.py`, y si `pagina > total_paginas` se redirige a la última página disponible. También se valida que `color` sea uno de `W, U, B, R, G, C`.

### 1.5 Endpoints `/api/mazos/...` sin validación ni manejo de errores en el cliente
- **Archivos afectados:** `app.py`, `static/js/api.js`, `templates/card_detail.html`, `templates/deck_builder.html`
- **Causa:**
  - En `app.py`, si el cuerpo no era JSON, faltaba `carta_id`, `cantidad` no era numérica o era negativa, o el mazo/carta no existía (violando la clave foránea), Flask devolvía un error 500 HTML.
  - En las plantillas, `fetch()` hacía `await resp.json()` sin comprobar `resp.ok` ni envolverlo en `try/catch`, fallando en silencio.
- **Solución:**
  - Función `leer_peticion_carta()` en `app.py` que valida el JSON, el `carta_id`, que `cantidad` sea un entero entre `1` y `99`, y que tanto el mazo como la carta existan en la base de datos, devolviendo códigos HTTP `400` o `404` con `{"ok": false, "error": "..."}`.
  - Nuevo módulo `static/js/api.js` con `enviarJSON(url, cuerpo)` que envía el token CSRF, captura fallos de red o respuestas no válidas y lanza un `Error` con el mensaje del servidor.
  - Se añadió además el endpoint `POST /api/mazos/<id>/restar` y los botones `+` y `−` en `deck_builder.html`, actualizando en vivo el contador de copias, el total del mazo y el mensaje de mazo vacío.

### 1.6 Cartas de doble cara incompletas en `download_cards.py`
- **Archivos afectados:** `download_cards.py`, `app.js`
- **Causa:** En Scryfall, las cartas de doble cara (`transform`, `modal_dfc`, `reversible_card`, etc.) guardan `oracle_text`, `mana_cost`, `colors`, `power` y `toughness` dentro de `card_faces` en lugar del nivel superior. `download_cards.py` solo miraba `card_faces` para la imagen, dejando el texto, coste y colores vacíos.
- **Solución:** Nuevas funciones `extraer_oracle_id`, `extraer_coste`, `extraer_texto`, `extraer_colores` y `extraer_poder_resistencia` en `download_cards.py` (y su equivalente en `transformarCartaScryfall` dentro de `app.js`) que recorren `card_faces` cuando los campos no están en el nivel raíz.

### 1.7 Duplicación de cartas al actualizar `mtg_cards.db`
- **Archivos afectados:** `database.py`, `download_cards.py`
- **Causa:** Se usaba el `id` de impresión de Scryfall como clave primaria. En el archivo *Oracle Cards*, la impresión representativa de una carta puede cambiar con el tiempo; al volver a ejecutar `download_cards.py`, `INSERT OR REPLACE` insertaba una fila nueva para la misma carta y además borraba y recreaba la fila cuando coincidía el `id`.
- **Solución:**
  - La clave primaria `cartas.id` pasa a ser el **`oracle_id`** de Scryfall (estable entre todas las impresiones y descargas de una misma carta), guardando el id de impresión en la columna `scryfall_id`.
  - Se usa `INSERT ... ON CONFLICT(id) DO UPDATE` (UPSERT) en lugar de `INSERT OR REPLACE`, de modo que las filas existentes se actualizan sin borrarse y las claves foráneas desde `mazo_cartas` no se rompen.
  - Se añade **migración automática en una única transacción** (`BEGIN` / `COMMIT` / `ROLLBACK`): si `download_cards.py` detecta una base de datos con el esquema antiguo (`PRAGMA user_version < 2`), guarda las cartas de los mazos del usuario por nombre, recrea `cartas` y `mazo_cartas` con el nuevo esquema, inserta las cartas y restaura los mazos.

### 1.8 `download_cards.py` fallaba con `KeyError: 'download_uri'` por cambio en la API de Scryfall
- **Archivo afectado:** `download_cards.py` (`obtener_url_descarga`, `cargar_cartas_de_archivo`)
- **Causa:** Scryfall reemplazó el campo `download_uri` (JSON sin comprimir de ~160 MB) por `jsonl_download_uri` (archivo `.jsonl.gz` comprimido con gzip de ~25 MB, con una carta JSON por línea).
- **Solución:** `obtener_url_descarga()` usa `info.get("jsonl_download_uri") or info.get("download_uri")` y `cargar_cartas_de_archivo()` descomprime automáticamente archivos `.gz` con el módulo estándar `gzip` y lee tanto `.jsonl` (línea por línea) como `.json` clásico. La descarga e importación completa tarda ahora **~6,5 segundos**.

---

## 2. Seguridad

### 2.1 Inyección HTML (XSS) en la versión estática
- **Archivos afectados:** `index.html`, `app.js`
- **Causa:** `renderizarListaMazos()`, `mostrarCartas()` y `verDetalleMazo()` interpolaban datos (`m.nombre`, `m.formato`, `carta.name`, `c.id`...) dentro de `innerHTML` e `onclick="..."`. Un nombre de mazo como `<img src=x onerror=alert(1)>` ejecutaba código JavaScript.
- **Solución:**
  - Se eliminaron todos los usos de `innerHTML` con datos dinámicos y todos los atributos `onclick`/`onsubmit` en línea del HTML.
  - Todos los nodos del DOM se construyen con la función auxiliar `crear(tag, opciones, ...hijos)` que asigna siempre el texto mediante `textContent` y registra los eventos con `addEventListener`.

### 2.2 Protección CSRF, `secret_key` y modo `debug` en Flask
- **Archivos afectados:** `app.py`, `templates/base.html`, `templates/my_decks.html`, `static/js/api.js`
- **Cambios:**
  - `app.secret_key` se lee de la variable de entorno `SECRET_KEY` (con fallback a `secrets.token_hex(32)` para uso local).
  - `debug` ya no está forzado a `True`: solo se activa si `FLASK_DEBUG=1`.
  - Protección CSRF integrada en `app.py` (`comprobar_csrf`) para todas las peticiones `POST`, tanto de formularios (`<input type="hidden" name="csrf_token">`) como de `fetch()` (cabecera `X-CSRFToken`).
  - En las plantillas, los valores inyectados en bloques `<script>` usan el filtro `| tojson`.

---

## 3. Base de datos, calidad de código y experiencia de usuario

- **Ruta absoluta a `mtg_cards.db`:** `database.py` calcula `DB_PATH` con `os.path.dirname(os.path.abspath(__file__))`, por lo que la app encuentra siempre la base de datos aunque se ejecute desde otro directorio.
- **Cierre garantizado de conexiones SQLite:** nuevo gestor de contexto `with conexion() as conn:` en `database.py` que cierra siempre la conexión en un bloque `finally`.
- **Esquema unificado y versionado:** el SQL de creación de tablas vive en un único sitio (`database.ESQUEMA_SQL`) con `PRAGMA user_version = 2`, restricción `UNIQUE (mazo_id, carta_id)` y `CHECK (cantidad > 0)` en `mazo_cartas`, y `ON DELETE CASCADE` al borrar un mazo.
- **Límite de 24 h en `download_cards.py`:** se guarda la fecha de la última descarga en la tabla `meta` y se evita descargar más de una vez al día (salvo que se pase `--forzar`), cumpliendo las normas de Scryfall. Además, la descarga se hace por bloques de 1 MB a un archivo temporal mostrando el progreso en pantalla.
- **Legalidades en la ficha de carta (Flask):** `card_detail.html` muestra ahora el estado de la carta (*Legal*, *No legal*, *Prohibida*, *Restringida*) en Standard, Pioneer, Modern, Legacy, Vintage, Commander, Pauper, Historic y Brawl, aprovechando la columna `legalidades` que antes se descargaba pero no se mostraba.
- **Páginas de error personalizadas:** nueva plantilla `templates/error.html` y manejadores para 404, 405 y 500 en `app.py` (que devuelven JSON si la petición era a `/api/...`).
- **Higiene del repositorio:** creado `.gitignore` para excluir `mtg_cards.db`, `__pycache__/`, entornos virtuales, `.env` y `mtg-wiki.zip`.
