/*
 * app.js — Versión estática (GitHub Pages) de Suso Demonic Consultation.
 *
 * - Busca cartas directamente en la API pública de Scryfall.
 * - Guarda los mazos en el localStorage del navegador.
 * - Si no hay conexión, usa unas cartas de muestra (modo offline).
 *
 * Reglas de seguridad que sigue este archivo:
 *   Nunca se mete texto que venga del usuario o de la API con innerHTML.
 *   Todo se construye con document.createElement + textContent (función crear()).
 */

'use strict';

// ================= CONSTANTES =================
const DECK_STORAGE_KEY = 'suso_mtg_mazos_v1';
const SCRYFALL_SEARCH_URL = 'https://api.scryfall.com/cards/search';
const CARTAS_POR_PAGINA_SCRYFALL = 175;   // tamaño fijo de página de Scryfall
const PAGINAS_ALREDEDOR = 2;              // páginas visibles a cada lado de la actual
const CONSULTA_POR_DEFECTO = 'game:paper'; // filtro real: Scryfall rechaza (400) consultas solo con "order:"
const MAX_COPIAS_POR_CARTA = 99;
const SEPARADOR_CARAS = '\n—————\n';
const ORDEN_COLORES = ['W', 'U', 'B', 'R', 'G'];

// ================= ESTADO =================
let cartaSeleccionadaActual = null;
let idMazoAbiertoActual = null;
let paginaActual = 1;
let peticionEnCurso = null;   // AbortController de la búsqueda activa
let temporizadorToast = null;

// Datos de cartas de demostración (Fallback por si falla la API o está sin conexión)
const SAMPLE_CARDS = [
    {
        id: 'demonic-consultation',
        name: 'Demonic Consultation',
        mana_cost: '{B}',
        type_line: 'Instant',
        oracle_text: 'Choose a card name. Exile the top six cards of your library, then reveal cards from the top of your library until you reveal a card with the chosen name. Put that card into your hand and exile all other cards revealed this way.',
        colors: ['B'],
        rarity: 'rare',
        set_name: 'Ice Age',
        image_url: 'https://cards.scryfall.io/normal/front/1/d/1d779f19-3068-4976-b96b-8f93d156900b.jpg'
    },
    {
        id: 'black-lotus',
        name: 'Black Lotus',
        mana_cost: '{0}',
        type_line: 'Artifact',
        oracle_text: '{T}, Sacrifice Black Lotus: Add three mana of any one color.',
        colors: [],
        rarity: 'rare',
        set_name: 'Alpha',
        image_url: 'https://cards.scryfall.io/normal/front/b/d/bd8fa327-dd41-4737-8f19-2cf5eb1f7cdd.jpg'
    },
    {
        id: 'sol-ring',
        name: 'Sol Ring',
        mana_cost: '{1}',
        type_line: 'Artifact',
        oracle_text: '{T}: Add {C}{C}.',
        colors: [],
        rarity: 'uncommon',
        set_name: 'Commander 2021',
        image_url: 'https://cards.scryfall.io/normal/front/4/c/4cbc508b-66d5-40b5-9610-8260c6d70ebc.jpg'
    },
    {
        id: 'counterspell',
        name: 'Counterspell',
        mana_cost: '{U}{U}',
        type_line: 'Instant',
        oracle_text: 'Counter target spell.',
        colors: ['U'],
        rarity: 'uncommon',
        set_name: 'Seventh Edition',
        image_url: 'https://cards.scryfall.io/normal/front/1/9/1920dae4-fb92-4f19-ae4b-eb3276b8edce.jpg'
    },
    {
        id: 'lightning-bolt',
        name: 'Lightning Bolt',
        mana_cost: '{R}',
        type_line: 'Instant',
        oracle_text: 'Lightning Bolt deals 3 damage to any target.',
        colors: ['R'],
        rarity: 'common',
        set_name: 'Magic 2011',
        image_url: 'https://cards.scryfall.io/normal/front/f/2/f29ba16f-c8fb-42fe-aabf-87089cb214a7.jpg'
    },
    {
        id: 'birds-of-paradise',
        name: 'Birds of Paradise',
        mana_cost: '{G}',
        type_line: 'Creature — Bird',
        oracle_text: 'Flying\n{T}: Add one mana of any color.',
        power: '0',
        toughness: '1',
        colors: ['G'],
        rarity: 'rare',
        set_name: 'Ravnica: City of Guilds',
        image_url: 'https://cards.scryfall.io/normal/front/f/e/fe469f6b-4595-4ede-b9b5-c740df4bd5d9.jpg'
    },
    {
        id: 'swords-to-plowshares',
        name: 'Swords to Plowshares',
        mana_cost: '{W}',
        type_line: 'Instant',
        oracle_text: 'Exile target creature. Its controller gains life equal to its power.',
        colors: ['W'],
        rarity: 'uncommon',
        set_name: 'Ice Age',
        image_url: 'https://cards.scryfall.io/normal/front/6/d/6d9634e4-080b-4497-b352-78d123e4299b.jpg'
    },
    {
        id: 'dark-ritual',
        name: 'Dark Ritual',
        mana_cost: '{B}',
        type_line: 'Instant',
        oracle_text: 'Add {B}{B}{B}.',
        colors: ['B'],
        rarity: 'common',
        set_name: 'Mercadian Masques',
        image_url: 'https://cards.scryfall.io/normal/front/9/5/95f27eeb-6f14-4db3-adb9-9be5ed76b34b.jpg'
    }
];

// ================= UTILIDADES DOM =================

/** Atajo para document.getElementById */
function $(id) {
    return document.getElementById(id);
}

/**
 * Crea un elemento de forma segura.
 *   crear('div', { className: 'x', text: 'hola', attrs: { 'aria-label': '...' }, onClick: fn }, hijo1, hijo2)
 * El texto SIEMPRE se asigna con textContent (nunca se interpreta como HTML).
 */
function crear(tag, opciones = {}, ...hijos) {
    const el = document.createElement(tag);
    if (opciones.className) el.className = opciones.className;
    if (opciones.text !== undefined) el.textContent = opciones.text;
    if (opciones.attrs) {
        for (const [clave, valor] of Object.entries(opciones.attrs)) {
            el.setAttribute(clave, valor);
        }
    }
    if (opciones.onClick) el.addEventListener('click', opciones.onClick);
    for (const hijo of hijos) {
        if (hijo) el.appendChild(hijo);
    }
    return el;
}

function mensajeVacio(texto) {
    return crear('p', { className: 'mensaje-vacio', text: texto });
}

// ================= ALMACENAMIENTO LOCAL (MAZOS) =================

/** Comprueba que un mazo leído de localStorage tiene la forma esperada. */
function esMazoValido(m) {
    return m && typeof m === 'object'
        && typeof m.id === 'number'
        && typeof m.nombre === 'string'
        && (m.cartas === undefined || (typeof m.cartas === 'object' && m.cartas !== null));
}

function obtenerMazosGuardados() {
    try {
        const raw = localStorage.getItem(DECK_STORAGE_KEY);
        if (!raw) {
            // Mazo inicial por defecto si es la primera vez
            const mazoInicial = [{
                id: 1,
                nombre: 'Mazo de Prueba',
                formato: 'Commander',
                creado_en: new Date().toLocaleDateString(),
                cartas: {}
            }];
            localStorage.setItem(DECK_STORAGE_KEY, JSON.stringify(mazoInicial));
            return mazoInicial;
        }
        const datos = JSON.parse(raw);
        if (!Array.isArray(datos)) return [];
        // Descartamos entradas corruptas en lugar de romper toda la app
        return datos.filter(esMazoValido).map(m => ({
            ...m,
            formato: typeof m.formato === 'string' ? m.formato : '',
            cartas: m.cartas || {}
        }));
    } catch (e) {
        console.error('Error al leer mazos:', e);
        return [];
    }
}

function guardarMazos(mazos) {
    try {
        localStorage.setItem(DECK_STORAGE_KEY, JSON.stringify(mazos));
    } catch (e) {
        console.error('Error al guardar mazos:', e);
        mostrarToast('No se pudieron guardar los mazos (¿almacenamiento lleno?)');
    }
    actualizarBadgeMazos();
}

function contarCartas(mazo) {
    return Object.values(mazo.cartas || {}).reduce((suma, item) => suma + (item.cantidad || 0), 0);
}

function actualizarBadgeMazos() {
    $('badge-total-mazos').textContent = obtenerMazosGuardados().length;
}

// ================= NAVEGACIÓN Y VISTAS =================
function navegarA(vistaId) {
    document.querySelectorAll('.seccion').forEach(sec => sec.classList.add('hidden'));
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.remove('active'));

    if (vistaId === 'grimorio') {
        $('seccion-grimorio').classList.remove('hidden');
        $('nav-btn-grimorio').classList.add('active');
    } else if (vistaId === 'mazos') {
        $('seccion-mazos').classList.remove('hidden');
        $('nav-btn-mazos').classList.add('active');
        renderizarListaMazos();
    } else if (vistaId === 'detalle-mazo') {
        $('seccion-detalle-mazo').classList.remove('hidden');
        $('nav-btn-mazos').classList.add('active');
    }
}

// ================= BÚSQUEDA Y SCRYFALL API =================

/** Construye la consulta en la sintaxis de Scryfall a partir de los filtros. */
function construirConsulta(q, tipo, color) {
    const partes = [];
    if (q) partes.push(q);
    if (tipo) {
        // "legendary creature" -> "t:legendary t:creature" (cada palabra debe estar en el tipo)
        tipo.split(/\s+/).filter(Boolean).forEach(palabra => partes.push(`t:${palabra}`));
    }
    if (color) {
        // c=C -> incolora; c>=X -> contiene el color X (igual que el filtro de la versión Flask)
        partes.push(color === 'C' ? 'c=c' : `c>=${color.toLowerCase()}`);
    }
    return partes.join(' ');
}

function mostrarAviso(texto) {
    const aviso = $('aviso-busqueda');
    if (texto) {
        aviso.textContent = texto;
        aviso.classList.remove('hidden');
    } else {
        aviso.textContent = '';
        aviso.classList.add('hidden');
    }
}

async function ejecutarBusqueda(pagina = 1) {
    paginaActual = pagina;
    const q = $('input-q').value.trim();
    const color = $('select-color').value;
    const tipo = $('input-tipo').value.trim();

    const spinner = $('loading-spinner');
    const txtResults = $('txt-resultados-count');
    const txtPagina = $('txt-pagina-info');

    // Si había una búsqueda anterior sin terminar, la cancelamos: así una
    // respuesta lenta y antigua nunca sobrescribe una más reciente.
    if (peticionEnCurso) peticionEnCurso.abort();
    const controlador = new AbortController();
    peticionEnCurso = controlador;

    $('grid-cartas').replaceChildren();
    $('paginacion').replaceChildren();
    mostrarAviso('');
    spinner.classList.remove('hidden');
    txtResults.textContent = 'Buscando en Scryfall...';
    txtPagina.textContent = '';

    const consultaUsuario = construirConsulta(q, tipo, color);
    const params = new URLSearchParams({
        q: consultaUsuario || CONSULTA_POR_DEFECTO,
        // Sin filtros: cartas más populares primero. Con filtros: orden alfabético.
        order: consultaUsuario ? 'name' : 'edhrec',
        page: String(pagina)
    });

    let resp;
    try {
        resp = await fetch(`${SCRYFALL_SEARCH_URL}?${params}`, {
            signal: controlador.signal,
            headers: { 'Accept': 'application/json' }
        });
    } catch (err) {
        if (err.name === 'AbortError') return; // la cancelamos nosotros: no hacer nada
        // Error de RED (sin conexión, DNS, CORS...): modo offline
        console.warn('Sin conexión con Scryfall, cargando cartas de muestra:', err);
        spinner.classList.add('hidden');
        mostrarModoOffline(q, tipo, color, 'No hay conexión con Scryfall. Mostrando cartas de muestra (modo offline).');
        return;
    }

    let data = null;
    try {
        data = await resp.json();
    } catch (e) {
        // respuesta sin JSON
    }
    if (controlador.signal.aborted) return;
    spinner.classList.add('hidden');
    peticionEnCurso = null;

    if (!resp.ok || !data) {
        // !data: Scryfall respondió algo que no es JSON -> lo tratamos como error de servidor
        manejarErrorScryfall(resp.ok ? 502 : resp.status, data, q, tipo, color);
        return;
    }

    const totalCartas = data.total_cards || 0;
    const totalPaginas = Math.max(1, Math.ceil(totalCartas / CARTAS_POR_PAGINA_SCRYFALL));

    txtResults.textContent = `${totalCartas} carta(s) encontrada(s)`;
    txtPagina.textContent = totalPaginas > 1 ? `Página ${pagina} de ${totalPaginas}` : '';

    if (Array.isArray(data.warnings) && data.warnings.length) {
        mostrarAviso(`Aviso de Scryfall: ${data.warnings.join(' ')}`);
    }

    mostrarCartas((data.data || []).map(transformarCartaScryfall));
    renderPaginacion(totalPaginas, pagina);
}

/** Decide qué hacer según el código de error HTTP de Scryfall. */
function manejarErrorScryfall(status, data, q, tipo, color) {
    const txtResults = $('txt-resultados-count');
    const detalle = data && data.details ? data.details : '';

    if (status === 404) {
        // Scryfall responde 404 cuando la búsqueda es válida pero no hay resultados
        txtResults.textContent = '0 cartas encontradas.';
        mostrarCartas([]);
    } else if (status === 400 || status === 422) {
        // Búsqueda mal escrita: NO es un problema de conexión
        txtResults.textContent = 'Búsqueda no válida.';
        mostrarAviso(`Scryfall no entiende la búsqueda. ${detalle}`);
        mostrarCartas([]);
    } else if (status === 429) {
        txtResults.textContent = 'Demasiadas peticiones.';
        mostrarAviso('Has hecho demasiadas búsquedas seguidas. Espera unos segundos y vuelve a intentarlo.');
    } else {
        // 5xx u otros: Scryfall no está disponible -> modo offline
        mostrarModoOffline(q, tipo, color, `Scryfall no está disponible (error ${status}). Mostrando cartas de muestra (modo offline).`);
    }
}

function mostrarModoOffline(q, tipo, color, motivo) {
    const qMin = q.toLowerCase();
    const tipoMin = tipo.toLowerCase();
    const filtradas = SAMPLE_CARDS.filter(c => {
        if (q && !(c.name.toLowerCase().includes(qMin) || c.oracle_text.toLowerCase().includes(qMin))) return false;
        if (tipo && !c.type_line.toLowerCase().includes(tipoMin)) return false;
        if (color === 'C' && c.colors.length !== 0) return false;
        if (color && color !== 'C' && !c.colors.includes(color)) return false;
        return true;
    });

    $('txt-resultados-count').textContent = `${filtradas.length} carta(s) encontrada(s) (Modo Offline)`;
    $('txt-pagina-info').textContent = '';
    mostrarAviso(motivo);
    mostrarCartas(filtradas);
    renderPaginacion(1, 1);
}

function transformarCartaScryfall(c) {
    const caras = Array.isArray(c.card_faces) ? c.card_faces : [];

    let img = '';
    if (c.image_uris && c.image_uris.normal) {
        img = c.image_uris.normal;
    } else if (caras[0] && caras[0].image_uris) {
        img = caras[0].image_uris.normal || '';
    }

    // Colores: en las cartas de doble cara vienen dentro de cada cara
    let colores = c.colors;
    if (!Array.isArray(colores)) {
        const conjunto = new Set();
        caras.forEach(cara => (cara.colors || []).forEach(col => conjunto.add(col)));
        colores = ORDEN_COLORES.filter(col => conjunto.has(col));
    }

    const caraConFuerza = caras.find(cara => cara.power !== undefined);

    return {
        id: c.id,
        name: c.name || '',
        mana_cost: c.mana_cost || caras.map(f => f.mana_cost).filter(Boolean).join(' // '),
        type_line: c.type_line || '',
        oracle_text: c.oracle_text
            || caras.filter(f => f.oracle_text).map(f => `${f.name}\n${f.oracle_text}`).join(SEPARADOR_CARAS),
        power: c.power || (caraConFuerza ? caraConFuerza.power : ''),
        toughness: c.toughness || (caraConFuerza ? caraConFuerza.toughness : ''),
        colors: colores,
        rarity: c.rarity || 'common',
        set_name: c.set_name || c.set || '',
        image_url: img
    };
}

function claseColor(colores) {
    if (colores && colores.length > 1) return 'color-M';
    if (colores && colores.length === 1) return `color-${colores[0]}`;
    return 'color-C';
}

function crearImagenCarta(carta, lazy) {
    if (!carta.image_url) {
        return crear('div', { className: 'sin-imagen', text: 'Sin imagen' });
    }
    const attrs = { src: carta.image_url, alt: carta.name };
    if (lazy) attrs.loading = 'lazy';
    return crear('img', { attrs });
}

function mostrarCartas(cartas) {
    const container = $('grid-cartas');
    container.replaceChildren();

    if (cartas.length === 0) {
        container.appendChild(mensajeVacio('No se encontraron cartas con esos filtros en el grimorio.'));
        return;
    }

    const fragmento = document.createDocumentFragment();
    cartas.forEach(carta => {
        const el = crear('div',
            {
                className: `tarjeta-carta ${claseColor(carta.colors)}`,
                attrs: { tabindex: '0', role: 'button', 'aria-label': `Ver ${carta.name}` },
                onClick: () => abrirModalCarta(carta)
            },
            crearImagenCarta(carta, true),
            crear('div', { className: 'nombre-carta', text: carta.name }),
            crear('div', { className: 'tipo-carta', text: carta.type_line })
        );
        // Accesibilidad: abrir también con Enter o Espacio
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                abrirModalCarta(carta);
            }
        });
        fragmento.appendChild(el);
    });
    container.appendChild(fragmento);
}

/**
 * Devuelve las páginas a mostrar, con null donde va "…".
 * Ej.: actual=50, total=200 -> [1, null, 48, 49, 50, 51, 52, null, 200]
 * (Mismo algoritmo que rango_paginas() en app.py.)
 */
function rangoPaginas(actual, total, alrededor = PAGINAS_ALREDEDOR) {
    const candidatas = new Set([1, total]);
    for (let p = actual - alrededor; p <= actual + alrededor; p++) candidatas.add(p);
    const paginas = [...candidatas].filter(p => p >= 1 && p <= total).sort((a, b) => a - b);

    const resultado = [];
    let anterior = 0;
    for (const p of paginas) {
        if (p - anterior > 1) resultado.push(null);
        resultado.push(p);
        anterior = p;
    }
    return resultado;
}

function irAPagina(p) {
    ejecutarBusqueda(p);
    $('seccion-grimorio').scrollIntoView({ behavior: 'smooth' });
}

function renderPaginacion(totalPaginas, actual) {
    const container = $('paginacion');
    container.replaceChildren();
    if (totalPaginas <= 1) return;

    if (actual > 1) {
        container.appendChild(crear('button', {
            text: '«', attrs: { type: 'button', 'aria-label': 'Página anterior' },
            onClick: () => irAPagina(actual - 1)
        }));
    }

    rangoPaginas(actual, totalPaginas).forEach(p => {
        if (p === null) {
            container.appendChild(crear('span', { className: 'puntos', text: '…' }));
            return;
        }
        const btn = crear('button', { text: String(p), attrs: { type: 'button' }, onClick: () => irAPagina(p) });
        if (p === actual) {
            btn.className = 'activa';
            btn.setAttribute('aria-current', 'page');
        }
        container.appendChild(btn);
    });

    if (actual < totalPaginas) {
        container.appendChild(crear('button', {
            text: '»', attrs: { type: 'button', 'aria-label': 'Página siguiente' },
            onClick: () => irAPagina(actual + 1)
        }));
    }
}

function limpiarFiltros() {
    $('input-q').value = '';
    $('select-color').value = '';
    $('input-tipo').value = '';
    ejecutarBusqueda(1);
}

// ================= MODAL DETALLE DE CARTA =================
function abrirModalCarta(carta) {
    cartaSeleccionadaActual = carta;

    $('modal-nombre').textContent = carta.name;
    $('modal-coste').textContent = carta.mana_cost || '—';
    $('modal-tipo').textContent = carta.type_line || '—';
    $('modal-rareza').textContent = (carta.rarity || '').toUpperCase();
    $('modal-set').textContent = carta.set_name || '—';
    $('modal-texto').textContent = carta.oracle_text || 'Sin texto explicativo.';

    if (carta.power || carta.toughness) {
        $('modal-pt-container').classList.remove('hidden');
        $('modal-pt').textContent = `${carta.power} / ${carta.toughness}`;
    } else {
        $('modal-pt-container').classList.add('hidden');
    }

    const imgEl = $('modal-img');
    if (carta.image_url) {
        imgEl.src = carta.image_url;
        imgEl.alt = carta.name;
        imgEl.classList.remove('hidden');
    } else {
        imgEl.removeAttribute('src');
        imgEl.classList.add('hidden');
    }

    // Cargar selector de mazos
    const mazos = obtenerMazosGuardados();
    const selectEl = $('modal-select-mazo');
    selectEl.replaceChildren();

    if (mazos.length === 0) {
        selectEl.appendChild(crear('option', { text: 'No tienes mazos creados', attrs: { value: '' } }));
    } else {
        mazos.forEach(m => {
            selectEl.appendChild(crear('option', {
                text: `${m.nombre} (${contarCartas(m)})`,
                attrs: { value: String(m.id) }
            }));
        });
    }

    $('modal-carta').classList.remove('hidden');
    $('btn-cerrar-modal').focus();
}

function cerrarModal() {
    $('modal-carta').classList.add('hidden');
}

// ================= GESTIÓN DE MAZOS (MIS MAZOS) =================
function crearNuevoMazo() {
    const nombreInput = $('nuevo-mazo-nombre');
    const formatoInput = $('nuevo-mazo-formato');

    const nombre = nombreInput.value.trim().slice(0, 100);
    const formato = formatoInput.value.trim().slice(0, 50) || 'Formato no especificado';

    if (!nombre) return;

    const mazos = obtenerMazosGuardados();
    // Date.now() podría repetirse si se crean dos mazos en el mismo milisegundo
    const idMaximo = mazos.reduce((max, m) => Math.max(max, m.id), 0);
    const nuevoMazo = {
        id: Math.max(Date.now(), idMaximo + 1),
        nombre: nombre,
        formato: formato,
        creado_en: new Date().toLocaleDateString(),
        cartas: {} // { cartaId: { carta: obj, cantidad: n } }
    };

    mazos.unshift(nuevoMazo);
    guardarMazos(mazos);

    nombreInput.value = '';
    formatoInput.value = '';

    mostrarToast(`Mazo "${nombre}" creado con éxito ✔`);
    renderizarListaMazos();
}

function renderizarListaMazos() {
    const container = $('lista-mazos');
    const mazos = obtenerMazosGuardados();
    container.replaceChildren();

    if (mazos.length === 0) {
        container.appendChild(mensajeVacio('Todavía no has creado ningún mazo arcano. Usa el formulario superior para empezar.'));
        return;
    }

    mazos.forEach(m => {
        const info = crear('div', { className: 'mazo-info' },
            document.createTextNode(`${m.formato} • `),
            crear('span', { className: 'cantidad', text: `${contarCartas(m)} cartas` })
        );

        const card = crear('div', { className: 'tarjeta-mazo' },
            crear('div', {},
                crear('h3', { text: m.nombre }),
                info
            ),
            crear('div', { className: 'mazo-acciones' },
                crear('button', { text: '⚔ Ver Mazo', attrs: { type: 'button' }, onClick: () => verDetalleMazo(m.id) }),
                crear('button', {
                    text: 'Eliminar', className: 'btn-eliminar', attrs: { type: 'button' },
                    onClick: () => eliminarMazo(m.id)
                })
            )
        );
        container.appendChild(card);
    });
}

function eliminarMazo(mazoId) {
    if (!confirm('¿Estás seguro de que deseas eliminar este mazo?')) return;

    const mazos = obtenerMazosGuardados().filter(m => m.id !== mazoId);
    guardarMazos(mazos);
    renderizarListaMazos();
    mostrarToast('Mazo eliminado');
}

function anadirCartaAMazoActual() {
    if (!cartaSeleccionadaActual) return;
    const mazoId = Number($('modal-select-mazo').value);

    if (!mazoId) {
        mostrarToast('Crea primero un mazo en la pestaña "Mis Mazos"');
        return;
    }

    const mazos = obtenerMazosGuardados();
    const mazo = mazos.find(m => m.id === mazoId);
    if (!mazo) return;

    const cId = cartaSeleccionadaActual.id;
    if (mazo.cartas[cId]) {
        mazo.cartas[cId].cantidad = Math.min(mazo.cartas[cId].cantidad + 1, MAX_COPIAS_POR_CARTA);
    } else {
        mazo.cartas[cId] = { carta: cartaSeleccionadaActual, cantidad: 1 };
    }

    guardarMazos(mazos);
    mostrarToast(`"${cartaSeleccionadaActual.name}" añadida a "${mazo.nombre}" ✔`);
    cerrarModal();
}

// ================= VISTA CONSTRUCTOR / DETALLE DE MAZO =================
function verDetalleMazo(mazoId) {
    idMazoAbiertoActual = mazoId;
    const mazo = obtenerMazosGuardados().find(m => m.id === mazoId);
    if (!mazo) return;

    $('mazo-titulo-detalle').textContent = mazo.nombre;
    $('mazo-subtitulo-detalle').textContent = `${mazo.formato} — ${contarCartas(mazo)} carta(s) en total`;

    const container = $('grid-cartas-mazo');
    container.replaceChildren();

    const items = Object.values(mazo.cartas || {}).filter(item => item && item.carta);
    if (items.length === 0) {
        container.appendChild(mensajeVacio('Este mazo todavía no tiene cartas. Búscalas en el Grimorio y añádelas.'));
    } else {
        items
            .sort((a, b) => String(a.carta.name).localeCompare(String(b.carta.name)))
            .forEach(item => {
                const c = item.carta;
                container.appendChild(crear('div', { className: 'tarjeta-carta-mazo' },
                    crearImagenCarta(c, true),
                    crear('div', { className: 'nombre-carta', text: c.name }),
                    crear('div', { className: 'cantidad', text: `x${item.cantidad}` }),
                    crear('div', { className: 'acciones-carta' },
                        crear('button', { text: '+', attrs: { type: 'button', 'aria-label': 'Añadir una copia' }, onClick: () => modificarCantidadMazo(c.id, 1) }),
                        crear('button', { text: '−', attrs: { type: 'button', 'aria-label': 'Quitar una copia' }, onClick: () => modificarCantidadMazo(c.id, -1) }),
                        crear('button', { text: 'Quitar', className: 'btn-eliminar', attrs: { type: 'button' }, onClick: () => quitarDelMazo(c.id) })
                    )
                ));
            });
    }

    navegarA('detalle-mazo');
}

function modificarCantidadMazo(cartaId, cambio) {
    const mazos = obtenerMazosGuardados();
    const mazo = mazos.find(m => m.id === idMazoAbiertoActual);

    if (mazo && mazo.cartas[cartaId]) {
        const nueva = Math.min(mazo.cartas[cartaId].cantidad + cambio, MAX_COPIAS_POR_CARTA);
        if (nueva <= 0) {
            delete mazo.cartas[cartaId];
        } else {
            mazo.cartas[cartaId].cantidad = nueva;
        }
        guardarMazos(mazos);
        verDetalleMazo(idMazoAbiertoActual);
    }
}

function quitarDelMazo(cartaId) {
    const mazos = obtenerMazosGuardados();
    const mazo = mazos.find(m => m.id === idMazoAbiertoActual);

    if (mazo && mazo.cartas[cartaId]) {
        delete mazo.cartas[cartaId];
        guardarMazos(mazos);
        verDetalleMazo(idMazoAbiertoActual);
        mostrarToast('Carta quitada del mazo');
    }
}

// ================= NOTIFICACIONES TOAST =================
function mostrarToast(msg) {
    const toast = $('toast-notif');
    toast.textContent = msg;
    toast.classList.remove('hidden');
    // Si ya había un toast visible, reiniciamos su temporizador
    clearTimeout(temporizadorToast);
    temporizadorToast = setTimeout(() => toast.classList.add('hidden'), 3000);
}

// ================= INICIALIZACIÓN =================
document.addEventListener('DOMContentLoaded', () => {
    // Navegación: cualquier botón con data-vista="..." cambia de sección
    document.querySelectorAll('[data-vista]').forEach(btn => {
        btn.addEventListener('click', () => navegarA(btn.dataset.vista));
    });

    $('form-busqueda').addEventListener('submit', (e) => {
        e.preventDefault();
        ejecutarBusqueda(1);
    });
    $('btn-reset').addEventListener('click', limpiarFiltros);

    $('form-nuevo-mazo').addEventListener('submit', (e) => {
        e.preventDefault();
        crearNuevoMazo();
    });

    $('form-anadir-mazo').addEventListener('submit', (e) => {
        e.preventDefault();
        anadirCartaAMazoActual();
    });

    // Modal: cerrar con la X, haciendo clic fuera o pulsando Escape
    $('btn-cerrar-modal').addEventListener('click', cerrarModal);
    $('modal-carta').addEventListener('click', (e) => {
        if (e.target.id === 'modal-carta') cerrarModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !$('modal-carta').classList.contains('hidden')) cerrarModal();
    });

    actualizarBadgeMazos();
    ejecutarBusqueda(1);
});
