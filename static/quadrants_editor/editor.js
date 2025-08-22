// Editor de cuadrantes - Leaflet con Draw y paleta propia
// Inicialización del mapa centrado por ciudad
console.debug('Inicializando editor de cuadrantes...');

// Estilo fijo para comunas: borde negro, sin relleno
const COMUNA_STYLE = {
  color: "#000000",
  weight: 1.5,
  fillOpacity: 0.0,
  // opcional; con fillOpacity 0 basta, pero mantenemos por compatibilidad:
  fillColor: "transparent"
};

function ensureComunaStyleProps(props) {
  const p = Object.assign({}, props || {});
  p.color = p.color ?? COMUNA_STYLE.color;
  p.weight = p.weight ?? COMUNA_STYLE.weight;
  p.fillOpacity = p.fillOpacity ?? COMUNA_STYLE.fillOpacity;
  p.fillColor = p.fillColor ?? COMUNA_STYLE.fillColor;
  return p;
}

// FC de comunas base de la ciudad actual
let COMUNAS_FC = null;

// === Config de color/borde ===
const PALETTE = [
  '#636EFA', // indigo
  '#EF553B', // orange-red
  '#00CC96', // green
  '#AB63FA', // purple
  '#FFA15A', // orange
  '#19D3F3', // cyan
  '#FF6692', // pink
  '#B6E880', // light green
  '#FF97FF', // light magenta
  '#FECB52', // gold
  '#2E91E5', // blue
  '#F46036', // vermillion
  '#1CA71C', // kelly green
  '#BC5090', // plum
  '#FFA600', // amber
  '#00F7F7', // aqua
  '#FF009D', // hot pink
  '#9A9A00'  // olive
];
let CURRENT_FILL = PALETTE[0];
const STROKE_POLICY = 'black'; // 'black' | 'match'  (borde negro o igual al relleno)
const STROKE_WEIGHT = 2;
const FILL_OPACITY = 0.4;

// Configuración de ciudades con sus coordenadas y zoom
const CITY_CFG = {
  CALI:      { center: [3.4516, -76.5320], zoom: 12 },
  MEDELLIN:  { center: [6.2442, -75.5812], zoom: 12 },
  MANIZALES: { center: [5.0672, -75.5174], zoom: 12 },
  PEREIRA:   { center: [4.8087, -75.6906], zoom: 12 },
  BOGOTA:    { center: [4.7110, -74.0721], zoom: 12 },
  BARRANQUILLA: { center: [10.9720, -74.7962], zoom: 12 },
  BUCARAMANGA:  { center: [7.1193, -73.1227], zoom: 12 },
};

// Mapeo de ciudades a archivos de comunas
const CITY_TO_COMUNAS_FILE = {
  CALI: 'comunas_cali.geojson',
  MEDELLIN: 'comunas_medellin.geojson',
  MANIZALES: 'comunas_manizales.geojson',
  PEREIRA: 'comunas_pereira.geojson',
  BOGOTA: 'comunas_bogota.geojson',
  BARRANQUILLA: 'comunas_barranquilla.geojson',
  BUCARAMANGA: 'comunas_bucaramanga.geojson',
};

// Función para obtener la ciudad desde la URL
function getCityFromQuery() {
    const urlParams = new URLSearchParams(window.location.search);
    const city = urlParams.get('city');
    return city ? city.toUpperCase() : 'BOGOTA';
}

// Resolver configuración de ciudad
const CITY = getCityFromQuery();
const cfg = CITY_CFG[CITY] || CITY_CFG.BOGOTA;

// Si la ciudad no existe, mostrar warning
if (!CITY_CFG[CITY]) {
    console.warn("Unknown city, fallback to BOGOTA:", CITY);
}

// Resolver archivo de comunas por ciudad
const file = CITY_TO_COMUNAS_FILE[CITY] || CITY_TO_COMUNAS_FILE.BOGOTA;
const comunasUrl = `/geojson/${file}`;

// Log de inicialización
console.debug("[EDITOR] init city:", CITY, "center:", cfg.center, "zoom:", cfg.zoom);

// Actualizar título del documento
document.title = `Editor de cuadrantes – ${CITY}`;

// Inicializar mapa Leaflet con configuración de ciudad
const map = L.map('map', {
    center: cfg.center,
    zoom: cfg.zoom,
    zoomControl: true
});

// Agregar tiles de OpenStreetMap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Grupos oficiales
const DRAWN_EDITABLE = new L.FeatureGroup(); // Nuevos => editables
const DRAWN_LOCKED   = new L.FeatureGroup(); // Importados => bloqueados

map.addLayer(DRAWN_LOCKED);
map.addLayer(DRAWN_EDITABLE);

// Flag interno: editable por defecto, con toggle en UI
let allowImportedEdit = true; // editable por defecto

function setImportedEditable(enabled) {
  allowImportedEdit = !!enabled;
  const btn = document.getElementById('btn-toggle-imported');
  if (btn) btn.textContent = allowImportedEdit ? '🔒 Bloquear importados' : '🔓 Editar importados';
  // Mover capas importadas entre grupos para que el control de edición las tome o no
  const toMove = [];
  if (allowImportedEdit) {
    DRAWN_LOCKED.eachLayer(l => { if (l._isImported) toMove.push(l); });
    toMove.forEach(l => { DRAWN_LOCKED.removeLayer(l); DRAWN_EDITABLE.addLayer(l); });
  } else {
    DRAWN_EDITABLE.eachLayer(l => { if (l._isImported) toMove.push(l); });
    toMove.forEach(l => { DRAWN_EDITABLE.removeLayer(l); DRAWN_LOCKED.addLayer(l); });
  }
}

// Track del estado de edición de Leaflet.Draw
let isEditingActive = false;

// Configurar control de dibujo con polygon y rectangle
const drawControl = new L.Control.Draw({
    position: 'topleft',
    draw: {
        polygon:   { showArea: true },
        rectangle: true,
        polyline:  false,
        marker:    false,
        circle:    false,
        circlemarker: false
    },
    edit: { featureGroup: DRAWN_EDITABLE }
});
map.addControl(drawControl);

// Borde forzado
function enforceStrokePolicy(layer) {
  const p = (layer.feature && layer.feature.properties) || (layer.feature = {properties:{}}).properties;
  const colorForStroke = (STROKE_POLICY === 'match') ? (p.fillColor || CURRENT_FILL) : '#000000';
  p.color = colorForStroke;
  p.weight = STROKE_WEIGHT;
  p.fillOpacity = (p.fillOpacity != null) ? p.fillOpacity : FILL_OPACITY;
  // aplicar
  if (layer.setStyle) layer.setStyle({ color: p.color, weight: p.weight, fillColor: p.fillColor || CURRENT_FILL, fillOpacity: p.fillOpacity });
}

// Aplicar estilo desde properties
function applyStyleFromProperties(layer) {
  const p = (layer.feature && layer.feature.properties) || {};
  const style = {
    fillColor:   p.fillColor || CURRENT_FILL,
    color:       (STROKE_POLICY === 'match') ? (p.fillColor || CURRENT_FILL) : '#000000',
    fillOpacity: (p.fillOpacity != null) ? p.fillOpacity : FILL_OPACITY,
    weight:      STROKE_WEIGHT
  };
  if (layer.setStyle) layer.setStyle(style);
}

// Click para recolor si el modo está activo
let recolorMode = false;
function attachRecolorOnClick(layer) {
  layer.on('click', () => {
    if (isEditingActive) return; // No recolor durante edición
    if (!recolorMode) return;
    layer.feature = layer.feature || { type:'Feature', properties:{} };
    const p = layer.feature.properties;
    p.fillColor = CURRENT_FILL;
    applyStyleFromProperties(layer);
    enforceStrokePolicy(layer);
  });
}

// Fetch y overlay de comunas (no editable, atrás)
console.debug('[COMUNAS] fetch:', comunasUrl);
fetch(comunasUrl)
  .then(r => r.json())
  .then(data => {
    // Inyectar estilo de comuna en las properties antes de guardar
    const comunasConEstilo = (data.features || []).map(f => ({
      type: "Feature",
      geometry: f.geometry,
      properties: ensureComunaStyleProps(f.properties)
    }));
    
    // Guardar FeatureCollection con estilos inyectados para export
    COMUNAS_FC = { type: "FeatureCollection", features: comunasConEstilo };
    
    // Crear capa Leaflet con style function que respete las properties
    const comunasLayer = L.geoJSON(COMUNAS_FC, {
      interactive: false, // <— clave: no reciben clicks/hover
      style: (feat) => ({
        color: feat.properties?.color ?? COMUNA_STYLE.color,
        weight: feat.properties?.weight ?? COMUNA_STYLE.weight,
        fillOpacity: feat.properties?.fillOpacity ?? COMUNA_STYLE.fillOpacity,
        fillColor: feat.properties?.fillColor ?? COMUNA_STYLE.fillColor
      })
    }).addTo(map);
    comunasLayer.bringToBack();
    console.debug('[COMUNAS] loaded features:', (data.features || []).length);
  })
  .catch(err => console.warn('[COMUNAS] failed to load', comunasUrl, err));

// NUEVOS => a EDITABLE
map.on(L.Draw.Event.CREATED, (e) => {
  const layer = e.layer;

  // Mantén tus helpers existentes:
  layer.feature = layer.feature || { type:'Feature', properties:{} };
  layer.feature.properties.fillColor = CURRENT_FILL;
  
  // Solicitar código al usuario
  const codigo = promptForCode();
  layer.feature.properties.codigo = codigo;
  
  if (typeof enforceStrokePolicy === 'function') enforceStrokePolicy(layer);
  if (typeof applyStyleFromProperties === 'function') applyStyleFromProperties(layer);
  if (typeof attachRecolorOnClick === 'function') attachRecolorOnClick(layer);

  DRAWN_EDITABLE.addLayer(layer);
  console.debug('[DRAW] created -> editable layers:', DRAWN_EDITABLE.getLayers().length, 'codigo:', codigo);
});

// Persistir estilo tras edición
map.on(L.Draw.Event.EDITED, (e) => {
  if (e.layers && e.layers.eachLayer) {
    e.layers.eachLayer((layer) => {
      // Permitir al usuario editar el código
      if (layer.feature && layer.feature.properties && layer.feature.properties.codigo) {
        const currentCode = layer.feature.properties.codigo;
        const newCode = promptForCode(currentCode);
        layer.feature.properties.codigo = newCode;
        console.debug('[EDIT] código actualizado:', currentCode, '->', newCode);
      }
      
      if (typeof applyStyleFromProperties === 'function') applyStyleFromProperties(layer);
      if (typeof enforceStrokePolicy === 'function') enforceStrokePolicy(layer);
    });
  }
});

// Desactivar recolor cuando entras a editar
map.on('draw:editstart', () => {
  isEditingActive = true;
  // si tienes un setter del UI de recolor, llámalo aquí para apagarlo visualmente
  if (typeof setRecolorMode === 'function') setRecolorMode(false);
});

// Volver a permitir recolor al salir
map.on('draw:editstop', () => {
  isEditingActive = false;
});

// IMPORT (función para agregar capas importadas)
function addImportedFeatureLayer(feature, layer) {
  layer._isImported = true;

  // Asegurar que tiene código, si no asignar uno automático
  if (!layer.feature) layer.feature = feature;
  if (!layer.feature.properties) layer.feature.properties = {};
  if (!layer.feature.properties.codigo) {
    layer.feature.properties.codigo = generateUniqueCode();
  }

  if (typeof applyStyleFromProperties === 'function') applyStyleFromProperties(layer);
  if (typeof enforceStrokePolicy === 'function') enforceStrokePolicy(layer);
  if (typeof attachRecolorOnClick === 'function') attachRecolorOnClick(layer);

  // Importados bloqueados por defecto:
  (allowImportedEdit ? DRAWN_EDITABLE : DRAWN_LOCKED).addLayer(layer);
}

// === GESTIÓN DE CÓDIGOS DE CUADRANTES ===

// Función para generar código automático único
function generateUniqueCode() {
  return `CUADRANTE_${Date.now()}`;
}

// Función para solicitar código al usuario
function promptForCode(currentCode = '') {
  const message = currentCode ? 
    `Código actual: ${currentCode}\n\nIngrese el nuevo código o identificador para este cuadrante:` :
    'Ingrese el código o identificador para este cuadrante:';
  
  const userInput = prompt(message, currentCode);
  
  // Si el usuario cancela o no ingresa nada, usar código automático
  if (userInput === null || userInput.trim() === '') {
    return generateUniqueCode();
  }
  
  return userInput.trim();
}

// Helper para recoger cuadrantes con estilo persistido
function collectQuadrantsFC() {
  const features = [];
  const collect = (group) => group.eachLayer((layer) => {
    if (!layer.toGeoJSON) return;
    // if (typeof persistStyleToProperties === 'function') persistStyleToProperties(layer);
    const f = layer.toGeoJSON();
    f.properties = Object.assign({}, layer.feature && layer.feature.properties || {});
    features.push(f);
  });
  collect(DRAWN_LOCKED);
  collect(DRAWN_EDITABLE);
  return { type: 'FeatureCollection', features };
}

// Helper para iterar todos los cuadrantes
function forEachQuadrantLayer(fn) {
  DRAWN_LOCKED.eachLayer(fn);
  DRAWN_EDITABLE.eachLayer(fn);
}

// Ajuste de vista tras importar
function fitToAllIfAny() {
  const bounds = L.latLngBounds([]);
  DRAWN_LOCKED.eachLayer(l => { if (l.getBounds) bounds.extend(l.getBounds()); });
  DRAWN_EDITABLE.eachLayer(l => { if (l.getBounds) bounds.extend(l.getBounds()); });
  if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
}

// Configurar controles cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', function() {
    // Construir paleta
    const paletteDiv = document.getElementById('palette');
    if (paletteDiv) {
      PALETTE.forEach((hex, i) => {
        const s = document.createElement('div');
        s.className = 'swatch' + (i===0 ? ' active' : '');
        s.style.background = hex;
        s.dataset.color = hex;
        s.addEventListener('click', () => {
          CURRENT_FILL = hex;
          [...paletteDiv.querySelectorAll('.swatch')].forEach(el => el.classList.toggle('active', el === s));
          // actualizar color por defecto del Draw
          drawControl.setDrawingOptions({
            polygon:   { shapeOptions: { color: '#000', weight: STROKE_WEIGHT, fillColor: CURRENT_FILL, fillOpacity: FILL_OPACITY } },
            rectangle: { shapeOptions: { color: '#000', weight: STROKE_WEIGHT, fillColor: CURRENT_FILL, fillOpacity: FILL_OPACITY } }
          });
        });
        paletteDiv.appendChild(s);
      });
      console.debug('Paleta de colores inicializada');
    }

// Función para controlar modo recolor desde código
function setRecolorMode(enabled) {
  recolorMode = !!enabled;
  const btnRecolor = document.getElementById('btn-recolor');
  if (btnRecolor) {
    btnRecolor.classList.toggle('btn-active', recolorMode);
    btnRecolor.textContent = recolorMode ? '✅ Recolor activo' : '🎨 Modo recolor';
  }
}

    // Botón recolor
    const btnRecolor = document.getElementById('btn-recolor');
    if (btnRecolor) {
      btnRecolor.addEventListener('click', () => {
        setRecolorMode(!recolorMode);
      });
      console.debug('Botón recolor configurado');
    }

    const exportBtn = document.getElementById('btn-export');
    if (exportBtn) {
        // Exportación combinada (comunas + cuadrantes)
        exportBtn.addEventListener('click', () => {
          const quadsFC = collectQuadrantsFC();
          const comunas = (COMUNAS_FC && Array.isArray(COMUNAS_FC.features)) ? COMUNAS_FC.features : [];
          const combined = {
            type: 'FeatureCollection',
            // Orden: comunas primero, luego cuadrantes
            features: [...comunas, ...quadsFC.features],
          };
          const fileName = `cuadrantes_${CITY.toLowerCase()}_${new Date().toISOString().slice(0,10)}.geojson`;

          // descarga "segura"
          const blob = new Blob([JSON.stringify(combined)], { type: 'application/geo+json' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = fileName;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);

          console.debug('[EXPORT] city=', CITY, 'comunas=', comunas.length, 'quadrants=', quadsFC.features.length, 'file=', fileName);
        });
        console.debug('Botón de exportación configurado');
    } else {
        console.warn('Botón con id "btn-export" no encontrado');
    }

    // Configurar botón de importación
    const importBtn = document.getElementById('btn-import');
    const fileInput = document.getElementById('file-import');
    
    if (importBtn && fileInput) {
        importBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', onImportFileChanged);
        console.debug('Botón de importación configurado');
    } else {
        console.warn('Botón de importación o input de archivo no encontrado');
    }

    // Configurar botón toggle para importados
    const btnToggleImported = document.getElementById('btn-toggle-imported');
    if (btnToggleImported) {
        btnToggleImported.addEventListener('click', () => setImportedEditable(!allowImportedEdit));
        setImportedEditable(true); // por defecto: editables
    }
});

// Función para manejar importación de archivos GeoJSON
async function onImportFileChanged(evt) {
    const file = evt.target.files?.[0];
    if (!file) return;
    
    try {
        // Leer archivo
        const text = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = e => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsText(file);
        });
        
        // Parsear JSON
        const data = JSON.parse(text);
        
        // Normalizar a FeatureCollection
        let features = [];
        if (data.type === 'FeatureCollection' && Array.isArray(data.features)) {
            features = data.features;
        } else if (data.type === 'Feature') {
            features = [data];
        } else {
            console.warn('[IMPORT] Formato no reconocido, esperaba FeatureCollection o Feature');
            return;
        }
        
        let total = features.length;
        let comunasFiltradas = 0;
        let noPoligonales = 0;
        let deduplicadas = 0;
        let agregadas = 0;
        
        // Obtener geometrías existentes para de-dupe
        const existingGeometries = new Set();
        forEachQuadrantLayer(layer => {
            if (layer.feature && layer.feature.geometry) {
                existingGeometries.add(JSON.stringify(layer.feature.geometry));
            }
        });
        
        // Procesar cada feature
        for (const feature of features) {
            if (!feature.geometry) continue;
            
            // Filtrar comunas (properties con NOMBRE, barrio o BARRIO)
            const props = feature.properties || {};
            if (props.NOMBRE || props.barrio || props.BARRIO) {
                comunasFiltradas++;
                continue;
            }
            
            // Solo geometrías poligonales
            const geomType = feature.geometry.type;
            if (!['Polygon', 'MultiPolygon'].includes(geomType)) {
                noPoligonales++;
                continue;
            }
            
            // Preparar polígonos para procesar
            let polygonsToProcess = [];
            
            if (geomType === 'Polygon') {
                polygonsToProcess.push({
                    type: 'Feature',
                    geometry: feature.geometry,
                    properties: { ...props }
                });
            } else if (geomType === 'MultiPolygon') {
                // Dividir MultiPolygon en varios Polygon
                feature.geometry.coordinates.forEach(polygonCoords => {
                    polygonsToProcess.push({
                        type: 'Feature',
                        geometry: {
                            type: 'Polygon',
                            coordinates: polygonCoords
                        },
                        properties: { ...props }
                    });
                });
            }
            
            // Procesar cada polígono
            for (const polygonFeature of polygonsToProcess) {
                // De-dupe por geometría
                const geomStr = JSON.stringify(polygonFeature.geometry);
                if (existingGeometries.has(geomStr)) {
                    deduplicadas++;
                    continue;
                }
                
                // Crear capa Leaflet
                const layer = L.geoJSON(polygonFeature, {
                    onEachFeature: (feat, lyr) => {
                        // Asignar feature al layer
                        lyr.feature = feat;
                        
                        // Aplicar estilos desde properties
                        applyStyleFromProperties(lyr);
                        
                        // Forzar política de borde
                        enforceStrokePolicy(lyr);
                        
                        // Agregar click handler para recolor
                        attachRecolorOnClick(lyr);
                    }
                }).getLayers()[0];
                
                if (layer) {
                    // Usar función específica para importados
                    addImportedFeatureLayer(feature, layer);
                    existingGeometries.add(geomStr);
                    agregadas++;
                }
            }
        }
        
        // Ajustar vista si se agregaron capas
        if (agregadas > 0) {
            try {
                fitToAllIfAny();
            } catch (e) {
                console.warn('[IMPORT] Error al ajustar vista:', e);
            }
        }
        
        // Log de resultados
        console.info('[IMPORT]', { total, comunasFiltradas, noPoligonales, deduplicadas, agregadas });
        
        // Resetear input para permitir reimportar el mismo archivo
        evt.target.value = '';
        
    } catch (error) {
        console.error('[IMPORT] Error al procesar archivo:', error);
        alert('Error al importar el archivo. Verifique que sea un GeoJSON válido.');
    }
}

console.debug('Editor de cuadrantes inicializado correctamente');
