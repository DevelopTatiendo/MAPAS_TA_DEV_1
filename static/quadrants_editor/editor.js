// Editor de cuadrantes - Leaflet con Draw y jerarquía cuadrante→subcuadrantes
// Inicialización del mapa centrado por ciudad
console.debug('Inicializando editor de cuadrantes...');

// Constante de opacidad fija para padres
const PARENT_FILL_OPACITY = 0.35; // 35% fijo

// Modo de exportación: 'none' | 'warn' | 'strict'
const EXPORT_VALIDATION_MODE = 'none'; // <<— modo "sin líos"

// === POLÍTICA DE VALIDACIÓN ===
const VALIDATION_POLICY = {
  blockOnChildrenOutside: false,
  blockOnCoverageIncomplete: false,
};

// === SISTEMA DE JERARQUÍA CUADRANTE→SUBCUADRANTES ===

// Estado del editor
const EditorState = {
  IDLE: 'idle',
  PADRE_ACTIVO: 'padre_activo', 
  CREANDO_PADRE: 'creando_padre',
  CREANDO_HIJO: 'creando_hijo',
  EDITANDO_PADRE: 'editando_padre',
  EDITANDO_HIJOS: 'editando_hijos'
};

// Estado global del editor (fuente única de verdad)
const state = {
  mode: EditorState.IDLE,
  activeParent: null, // Layer del cuadrante padre activo
  children: [], // Array de layers de subcuadrantes hijos del padre activo
  childrenGroup: null, // FeatureGroup para manejar hijos
  isAislado: false // Si está en modo aislar
};

// Extensión para múltiples padres
state.parents = state.parents || [];                 // lista de layers padre
state.childrenByParent = state.childrenByParent || {}; // { codigoPadre: Layer[] }
state.childGroupsByParent = state.childGroupsByParent || {}; // { codigoPadre: L.FeatureGroup }
state.selectedChild = null; // hijo seleccionado para eliminar

// Compatibilidad hacia atrás
let currentEditorState = EditorState.IDLE;
let activePadre = null;
let activeHijos = [];
let isAislado = false;
let padreOpacity = 0.4; // Opacidad del padre

// Sesión de edición activa (Leaflet.Draw)
let EDIT_SESSION = { tempGroup: null, handler: null };

// Backup para edición de hijos
let _childrenBackup = null;

// Configuración de tolerancias según T7 (en metros)
const TOLERANCIAS = {
  SNAP_DISTANCE: 1.0, // tol_snapping = 1.0 m
  MIN_AREA_RESTO: 0.5, // Área mínima para considerar resto válido
  MAX_OVERLAP_AREA: 0.01, // area_tol = 0.01 m²
  BUFFER_TOLERANCE: 0.5, // tol_m_valid = 0.5 m
  VALIDATION_TOLERANCE: 0.5 // tol_m_valid para validaciones
};

// Configuración de CRS según T7
const CRS_CONFIG = {
  INPUT_CRS: "EPSG:4326", // WGS84 - sistema de entrada
  METRIC_CRS: "EPSG:3116", // CRS métrico para áreas y buffers (Colombia)
  DISPLAY_CRS: "EPSG:4326" // Para visualización en Leaflet
};

// Metadata del sistema
const SYSTEM_METADATA = {
  VERSION: "3.0",
  EXPORT_TYPE_HIERARCHY: "hierarchy_export",
  EXPORT_TYPE_GENERAL: "general_export",
  NIVEL_PADRE: "cuadrante",
  NIVEL_HIJO: "subcuadrante"
};

// Estilo fijo para comunas: borde negro, sin relleno
const COMUNA_STYLE = {
  color: "#000000",
  weight: 1.5,
  fillOpacity: 0.0,
  fillColor: "transparent"
};

// Estilos para jerarquía
const PADRE_STYLE = {
  color: "#000000",
  weight: 3,
  fillOpacity: PARENT_FILL_OPACITY,
  fillColor: "#667eea",
  dashArray: "5, 5"
};

const HIJO_STYLE = {
  color: "#000000",
  weight: 2,
  fillOpacity: 0.6,
  fillColor: "#11998e"
};

const ERROR_STYLE = {
  OVERLAP: { color: "#ff6b35", weight: 3, fillColor: "#ff6b35", fillOpacity: 0.7 },
  GAP: { color: "#d63031", weight: 3, fillColor: "#d63031", fillOpacity: 0.7 },
  OUTSIDE: { color: "#d63031", weight: 3, fillColor: "#d63031", fillOpacity: 1.0 }
};

// Asegura que la feature tenga props de estilo persistentes según su nivel
function ensureStyleProps(featureOrLayer, isPadre = null) {
  const feat = featureOrLayer.feature ? featureOrLayer.feature : featureOrLayer;
  feat.properties = feat.properties || {};
  const p = feat.properties;

  // Determinar nivel
  const nivel = p.nivel || (isPadre === true ? 'cuadrante' : isPadre === false ? 'subcuadrante' : null);
  const defaults = (nivel === 'cuadrante') ? PADRE_STYLE : HIJO_STYLE;

  // Defaults una sola vez (si faltan)
  if (p.fillColor == null)   p.fillColor   = defaults.fillColor;
  if (p.fillOpacity == null) p.fillOpacity = defaults.fillOpacity;
  if (p.weight == null)      p.weight      = defaults.weight;
  if (p.color == null)       p.color       = (STROKE_POLICY === 'match') ? p.fillColor : '#000000';

  // Regrabar nivel si no venía
  if (!p.nivel && nivel) p.nivel = nivel;

  return p;
}

function ensureComunaStyleProps(props) {
  const p = Object.assign({}, props || {});
  p.color = p.color ?? COMUNA_STYLE.color;
  p.weight = p.weight ?? COMUNA_STYLE.weight;
  p.fillOpacity = p.fillOpacity ?? COMUNA_STYLE.fillOpacity;
  p.fillColor = p.fillColor ?? COMUNA_STYLE.fillColor;
  return p;
}

// === UTILIDADES PARA EXPORTACIÓN COMPLETA ===

// Detecta si un feature es un cuadrante válido (para exportación)
function isQuadrantFeature(f) {
  const p = f?.properties || {};
  if (p.nivel === 'cuadrante' || p.nivel === 'subcuadrante') return true;
  // Fallback para archivos antiguos
  return typeof p.codigo === 'string' && /^CL_/i.test(p.codigo);
}

// Convierte layer a feature preservando propiedades de estilo
function layerToFeature(layer) {
  // Asegura que layer.feature exista y que estilos estén persistidos en properties
  const f = layer.toGeoJSON();
  f.properties = layer.feature?.properties || f.properties || {};
  // NO modificar opacidades/colores aquí: respetar lo que venga
  return f;
}

// FC de comunas base de la ciudad actual
let COMUNAS_FC = null;

// === UTILIDADES GEOESPACIALES ===

// Calcular área de polígono usando fórmula de Shoelace (en m² aproximado)
function calculateArea(geojson) {
  if (!geojson || !geojson.geometry) return 0;
  
  let coords = [];
  if (geojson.geometry.type === 'Polygon') {
    coords = geojson.geometry.coordinates[0];
  } else if (geojson.geometry.type === 'MultiPolygon') {
    // Para MultiPolygon, sumar todas las áreas
    return geojson.geometry.coordinates.reduce((total, poly) => {
      return total + calculateArea({ geometry: { type: 'Polygon', coordinates: poly } });
    }, 0);
  } else {
    return 0;
  }
  
  if (!coords || coords.length < 3) return 0;
  
  // Fórmula de Shoelace para área de polígono
  let area = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const [x1, y1] = coords[i];
    const [x2, y2] = coords[i + 1];
    area += (x1 * y2 - x2 * y1);
  }
  
  // Conversión aproximada a m² usando factor de lat promedio
  const avgLat = coords.reduce((sum, coord) => sum + coord[1], 0) / coords.length;
  const latFactor = Math.cos(avgLat * Math.PI / 180);
  const meterPerDegree = 111320;
  
  return Math.abs(area * meterPerDegree * meterPerDegree * latFactor / 2);
}

// Verificar intersección básica entre dos polígonos
function intersectGeometries(geom1, geom2) {
  // Implementación básica usando detección de vértices
  if (!geom1 || !geom2) return null;
  
  const coords1 = geom1.geometry.coordinates[0];
  const coords2 = geom2.geometry.coordinates[0];
  
  // Verificar si algún vértice de geom1 está dentro de geom2
  for (const point of coords1) {
    if (pointInPolygon(point, geom2)) {
      // Hay intersección, devolver una geometría aproximada
      return {
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [coords1.slice(0, 4)] // Intersección aproximada
        }
      };
    }
  }
  
  return null;
}

// Diferencia aproximada entre geometrías
function differenceGeometries(geom1, geom2) {
  // Por simplicidad, devolver la geometría original
  // En producción, usar turf.difference()
  return geom1;
}

// Unión de múltiples geometrías (aproximada)
function unionGeometries(geometries) {
  if (!geometries || geometries.length === 0) return null;
  
  // Devolver el primer polígono como aproximación
  // En producción, usar turf.union()
  return geometries[0];
}

// Buffer de geometría (simplificado)
function bufferGeometry(geojson, distance) {
  // Para buffer = 0, limpiar la geometría devolviendo la original
  if (distance === 0) return geojson;
  
  // En producción, usar turf.buffer()
  return geojson;
}

// Verificar si un punto está dentro de un polígono (Ray casting algorithm)
function pointInPolygon(point, polygon) {
  const [x, y] = point;
  let coords = [];
  
  if (polygon.geometry.type === 'Polygon') {
    coords = polygon.geometry.coordinates[0];
  } else {
    return false;
  }
  
  let inside = false;
  
  for (let i = 0, j = coords.length - 1; i < coords.length; j = i++) {
    const [xi, yi] = coords[i];
    const [xj, yj] = coords[j];
    
    if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
      inside = !inside;
    }
  }
  
  return inside;
}

// Verificar si una geometría está completamente dentro de otra
function geometryWithin(inner, outer) {
  if (!inner || !outer) return false;
  
  const innerCoords = inner.geometry.coordinates[0];
  
  // Verificar que todos los vértices del polígono interior estén dentro del exterior
  for (const point of innerCoords) {
    if (!pointInPolygon(point, outer)) {
      return false;
    }
  }
  
  return true;
}

// Calcular centroide aproximado de un polígono
function calculateCentroid(geojson) {
  if (!geojson || !geojson.geometry) return null;
  
  const coords = geojson.geometry.coordinates[0];
  let x = 0, y = 0;
  
  for (const coord of coords) {
    x += coord[0];
    y += coord[1];
  }
  
  return [x / coords.length, y / coords.length];
}

// === GESTIÓN DE CÓDIGOS ===

// Generar próximo código de cuadrante disponible
function generateNextCuadranteCode(ciudad, ruta) {
  const existingCodes = getAllExistingCodes();
  const prefix = `CL_${ruta}_`;
  
  let nextNum = 1;
  while (existingCodes.includes(`${prefix}${String(nextNum).padStart(2, '0')}`)) {
    nextNum++;
  }
  
  return `${prefix}${String(nextNum).padStart(2, '0')}`;
}

// Generar próximo código de subcuadrante
function generateNextSubcuadranteCode(codigoPadre) {
  const existingCodes = getAllExistingCodes();
  const prefix = `${codigoPadre}_S`;
  
  let nextNum = 1;
  while (existingCodes.includes(`${prefix}${String(nextNum).padStart(2, '0')}`)) {
    nextNum++;
  }
  
  return `${prefix}${String(nextNum).padStart(2, '0')}`;
}

// Obtener todos los códigos existentes
function getAllExistingCodes() {
  const codes = [];
  
  // Revisar cuadrantes padre
  if (activePadre && activePadre.feature && activePadre.feature.properties.codigo) {
    codes.push(activePadre.feature.properties.codigo);
  }
  
  // Revisar subcuadrantes hijos
  activeHijos.forEach(hijo => {
    if (hijo.feature && hijo.feature.properties.codigo) {
      codes.push(hijo.feature.properties.codigo);
    }
  });
  
  // Revisar otras capas existentes
  DRAWN_EDITABLE.eachLayer(layer => {
    if (layer.feature && layer.feature.properties.codigo) {
      codes.push(layer.feature.properties.codigo);
    }
  });
  
  DRAWN_LOCKED.eachLayer(layer => {
    if (layer.feature && layer.feature.properties.codigo) {
      codes.push(layer.feature.properties.codigo);
    }
  });
  
  return codes;
}

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



// Track del estado de edición de Leaflet.Draw
let isEditingActive = false;

// === FUNCIÓN GLOBAL PARA CONTROLAR MODO RECOLOR ===

// Función global para controlar modo recolor (one-shot)
function setRecolorMode(enabled) {
  recolorMode = !!enabled;
  const btnRecolor = document.getElementById('btn-recolor');
  if (btnRecolor) {
    btnRecolor.classList.toggle('btn-active', recolorMode);
    btnRecolor.textContent = recolorMode ? '✅ Recolor activo' : '🎨 Modo recolor';
  }
  
  // Cambiar cursor del mapa
  const mapContainer = document.getElementById('map');
  if (mapContainer) {
    mapContainer.style.cursor = recolorMode ? 'pointer' : '';
  }
  
  console.debug('[RECOLOR]', recolorMode ? 'Activado (one-shot)' : 'Desactivado');
}

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
    edit: { 
        featureGroup: DRAWN_EDITABLE,
        remove: false // Desactivar eliminación masiva
    }
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
  const defaults = (p.nivel === 'cuadrante') ? PADRE_STYLE : HIJO_STYLE;

  const style = {
    fillColor:   (p.fillColor != null)   ? p.fillColor   : defaults.fillColor,
    color:       (STROKE_POLICY === 'match') ? ((p.fillColor != null) ? p.fillColor : defaults.fillColor) : '#000000',
    fillOpacity: (p.fillOpacity != null) ? p.fillOpacity : defaults.fillOpacity,
    weight:      (p.weight != null)      ? p.weight      : defaults.weight
  };
  if (layer.setStyle) layer.setStyle(style);
}

// Click para recolor si el modo está activo (one-shot)
let recolorMode = false;
function attachRecolorOnClick(layer) {
  layer.on('click', () => {
    if (isEditingActive) return; // No recolor durante edición
    if (!recolorMode) return; // Solo si modo está activo
    
    // Opcional: restringir al padre activo cuando está aislado
    if (state.isAislado && state.activeParent && !isLayerOfActiveParent(layer)) return;
    
    // Aplicar color, preservando opacidad existente
    layer.feature = layer.feature || { type:'Feature', properties:{} };
    const p = layer.feature.properties;
    const prevOpacity = p.fillOpacity; // conservar
    p.fillColor = CURRENT_FILL;
    if (prevOpacity != null) p.fillOpacity = prevOpacity; // reforzar
    applyStyleFromProperties(layer);
    enforceStrokePolicy(layer);
    
    // Apagar modo recolor (one-shot)
    setRecolorMode(false);
  });
}

// Verificar si una capa pertenece al padre activo
function isLayerOfActiveParent(layer) {
  if (!state.activeParent) return false;
  
  const activeCode = state.activeParent.feature?.properties?.codigo;
  if (!activeCode) return false;
  
  const layerCode = layer.feature?.properties?.codigo;
  const layerParentCode = layer.feature?.properties?.codigo_padre;
  
  // Es el padre activo o es hijo del padre activo
  return (layerCode === activeCode) || (layerParentCode === activeCode);
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

// === MANEJO DE HERRAMIENTAS DE DIBUJO ===

// Activar modo de dibujo
function enableDrawingMode(type) {
  // Activar la herramienta de dibujo correspondiente
  if (type === 'polygon') {
    // Simular click en botón de polígono de Leaflet.Draw
    const polygonButton = document.querySelector('.leaflet-draw-draw-polygon');
    if (polygonButton && !polygonButton.classList.contains('leaflet-draw-toolbar-button-enabled')) {
      polygonButton.click();
    }
  }
}

// Desactivar modo de dibujo
function disableDrawingMode() {
  // Cancelar cualquier herramienta de dibujo activa
  const activeButtons = document.querySelectorAll('.leaflet-draw-toolbar-button-enabled');
  activeButtons.forEach(btn => btn.click());
}

// === MANEJO DE EVENTOS DE DIBUJO MEJORADO ===

// Handler principal para creación de elementos
map.on(L.Draw.Event.CREATED, (e) => {
  const layer = e.layer;
  layer.feature = layer.feature || { type:'Feature', properties:{} };
  
  if (state.mode === EditorState.CREANDO_PADRE) {
    // Crear cuadrante padre
    handlePadreCreated(layer);
  } else if (state.mode === EditorState.CREANDO_HIJO) {
    // Crear subcuadrante hijo
    onChildCreated(e);
  } else {
    // Comportamiento original para otros casos
    layer.feature.properties.fillColor = CURRENT_FILL;
    const codigo = generateUniqueCode();
    layer.feature.properties.codigo = codigo;
    
    if (typeof enforceStrokePolicy === 'function') enforceStrokePolicy(layer);
    if (typeof applyStyleFromProperties === 'function') applyStyleFromProperties(layer);
    if (typeof attachRecolorOnClick === 'function') attachRecolorOnClick(layer);

    DRAWN_EDITABLE.addLayer(layer);
    console.debug('[DRAW] created -> editable layers:', DRAWN_EDITABLE.getLayers().length, 'codigo:', codigo);
  }
});

// Handler para cuando se termina cualquier dibujo
map.on(L.Draw.Event.DRAWSTOP, onDrawStopForAnyMode);

// Función para manejar creación de hijos
function onChildCreated(e) {
  if (state.mode !== EditorState.CREANDO_HIJO) return;

  const layer = e.layer;

  // 1) Validar que esté dentro del padre activo
  if (!isInsideParent(layer, state.activeParent)) {
    alert('El subcuadrante debe quedar completamente dentro del padre activo.');
    if (layer.remove) layer.remove();
    setEditorState(EditorState.PADRE_ACTIVO);
    return;
  }

  // 2) Preparar layer.feature.properties si no existe
  if (!layer.feature) layer.feature = { type: 'Feature', properties: {}, geometry: null };

  // 3) Obtener idRuta del padre
  const parentProps = state.activeParent?.feature?.properties || {};
  const parentCode = parentProps.codigo || 'PADRE';
  let idRuta = parentProps.id_ruta;
  
  // Si no tiene id_ruta, intentar extraer del código (ej: CL_3 -> ruta 3)
  if (!idRuta) {
    const match = parentCode.match(/CL_(\d+)/);
    idRuta = match ? match[1] : '1';
  }

  // 4) Crear sugerencia
  const sugerido = suggestedChildCode();

  // 5) Abrir el modal
  openChildCodeModal({
    ruta: idRuta,
    padre: parentCode,
    sugerido: sugerido,
    onCancel: () => { 
      layer.remove(); 
      setEditorState(EditorState.PADRE_ACTIVO); 
    },
    onSave: (codigo) => {
      const code = sanitizeCode(codigo);
      
      // Validar formato
      const validation = validateChildCode(code);
      if (!validation.valid) {
        alert(validation.message);
        return false; // no cerrar
      }
      
      if (isChildCodeTaken(code, state.children)) {
        alert('Ese código ya existe en este padre.');
        return false; // no cerrar
      }
      
      // Asignar propiedades
      const p = layer.feature.properties;
      p.codigo = code;
      p.nivel = 'subcuadrante';
      p.tipo = 'HIJO';
      p.codigo_padre = parentCode;
      p.id_ruta = idRuta;
      p.ciudad = parentProps.ciudad || getCityFromQuery();
      
      // Persistir props de estilo en properties
      ensureStyleProps(layer, false);
      applyStyleFromProperties(layer);
      enforceStrokePolicy(layer);
      
      // Agregar al mapa
      addChildLayer(layer);
      setEditorState(EditorState.PADRE_ACTIVO);
      return true; // cerrar modal
    }
  });
}

// Función para manejar fin de dibujo
function onDrawStopForAnyMode() {
  // Si por cualquier motivo se abortó el dibujo de hijo,
  // regresamos a un estado sano (evita quedar bloqueado)
  if (state.mode === EditorState.CREANDO_HIJO) {
    setEditorState(EditorState.PADRE_ACTIVO);
  } else if (state.mode === EditorState.CREANDO_PADRE) {
    setEditorState(EditorState.IDLE);
  }
}

// Persistir estilo tras edición
map.on(L.Draw.Event.EDITED, (e) => {
  if (e.layers && e.layers.eachLayer) {
    e.layers.eachLayer((layer) => {
      // Mantener código existente (sin prompt)
      if (layer.feature && layer.feature.properties && !layer.feature.properties.codigo) {
        layer.feature.properties.codigo = generateUniqueCode();
        console.debug('[EDIT] código generado automáticamente:', layer.feature.properties.codigo);
      }
      
      if (typeof applyStyleFromProperties === 'function') applyStyleFromProperties(layer);
      if (typeof enforceStrokePolicy === 'function') enforceStrokePolicy(layer);
    });
  }
});

// Desactivar recolor cuando entras a editar
map.on('draw:editstart', () => {
  isEditingActive = true;
  setRecolorMode(false);
});

// Al salir de edición, NO reactivar recolor automáticamente
map.on('draw:editstop', () => {
  isEditingActive = false;
  // Mantener recolor apagado hasta que usuario lo active manualmente
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

  // Agregar a capa editable
  DRAWN_EDITABLE.addLayer(layer);
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

// === VALIDACIÓN DE INTEGRIDAD ===

// Validar integridad de subcuadrantes
function validarIntegridadSubcuadrantes(geomPadre, geomsHijos, tolM = TOLERANCIAS.BUFFER_TOLERANCE) {
  const errores = [];
  const warnings = [];
  let geojsonDebug = { type: 'FeatureCollection', features: [] };
  
  if (!geomPadre) {
    errores.push('No hay cuadrante padre definido');
    return { ok: false, errores, warnings, geojsonDebug };
  }
  
  if (!geomsHijos || geomsHijos.length === 0) {
    errores.push('No hay subcuadrantes definidos');
    return { ok: false, errores, warnings, geojsonDebug };
  }
  
  const areaPadre = calculateArea(geomPadre);
  
  // 1. Verificar que todos los hijos están dentro del padre
  geomsHijos.forEach((hijo, i) => {
    const areaHijo = calculateArea(hijo);
    
    // Verificar si está dentro del padre (simplificado)
    // En implementación real, usar turf.booleanWithin()
    if (areaHijo > areaPadre * 0.1) { // Si el hijo es > 10% del padre, probablemente está mal
      const hijoFueraGeom = {
        type: 'Feature',
        geometry: hijo.geometry,
        properties: { 
          error: 'outside_parent',
          message: `Subcuadrante ${i + 1} se extiende fuera del cuadrante padre`
        }
      };
      geojsonDebug.features.push(hijoFueraGeom);
      
      warnings.push(`Subcuadrante ${i + 1} se extiende fuera del cuadrante padre`);
    }
  });
  
  // 2. Verificar solapes entre hijos
  for (let i = 0; i < geomsHijos.length; i++) {
    for (let j = i + 1; j < geomsHijos.length; j++) {
      // En implementación real, usar turf.intersect()
      const overlap = intersectGeometries(geomsHijos[i], geomsHijos[j]);
      if (overlap && calculateArea(overlap) > TOLERANCIAS.MAX_OVERLAP_AREA) {
        const overlapGeom = {
          type: 'Feature',
          geometry: overlap.geometry,
          properties: {
            error: 'overlap',
            message: `Solape entre subcuadrantes ${i + 1} y ${j + 1}`
          }
        };
        geojsonDebug.features.push(overlapGeom);
        warnings.push(`Solape detectado entre subcuadrantes ${i + 1} y ${j + 1}`);
      }
    }
  }
  
  // 3. Verificar cobertura total
  const unionHijos = unionGeometries(geomsHijos);
  const huecos = differenceGeometries(geomPadre, unionHijos);
  
  if (huecos && calculateArea(huecos) > TOLERANCIAS.MIN_AREA_RESTO) {
    const huecosGeom = {
      type: 'Feature',
      geometry: huecos.geometry,
      properties: {
        error: 'gaps',
        message: 'Áreas no cubiertas por subcuadrantes'
      }
    };
    geojsonDebug.features.push(huecosGeom);
    warnings.push('Existen áreas no cubiertas por los subcuadrantes');
  }
  
  // Calcular cobertura
  const areaUnionHijos = calculateArea(unionHijos);
  const cobertura = (areaUnionHijos / areaPadre) * 100;
  
  if (cobertura < 100) {
    warnings.push(`Cobertura incompleta: ${cobertura.toFixed(1)}%`);
  }
  
  const ok = errores.length === 0;
  
  console.debug('[VALIDACION]', { ok, errores: errores.length, warnings: warnings.length, cobertura: cobertura.toFixed(1) });
  
  return { ok, errores, warnings, geojsonDebug, cobertura };
}

// === GESTIÓN DE ESTADO DEL EDITOR ===

// === FUNCIONES PARA CÓDIGOS DE SUBCUADRANTES ===

// Mapeo de ciudades a prefijos
const CITY_PREFIX = {
  'CALI': 'CL', 'BOGOTA': 'BO', 'BOGOTÁ': 'BO', 'MEDELLIN': 'ME', 'MEDELLÍN': 'ME',
  'BARRANQUILLA': 'BA', 'MANIZALES': 'MZ', 'PEREIRA': 'PE', 'BUCARAMANGA': 'BU'
};

// Obtener prefijo de ciudad desde URL
function cityPrefix() {
  const p = new URLSearchParams(location.search).get('city') || '';
  return CITY_PREFIX[p.toUpperCase()] || p.slice(0, 2).toUpperCase();
}

// Contador por padre para códigos únicos
if (!window.state) window.state = {};
state.childCounters = state.childCounters || {};

// Generar siguiente índice de subcuadrante
function nextChildIndex(parentCode, children) {
  if (!(parentCode in state.childCounters)) {
    const max = (children || [])
      .map(ch => (ch.feature?.properties?.codigo || '').match(/_S(\d{2})$/))
      .filter(Boolean).map(m => parseInt(m[1], 10))
      .reduce((a, b) => Math.max(a, b), 0);
    state.childCounters[parentCode] = max + 1;
  }
  return state.childCounters[parentCode]++; // 1, 2, 3...
}

// Generar sugerencia de código de subcuadrante
function suggestedChildCode() {
  const parent = state.activeParent;
  const propsP = parent?.feature?.properties || {};
  const city = cityPrefix(); // 'CL'
  const ruta = propsP.id_ruta ?? (parseInt((propsP.codigo || '').split('_')[1], 10) || 0);
  const cuad = (propsP.cuadrante || ((propsP.codigo || '').split('_')[2] || '01')).toString().padStart(2, '0');

  const idx = nextChildIndex(propsP.codigo, state.children);
  const sub = `S${String(idx).padStart(2, '0')}`;
  return `${city}_${ruta}_${cuad}_${sub}`; // ej. CL_1_01_S01
}

// Verificar si un código ya está en uso
function isChildCodeTaken(code, children) {
  return (children || []).some(c => c.feature?.properties?.codigo === code);
}

// Sanitizar código
function sanitizeCode(code) {
  return (code || '').toUpperCase().trim();
}

// Validar formato de código de subcuadrante
function validateChildCode(code) {
  if (!code || code.trim() === '') {
    return { valid: false, message: 'El código no puede estar vacío' };
  }
  
  // Formato esperado: ^[A-Z]{2}_\d+_\d{2}_S\d{2}$
  const pattern = /^[A-Z]{2}_\d+_\d{2}_S\d{2}$/;
  if (!pattern.test(code.trim())) {
    return { valid: false, message: 'Formato inválido. Use: CL_1_01_S01' };
  }
  
  return { valid: true };
}

// === MODAL SIMPLIFICADO PARA CÓDIGO DE SUBCUADRANTES ===

let modalChildOptions = null; // Opciones del modal actual

// Abrir modal para código de hijo
function openChildCodeModal(opts) {
  modalChildOptions = opts;
  
  // Extraer componentes del código sugerido
  const codigo = opts.sugerido || '';
  const parts = codigo.split('_');
  const ciudad = parts[0] || cityPrefix();
  const ruta = parts[1] || opts.ruta || '1';
  const cuadrante = parts[2] || '01';
  
  // Llenar campos
  document.getElementById('hijo-ciudad').value = ciudad;
  document.getElementById('hijo-ruta').value = ruta;
  document.getElementById('hijo-cuadrante').value = cuadrante;
  document.getElementById('hijo-codigo').value = opts.sugerido;
  
  // Mostrar modal
  const modal = document.getElementById('modal-codigo-hijo');
  modal.classList.remove('hidden');
  
  // Focus en el input de código
  setTimeout(() => {
    document.getElementById('hijo-codigo').select();
  }, 100);
  
  console.debug('[MODAL]', 'Modal de código de hijo abierto', opts);
}

// Cerrar modal de código de hijo
function closeChildCodeModal() {
  const modal = document.getElementById('modal-codigo-hijo');
  modal.classList.add('hidden');
  modalChildOptions = null;
}

// Asignar código único a un subcuadrante (versión actualizada)
function assignChildCode(layer) {
  // Esta función ya no se usa directamente, 
  // el flujo ahora es manejado por onChildCreated() -> openChildCodeModal()
  console.warn('[DEPRECATED] assignChildCode() - usar onChildCreated() en su lugar');
}

// Añadir hijo al padre activo
function addChildLayer(layer) {
  // Normaliza geometry GeoJSON de la capa
  layer.feature.geometry = layer.toGeoJSON().geometry;

  // Obtener código del padre activo
  const parentCode = state.activeParent?.feature?.properties?.codigo;
  if (!parentCode) {
    console.warn('[CHILD_ADDED] No hay padre activo, no se puede agregar hijo');
    return;
  }

  // Crear grupo de hijos para este padre si no existe
  if (!state.childGroupsByParent[parentCode]) {
    const childGroup = new L.FeatureGroup();
    state.childGroupsByParent[parentCode] = childGroup;
    map.addLayer(childGroup);
  }

  // Agregar al grupo específico del padre
  state.childGroupsByParent[parentCode].addLayer(layer);

  // Persistir la asociación hijo→padre
  state.childrenByParent[parentCode] = state.childrenByParent[parentCode] || [];
  state.childrenByParent[parentCode].push(layer);

  // Actualizar estado actual (compatibilidad)
  state.children = state.childrenByParent[parentCode];
  activeHijos = state.children;

  // Actualizar grupo de hijos actual
  state.childrenGroup = state.childGroupsByParent[parentCode];

  // Popup sencillo
  const code = layer.feature.properties?.codigo || '(sin código)';
  layer.bindPopup(`<b>Subcuadrante</b><br>Código: ${code}`);
  
  // Agregar funcionalidad de recolor
  attachRecolorOnClick(layer);
  
  // Registrar hijo para selección y eliminación
  registerChild(layer, parentCode);
  
  console.debug('[CHILD_ADDED]', `Hijo "${code}" agregado al padre "${parentCode}"`);
}

// === FUNCIONES PARA EDICIÓN DEL PADRE ===

// Validar que todos los hijos estén dentro del padre
function validateChildrenWithinParent(parentGeom, children) {
  const errors = [];
  for (const ch of (children || [])) {
    const chGeom = ch.toGeoJSON().geometry;
    let ok = false;
    
    try {
      if (window.turf) {
        ok = turf.booleanWithin(chGeom, parentGeom) || turf.booleanContains(parentGeom, chGeom);
      } else {
        // Fallback: verificar bounds
        const childBounds = ch.getBounds();
        const parentLayer = L.geoJSON({type: 'Feature', geometry: parentGeom});
        const parentBounds = parentLayer.getBounds();
        ok = parentBounds.contains(childBounds);
      }
    } catch (error) {
      console.warn('[VALIDATION] Error validando hijo:', error);
      ok = true; // En caso de error, permitir
    }
    
    if (!ok) {
      errors.push(ch);
    }
  }
  return errors;
}

// Resaltar hijos con error
function highlightErrorChildren(errorChildren) {
  errorChildren.forEach(child => {
    child.setStyle({
      color: '#ff0000',
      weight: 3,
      dashArray: '10, 5'
    });
  });
}

// Limpiar resaltado de hijos
function clearChildrenHighlight(children) {
  (children || []).forEach(child => {
    child.setStyle({
      color: '#666',
      weight: 2,
      dashArray: null
    });
  });
}

// Iniciar edición del padre
function startParentEditing() {
  if (!state.activeParent) return;
  
  // Guardar backup de la geometría
  state._parentBackup = state.activeParent.toGeoJSON().geometry;
  
  // Cambiar estado
  setEditorState(EditorState.EDITANDO_PADRE);
  
  // Habilitar edición solo del padre
  enableEditMode([state.activeParent]);
  
  console.debug('[EDIT_PARENT] Iniciando edición del padre');
}

// Guardar cambios del padre
function saveParentEditing() {
  if (!state.activeParent || state.mode !== EditorState.EDITANDO_PADRE) return;
  
  const padreGeom = state.activeParent.toGeoJSON().geometry;
  
  // Validar que todos los hijos estén dentro
  const errors = validateChildrenWithinParent(padreGeom, state.children);
  
  if (errors.length > 0) {
    // Resaltar hijos problemáticos
    highlightErrorChildren(errors);
    
    const codes = errors.map(ch => ch.feature?.properties?.codigo || 'Sin código').join(', ');
    alert(`Hay subcuadrantes fuera del padre: ${codes}. Ajusta el padre o corrige esos hijos antes de guardar.`);
    
    return; // No salir del modo edición
  }
  
  // Limpiar cualquier resaltado
  clearChildrenHighlight(state.children);
  
  // Persistir la geometría nueva
  state.activeParent.feature.geometry = padreGeom;
  
  // Limpiar backup
  state._parentBackup = null;
  
  // Cerrar edición visual y volver a estado normal
  endEditMode(true);
  
  // Restaurar opacidad fija del padre
  state.activeParent.setStyle({ fillOpacity: PARENT_FILL_OPACITY });
  
  setEditorState(EditorState.PADRE_ACTIVO);
  
  // Apagar recolor al guardar
  setRecolorMode(false);
  
  console.debug('[EDIT_PARENT] Cambios guardados correctamente');
}

// Cancelar edición del padre
function cancelParentEditing() {
  if (!state.activeParent || state.mode !== EditorState.EDITANDO_PADRE) return;
  
  // Restaurar geometría desde backup
  if (state._parentBackup) {
    const restored = L.geoJSON({ 
      type: 'Feature', 
      properties: state.activeParent.feature.properties, 
      geometry: state._parentBackup 
    });
    
    const restoredLayer = restored.getLayers()[0];
    state.activeParent.setLatLngs(restoredLayer.getLatLngs());
  }
  
  // Limpiar backup
  state._parentBackup = null;
  
  // Limpiar cualquier resaltado
  clearChildrenHighlight(state.children);
  
  // Cerrar edición visual y volver a estado normal
  endEditMode(false);
  
  // Restaurar opacidad fija del padre
  state.activeParent.setStyle({ fillOpacity: PARENT_FILL_OPACITY });
  
  setEditorState(EditorState.PADRE_ACTIVO);
  
  // Apagar recolor al cancelar
  setRecolorMode(false);
  
  console.debug('[EDIT_PARENT] Edición cancelada');
}

// === FUNCIONES PARA EDICIÓN DE HIJOS ===

// Iniciar edición de hijos
function startChildrenEditing() {
  if (!activeHijos || activeHijos.length === 0) return;
  // backup geometrías
  _childrenBackup = activeHijos.map(l => l.toGeoJSON().geometry);
  setEditorState(EditorState.EDITANDO_HIJOS);
  enableEditMode(activeHijos);
  console.debug('[EDIT_CHILDREN] Iniciando edición de hijos');
}

// Guardar cambios de hijos
function saveChildrenEditing() {
  if (!activePadre) return;
  const parentGeom = activePadre.toGeoJSON().geometry;

  // validar cada hijo
  const fuera = [];
  activeHijos.forEach(h => {
    const g = h.toGeoJSON().geometry;
    const ok = (window.turf)
      ? turf.booleanWithin(g, parentGeom) || turf.booleanContains(parentGeom, g)
      : activePadre.getBounds().contains(h.getBounds());
    if (!ok) fuera.push(h);
  });

  if (fuera.length) {
    fuera.forEach(h => h.setStyle({ color:'#ff0000', dashArray:'10,5' }));
    alert('Hay subcuadrantes fuera del padre. Corrige antes de guardar.');
    return;
  }

  // persistir (ya quedan en la capa), limpiar y salir
  activeHijos.forEach(h => h.setStyle({ dashArray:null, color:'#000' }));
  _childrenBackup = null;
  endEditMode(true);
  setEditorState(EditorState.PADRE_ACTIVO);
  setRecolorMode(false); // Apagar recolor al guardar
  console.debug('[EDIT_CHILDREN] Cambios guardados correctamente');
}

// Cancelar edición de hijos
function cancelChildrenEditing() {
  if (_childrenBackup && _childrenBackup.length === activeHijos.length) {
    activeHijos.forEach((h, i) => {
      const restored = L.geoJSON({ type:'Feature', properties:h.feature.properties, geometry:_childrenBackup[i]}).getLayers()[0];
      h.setLatLngs(restored.getLatLngs());
    });
  }
  _childrenBackup = null;
  endEditMode(false);
  setEditorState(EditorState.PADRE_ACTIVO);
  setRecolorMode(false); // Apagar recolor al cancelar
  console.debug('[EDIT_CHILDREN] Edición cancelada');
}

// Validar si el hijo está dentro del padre usando Turf
function isInsideParent(childLayer, parentLayer) {
  if (!parentLayer) return false;
  
  try {
    if (window.turf) {
      const childGeoJSON = childLayer.toGeoJSON();
      const parentGeoJSON = parentLayer.toGeoJSON();
      return turf.booleanContains(parentGeoJSON, childGeoJSON) || 
             turf.booleanWithin(childGeoJSON, parentGeoJSON);
    } else {
      // Fallback: verificar que al menos el centroide esté dentro
      const childBounds = childLayer.getBounds();
      const parentBounds = parentLayer.getBounds();
      return parentBounds.contains(childBounds);
    }
  } catch (error) {
    console.warn('[VALIDATION] Error validando contención:', error);
    return true; // Permitir en caso de error
  }
}

// === GESTIÓN DE ESTADO MEJORADA ===

// Cambiar estado del editor (versión mejorada)
function setEditorState(next) {
  // Apagar recolor al cambiar a estados de dibujo/edición
  if ([EditorState.CREANDO_PADRE, EditorState.CREANDO_HIJO, EditorState.EDITANDO_PADRE, EditorState.EDITANDO_HIJOS].includes(next)) {
    setRecolorMode(false);
  }
  
  const prevState = state.mode;
  state.mode = next;
  
  // Mantener compatibilidad
  currentEditorState = next;
  activePadre = state.activeParent;
  activeHijos = state.children;
  isAislado = state.isAislado;
  
  console.debug('[STATE]', prevState, '->', next);

  const dis = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!v;
  };

  // baseline según contexto
  const hasParent = !!state.activeParent;
  const hasChildren = (state.children?.length || 0) > 0;

  dis('btn-crear-padre', false);
  dis('btn-crear-hijo', !hasParent);
  dis('btn-editar-padre', !hasParent);
  dis('btn-editar-hijo', !hasChildren);
  
  // Controles adicionales
  dis('btn-aislar', !hasParent);
  // Removed opacity slider references
  
  // Controles de eliminación
  dis('btn-delete-parent', !hasParent);
  const btnDelChild = document.getElementById('btn-delete-child');
  if (btnDelChild) {
    // visible sólo cuando haya selección
    btnDelChild.disabled = !state.selectedChild;
    if (!state.selectedChild) {
      btnDelChild.style.display = 'none';
    }
  }

  // overrides por modo
  if (next === EditorState.CREANDO_HIJO) {
    // mientras dibujo un hijo, bloqueo crear otro padre e impedir editar padre
    dis('btn-crear-padre', true);
    dis('btn-editar-padre', true);
    
    // Activar herramienta de dibujo
    enableDrawingMode('polygon');
  }

  if (next === EditorState.PADRE_ACTIVO || next === EditorState.IDLE) {
    // Reactivar todo lo que dependa del padre
    dis('btn-crear-hijo', !hasParent);
    dis('btn-editar-padre', !hasParent);
    dis('btn-editar-hijo', !hasChildren);
    
    // Desactivar herramientas de dibujo si estamos en IDLE
    if (next === EditorState.IDLE) {
      disableDrawingMode();
    }
  }
  
  if (next === EditorState.CREANDO_PADRE) {
    enableDrawingMode('polygon');
  }
  
  // Manejo específico para EDITANDO_PADRE
  if (next === EditorState.EDITANDO_PADRE) {
    // Deshabilitar acciones peligrosas
    dis('btn-crear-padre', true);
    dis('btn-crear-hijo', true);
    
    // Mostrar botones de guardar/cancelar, ocultar editar
    const btnEditarPadre = document.getElementById('btn-editar-padre');
    const btnGuardarPadre = document.getElementById('btn-guardar-padre');
    const btnCancelarEdicion = document.getElementById('btn-cancelar-edicion-padre');
    
    if (btnEditarPadre) btnEditarPadre.style.display = 'none';
    if (btnGuardarPadre) btnGuardarPadre.style.display = 'inline-block';
    if (btnCancelarEdicion) btnCancelarEdicion.style.display = 'inline-block';
  } else {
    // Restaurar botones normales
    const btnEditarPadre = document.getElementById('btn-editar-padre');
    const btnGuardarPadre = document.getElementById('btn-guardar-padre');
    const btnCancelarEdicion = document.getElementById('btn-cancelar-edicion-padre');
    
    if (btnEditarPadre) btnEditarPadre.style.display = 'inline-block';
    if (btnGuardarPadre) btnGuardarPadre.style.display = 'none';
    if (btnCancelarEdicion) btnCancelarEdicion.style.display = 'none';
  }
  
  // Manejo específico para EDITANDO_HIJOS
  const btnEditarHijo = document.getElementById('btn-editar-hijo');
  const btnGuardarHijo = document.getElementById('btn-guardar-hijo');
  const btnCancelarHijo = document.getElementById('btn-cancelar-edicion-hijo');

  if (next === EditorState.EDITANDO_HIJOS) {
    if (btnEditarHijo) btnEditarHijo.style.display = 'none';
    if (btnGuardarHijo) btnGuardarHijo.style.display = 'inline-block';
    if (btnCancelarHijo) btnCancelarHijo.style.display = 'inline-block';
  } else {
    if (btnEditarHijo) btnEditarHijo.style.display = 'inline-block';
    if (btnGuardarHijo) btnGuardarHijo.style.display = 'none';
    if (btnCancelarHijo) btnCancelarHijo.style.display = 'none';
  }
  
  // Actualizar textos de botones
  const btnAislar = document.getElementById('btn-aislar');
  if (btnAislar) {
    btnAislar.textContent = state.isAislado ? '👁️ Mostrar todo' : '🔍 Aislar cuadrante';
  }
  

  
  // Marcar botón activo
  document.querySelectorAll('.btn').forEach(btn => btn.classList.remove('active-mode'));
  
  if (currentEditorState === EditorState.CREANDO_PADRE) {
    document.getElementById('btn-crear-padre').classList.add('active-mode');
  } else if (currentEditorState === EditorState.CREANDO_HIJO) {
    document.getElementById('btn-crear-hijo').classList.add('active-mode');
  } else if (currentEditorState === EditorState.EDITANDO_PADRE) {
    document.getElementById('btn-editar-padre').classList.add('active-mode');
  } else if (currentEditorState === EditorState.EDITANDO_HIJOS) {
    document.getElementById('btn-editar-hijo').classList.add('active-mode');
  }
  
  // Actualizar indicador de cobertura
  updateCoverageIndicator();
  
  // Asegurar que Import/Export siempre estén habilitados
  dis('btn-export', false);
  dis('btn-import', false);
}

// Helper para actualizar estado de UI
function updateUIState() {
  // Reaplica el estado actual a los controles
  setEditorState(state.mode);
}

// Actualizar indicador de cobertura - función vacía (UI removida)
function updateCoverageIndicator() {
  // UI de cobertura removida - mantener función para compatibilidad
  return;
  
  // Colorear según cobertura
  if (cobertura >= 95) {
    coverageElement.style.color = '#00b894';
  } else if (cobertura >= 80) {
    coverageElement.style.color = '#fdcb6e';
  } else {
    coverageElement.style.color = '#e17055';
  }
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

// === FUNCIONES PRINCIPALES DE JERARQUÍA ===

// Helpers para registrar y activar padres
function registerParent(layer) {
  const code = layer?.feature?.properties?.codigo;
  if (!code) return;
  if (!state.parents.includes(layer)) state.parents.push(layer);
  if (!state.childrenByParent[code]) state.childrenByParent[code] = [];

  // Click para activar este padre (si no estamos editando)
  layer.on('click', () => {
    if (isEditingActive) return;
    setActiveParent(layer);
  });
}

// Registrar hijo con click handler para selección
function registerChild(layer, parentCode) {
  if (!parentCode) parentCode = state.activeParent?.feature?.properties?.codigo;
  if (!parentCode) return;
  
  state.childrenByParent[parentCode] = state.childrenByParent[parentCode] || [];
  state.childrenByParent[parentCode].push(layer);

  if (!state.childGroupsByParent[parentCode]) {
    state.childGroupsByParent[parentCode] = L.featureGroup().addTo(map);
  }
  state.childGroupsByParent[parentCode].addLayer(layer);

  // Selección para eliminar hijo
  layer.on('click', (e) => {
    if (isEditingActive) return;
    selectChild(layer);
    e.originalEvent?.stopPropagation?.();
  });
}

// Seleccionar hijo para eliminar
function selectChild(layer) {
  // destacar visualmente el hijo y habilitar botón
  if (state.selectedChild && state.selectedChild !== layer) {
    applyStyleFromProperties(state.selectedChild); // quitar highlight anterior
  }
  state.selectedChild = layer;
  layer.setStyle({ weight: 3, dashArray: '6,3' });
  
  const btnDelChild = document.getElementById('btn-delete-child');
  if (btnDelChild) { 
    btnDelChild.style.display = 'inline-block'; 
    btnDelChild.disabled = false; 
  }
}

function setActiveParent(layer) {
  if (!layer) return;
  state.activeParent = layer;

  const code = layer.feature?.properties?.codigo;
  state.children = state.childrenByParent[code] || [];
  activePadre = state.activeParent;           // compat
  activeHijos = state.children;               // compat

  // NO eliminar otros grupos de hijos - mantener todos visibles
  // Solo actualizar referencia al grupo actual
  state.childrenGroup = state.childGroupsByParent[code] || null;

  // Crear grupo si no existe pero hay hijos
  if (!state.childrenGroup && state.children.length > 0) {
    state.childrenGroup = new L.FeatureGroup(state.children);
    state.childGroupsByParent[code] = state.childrenGroup;
    map.addLayer(state.childrenGroup);
  }

  // Mantener/actualizar aislamiento y UI
  applyAislamiento();
  setEditorState(EditorState.PADRE_ACTIVO);
  
  console.debug('[ACTIVE_PARENT_CHANGED]', `Padre activo: ${code}, Hijos: ${state.children.length}`);
}

// Manejar creación de cuadrante padre
function handlePadreCreated(layer) {
  // Aplicar buffer(0) para limpiar geometría
  const bufferedGeom = bufferGeometry(layer.toGeoJSON(), 0);
  
  // Mostrar diálogo de configuración
  showPadreConfigDialog((config) => {
    // Configurar propiedades del padre
    layer.feature.properties = {
      nivel: 'cuadrante',
      codigo: config.codigo,
      ciudad: config.ciudad,
      id_ruta: config.ruta,
      tipo: 'PADRE' // Identificador de tipo
    };
    
    // Persistir props de estilo en properties
    ensureStyleProps(layer, true);
    applyStyleFromProperties(layer);
    enforceStrokePolicy(layer);
    
    // Agregar funcionalidad de recolor
    attachRecolorOnClick(layer);
    
    // Registrar y activar nuevo padre (sin eliminar los anteriores)
    registerParent(layer);
    setActiveParent(layer);
    
    // NO forzar aislamiento automático, respetar estado del usuario
    // state.isAislado = true;
    // isAislado = state.isAislado;
    
    // Aplicar estado actual (puede estar aislado o no)
    applyAislamiento();
    
    DRAWN_EDITABLE.addLayer(layer);
    
    // Cambiar a estado PADRE_ACTIVO (permite crear hijos inmediatamente)
    setEditorState(EditorState.PADRE_ACTIVO);
    
    // Apagar recolor por seguridad
    setRecolorMode(false);
    
    console.debug('[PADRE] created:', config.codigo);
  });
}

// Manejar creación de subcuadrante hijo
function handleHijoCreated(layer) {
  if (!activePadre) {
    alert('Error: No hay cuadrante padre activo');
    return;
  }
  
  // Auto-clip: intersección con padre
  const geomHijo = layer.toGeoJSON();
  const geomPadre = activePadre.toGeoJSON();
  const clippedGeom = intersectGeometries(geomHijo, geomPadre);
  
  if (!clippedGeom || calculateArea(clippedGeom) < TOLERANCIAS.MIN_AREA_RESTO) {
    alert('El subcuadrante debe estar dentro del cuadrante padre');
    return;
  }
  
  // Aplicar snapping
  const snappedGeom = applySnapping(clippedGeom);
  
  // Chequeo de solape incremental
  const overlapCheck = checkOverlapWithExistingHijos(snappedGeom);
  if (!overlapCheck.valid) {
    showOverlapWarning(overlapCheck.overlaps);
    return;
  }
  
  // Autocódigo
  const codigoPadre = activePadre.feature.properties.codigo;
  const codigoHijo = generateNextSubcuadranteCode(codigoPadre);
  
  // Configurar propiedades del hijo
  layer.feature.properties = {
    nivel: 'subcuadrante',
    codigo: codigoHijo,
    codigo_padre: codigoPadre,
    fillColor: HIJO_STYLE.fillColor,
    ...HIJO_STYLE
  };
  
  // Aplicar estilos
  layer.setStyle(HIJO_STYLE);
  
  // Agregar a hijos activos
  activeHijos.push(layer);
  
  DRAWN_EDITABLE.addLayer(layer);
  
  // Actualizar indicador de cobertura
  updateCoverageIndicator();
  
  console.debug('[HIJO] created:', codigoHijo, 'total hijos:', activeHijos.length);
}

// Aplicar snapping a geometría
function applySnapping(geojson) {
  // Por simplicidad, retornamos la geometría original
  // En implementación completa, ajustar vértices cerca del padre y otros hijos
  return geojson;
}

// Verificar solape con hijos existentes
function checkOverlapWithExistingHijos(newGeom) {
  const overlaps = [];
  
  activeHijos.forEach((hijo, index) => {
    const hijoGeom = hijo.toGeoJSON();
    const overlap = intersectGeometries(newGeom, hijoGeom);
    
    if (overlap && calculateArea(overlap) > TOLERANCIAS.MAX_OVERLAP_AREA) {
      overlaps.push({
        index,
        area: calculateArea(overlap),
        geometry: overlap
      });
    }
  });
  
  return {
    valid: overlaps.length === 0,
    overlaps
  };
}

// Mostrar advertencia de solape
function showOverlapWarning(overlaps) {
  // Dibujar solapes en el mapa temporalmente
  const overlapLayers = overlaps.map(overlap => {
    const layer = L.geoJSON(overlap.geometry, {
      style: ERROR_STYLE.OVERLAP
    }).addTo(map);
    
    setTimeout(() => {
      map.removeLayer(layer);
    }, 3000);
    
    return layer;
  });
  
  alert(`Solape detectado con ${overlaps.length} subcuadrante(s) existente(s). Los solapes se muestran en naranja.`);
}



// Aplicar/quitar aislamiento
function applyAislamiento() {
  if (!state.isAislado) {
    // Modo normal: mostrar todo con estilos normales
    forEachQuadrantLayer(layer => {
      applyStyleFromProperties(layer);
    });
    return;
  }
  
  // Modo aislado: solo destacar padre activo y sus hijos
  if (!state.activeParent) return;
  
  const activeCode = state.activeParent.feature?.properties?.codigo;
  
  forEachQuadrantLayer(layer => {
    const layerCode = layer.feature?.properties?.codigo;
    const layerParentCode = layer.feature?.properties?.codigo_padre;
    
    // Determinar si es el padre activo o hijo del padre activo
    const isActiveParent = (layerCode === activeCode);
    const isActiveChild = (layerParentCode === activeCode);
    
    if (isActiveParent || isActiveChild) {
      // Destacar: estilo normal
      applyStyleFromProperties(layer);
    } else {
      // Atenuar: baja opacidad
      const currentStyle = layer.options || {};
      layer.setStyle({
        ...currentStyle,
        opacity: 0.1,
        fillOpacity: 0.05
      });
    }
  });
}

// === FUNCIONES DE ELIMINACIÓN SEGURA ===

// Eliminar padre activo y todos sus hijos
function deleteActiveParent() {
  const parent = state.activeParent;
  if (!parent) return;

  const code = parent.feature?.properties?.codigo || '(sin código)';
  const hijos = state.childrenByParent[code] || [];
  const count = hijos.length;

  const ok = confirm(`¿Eliminar el cuadrante ${code}? Se eliminarán ${count} subcuadrante(s). Esta acción no se puede deshacer.`);
  if (!ok) return;

  // 1) Borrar hijos del mapa/estado
  if (state.childGroupsByParent[code]) {
    state.childGroupsByParent[code].eachLayer(l => state.childGroupsByParent[code].removeLayer(l));
    map.removeLayer(state.childGroupsByParent[code]);
    delete state.childGroupsByParent[code];
  }
  (hijos || []).forEach(l => {
    try { DRAWN_EDITABLE.removeLayer(l); } catch(e) {}
  });
  delete state.childrenByParent[code];

  // 2) Borrar el padre del mapa/estado
  try { DRAWN_EDITABLE.removeLayer(parent); } catch(e) {}
  state.parents = state.parents.filter(p => p !== parent);

  // 3) Elegir nuevo activo (si queda alguno)
  state.activeParent = state.parents[0] || null;
  if (state.activeParent) {
    const newCode = state.activeParent.feature?.properties?.codigo;
    state.children = state.childrenByParent[newCode] || [];
    setEditorState(EditorState.PADRE_ACTIVO);
  } else {
    state.children = [];
    setEditorState(EditorState.IDLE);
  }

  // 4) Limpiar selección de hijo
  state.selectedChild = null;
  const btnDelChild = document.getElementById('btn-delete-child');
  if (btnDelChild) { 
    btnDelChild.disabled = true; 
    btnDelChild.style.display = 'none'; 
  }

  fitToAllIfAny();
  
  // Apagar recolor tras eliminar
  setRecolorMode(false);
  
  console.debug('[DELETE_PARENT]', `Padre "${code}" y ${count} hijos eliminados`);
}

// Eliminar hijo seleccionado
function deleteSelectedChild() {
  const ch = state.selectedChild;
  if (!ch) return;

  const codeParent = state.activeParent?.feature?.properties?.codigo;
  const chCode = ch.feature?.properties?.codigo || '(sin código)';
  const ok = confirm(`¿Eliminar el subcuadrante ${chCode}?`);
  if (!ok) return;

  // 1) Quitar del grupo y del mapa
  const grp = state.childGroupsByParent[codeParent];
  try { grp?.removeLayer(ch); } catch(e) {}
  try { DRAWN_EDITABLE.removeLayer(ch); } catch(e) {}

  // 2) Quitar de colecciones
  state.children = (state.children || []).filter(x => x !== ch);
  if (codeParent) {
    state.childrenByParent[codeParent] = (state.childrenByParent[codeParent] || []).filter(x => x !== ch);
  }

  // 3) Limpiar selección y UI
  state.selectedChild = null;
  const btn = document.getElementById('btn-delete-child');
  if (btn) { 
    btn.disabled = true; 
    btn.style.display = 'none'; 
  }

  fitToAllIfAny();
  setEditorState(EditorState.PADRE_ACTIVO);
  
  // Apagar recolor tras eliminar
  setRecolorMode(false);
  
  console.debug('[DELETE_CHILD]', `Hijo "${chCode}" eliminado`);
}

// Mostrar diálogo de configuración de padre
function showPadreConfigDialog(callback) {
  const ciudad = getCityFromQuery();
  
  // Crear modal
  const modal = document.createElement('div');
  modal.className = 'cuadrante-modal';
  modal.innerHTML = `
    <div class="cuadrante-modal-content">
      <h3>Configurar Cuadrante Padre</h3>
      
      <div class="form-group">
        <label>Ciudad:</label>
        <input type="text" id="modal-ciudad" value="${ciudad}" readonly>
      </div>
      
      <div class="form-group">
        <label>ID Ruta:</label>
        <input type="number" id="modal-ruta" min="1" max="99" value="1" required>
      </div>
      
      <div class="form-group">
        <label>Código (se generará automáticamente):</label>
        <div id="codigo-preview" class="codigo-preview">CL_1_01</div>
      </div>
      
      <div class="modal-buttons">
        <button type="button" class="btn btn-secondary" id="modal-cancel">Cancelar</button>
        <button type="button" class="btn btn-primary" id="modal-confirm">Crear Cuadrante</button>
      </div>
    </div>
  `;
  
  document.body.appendChild(modal);
  
  // Actualizar código en tiempo real
  const rutaInput = document.getElementById('modal-ruta');
  const codigoPreview = document.getElementById('codigo-preview');
  
  function updateCodigoPreview() {
    const ruta = rutaInput.value || '1';
    const codigo = generateNextCuadranteCode(ciudad, ruta);
    codigoPreview.textContent = codigo;
  }
  
  rutaInput.addEventListener('input', updateCodigoPreview);
  updateCodigoPreview();
  
  // Eventos de botones
  document.getElementById('modal-cancel').addEventListener('click', () => {
    document.body.removeChild(modal);
    setEditorState(EditorState.IDLE);
  });
  
  document.getElementById('modal-confirm').addEventListener('click', () => {
    const ruta = rutaInput.value;
    
    if (!ruta || ruta < 1) {
      alert('Ingrese un ID de ruta válido');
      return;
    }
    
    const config = {
      ciudad: ciudad,
      ruta: ruta,
      codigo: codigoPreview.textContent
    };
    
    document.body.removeChild(modal);
    callback(config);
  });
  
  // Focus en ruta
  rutaInput.focus();
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

    // Botón recolor (usar función global)
    const btnRecolor = document.getElementById('btn-recolor');
    if (btnRecolor) {
      btnRecolor.addEventListener('click', () => {
        setRecolorMode(!recolorMode);
      });
      console.debug('Botón recolor configurado');
    }

    const exportBtn = document.getElementById('btn-export');
    if (exportBtn) {
        exportBtn.addEventListener('click', (ev) => {
          try {
            // Alt+Click (opcional) para exportar SOLO jerarquía activa
            const onlyActiveHierarchy = ev.altKey === true;

            const fc = onlyActiveHierarchy ? buildActiveHierarchyFC() : buildFullFeatureCollection();
            
            // Descargar directamente usando el nuevo sistema
            const fileName = onlyActiveHierarchy ? 
              `subcuadrante_${activePadre?.feature?.properties?.codigo || 'activa'}.geojson` :
              suggestFileNameForFullExport();
            
            downloadGeoJSON(fc, fileName);
            
            const exportType = onlyActiveHierarchy ? 'jerarquía activa' : 'TODO el dataset';
            console.log(`✅ Exportado ${exportType}: ${fc.features?.length || 0} features`);
            
            // Toast notification if available
            if (typeof toast === 'function') {
              toast(`✅ Exportado ${exportType}`);
            }
          } catch (e) {
            console.error('[EXPORT] Falló la exportación:', e);
            alert('No se pudo exportar. Revisa la consola para más detalles.');
          }
        });
        
        console.debug('Botón de exportación configurado');
    } else {
        console.warn('Botón con id "btn-export" no encontrado');
    }

    // Nota: La configuración de importación se hace más abajo con la lógica de jerarquía

// === FUNCIONES GLOBALES DE EXPORTACIÓN ===

// Nueva función para recolectar todo el dataset exportable
function buildFullFeatureCollection() {
  const byCode = new Map();         // deduplicación por properties.codigo
  const push = (f) => {
    if (!isQuadrantFeature(f)) return;
    const code = f.properties?.codigo || null;
    if (code) {
      // Si existe en editable y en importado, prioriza el de EDITABLE (última edición)
      byCode.set(code, f);
    } else {
      // Sin codigo: usa clave geométrica para evitar duplicados
      byCode.set(JSON.stringify(f.geometry), f);
    }
  };

  // 1) Capas EDITABLES
  DRAWN_EDITABLE?.eachLayer(l => {
    try { push(layerToFeature(l)); } catch(e) { console.warn('[EXPORT] Error en EDITABLE:', e); }
  });

  // 2) Capas IMPORTADAS/BLOQUEADAS
  DRAWN_LOCKED?.eachLayer?.(l => {
    try {
      const f = layerToFeature(l);
      const code = f.properties?.codigo;
      // Solo inserta si no está ya (para respetar ediciones en editable)
      if (code && !byCode.has(code)) byCode.set(code, f);
      else if (!code) {
        const key = JSON.stringify(f.geometry);
        if (!byCode.has(key)) byCode.set(key, f);
      }
    } catch(e) { console.warn('[EXPORT] Error en LOCKED:', e); }
  });

  // 3) Otros contenedores (hijos por padre) si no están en DRAWN_EDITABLE
  for (const grp of Object.values(state.childGroupsByParent || {})) {
    grp.eachLayer?.(l => {
      try { push(layerToFeature(l)); } catch(e) { console.warn('[EXPORT] Error en childGroup:', e); }
    });
  }

  const features = Array.from(byCode.values());
  console.debug(`[EXPORT] Recolectado dataset completo: ${features.length} features`);
  
  return { 
    type: 'FeatureCollection', 
    properties: {
      type: 'full_dataset_export',
      city: CITY,
      total_features: features.length,
      export_timestamp: new Date().toISOString(),
      editor_version: '3.0'
    },
    features 
  };
}

// Función para exportar SOLO jerarquía activa (Alt+Click)
function buildActiveHierarchyFC() {
  return buildFeatureCollection(activePadre, activeHijos);
}

// Función helper para construir FeatureCollection (original)
function buildFeatureCollection(padre, hijos) {
  if (padre && hijos && hijos.length > 0) {
    // Exportación de jerarquía específica
    const features = [];
    const timestamp = new Date().toISOString();
    
    // Preparar padre
    const padreFeature = {
      ...padre.toGeoJSON(),
      properties: {
        nivel: "cuadrante",
        codigo: padre.feature.properties.codigo,
        ciudad: padre.feature.properties.ciudad,
        id_ruta: padre.feature.properties.id_ruta,
        ruta: padre.feature.properties.id_ruta,
        created_at: timestamp,
        editor_version: "3.0",
        total_hijos: hijos.length,
        fillColor: padre.feature.properties.fillColor || PADRE_STYLE.fillColor,
        color: padre.feature.properties.color || PADRE_STYLE.color,
        weight: padre.feature.properties.weight || PADRE_STYLE.weight,
        fillOpacity: padre.feature.properties.fillOpacity || PADRE_STYLE.fillOpacity
      }
    };
    features.push(padreFeature);
    
    // Preparar hijos
    hijos.forEach((hijo, index) => {
      const hijoFeature = {
        ...hijo.toGeoJSON(),
        properties: {
          nivel: "subcuadrante",
          codigo: hijo.feature.properties.codigo,
          codigo_padre: padre.feature.properties.codigo,
          ciudad: padre.feature.properties.ciudad,
          id_ruta: padre.feature.properties.id_ruta,
          ruta: padre.feature.properties.id_ruta,
          orden: index + 1,
          created_at: timestamp,
          editor_version: "3.0",
          fillColor: hijo.feature.properties.fillColor || HIJO_STYLE.fillColor,
          color: hijo.feature.properties.color || HIJO_STYLE.color,
          weight: hijo.feature.properties.weight || HIJO_STYLE.weight,
          fillOpacity: hijo.feature.properties.fillOpacity || HIJO_STYLE.fillOpacity
        }
      };
      features.push(hijoFeature);
    });
    
    return {
      type: 'FeatureCollection',
      properties: {
        type: 'hierarchy_export',
        parent_code: padre.feature.properties.codigo,
        city: padre.feature.properties.ciudad,
        route: padre.feature.properties.id_ruta,
        total_features: features.length,
        export_timestamp: timestamp,
        crs: "EPSG:4326",
        target_crs: "EPSG:3116",
        validation_passed: true
      },
      features: features
    };
  } else {
    // Exportación general de cuadrantes
    const quadsFC = collectQuadrantsFC();
    const comunas = (COMUNAS_FC && Array.isArray(COMUNAS_FC.features)) ? COMUNAS_FC.features : [];
    
    const enrichedQuads = quadsFC.features.map(feature => ({
      ...feature,
      properties: {
        ...feature.properties,
        nivel: feature.properties.nivel || 'cuadrante',
        created_at: new Date().toISOString(),
        editor_version: '3.0',
        crs: "EPSG:4326"
      }
    }));
    
    return {
      type: 'FeatureCollection',
      properties: {
        type: 'general_export',
        city: CITY,
        total_comunas: comunas.length,
        total_quadrants: enrichedQuads.length,
        export_timestamp: new Date().toISOString()
      },
      features: [...comunas, ...enrichedQuads],
    };
  }
}

// Función helper para exportar FeatureCollection
function doExport(fc) {
  let fileName;
  if (fc.properties && fc.properties.type === 'hierarchy_export' && fc.properties.parent_code) {
    fileName = `subcuadrante_${fc.properties.parent_code}.geojson`;
  } else {
    fileName = `cuadrantes_${CITY.toLowerCase()}_${new Date().toISOString().slice(0,10)}.geojson`;
  }
  
  downloadGeoJSON(fc, fileName);
}

// Sugiere nombre de archivo para exportación completa
function suggestFileNameForFullExport() {
  const now = new Date();
  const dateStr = now.toISOString().slice(0,10); // YYYY-MM-DD
  const timeStr = now.toTimeString().slice(0,5).replace(':', ''); // HHMM
  return `cuadrantes_rutas_${CITY.toLowerCase()}_${dateStr}-${timeStr}.geojson`;
}

// Función para exportación directa (global)
function doDirectExport() {
  const fc = buildFeatureCollection(activePadre, activeHijos);
  doExport(fc);
}

// Función para exportar jerarquía específica (global)
function exportHierarchy() {
  const features = [];
  const timestamp = new Date().toISOString();
  
  // Preparar padre con propiedades completas
  const padreFeature = {
    ...activePadre.toGeoJSON(),
    properties: {
      nivel: "cuadrante",
      codigo: activePadre.feature.properties.codigo,
      ciudad: activePadre.feature.properties.ciudad,
      id_ruta: activePadre.feature.properties.id_ruta,
      ruta: activePadre.feature.properties.id_ruta, // Alias
      created_at: timestamp,
      editor_version: "3.0",
      total_hijos: activeHijos.length,
      // Preservar propiedades de estilo
      fillColor: activePadre.feature.properties.fillColor || PADRE_STYLE.fillColor,
      color: activePadre.feature.properties.color || PADRE_STYLE.color,
      weight: activePadre.feature.properties.weight || PADRE_STYLE.weight,
      fillOpacity: activePadre.feature.properties.fillOpacity || PADRE_STYLE.fillOpacity
    }
  };
  features.push(padreFeature);
  
  // Preparar hijos con propiedades completas y orden
  activeHijos.forEach((hijo, index) => {
    const hijoFeature = {
      ...hijo.toGeoJSON(),
      properties: {
        nivel: "subcuadrante",
        codigo: hijo.feature.properties.codigo,
        codigo_padre: activePadre.feature.properties.codigo,
        ciudad: activePadre.feature.properties.ciudad,
        id_ruta: activePadre.feature.properties.id_ruta,
        ruta: activePadre.feature.properties.id_ruta, // Alias
        orden: index + 1,
        created_at: timestamp,
        editor_version: "3.0",
        // Preservar propiedades de estilo
        fillColor: hijo.feature.properties.fillColor || HIJO_STYLE.fillColor,
        color: hijo.feature.properties.color || HIJO_STYLE.color,
        weight: hijo.feature.properties.weight || HIJO_STYLE.weight,
        fillOpacity: hijo.feature.properties.fillOpacity || HIJO_STYLE.fillOpacity
      }
    };
    features.push(hijoFeature);
  });
  
  // Crear FeatureCollection
  const hierarchyFC = {
    type: 'FeatureCollection',
    properties: {
      type: 'hierarchy_export',
      parent_code: activePadre.feature.properties.codigo,
      city: activePadre.feature.properties.ciudad,
      route: activePadre.feature.properties.id_ruta,
      total_features: features.length,
      export_timestamp: timestamp,
      crs: "EPSG:4326", // WGS84 para compatibilidad
      target_crs: "EPSG:3116", // CRS métrico recomendado para Colombia
      validation_passed: true
    },
    features: features
  };
  
  // Nombre de archivo según T6: subcuadrante_CL_{ruta}_{nn}.geojson
  const codigoPadre = activePadre.feature.properties.codigo;
  const fileName = `subcuadrante_${codigoPadre}.geojson`;
  
  downloadGeoJSON(hierarchyFC, fileName);
  
  console.debug('[EXPORT HIERARCHY]', {
    padre: codigoPadre,
    hijos: activeHijos.length,
    archivo: fileName
  });
}

// Función para exportar cuadrantes generales (global)
function exportGeneralQuadrants() {
  const quadsFC = collectQuadrantsFC();
  const comunas = (COMUNAS_FC && Array.isArray(COMUNAS_FC.features)) ? COMUNAS_FC.features : [];
  
  // Enriquecer features con propiedades de jerarquía
  const enrichedQuads = quadsFC.features.map(feature => ({
    ...feature,
    properties: {
      ...feature.properties,
      // Asegurar propiedades de jerarquía
      nivel: feature.properties.nivel || 'cuadrante',
      created_at: new Date().toISOString(),
      editor_version: '3.0',
      crs: "EPSG:4326"
    }
  }));
  
  const combined = {
    type: 'FeatureCollection',
    properties: {
      type: 'general_export',
      city: CITY,
      total_comunas: comunas.length,
      total_quadrants: enrichedQuads.length,
      export_timestamp: new Date().toISOString()
    },
    // Orden: comunas primero, luego cuadrantes
    features: [...comunas, ...enrichedQuads],
  };
  
  const fileName = `cuadrantes_${CITY.toLowerCase()}_${new Date().toISOString().slice(0,10)}.geojson`;
  downloadGeoJSON(combined, fileName);
  
  console.debug('[EXPORT GENERAL]', {
    city: CITY,
    comunas: comunas.length,
    cuadrantes: enrichedQuads.length,
    archivo: fileName
  });
}

// Helper para descarga de GeoJSON (global)
function downloadGeoJSON(geojsonData, fileName) {
  const blob = new Blob([JSON.stringify(geojsonData, null, 2)], { 
    type: 'application/geo+json' 
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  
  // Mostrar notificación de éxito
  showExportSuccess(fileName, geojsonData.features.length);
}

// Mostrar notificación de éxito de exportación (global)
function showExportSuccess(fileName, featureCount) {
  const notification = document.createElement('div');
  notification.style.cssText = `
    position: fixed; top: 20px; right: 20px; z-index: 9999;
    background: #2ecc71; color: white; padding: 15px 20px;
    border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 14px; font-weight: 500;
  `;
  notification.innerHTML = `
    ✅ <strong>Exportado exitosamente</strong><br>
    📄 ${fileName}<br>
    📊 ${featureCount} geometrías
  `;
  
  document.body.appendChild(notification);
  
  setTimeout(() => {
    if (document.body.contains(notification)) {
      document.body.removeChild(notification);
    }
  }, 4000);
}

    // === AUTO-CARGA Y FUNCIONES DE CARGA ===

// Obtener ciudad de la URL
function getCityFromURL() {
    const params = new URLSearchParams(window.location.search);
    return (params.get('city') || 'CALI').toUpperCase();
}

// Cargar GeoJSON por defecto de la ciudad
async function loadDefaultCityGeoJSON() {
    const city = getCityFromURL();
    const url = `/geojson/default?city=${encodeURIComponent(city)}`;
    
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`No se pudo cargar GeoJSON por defecto (${city}): ${response.status}`);
        }
        
        const featureCollection = await response.json();
        loadFeatureCollection(featureCollection, { source: 'default', lockImported: true });
        
        console.log(`[AUTO-LOAD] GeoJSON por defecto cargado para ${city}:`, featureCollection.features?.length || 0, 'features');
        
        // Ajustar vista al contenido cargado
        fitToAllIfAny();
        
    } catch (error) {
        console.warn('[AUTO-LOAD]', error.message);
        // No mostrar error al usuario, es opcional
    }
}

// Función general para cargar FeatureCollection
function loadFeatureCollection(featureCollection, options = {}) {
    const { source = 'unknown', lockImported = false } = options;
    
    if (!featureCollection || featureCollection.type !== 'FeatureCollection') {
        throw new Error('Debe ser un FeatureCollection válido');
    }
    
    const features = featureCollection.features || [];
    let loaded = 0;
    let skipped = 0;
    
    features.forEach(feature => {
        if (!feature.geometry) {
            skipped++;
            return;
        }
        
        // Filtrar comunas (properties con NOMBRE, barrio o BARRIO)
        const props = feature.properties || {};
        if (props.NOMBRE || props.barrio || props.BARRIO) {
            // Las comunas se cargan como referencia, no editables
            const layer = L.geoJSON(feature, {
                interactive: false,
                style: COMUNA_STYLE
            }).addTo(map);
            layer.bringToBack();
            skipped++;
            return;
        }
        
        // Solo cargar geometrías poligonales
        const geomType = feature.geometry.type;
        if (!['Polygon', 'MultiPolygon'].includes(geomType)) {
            skipped++;
            return;
        }
        
        // Crear capa Leaflet
        const layer = L.geoJSON(feature, {
            onEachFeature: (feat, lyr) => {
                lyr.feature = feat;
                
                // Aplicar estilos desde properties o usar por defecto
                applyStyleFromProperties(lyr);
                enforceStrokePolicy(lyr);
                attachRecolorOnClick(lyr);
                
                // Si es un padre (cuadrante), registrarlo para activación
                if (feat.properties && feat.properties.nivel === 'cuadrante' && feat.properties.codigo) {
                    registerParent(lyr);
                }
            }
        }).getLayers()[0];
        
        if (layer) {
            // Marcar si es importado
            if (source !== 'default') {
                layer._isImported = true;
            }
            
            // Agregar al grupo apropiado
            const targetGroup = lockImported ? DRAWN_LOCKED : DRAWN_EDITABLE;
            targetGroup.addLayer(layer);
            loaded++;
        }
    });
    
    console.log(`[LOAD] ${source}:`, { loaded, skipped, total: features.length });
    
    return { loaded, skipped };
}

// === CONFIGURAR EVENTOS DE JERARQUÍA ===
    
    // Botón crear cuadrante padre
    document.getElementById('btn-crear-padre').addEventListener('click', () => {
        if (currentEditorState === EditorState.CREANDO_PADRE) {
            setEditorState(EditorState.IDLE);
        } else {
            setEditorState(EditorState.CREANDO_PADRE);
        }
    });
    
    // Botón crear subcuadrantes hijos
    document.getElementById('btn-crear-hijo').addEventListener('click', () => {
        if (state.mode === EditorState.CREANDO_HIJO) {
            setEditorState(EditorState.PADRE_ACTIVO);
        } else {
            setEditorState(EditorState.CREANDO_HIJO);
        }
    });
    
    // Botón editar padre
    document.getElementById('btn-editar-padre').addEventListener('click', () => {
        startParentEditing();
    });
    
    // Botón guardar padre
    document.getElementById('btn-guardar-padre').addEventListener('click', () => {
        saveParentEditing();
    });
    
    // Botón cancelar edición padre
    document.getElementById('btn-cancelar-edicion-padre').addEventListener('click', () => {
        cancelParentEditing();
    });
    
    // Botón editar hijos
    document.getElementById('btn-editar-hijo').addEventListener('click', startChildrenEditing);
    
    // Botón guardar hijos
    document.getElementById('btn-guardar-hijo').addEventListener('click', saveChildrenEditing);
    
    // Botón cancelar edición hijos
    document.getElementById('btn-cancelar-edicion-hijo').addEventListener('click', cancelChildrenEditing);
    
    // Botón aislar
    document.getElementById('btn-aislar').addEventListener('click', () => {
        state.isAislado = !state.isAislado;
        isAislado = state.isAislado; // mantener compatibilidad
        applyAislamiento();
        updateUIState();
    });
    
    // Botones de eliminación
    document.getElementById('btn-delete-parent')?.addEventListener('click', deleteActiveParent);
    document.getElementById('btn-delete-child')?.addEventListener('click', deleteSelectedChild);
    

    

    
    // Control de opacidad removido - ahora usando constante fija PARENT_FILL_OPACITY
    
    // === EVENTOS DEL MODAL DE CÓDIGO DE HIJO ===
    
    // Botón guardar en modal de hijo
    document.getElementById('hijo-guardar').addEventListener('click', () => {
        if (!modalChildOptions) return;
        
        const codigo = document.getElementById('hijo-codigo').value;
        const success = modalChildOptions.onSave(codigo);
        
        if (success) {
            closeChildCodeModal();
        }
    });
    
    // Botón cancelar en modal de hijo
    document.getElementById('hijo-cancelar').addEventListener('click', () => {
        if (modalChildOptions && modalChildOptions.onCancel) {
            modalChildOptions.onCancel();
        }
        closeChildCodeModal();
    });
    
    // Tecla Enter en el input de código
    document.getElementById('hijo-codigo').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('hijo-guardar').click();
        }
    });
    
    // === CONFIGURAR EVENTOS DE IMPORTACIÓN ===
    
    // Configurar botón de importación
    const btnImport = document.getElementById('btn-import');
    const fileInput = document.getElementById('file-import');
    
    if (btnImport && fileInput) {
        btnImport.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', onImportFileChanged);
        
        console.debug('Eventos de importación configurados');
    }
    
    // Cargar GeoJSON por defecto al inicializar
    loadDefaultCityGeoJSON();
    
    // Inicializar estado de la UI
    setEditorState(EditorState.IDLE);
    
    console.debug('Editor de cuadrantes con jerarquía inicializado completamente');
});

// === FUNCIONES DE VALIDACIÓN EXPORTACIÓN ===

// Habilitar modo de edición para capas específicas
function enableEditMode(layers) {
  // Cerrar edición previa si existiera
  if (EDIT_SESSION.handler) endEditMode(false);

  // 1) Mover capas a un FeatureGroup temporal
  const tempGroup = new L.FeatureGroup();
  layers.forEach(layer => {
    if (DRAWN_EDITABLE.hasLayer(layer)) DRAWN_EDITABLE.removeLayer(layer);
    if (DRAWN_LOCKED.hasLayer(layer))   DRAWN_LOCKED.removeLayer(layer);
    tempGroup.addLayer(layer);
  });
  map.addLayer(tempGroup);

  // 2) Crear y habilitar el handler de edición
  const handler = new L.EditToolbar.Edit(map, { featureGroup: tempGroup });
  handler.enable();

  // 3) Guardar sesión
  EDIT_SESSION = { tempGroup, handler };
  isEditingActive = true;
}

// Finalizar modo de edición
function endEditMode(commit = true) {
  if (!EDIT_SESSION.handler) return;

  // 1) Deshabilitar edición visual
  EDIT_SESSION.handler.disable();

  // 2) Regresar capas al grupo editable por defecto
  const { tempGroup } = EDIT_SESSION;
  if (tempGroup) {
    tempGroup.eachLayer(layer => {
      tempGroup.removeLayer(layer);
      DRAWN_EDITABLE.addLayer(layer);
    });
    map.removeLayer(tempGroup);
  }

  // 3) Limpiar sesión
  EDIT_SESSION = { tempGroup: null, handler: null };
  isEditingActive = false;
}

// Validar antes de exportar
function validateBeforeExport() {
    if (!activePadre || activeHijos.length === 0) {
        return { 
          valid: true, 
          errors: [], 
          warnings: [], 
          geojsonDebug: { type: 'FeatureCollection', features: [] } 
        }; // No hay jerarquía que validar
    }
    
    const geomPadre = activePadre.toGeoJSON();
    const geomsHijos = activeHijos.map(hijo => hijo.toGeoJSON());
    
    const validation = validarIntegridadSubcuadrantes(geomPadre, geomsHijos);
    
    // Convertir estructura de respuesta
    return {
      valid: validation.ok,
      errors: validation.errores || [],
      warnings: validation.warnings || [],
      geojsonDebug: validation.geojsonDebug || { type: 'FeatureCollection', features: [] }
    };
}

// Mostrar modal de validación nuevo con opciones de exportación
function openValidationModal(validation, opts = {}) {
    if (EXPORT_VALIDATION_MODE === 'none') {
        // Nunca mostrar el modal
        const fc = buildFeatureCollection(activePadre, activeHijos);
        return doExport(fc);
    }
    
    const modal = document.createElement('div');
    modal.className = 'validation-overlay';
    
    let errorsHtml = '';
    let warningsHtml = '';
    
    // Errores críticos en rojo
    validation.errors.forEach(error => {
        errorsHtml += `<div class="validation-error critical">${error}</div>`;
    });
    
    // Warnings en amarillo
    validation.warnings.forEach(warning => {
        warningsHtml += `<div class="validation-warning">${warning}</div>`;
    });
    
    const title = validation.errors.length > 0 ? '❌ Errores Críticos' : '⚠️ Advertencias de Validación';
    const description = validation.errors.length > 0 
      ? 'Se encontraron errores críticos que deben corregirse:'
      : 'Se encontraron advertencias. Puede continuar exportando:';
    
    // Botones de acción
    let actionButtons = `
        <button class="btn btn-secondary" id="validation-close">Cerrar</button>
        <button class="btn btn-info" id="validation-debug">Ver en Mapa</button>
    `;
    
    if (opts.allowExport) {
        actionButtons += `
            <button class="btn btn-success" id="validation-export-anyway">Exportar de todos modos</button>
        `;
        // TODO: Agregar botón de recortar cuando esté implementado Turf
        // actionButtons += `<button class="btn btn-warning" id="validation-clip-export">Recortar y exportar</button>`;
    }
    
    modal.innerHTML = `
        <div class="validation-panel">
            <h3>${title}</h3>
            <p>${description}</p>
            ${errorsHtml}
            ${warningsHtml}
            <div class="validation-actions">
                ${actionButtons}
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Event listeners
    document.getElementById('validation-close').addEventListener('click', () => {
        document.body.removeChild(modal);
    });
    
    document.getElementById('validation-debug').addEventListener('click', () => {
        // Mostrar geometrías de debug en el mapa
        if (validation.geojsonDebug && validation.geojsonDebug.features.length > 0) {
            const debugLayer = L.geoJSON(validation.geojsonDebug, {
                style: (feature) => {
                    const errorType = feature.properties.error;
                    return ERROR_STYLE[errorType.toUpperCase()] || ERROR_STYLE.GAP;
                }
            }).addTo(map);
            
            // Auto-remover después de 5 segundos
            setTimeout(() => {
                map.removeLayer(debugLayer);
            }, 5000);
        }
        
        document.body.removeChild(modal);
    });
    
    // Botón exportar de todos modos
    if (opts.allowExport) {
        const exportAnywayBtn = document.getElementById('validation-export-anyway');
        if (exportAnywayBtn) {
            exportAnywayBtn.addEventListener('click', () => {
                document.body.removeChild(modal);
                const fc = buildFeatureCollection(activePadre, activeHijos);
                doExport(fc);
            });
        }
        
        // TODO: Implementar cuando esté Turf disponible
        // const clipExportBtn = document.getElementById('validation-clip-export');
        // if (clipExportBtn) {
        //     clipExportBtn.addEventListener('click', () => {
        //         const clippedChildren = clipChildrenToParent(activeHijos, activePadre);
        //         document.body.removeChild(modal);
        //         doExport(buildFeatureCollection(activePadre, clippedChildren));
        //     });
        // }
    }
}

// Función antigua mantenida para compatibilidad (por si se usa en otro lado)
function showValidationPanel(validation) {
    // Redirigir a la nueva función
    openValidationModal(validation, { allowExport: false });
}

// === T7 — IMPORTACIÓN CON JERARQUÍA ===

// Función principal de importación con detección de jerarquía
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
        
        // Logs de depuración
        console.debug('[IMPORT] archivo leído OK, longitud:', text.length);
        console.debug('[IMPORT] tipo:', data?.type, 'features:', data?.features?.length ?? 'n/a');
        
        // Detectar si es importación con jerarquía
        const hasHierarchy = detectHierarchyStructure(data);
        
        if (hasHierarchy.detected) {
            console.log('[IMPORT] Detectada estructura de jerarquía, procesando...');
            await importWithHierarchy(data, hasHierarchy);
        } else {
            console.log('[IMPORT] Importación general de cuadrantes');
            await importGeneralQuadrants(data);
        }
        
    } catch (error) {
        console.error('[IMPORT] Error al procesar archivo:', error);
        alert('Error al importar el archivo. Verifique que sea un GeoJSON válido.');
    } finally {
        // Resetear input
        evt.target.value = '';
    }
}

// Detectar estructura de jerarquía en el archivo
function detectHierarchyStructure(data) {
    let features = [];
    
    if (data.type === 'FeatureCollection' && Array.isArray(data.features)) {
        features = data.features;
    } else if (data.type === 'Feature') {
        features = [data];
    } else {
        return { detected: false };
    }
    
    // Buscar features con propiedades de jerarquía
    const padres = features.filter(f => 
        f.properties && f.properties.nivel === 'cuadrante'
    );
    
    const hijos = features.filter(f => 
        f.properties && f.properties.nivel === 'subcuadrante' && f.properties.codigo_padre
    );
    
    // 💡 considerar jerarquía si hay al menos un padre (aunque no tenga hijos)
    const detected = padres.length > 0;
    
    return {
        detected,
        padres: padres.length,
        hijos: hijos.length,
        features: features.length,
        totalComunas: features.filter(f => 
            f.properties && (f.properties.NOMBRE || f.properties.barrio || f.properties.BARRIO)
        ).length
    };
}

// Importar archivo con jerarquía (T7)
async function importWithHierarchy(data, hierarchyInfo) {
    const features = data.features || [data];
    
    // Indexar jerarquía según T7
    const padres = {};
    const hijos = {};
    
    // Indexar padres
    features.forEach(f => {
        if (f.properties && f.properties.nivel === 'cuadrante') {
            padres[f.properties.codigo] = f;
        }
    });
    
    // Indexar hijos por código del padre
    features.forEach(f => {
        if (f.properties && f.properties.nivel === 'subcuadrante' && f.properties.codigo_padre) {
            if (!hijos[f.properties.codigo_padre]) {
                hijos[f.properties.codigo_padre] = [];
            }
            hijos[f.properties.codigo_padre].push(f);
        }
    });
    
    console.log('[HIERARCHY INDEX]', {
        padres: Object.keys(padres).length,
        relaciones: Object.keys(hijos).length,
        totalHijos: Object.values(hijos).flat().length
    });
    
    // Mostrar selector de jerarquía
    showHierarchySelector(padres, hijos, (selectedPadre, selectedHijos) => {
        loadSelectedHierarchy(selectedPadre, selectedHijos);
    });
}

// Mostrar selector de jerarquía para continuar edición
function showHierarchySelector(padres, hijos, callback) {
    const modal = document.createElement('div');
    modal.className = 'cuadrante-modal';
    
    // Construir opciones del selector
    let optionsHtml = '<option value="">Seleccionar cuadrante padre...</option>';
    
    // Agrupar por ruta para mejor organización
    const padresByRuta = {};
    Object.values(padres).forEach(padre => {
        const ruta = padre.properties.ruta || padre.properties.id_ruta || 'sin_ruta';
        if (!padresByRuta[ruta]) {
            padresByRuta[ruta] = [];
        }
        padresByRuta[ruta].push(padre);
    });
    
    // Generar HTML agrupado por ruta
    Object.keys(padresByRuta).sort((a, b) => {
        const numA = parseInt(a) || 999;
        const numB = parseInt(b) || 999;
        return numA - numB;
    }).forEach(ruta => {
        optionsHtml += `<optgroup label="Ruta ${ruta}">`;
        padresByRuta[ruta].forEach(padre => {
            const numHijos = hijos[padre.properties.codigo]?.length || 0;
            optionsHtml += `
                <option value="${padre.properties.codigo}">
                    ${padre.properties.codigo} (${numHijos} subcuadrantes)
                </option>
            `;
        });
        optionsHtml += '</optgroup>';
    });
    
    modal.innerHTML = `
        <div class="cuadrante-modal-content">
            <h3>📂 Importar Jerarquía de Cuadrantes</h3>
            
            <div class="form-group">
                <label>Cuadrantes encontrados:</label>
                <div class="hierarchy-summary">
                    <div>👔 Padres: ${Object.keys(padres).length}</div>
                    <div>👶 Subcuadrantes: ${Object.values(hijos).flat().length}</div>
                    <div>🔗 Relaciones: ${Object.keys(hijos).length}</div>
                </div>
            </div>
            
            <div class="form-group">
                <label for="padre-selector">Seleccionar cuadrante para editar:</label>
                <select id="padre-selector" class="form-control">
                    ${optionsHtml}
                </select>
            </div>
            
            <div id="hijos-preview" class="form-group" style="display: none;">
                <label>Subcuadrantes incluidos:</label>
                <div id="hijos-list" class="hijos-preview-list"></div>
            </div>
            
            <div class="modal-buttons">
                <button type="button" class="btn btn-secondary" id="modal-cancel">Cancelar</button>
                <button type="button" class="btn btn-info" id="modal-import-all">Importar Todos</button>
                <button type="button" class="btn btn-primary" id="modal-import" disabled>Importar Selección</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // Configurar eventos
    const selector = document.getElementById('padre-selector');
    const importBtn = document.getElementById('modal-import');
    const hijosPreview = document.getElementById('hijos-preview');
    const hijosList = document.getElementById('hijos-list');
    
    selector.addEventListener('change', (e) => {
        const codigoPadre = e.target.value;
        
        if (codigoPadre && padres[codigoPadre]) {
            importBtn.disabled = false;
            
            // Mostrar preview de hijos
            const hijosArray = hijos[codigoPadre] || [];
            if (hijosArray.length > 0) {
                hijosPreview.style.display = 'block';
                hijosList.innerHTML = hijosArray
                    .sort((a, b) => (a.properties.orden || 0) - (b.properties.orden || 0))
                    .map(hijo => `
                        <div class="hijo-preview-item">
                            <span class="codigo">${hijo.properties.codigo}</span>
                            <span class="orden">Orden: ${hijo.properties.orden || 'N/A'}</span>
                        </div>
                    `).join('');
            } else {
                hijosPreview.style.display = 'block';
                hijosList.innerHTML = `
                    <div class="hijo-preview-item no-children">
                        <span class="mensaje">Sin subcuadrantes - se habilitará creación</span>
                    </div>
                `;
            }
        } else {
            importBtn.disabled = true;
            hijosPreview.style.display = 'none';
        }
    });
    
    // Botón cancelar
    document.getElementById('modal-cancel').addEventListener('click', () => {
        document.body.removeChild(modal);
    });
    
    // Botón importar selección
    importBtn.addEventListener('click', () => {
        const codigoPadre = selector.value;
        const selectedPadre = padres[codigoPadre];
        const selectedHijos = hijos[codigoPadre] || [];
        
        document.body.removeChild(modal);
        callback(selectedPadre, selectedHijos);
    });
    
    // Botón importar todos
    document.getElementById('modal-import-all').addEventListener('click', () => {
        document.body.removeChild(modal);
        loadAllHierarchies(padres, hijos);
    });
}

// Cargar jerarquía seleccionada en el editor
function loadSelectedHierarchy(padreFeature, hijosFeatures) {
    // 1) NO borrar padres/hijos anteriores. Solo cargamos la nueva jerarquía.
    
    // 2) Cargar padre
    const padreLayer = L.geoJSON(padreFeature, { 
        style: PADRE_STYLE, 
        onEachFeature: (f, l) => { 
            l.feature = f; 
            ensureStyleProps(l, true);
            applyStyleFromProperties(l);
            enforceStrokePolicy(l);
            attachRecolorOnClick(l);
        } 
    }).getLayers()[0];
    DRAWN_EDITABLE.addLayer(padreLayer);
    
    // 3) Cargar hijos y crear grupo específico para este padre
    const code = padreFeature.properties?.codigo;
    const hijosLayers = hijosFeatures
      .sort((a,b)=>(a.properties.orden||0)-(b.properties.orden||0))
      .map(f => L.geoJSON(f, { 
          style: HIJO_STYLE, 
          onEachFeature: (ft, ly) => { 
              ly.feature = ft; 
              ensureStyleProps(ly, false);
              applyStyleFromProperties(ly);
              enforceStrokePolicy(ly);
              attachRecolorOnClick(ly);
          } 
      }).getLayers()[0]);
    
    // Crear grupo de hijos específico para este padre
    if (hijosLayers.length > 0 && code) {
      const childGroup = new L.FeatureGroup(hijosLayers);
      state.childGroupsByParent[code] = childGroup;
      map.addLayer(childGroup);
    }
    
    // Agregar hijos al grupo editable y registrarlos para selección
    hijosLayers.forEach(l => {
      DRAWN_EDITABLE.addLayer(l);
      registerChild(l, code);
    });
    
    // 4) Registrar padre, asociar sus hijos y activarlo
    registerParent(padreLayer);
    if (code) state.childrenByParent[code] = hijosLayers;
    setActiveParent(padreLayer);
    fitToAllIfAny();
    
    // Apagar recolor tras importar
    setRecolorMode(false);
    
    console.log('[HIERARCHY LOADED]', {
        padre: padreFeature.properties.codigo,
        hijos: hijosFeatures.length
    });
    
    // Notificación de éxito
    showImportSuccess(padreFeature.properties.codigo, hijosFeatures.length);
}

// Cargar todas las jerarquías (padres + hijos)
function loadAllHierarchies(padres, hijos) {
    let totalPadres = 0;
    let totalHijos = 0;
    
    // Cargar todos los padres
    Object.values(padres).forEach(padreFeature => {
        // Crear layer del padre
        const padreLayer = L.geoJSON(padreFeature, { 
            style: PADRE_STYLE, 
            onEachFeature: (f, l) => { 
                l.feature = f; 
                attachRecolorOnClick(l);
            } 
        }).getLayers()[0];
        
        DRAWN_EDITABLE.addLayer(padreLayer);
        
        // Registrar padre (sin activar automáticamente)
        registerParent(padreLayer);
        
        // Cargar hijos de este padre
        const code = padreFeature.properties?.codigo;
        if (code && hijos[code]) {
            const hijosFeatures = hijos[code];
            const hijosLayers = hijosFeatures
                .sort((a, b) => (a.properties.orden || 0) - (b.properties.orden || 0))
                .map(f => L.geoJSON(f, { 
                    style: HIJO_STYLE, 
                    onEachFeature: (ft, ly) => { 
                        ly.feature = ft; 
                        attachRecolorOnClick(ly);
                    } 
                }).getLayers()[0]);
            
            // Crear grupo de hijos específico
            if (hijosLayers.length > 0) {
                const childGroup = new L.FeatureGroup(hijosLayers);
                state.childGroupsByParent[code] = childGroup;
                map.addLayer(childGroup);
                totalHijos += hijosLayers.length;
            }
            
            // Agregar hijos al grupo editable y registrarlos para selección
            hijosLayers.forEach(l => {
                DRAWN_EDITABLE.addLayer(l);
                registerChild(l, code);
            });
            
            // Registrar asociación
            state.childrenByParent[code] = hijosLayers;
        }
        
        totalPadres++;
    });
    
    // NO cambiar estado de aislamiento automáticamente
    // NO activar padre específico - mostrar todos
    state.activeParent = null;
    activePadre = null;
    state.children = [];
    activeHijos = [];
    
    // Ajustar vista
    fitToAllIfAny();
    
    // Apagar recolor tras importar todo
    setRecolorMode(false);
    
    console.log('[ALL HIERARCHIES LOADED]', {
        padres: totalPadres,
        hijos: totalHijos
    });
    
    // Notificación de éxito
    showImportAllSuccess(totalPadres, totalHijos);
}

// Mostrar notificación de importación masiva exitosa
function showImportAllSuccess(numPadres, numHijos) {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #00b894;
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 184, 148, 0.3);
        z-index: 10000;
        font-family: Arial, sans-serif;
        font-size: 14px;
        max-width: 300px;
    `;
    
    notification.innerHTML = `
        <strong>📂 Todas las Jerarquías Importadas</strong><br>
        👔 Padres: ${numPadres}<br>
        👶 Subcuadrantes: ${numHijos}<br>
        💡 Click en un padre para activarlo
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (document.body.contains(notification)) {
            document.body.removeChild(notification);
        }
    }, 5000);
}

// Mostrar notificación de importación exitosa
function showImportSuccess(codigoPadre, numHijos) {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #6c5ce7;
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(108, 92, 231, 0.3);
        z-index: 10000;
        font-family: Arial, sans-serif;
        font-size: 14px;
        max-width: 300px;
    `;
    
    const hijosText = numHijos > 0 
        ? `👶 Subcuadrantes: ${numHijos}`
        : `✏️ Listo para crear subcuadrantes`;
    
    notification.innerHTML = `
        <strong>📂 Jerarquía Importada</strong><br>
        👔 Padre: ${codigoPadre}<br>
        ${hijosText}
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (document.body.contains(notification)) {
            document.body.removeChild(notification);
        }
    }, 4000);
}

// Función de importación general (sin jerarquía)
async function importGeneralQuadrants(data) {
    try {
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
        
        // Obtener geometrías y códigos existentes para de-dupe y merge
        const existingGeometries = new Set();
        const existingCodigos = new Map(); // codigo -> layer
        forEachQuadrantLayer(layer => {
            if (layer.feature && layer.feature.geometry) {
                existingGeometries.add(JSON.stringify(layer.feature.geometry));
            }
            const codigo = layer.feature?.properties?.codigo;
            if (codigo) {
                existingCodigos.set(codigo, layer);
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
                // Dividir MultiPolygon en varios Polygon, copiando todas las propiedades de estilo
                feature.geometry.coordinates.forEach(polygonCoords => {
                    polygonsToProcess.push({
                        type: 'Feature',
                        geometry: {
                            type: 'Polygon',
                            coordinates: polygonCoords
                        },
                        properties: { ...props } // Copiar todas las propiedades incluyendo fillColor, fillOpacity, etc.
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
                
                // Verificar si existe por codigo para reemplazar
                const incomingCodigo = polygonFeature.properties?.codigo;
                const existingLayer = incomingCodigo ? existingCodigos.get(incomingCodigo) : null;
                
                if (existingLayer) {
                    // Reemplazar layer existente con el mismo codigo
                    console.debug(`[IMPORT] Reemplazando feature con codigo: ${incomingCodigo}`);
                    
                    // Remover layer existente
                    if (DRAWN_EDITABLE.hasLayer(existingLayer)) DRAWN_EDITABLE.removeLayer(existingLayer);
                    if (DRAWN_LOCKED.hasLayer(existingLayer)) DRAWN_LOCKED.removeLayer(existingLayer);
                    
                    // Remover de grupos de hijos si aplica
                    for (const grp of Object.values(state.childGroupsByParent || {})) {
                        if (grp.hasLayer && grp.hasLayer(existingLayer)) {
                            grp.removeLayer(existingLayer);
                        }
                    }
                }
                
                // Crear capa Leaflet
                const layer = L.geoJSON(polygonFeature, {
                    onEachFeature: (feat, lyr) => {
                        // Asignar feature al layer
                        lyr.feature = feat;
                        
                        // Detectar si es padre por nivel
                        const isPadre = (feat.properties && feat.properties.nivel === 'cuadrante');
                        
                        // Asegurar propiedades de estilo
                        ensureStyleProps(lyr, isPadre);
                        applyStyleFromProperties(lyr);
                        enforceStrokePolicy(lyr);
                        attachRecolorOnClick(lyr);
                    }
                }).getLayers()[0];
                
                if (layer) {
                    // Usar función específica para importados
                    addImportedFeatureLayer(polygonFeature, layer);
                    existingGeometries.add(geomStr);
                    if (incomingCodigo) existingCodigos.set(incomingCodigo, layer);
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
        
        // Fallback: si no hay padre activo pero cargamos 1–N polígonos,
        // intenta adoptar uno como padre (por propiedades o por el mayor área).
        if (!state.activeParent) {
            let candidate = null;

            DRAWN_EDITABLE.eachLayer(l => {
                const p = l.feature?.properties || {};
                if (p.nivel === 'cuadrante' || p.tipo === 'PADRE' || p.codigo) {
                    candidate = candidate || l;
                }
            });

            // si aún no hay, tomar el polígono de mayor área
            if (!candidate) {
                let maxArea = -1;
                DRAWN_EDITABLE.eachLayer(l => {
                    const a = calculateArea(l.toGeoJSON());
                    if (a > maxArea) { maxArea = a; candidate = l; }
                });
            }

            if (candidate) {
                // Registrar y activar el padre adoptado
                registerParent(candidate);
                setActiveParent(candidate);
                // NO forzar aislamiento automático
                // state.isAislado = true;
                // isAislado = true;
                applyAislamiento();
                fitToAllIfAny();
                console.debug('[IMPORT][FALLBACK] Padre adoptado automáticamente:', candidate.feature?.properties?.codigo || '(sin código)');
            }
        }

        // Log de resultados
        console.info('[IMPORT]', { total, comunasFiltradas, noPoligonales, deduplicadas, agregadas });
        
    } catch (error) {
        console.error('[IMPORT] Error al procesar archivo:', error);
        alert('Error al importar el archivo. Verifique que sea un GeoJSON válido.');
    }
}

console.debug('Editor de cuadrantes inicializado correctamente');
