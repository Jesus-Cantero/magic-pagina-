/*
 * static/js/api.js
 *
 * Utilidad compartida por las plantillas de la versión Flask para llamar
 * a la API JSON del servidor (/api/...).
 *
 * - Envía siempre el token CSRF en la cabecera X-CSRFToken.
 * - Si el servidor responde con error (400, 404, 500...) o no responde,
 *   lanza un Error con un mensaje legible, para que la plantilla lo muestre.
 */

function obtenerTokenCsrf() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
}

async function enviarJSON(url, cuerpo) {
    let resp;
    try {
        resp = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': obtenerTokenCsrf()
            },
            body: JSON.stringify(cuerpo)
        });
    } catch (e) {
        throw new Error('No se pudo conectar con el servidor.');
    }

    let data = null;
    try {
        data = await resp.json();
    } catch (e) {
        // La respuesta no era JSON (por ejemplo, una página de error HTML)
    }

    if (!resp.ok || !data || !data.ok) {
        const mensaje = (data && data.error) ? data.error : `Error del servidor (${resp.status}).`;
        throw new Error(mensaje);
    }
    return data;
}

/**
 * Abre el modal global de Alters Oficiales y Ediciones en Alta Calidad (HD).
 *
 * Opciones:
 *   - cartaId: ID (oracle_id) de la carta
 *   - nombreCarta: nombre de la carta (opcional)
 *   - mazoId: ID del mazo activo (opcional)
 *   - mazosLista: array de {id, nombre} si estamos en el catálogo y queremos elegir a qué mazo añadir
 *   - esComandante: true si se está eligiendo o cambiando el arte del Comandante
 *   - modo: 'anadir_mazo' | 'cambiar_en_mazo' | 'catalogo'
 *   - onImagenCambiada: callback(imagenUrl) cuando se cambia el arte
 */
async function abrirSelectorAlters(opciones) {
    const modal = document.getElementById('modal-alters-oficiales');
    const titulo = document.getElementById('modal-alters-titulo');
    const subbarra = document.getElementById('modal-alters-subbarra');
    const cuerpo = document.getElementById('modal-alters-cuerpo');
    const btnCerrar = document.getElementById('btn-cerrar-modal-alters');

    if (!modal || !cuerpo) return;

    const cerrar = () => modal.classList.add('hidden');
    btnCerrar.onclick = cerrar;
    modal.onclick = (e) => {
        if (e.target === modal) cerrar();
    };

    titulo.textContent = `🎨 Alters Oficiales · ${opciones.nombreCarta || 'Cargando...'}`;
    subbarra.replaceChildren();
    cuerpo.replaceChildren();

    const cargando = document.createElement('p');
    cargando.className = 'texto-suave';
    cargando.textContent = 'Consultando todas las ediciones y alters oficiales en alta resolución (HD) en Scryfall...';
    cuerpo.appendChild(cargando);
    modal.classList.remove('hidden');

    let selectMazoModal = null;
    if (opciones.mazosLista && opciones.mazosLista.length > 0 && !opciones.mazoId) {
        const lbl = document.createElement('span');
        lbl.textContent = 'Mazo destino para añadir: ';
        selectMazoModal = document.createElement('select');
        selectMazoModal.className = 'select-formato-header';
        opciones.mazosLista.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.nombre;
            selectMazoModal.appendChild(opt);
        });
        subbarra.appendChild(lbl);
        subbarra.appendChild(selectMazoModal);
    } else {
        const info = document.createElement('span');
        info.className = 'texto-suave';
        info.textContent = 'Todas las imágenes se muestran en calidad HD (672×936 / PNG 745×1040). Elige el alter oficial que prefieras:';
        subbarra.appendChild(info);
    }

    try {
        const resp = await fetch(`/api/cartas/${encodeURIComponent(opciones.cartaId)}/alters`);
        const data = await resp.json();
        cuerpo.replaceChildren();

        if (!data.ok || !data.alters || data.alters.length === 0) {
            const vacio = document.createElement('p');
            vacio.className = 'texto-suave';
            vacio.textContent = 'No se encontraron versiones adicionales en Scryfall para esta carta.';
            cuerpo.appendChild(vacio);
            return;
        }

        titulo.textContent = `🎨 Alters Oficiales de ${data.nombre} (${data.alters.length} versiones HD)`;

        data.alters.forEach(alt => {
            const card = document.createElement('div');
            card.className = 'alter-card-item' + (alt.es_alter_especial ? ' alter-especial' : '');

            const badge = document.createElement('span');
            badge.className = 'alter-style-badge' + (alt.es_alter_especial ? ' badge-especial' : '');
            badge.textContent = alt.etiqueta;

            const imgWrap = document.createElement('div');
            imgWrap.className = 'alter-img-wrap';
            const img = document.createElement('img');
            img.src = alt.imagen_url;
            img.alt = `${data.nombre} (${alt.set_nombre})`;
            img.loading = 'lazy';
            imgWrap.appendChild(img);

            const meta = document.createElement('div');
            meta.className = 'alter-meta';
            const setLine = document.createElement('strong');
            setLine.textContent = `${alt.set_code} #${alt.collector_number} · ${alt.set_nombre}`;
            const artistLine = document.createElement('span');
            artistLine.textContent = `🖌️ ${alt.artista}${alt.fecha ? ' (' + alt.fecha + ')' : ''}`;
            meta.appendChild(setLine);
            meta.appendChild(artistLine);

            const acciones = document.createElement('div');
            acciones.className = 'alter-acciones';

            const mazoDestinoId = () => opciones.mazoId || (selectMazoModal ? selectMazoModal.value : null);

            if (opciones.modo === 'cambiar_en_mazo' && opciones.mazoId) {
                const btnUsarMazo = document.createElement('button');
                btnUsarMazo.type = 'button';
                btnUsarMazo.className = 'btn btn-sm';
                btnUsarMazo.textContent = '✓ Usar este alter en el mazo';
                btnUsarMazo.addEventListener('click', async () => {
                    btnUsarMazo.disabled = true;
                    await enviarJSON(`/api/mazos/${opciones.mazoId}/imagen_carta`, {
                        carta_id: opciones.cartaId,
                        imagen_url: alt.imagen_url,
                        es_comandante: Boolean(opciones.esComandante),
                    });
                    cerrar();
                    if (opciones.onImagenCambiada) opciones.onImagenCambiada(alt.imagen_url);
                    else window.location.reload();
                });
                acciones.appendChild(btnUsarMazo);
            } else if (opciones.modo === 'anadir_mazo' && opciones.mazoId) {
                const btnAdd = document.createElement('button');
                btnAdd.type = 'button';
                btnAdd.className = 'btn btn-sm';
                btnAdd.textContent = opciones.esComandante ? '👑 Fijar Comandante con este arte' : '+ Añadir al mazo con este arte';
                btnAdd.addEventListener('click', async () => {
                    btnAdd.disabled = true;
                    if (opciones.esComandante) {
                        await enviarJSON(`/api/mazos/${opciones.mazoId}/comandante`, {
                            carta_id: opciones.cartaId,
                            imagen_url: alt.imagen_url,
                        });
                    } else {
                        await enviarJSON(`/api/mazos/${opciones.mazoId}/anadir`, {
                            carta_id: opciones.cartaId,
                            cantidad: 1,
                            imagen_url: alt.imagen_url,
                        });
                    }
                    cerrar();
                    window.location.reload();
                });
                acciones.appendChild(btnAdd);
            } else {
                // Modo catálogo / ficha de carta: permite cambiar imagen de la carta Y/O añadir a un mazo con este arte
                const btnFijar = document.createElement('button');
                btnFijar.type = 'button';
                btnFijar.className = 'btn btn-secundario btn-sm';
                btnFijar.textContent = '🖼️ Fijar en la carta';
                btnFijar.addEventListener('click', async () => {
                    btnFijar.disabled = true;
                    await enviarJSON(`/api/cartas/${encodeURIComponent(opciones.cartaId)}/imagen`, {
                        imagen_url: alt.imagen_url,
                    });
                    if (opciones.onImagenCambiada) opciones.onImagenCambiada(alt.imagen_url);
                    cerrar();
                });
                acciones.appendChild(btnFijar);

                if (mazoDestinoId()) {
                    const btnAddConArte = document.createElement('button');
                    btnAddConArte.type = 'button';
                    btnAddConArte.className = 'btn btn-sm';
                    btnAddConArte.textContent = '+ Al mazo con este arte';
                    btnAddConArte.addEventListener('click', async () => {
                        btnAddConArte.disabled = true;
                        const idMazo = mazoDestinoId();
                        await enviarJSON(`/api/mazos/${idMazo}/anadir`, {
                            carta_id: opciones.cartaId,
                            cantidad: 1,
                            imagen_url: alt.imagen_url,
                        });
                        btnAddConArte.textContent = '✓ Añadida al mazo';
                        setTimeout(cerrar, 500);
                    });
                    acciones.appendChild(btnAddConArte);
                }
            }

            card.appendChild(badge);
            card.appendChild(imgWrap);
            card.appendChild(meta);
            card.appendChild(acciones);
            cuerpo.appendChild(card);
        });
    } catch (err) {
        cuerpo.replaceChildren();
        const errorP = document.createElement('p');
        errorP.className = 'mensaje-error';
        errorP.textContent = `No se pudieron cargar los alters: ${err.message}`;
        cuerpo.appendChild(errorP);
    }
}
