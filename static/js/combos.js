/*
 * static/js/combos.js
 *
 * Motor visual del Analizador de Combos y Mapa de Rutas (estilo LoopLine).
 * Conecta con /api/combos/analizar y /api/mazos/<id>/anadir usando enviarJSON().
 */

'use strict';

const SVG_NS = 'http://www.w3.org/2000/svg';

const LISTA_EJEMPLO_COMBOS = [
    "1 Demonic Consultation",
    "1 Thassa's Oracle",
    "1 Isochron Scepter",
    "1 Dramatic Reversal",
    "1 Sol Ring",
    "1 Arcane Signet",
    "1 Basalt Monolith",
    "1 Rings of Brighthearth",
    "1 Heliod, Sun-Crowned",
    "1 Niv-Mizzet, Parun"
].join('\n');

let estadoDatos = {
    incluidos: [],
    sugerencias: [],
    modoMapa: 'todos', // 'todos' | 'incluidos' | 'sugerencias'
};

let zoomTransform = { x: 0, y: 0, scale: 1 };
let arrastrando = false;
let inicioArrastre = { x: 0, y: 0 };

function $(id) {
    return document.getElementById(id);
}

function crearEl(tag, opts = {}, ...hijos) {
    const el = document.createElement(tag);
    if (opts.className) el.className = opts.className;
    if (opts.text !== undefined) el.textContent = opts.text;
    if (opts.attrs) {
        for (const [k, v] of Object.entries(opts.attrs)) {
            if (v !== null && v !== undefined) el.setAttribute(k, v);
        }
    }
    if (opts.onClick) el.addEventListener('click', opts.onClick);
    for (const h of hijos) {
        if (h) el.appendChild(h);
    }
    return el;
}

function crearSvg(tag, attrs = {}, ...hijos) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
        if (v !== null && v !== undefined) el.setAttribute(k, String(v));
    }
    for (const h of hijos) {
        if (h) el.appendChild(h);
    }
    return el;
}

function truncar(texto, max = 24) {
    if (!texto) return '';
    return texto.length > max ? texto.slice(0, max - 1) + '…' : texto;
}

// ================= LLAMADA AL BACKEND =================

async function ejecutarAnalisis({ usarTexto = false } = {}) {
    const selectMazo = $('select-mazo-combo');
    const textarea = $('textarea-lista-combo');
    const loading = $('combos-loading');
    const errorEl = $('combos-error');
    const secResultados = $('combos-resultados');
    const resumen = $('resumen-analisis');

    const cuerpo = {};
    if (usarTexto) {
        cuerpo.lista_texto = textarea.value.trim();
        if (!cuerpo.lista_texto) {
            errorEl.textContent = 'Pega primero al menos una carta en el cuadro de texto.';
            errorEl.classList.remove('hidden');
            return;
        }
    } else {
        cuerpo.mazo_id = selectMazo.value;
        if (!cuerpo.mazo_id) {
            errorEl.textContent = 'Selecciona un mazo o usa el botón «⚡ Probar ejemplo con combos».';
            errorEl.classList.remove('hidden');
            return;
        }
    }

    errorEl.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const data = await enviarJSON('/api/combos/analizar', cuerpo);
        loading.classList.add('hidden');
        secResultados.classList.remove('hidden');

        estadoDatos.incluidos = data.incluidos || [];
        estadoDatos.sugerencias = data.sugerencias || [];

        $('badge-incluidos').textContent = estadoDatos.incluidos.length;
        $('badge-sugerencias').textContent = estadoDatos.sugerencias.length;

        resumen.textContent = `${data.nombre_mazo}: ${data.total_cartas_analizadas} carta(s) analizadas · ${estadoDatos.incluidos.length} combo(s) activos · ${estadoDatos.sugerencias.length} sugerencia(s) a 1 carta`;

        renderizarListaCombos($('lista-combos-incluidos'), estadoDatos.incluidos, false);
        renderizarListaCombos($('lista-combos-sugerencias'), estadoDatos.sugerencias, true);
        renderizarMapa();
    } catch (err) {
        loading.classList.add('hidden');
        errorEl.textContent = err.message;
        errorEl.classList.remove('hidden');
    }
}

// ================= TARJETAS DETALLADAS DE COMBOS =================

function crearTarjetaCombo(combo, esSugerencia) {
    const mazoIdActual = $('select-mazo-combo').value;

    // Cabecera del combo
    const badges = crearEl('div', { className: 'combo-badges' },
        crearEl('span', {
            className: esSugerencia ? 'badge-combo badge-combo-sugerencia' : 'badge-combo badge-combo-activo',
            text: esSugerencia ? '✦ Falta 1 carta' : '✔ Combo completo en mazo'
        }),
        crearEl('span', { className: 'badge-formato', text: `Identidad: ${combo.identidad}` }),
        combo.mana_necesario ? crearEl('span', { className: 'chip', text: `Maná: ${combo.mana_necesario}` }) : null
    );

    const linkSpellbook = crearEl('a', {
        className: 'btn btn-secundario btn-sm',
        text: 'Ver en Spellbook ↗',
        attrs: { href: combo.url_spellbook, target: '_blank', rel: 'noopener noreferrer' }
    });

    const header = crearEl('div', { className: 'combo-card-header' }, badges, linkSpellbook);

    // Tira visual de cartas del combo
    const tiraCartas = crearEl('div', { className: 'combo-cartas-strip' });
    (combo.cartas || []).forEach(c => {
        const estadoBadge = crearEl('span', {
            className: c.en_mazo ? 'combo-carta-tag tag-ok' : 'combo-carta-tag tag-missing',
            text: c.en_mazo ? '✔ En tu mazo' : '+ Carta que falta'
        });

        const img = c.imagen_url
            ? crearEl('img', { attrs: { src: c.imagen_url, alt: c.nombre, loading: 'lazy' } })
            : crearEl('div', { className: 'sin-imagen', text: c.nombre });

        const tituloNombre = c.local_id
            ? crearEl('a', { className: 'combo-carta-nombre', text: c.nombre, attrs: { href: `/carta/${c.local_id}` } })
            : crearEl('span', { className: 'combo-carta-nombre', text: c.nombre });

        // Si falta esta carta y existe en nuestra BD y hay un mazo seleccionado, botón para añadirla en 1 clic
        let btnAnadir = null;
        if (!c.en_mazo && c.local_id && mazoIdActual) {
            btnAnadir = crearEl('button', {
                className: 'btn btn-sm btn-anadir-sugerencia',
                text: '+ Añadir a mi mazo',
                attrs: { type: 'button' },
                onClick: async (ev) => {
                    const b = ev.currentTarget;
                    b.disabled = true;
                    b.textContent = 'Añadiendo...';
                    try {
                        await enviarJSON(`/api/mazos/${mazoIdActual}/anadir`, { carta_id: c.local_id, cantidad: 1 });
                        b.textContent = '¡Añadida! Recalculando...';
                        await ejecutarAnalisis({ usarTexto: false });
                    } catch (e) {
                        b.disabled = false;
                        b.textContent = 'Error al añadir';
                    }
                }
            });
        }

        const itemCarta = crearEl('div', {
            className: `combo-carta-item ${c.en_mazo ? 'en-mazo' : 'falta-mazo'}`
        }, estadoBadge, img, tituloNombre, btnAnadir);

        tiraCartas.appendChild(itemCarta);
    });

    // Efectos producidos (Produces)
    const contenedorProduce = crearEl('div', { className: 'combo-produce-wrap' });
    (combo.produce || []).forEach(efecto => {
        contenedorProduce.appendChild(crearEl('span', { className: 'chip chip-outcome', text: `⚡ ${efecto}` }));
    });

    // Requisitos
    const bloqueReq = combo.requisitos
        ? crearEl('p', { className: 'combo-requisitos' },
            crearEl('strong', { text: 'Requisitos previos: ' }),
            document.createTextNode(combo.requisitos)
        )
        : null;

    // Pasos numerados
    const listaPasos = crearEl('ol', { className: 'combo-pasos' });
    (combo.pasos || []).forEach(paso => {
        listaPasos.appendChild(crearEl('li', { text: paso }));
    });

    return crearEl('article', {
        className: 'combo-card',
        attrs: { id: `combo-card-${combo.id}` }
    }, header, tiraCartas, contenedorProduce, bloqueReq, listaPasos);
}

function renderizarListaCombos(contenedor, lista, esSugerencia) {
    contenedor.replaceChildren();
    if (!lista || lista.length === 0) {
        contenedor.appendChild(crearEl('div', { className: 'estado-vacio' },
            crearEl('h3', {
                text: esSugerencia
                    ? 'No se encontraron sugerencias a 1 carta'
                    : 'Todavía no hay combos completos en estas cartas'
            }),
            crearEl('p', {
                text: esSugerencia
                    ? 'Añade más cartas a tu mazo para descubrir líneas cercanas.'
                    : 'Revisa la pestaña «✦ Sugerencias (Falta 1 carta)» o prueba el mazo de ejemplo.'
            })
        ));
        return;
    }

    lista.forEach(combo => {
        contenedor.appendChild(crearTarjetaCombo(combo, esSugerencia));
    });
}

// ================= MAPA VISUAL INTERACTIVO (LOOPLINE ROUTE MAP) =================

function obtenerCombosParaMapa() {
    if (estadoDatos.modoMapa === 'incluidos') {
        return estadoDatos.incluidos.map(c => ({ ...c, _sugerencia: false }));
    }
    if (estadoDatos.modoMapa === 'sugerencias') {
        return estadoDatos.sugerencias.map(c => ({ ...c, _sugerencia: true }));
    }
    return [
        ...estadoDatos.incluidos.map(c => ({ ...c, _sugerencia: false })),
        ...estadoDatos.sugerencias.slice(0, 12).map(c => ({ ...c, _sugerencia: true }))
    ];
}

function aplicarTransformMapa() {
    const grupo = document.getElementById('loopline-viewport');
    if (grupo) {
        grupo.setAttribute('transform', `translate(${zoomTransform.x}, ${zoomTransform.y}) scale(${zoomTransform.scale})`);
    }
}

function renderizarMapa() {
    const svg = $('loopline-svg');
    const emptyEl = $('loopline-empty');
    const inspector = $('loopline-inspector');
    svg.replaceChildren();
    inspector.classList.add('hidden');

    const combos = obtenerCombosParaMapa().slice(0, 16);
    if (combos.length === 0) {
        emptyEl.classList.remove('hidden');
        return;
    }
    emptyEl.classList.add('hidden');

    // Construir nodos únicos de Cartas (columna izquierda), Combos (columna central) y Resultados (columna derecha)
    const mapaCartas = new Map();
    const mapaResultados = new Map();

    combos.forEach(combo => {
        (combo.cartas || []).forEach(c => {
            if (!mapaCartas.has(c.nombre)) {
                mapaCartas.set(c.nombre, { nombre: c.nombre, en_mazo: c.en_mazo, combosIds: new Set() });
            }
            mapaCartas.get(c.nombre).combosIds.add(combo.id);
        });
        (combo.produce || []).forEach(efecto => {
            if (!mapaResultados.has(efecto)) {
                mapaResultados.set(efecto, { nombre: efecto, combosIds: new Set() });
            }
            mapaResultados.get(efecto).combosIds.add(combo.id);
        });
    });

    const nodosCartas = Array.from(mapaCartas.values());
    const nodosResultados = Array.from(mapaResultados.values());

    const maxFilas = Math.max(nodosCartas.length, combos.length, nodosResultados.length, 6);
    const altoTotal = Math.max(660, maxFilas * 56 + 110);
    const anchoTotal = 1200;
    svg.setAttribute('viewBox', `0 0 ${anchoTotal} ${altoTotal}`);

    const xCarta = 190;
    const xCombo = 600;
    const xResultado = 1010;

    const distribuirY = (total, idx) => {
        const margenSup = 80;
        const espacioUtil = altoTotal - margenSup - 50;
        if (total <= 1) return margenSup + espacioUtil / 2;
        return margenSup + (idx * espacioUtil) / (total - 1);
    };

    nodosCartas.forEach((n, i) => { n.x = xCarta; n.y = distribuirY(nodosCartas.length, i); });
    combos.forEach((c, i) => { c.x = xCombo; c.y = distribuirY(combos.length, i); });
    nodosResultados.forEach((r, i) => { r.x = xResultado; r.y = distribuirY(nodosResultados.length, i); });

    const viewport = crearSvg('g', { id: 'loopline-viewport' });
    const capaLineas = crearSvg('g', { class: 'loopline-edges' });
    const capaNodos = crearSvg('g', { class: 'loopline-nodes' });

    // Títulos de las 3 columnas en el lienzo
    viewport.appendChild(crearSvg('text', { x: xCarta, y: 38, 'text-anchor': 'middle', class: 'map-col-title' }, document.createTextNode('PIEZAS / CARTAS')));
    viewport.appendChild(crearSvg('text', { x: xCombo, y: 38, 'text-anchor': 'middle', class: 'map-col-title' }, document.createTextNode('RUTAS DE COMBO')));
    viewport.appendChild(crearSvg('text', { x: xResultado, y: 38, 'text-anchor': 'middle', class: 'map-col-title' }, document.createTextNode('RESULTADOS / EFECTOS')));

    const todasLasLineas = [];
    const todosLosNodos = [];

    // Crear curvas Bézier: Carta -> Combo y Combo -> Resultado
    combos.forEach(combo => {
        (combo.cartas || []).forEach(c => {
            const origen = mapaCartas.get(c.nombre);
            if (!origen) return;
            const x1 = origen.x + 115;
            const y1 = origen.y;
            const x2 = combo.x - 105;
            const y2 = combo.y;
            const d = `M ${x1} ${y1} C ${x1 + 95} ${y1}, ${x2 - 95} ${y2}, ${x2} ${y2}`;
            const path = crearSvg('path', {
                d,
                class: `map-edge ${combo._sugerencia ? 'edge-suggestion' : 'edge-active'}`,
                'data-combo-id': combo.id,
                'data-card': c.nombre
            });
            capaLineas.appendChild(path);
            todasLasLineas.push(path);
        });

        (combo.produce || []).forEach(efecto => {
            const destino = mapaResultados.get(efecto);
            if (!destino) return;
            const x1 = combo.x + 105;
            const y1 = combo.y;
            const x2 = destino.x - 115;
            const y2 = destino.y;
            const d = `M ${x1} ${y1} C ${x1 + 95} ${y1}, ${x2 - 95} ${y2}, ${x2} ${y2}`;
            const path = crearSvg('path', {
                d,
                class: 'map-edge edge-outcome',
                'data-combo-id': combo.id,
                'data-outcome': efecto
            });
            capaLineas.appendChild(path);
            todasLasLineas.push(path);
        });
    });

    function resaltarPorCombos(idsActivos, comboDetalle = null) {
        todasLasLineas.forEach(l => {
            const cid = l.getAttribute('data-combo-id');
            l.classList.toggle('is-highlighted', idsActivos.has(cid));
            l.classList.toggle('is-dimmed', !idsActivos.has(cid));
        });
        todosLosNodos.forEach(item => {
            const coincide = item.combosIds.some(id => idsActivos.has(id));
            item.el.classList.toggle('is-highlighted', coincide);
            item.el.classList.toggle('is-dimmed', !coincide);
        });

        if (comboDetalle) {
            inspector.replaceChildren(crearTarjetaCombo(comboDetalle, comboDetalle._sugerencia));
            inspector.classList.remove('hidden');
        }
    }

    // Dibujar nodos de Cartas
    nodosCartas.forEach(n => {
        const g = crearSvg('g', {
            class: `map-node ${n.en_mazo ? 'node-card-ok' : 'node-card-missing'}`,
            transform: `translate(${n.x - 115}, ${n.y - 18})`
        },
            crearSvg('rect', { width: 230, height: 36, rx: 8 }),
            crearSvg('text', { x: 14, y: 22, class: 'map-node-label' },
                document.createTextNode(`${n.en_mazo ? '● ' : '+ '} ${truncar(n.nombre, 24)}`)
            )
        );
        g.addEventListener('click', () => {
            const primerCombo = combos.find(c => n.combosIds.has(c.id));
            resaltarPorCombos(n.combosIds, primerCombo);
        });
        capaNodos.appendChild(g);
        todosLosNodos.push({ el: g, combosIds: Array.from(n.combosIds) });
    });

    // Dibujar nodos de Combos (columna central)
    combos.forEach((c, idx) => {
        const etiqueta = c._sugerencia ? `✦ Sugerencia #${idx + 1}` : `∞ Combo #${idx + 1}`;
        const sub = `${(c.cartas || []).length} cartas · ${c.identidad}`;
        const g = crearSvg('g', {
            class: `map-node ${c._sugerencia ? 'node-combo-sug' : 'node-combo-inc'}`,
            transform: `translate(${c.x - 105}, ${c.y - 22})`
        },
            crearSvg('rect', { width: 210, height: 44, rx: 10 }),
            crearSvg('text', { x: 105, y: 19, 'text-anchor': 'middle', class: 'map-node-title' }, document.createTextNode(etiqueta)),
            crearSvg('text', { x: 105, y: 34, 'text-anchor': 'middle', class: 'map-node-sub' }, document.createTextNode(sub))
        );
        g.addEventListener('click', () => resaltarPorCombos(new Set([c.id]), c));
        capaNodos.appendChild(g);
        todosLosNodos.push({ el: g, combosIds: [c.id] });
    });

    // Dibujar nodos de Resultados
    nodosResultados.forEach(r => {
        const g = crearSvg('g', {
            class: 'map-node node-outcome',
            transform: `translate(${r.x - 115}, ${r.y - 18})`
        },
            crearSvg('rect', { width: 230, height: 36, rx: 8 }),
            crearSvg('text', { x: 14, y: 22, class: 'map-node-label' },
                document.createTextNode(`⚡ ${truncar(r.nombre, 24)}`)
            )
        );
        g.addEventListener('click', () => {
            const primerCombo = combos.find(c => r.combosIds.has(c.id));
            resaltarPorCombos(r.combosIds, primerCombo);
        });
        capaNodos.appendChild(g);
        todosLosNodos.push({ el: g, combosIds: Array.from(r.combosIds) });
    });

    viewport.appendChild(capaLineas);
    viewport.appendChild(capaNodos);
    svg.appendChild(viewport);

    zoomTransform = { x: 0, y: 0, scale: 1 };
    aplicarTransformMapa();
}

// ================= INICIALIZACIÓN Y EVENTOS =================

document.addEventListener('DOMContentLoaded', () => {
    // Pestañas
    document.querySelectorAll('.combo-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.combo-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.combo-tab-panel').forEach(p => p.classList.add('hidden'));
            btn.classList.add('active');
            $(btn.dataset.tab).classList.remove('hidden');
        });
    });

    // Botones de análisis
    $('btn-analizar-mazo').addEventListener('click', () => ejecutarAnalisis({ usarTexto: false }));
    $('btn-analizar-texto').addEventListener('click', () => ejecutarAnalisis({ usarTexto: true }));
    $('btn-limpiar-texto').addEventListener('click', () => {
        $('textarea-lista-combo').value = '';
    });

    $('btn-probar-ejemplo').addEventListener('click', () => {
        $('textarea-lista-combo').value = LISTA_EJEMPLO_COMBOS;
        $('details-lista-texto').open = true;
        ejecutarAnalisis({ usarTexto: true });
    });

    // Filtros del mapa
    const activarFiltroMapa = (modo, btnId) => {
        estadoDatos.modoMapa = modo;
        ['btn-mapa-ver-todos', 'btn-mapa-ver-incluidos', 'btn-mapa-ver-sugerencias'].forEach(id => {
            $(id).classList.toggle('active', id === btnId);
        });
        renderizarMapa();
    };
    $('btn-mapa-ver-todos').addEventListener('click', () => activarFiltroMapa('todos', 'btn-mapa-ver-todos'));
    $('btn-mapa-ver-incluidos').addEventListener('click', () => activarFiltroMapa('incluidos', 'btn-mapa-ver-incluidos'));
    $('btn-mapa-ver-sugerencias').addEventListener('click', () => activarFiltroMapa('sugerencias', 'btn-mapa-ver-sugerencias'));

    // Controles de Zoom y Pan en el mapa SVG
    const stage = $('loopline-stage');
    $('btn-zoom-in').addEventListener('click', () => {
        zoomTransform.scale = Math.min(2.2, zoomTransform.scale + 0.2);
        aplicarTransformMapa();
    });
    $('btn-zoom-out').addEventListener('click', () => {
        zoomTransform.scale = Math.max(0.5, zoomTransform.scale - 0.2);
        aplicarTransformMapa();
    });
    $('btn-zoom-reset').addEventListener('click', () => {
        zoomTransform = { x: 0, y: 0, scale: 1 };
        aplicarTransformMapa();
    });

    stage.addEventListener('mousedown', (e) => {
        if (e.target.closest('.map-node')) return;
        arrastrando = true;
        inicioArrastre = { x: e.clientX - zoomTransform.x, y: e.clientY - zoomTransform.y };
    });
    window.addEventListener('mousemove', (e) => {
        if (!arrastrando) return;
        zoomTransform.x = e.clientX - inicioArrastre.x;
        zoomTransform.y = e.clientY - inicioArrastre.y;
        aplicarTransformMapa();
    });
    window.addEventListener('mouseup', () => { arrastrando = false; });

    // Si hay un mazo seleccionado al abrir la página, lo analizamos automáticamente
    if ($('select-mazo-combo').value) {
        ejecutarAnalisis({ usarTexto: false });
    }
});
