import pandas as pd
import folium
import json
import numpy as np
import logging
import re
import math
import streamlit as st
from folium import FeatureGroup
from folium.plugins import FeatureGroupSubGroup
from matplotlib import colors
from hashlib import md5
from pre_procesamiento.preprocesamiento_muestras import (
    crear_df,
    resolver_nombre_ruta,
    prepo_metricas_promotores_muestras,      # nueva API métricas por promotor (muestras)
    metricas_areas_muestras                  # placeholder métricas de área por promotor
)
import unicodedata
from utils.gestor_mapas import guardar_mapa_controlado

# Nuevas importaciones para popups de cuadrantes
from shapely.geometry import shape, Point
from shapely.prepared import prep
from pyproj import Geod

# Reusar helpers de consultores
from mapa_consultores import _es_cuadrante_padre, _es_cuadrante_hijo, _style_cuadrante

# === CONSTANTES PARA DENSIDAD Y COBERTURA ===
DENSIDAD_BASE_M2 = 1000.0      # base de lectura: 1.000 m²
OBJETIVO_X_1000M2 = 1.0        # meta: 1 muestra por 1.000 m² (ajustable)

# === CONSTANTES PARA CÁLCULO DE ÁREAS ===
DEBUG_AREAS = False  # Si True, el popup mostrará el método: "geodésico" o "fallback"


# === PALETA DE COLORES POR MES ===
PALETA_MESES = {
    1:"#1f78b4", 2:"#a6cee3", 3:"#33a02c", 4:"#b2df8a",
    5:"#e31a1c", 6:"#fb9a99", 7:"#ff7f00", 8:"#fdbf6f",
    9:"#6a3d9a",10:"#cab2d6",11:"#b15928",12:"#ffff99"
}

# Importar control de capas disponibles
from folium.plugins import GroupedLayerControl

# Intentar usar control de árbol de capas si está disponible en folium
try:
    from folium.plugins import TreeLayerControl
    HAS_TREE_CONTROL = True
except Exception:
    HAS_TREE_CONTROL = False


def __fmt_es(valor, decimales=0, miles=True):
    """Formatea números con estilo ES-CO: separador de miles con punto y decimal con coma.
    - valor: int|float
    - decimales: cantidad de cifras decimales
    - miles: si True, usa separador de miles
    """
    try:
        if valor is None or (isinstance(valor, float) and math.isnan(valor)):
            return "0" if decimales == 0 else ("0," + ("0" * decimales))
        if decimales > 0:
            s = f"{float(valor):,.{decimales}f}"
        else:
            s = f"{float(valor):,.0f}"
        # Cambiar formato US a ES (coma a punto en miles y punto a coma en decimal)
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
        if not miles:
            # eliminar separador de miles
            if "," in s:
                entier, frac = s.split(",", 1)
                entier = entier.replace(".", "")
                return f"{entier},{frac}"
            return s.replace(".", "")
        return s
    except Exception:
        return str(valor)


def area_m2_geodesic(geom_geojson: dict) -> float:
    """Calcula el área geodésica en m² de una geometría GeoJSON (Polygon/MultiPolygon)."""
    g = Geod(ellps="WGS84")
    geom = shape(geom_geojson)
    area = 0.0
    try:
        if geom.geom_type == 'Polygon':
            lons, lats = geom.exterior.coords.xy
            area_poly, _ = g.polygon_area_perimeter(lons, lats)
            area += abs(area_poly)
            for interior in geom.interiors:
                lons, lats = interior.coords.xy
                hole_area, _ = g.polygon_area_perimeter(lons, lats)
                area -= abs(hole_area)
        elif geom.geom_type == 'MultiPolygon':
            for poly in geom.geoms:
                lons, lats = poly.exterior.coords.xy
                area_poly, _ = g.polygon_area_perimeter(lons, lats)
                area += abs(area_poly)
                for interior in poly.interiors:
                    lons, lats = interior.coords.xy
                    hole_area, _ = g.polygon_area_perimeter(lons, lats)
                    area -= abs(hole_area)
        else:
            return 0.0
        return float(area)
    except Exception:
        return 0.0


def _asignar_cuadrante_a_puntos(df_pts: pd.DataFrame, features: list) -> pd.Series:
    """Asigna a cada punto el código de cuadrante cuyo polígono lo contiene.
    Retorna una Serie indexada igual que df_pts con el código o None.
    Requiere columnas 'lat' y 'lon' en df_pts.
    """
    if df_pts.empty:
        return pd.Series([None] * 0, name="cod_cuadrante")
    puntos = []
    for _, r in df_pts.iterrows():
        try:
            puntos.append(Point(float(r['lon']), float(r['lat'])))
        except Exception:
            puntos.append(None)
    res = [None] * len(df_pts)
    for feat in features:
        props = feat.get('properties', {})
        codigo = props.get('codigo') or props.get('CODIGO') or props.get('code') or ''
        if not codigo:
            continue
        try:
            geom = shape(feat.get('geometry', {}))
            pgeom = prep(geom)
            for i, p in enumerate(puntos):
                if p is None:
                    continue
                if res[i] is None and pgeom.contains(p):
                    res[i] = codigo
        except Exception:
            continue
    return pd.Series(res, index=df_pts.index, name="cod_cuadrante")

def _conteo_muestras_por_poligono(df_pts, features):
    """
    Cuenta muestras por polígono usando shapely puro (sin geopandas).
    df_pts requiere columnas 'lat' y 'lon'
    """
    puntos = [Point(float(x), float(y)) for y, x in zip(df_pts['lat'], df_pts['lon'])]
    res = {}  # codigo -> conteo
    for feat in features:
        props = feat.get('properties', {})
        codigo = props.get('codigo', '')
        if not codigo:
            continue
        geom = shape(feat.get('geometry', {}))
        prep_geom = prep(geom)
        # Conteo local por polígono
        count = sum(1 for p in puntos if prep_geom.contains(p))
        res[codigo] = count
    return res

def _calcular_area_m2_fallback(geom_geojson: dict) -> float:
    """Fallback aproximado cuando la geometría es inválida y falla Geod."""
    try:
        geom = shape(geom_geojson)
        bounds = geom.bounds
        lat_center = (bounds[1] + bounds[3]) / 2
        lat_rad = math.radians(lat_center)
        meters_per_degree_lat = 111000
        meters_per_degree_lon = 111000 * math.cos(lat_rad)
        width_m = (bounds[2] - bounds[0]) * meters_per_degree_lon
        height_m = (bounds[3] - bounds[1]) * meters_per_degree_lat
        # Escalar el área shapely (grados²) a m² usando el área del bbox como referencia
        area_deg2 = geom.area
        bbox_deg2 = (bounds[2]-bounds[0]) * (bounds[3]-bounds[1])
        escala = (width_m * height_m / bbox_deg2) if bbox_deg2 > 0 else 0.0
        return max(0.0, area_deg2 * escala)
    except Exception:
        return 0.0

def _contar_muestras_en_geom(feature_geom: dict, df_pts: pd.DataFrame) -> int:
    """Cuenta muestras dentro de una geometría GeoJSON usando df_pts con columnas 'lat' y 'lon'."""
    try:
        geom = shape(feature_geom)
        prep_geom = prep(geom)
        count = 0
        for _, r in df_pts.iterrows():
            p = Point(float(r['lon']), float(r['lat']))
            if prep_geom.contains(p):
                count += 1
        return count
    except Exception:
        return 0

def _dias_activos_global(df_pts: pd.DataFrame) -> int:
    """Días con al menos 1 muestra en todo el df."""
    if df_pts.empty or 'fecha_dia' not in df_pts.columns:
        return 0
    return int(df_pts['fecha_dia'].nunique())

def _dias_activos_en_geom(feature_geom: dict, df_pts: pd.DataFrame) -> int:
    """Días con al menos 1 muestra dentro de la geometría dada."""
    if df_pts.empty or 'fecha_dia' not in df_pts.columns:
        return 0
    try:
        geom = shape(feature_geom)
        prep_geom = prep(geom)
        # filtrar puntos que caen dentro y tomar días únicos
        dias = set()
        for _, r in df_pts.iterrows():
            p = Point(float(r['lon']), float(r['lat']))
            if prep_geom.contains(p):
                dias.add(r['fecha_dia'])
        return len(dias)
    except Exception:
        return 0

def _calcular_metricas_hijo(feature: dict, df_filtrado: pd.DataFrame) -> dict:
    """
    Calcula métricas para un cuadrante hijo (subcuadrante).
    """
    props = feature.get('properties', {})
    codigo = props.get('codigo', '')
    
    # 1. Área geodésica SIEMPRE del polígono
    try:
        area_m2 = area_m2_geodesic(feature.get('geometry', {}))
        metodo_area = "geodésico"
    except Exception:
        area_m2 = _calcular_area_m2_fallback(feature.get('geometry', {}))
        metodo_area = "fallback"
        logging.warning(f"[AREAS] Fallback en hijo {codigo}")
    
    # 2. Contar muestras dentro del polígono
    total_muestras = _contar_muestras_en_geom(feature.get('geometry', {}), df_filtrado)
    
    # 3. Contar días activos dentro del polígono
    dias_activos = _dias_activos_en_geom(feature.get('geometry', {}), df_filtrado)
    
    result = {
        'codigo': codigo,
        'area_m2': area_m2,
        'total_muestras': total_muestras,
        'dias_activos': dias_activos
    }
    
    if DEBUG_AREAS:
        result['metodo_area'] = metodo_area
        
    return result

def _calcular_metricas_padre(feature_padre: dict, features_hijos: list, metricas_hijos: dict, df_for_conteo: pd.DataFrame) -> dict:
    """
    Calcula métricas para un cuadrante padre directamente sobre su geometría.
    """
    props_padre = feature_padre.get('properties', {})
    codigo_padre = props_padre.get('codigo', '')

    # 1) Área geodésica SIEMPRE del polígono del padre
    try:
        area_total = area_m2_geodesic(feature_padre.get('geometry', {}))
        metodo_area = "geodésico"
    except Exception:
        area_total = _calcular_area_m2_fallback(feature_padre.get('geometry', {}))
        metodo_area = "fallback"
        logging.warning(f"[AREAS] Fallback en padre {codigo_padre}")

    # 2) Conteo de muestras DIRECTO dentro de la geometría del PADRE
    muestras_total = _contar_muestras_en_geom(feature_padre.get('geometry', {}), df_for_conteo)

    # 3) Contar días activos dentro del polígono del padre
    dias_activos = _dias_activos_en_geom(feature_padre.get('geometry', {}), df_for_conteo)

    result = {
        'codigo': codigo_padre,
        'area_m2': area_total,
        'total_muestras': muestras_total,
        'dias_activos': dias_activos
    }
    
    if DEBUG_AREAS:
        result['metodo_area'] = metodo_area
        
    return result

 

def _popup_cuadrante_muestras(codigo: str, area_m2: float, total_local: int, dias_activos: int, metodo_area: str = None, tipo_capa: str = None, verificacion_info: dict = None, ciudad: str = None, n_promotores: int = None) -> str:
    """
    Genera popup HTML para cuadrantes con métricas tradicionales: muestras, días, promotores, tasa, área y hogares estimados.
    """
    # Verificación y alertas de área inusual
    area_km2 = area_m2 / 1_000_000 if area_m2 > 0 else 0.0
    # if area_km2 < 0.005:
    #     st.warning(f"Área muy pequeña detectada en {codigo}: {area_km2:.6f} km²")
    # elif area_km2 > 5.0:
    #     st.warning(f"Área muy grande detectada en {codigo}: {area_km2:.2f} km²")
    
    # Cálculo de tasa (lambda aproximado)
    if n_promotores is None:
        n_promotores = 1  # Valor por defecto si no se proporciona
    
    # Tasa aproximada: muestras / (promotores * días)
    tasa = (total_local / (n_promotores * dias_activos)) if (n_promotores > 0 and dias_activos > 0) else 0.0
    
    # Cálculo de hogares estimados
    hogares_estimados = 0


    # Formateo ES-CO con punto como separador de miles y coma como decimal
    area_m2_fmt = __fmt_es(area_m2, 0)  # Usar la función estándar ya disponible
    area_km2_fmt = __fmt_es(area_km2, 2, False)  # Sin separador de miles para decimales
    cantidad_fmt = __fmt_es(total_local, 0)  # Con separador de miles
    tasa_fmt = __fmt_es(tasa, 2, False)
    hogares_estimados_fmt = __fmt_es(hogares_estimados, 0) if hogares_estimados > 0 else "N/D"

    # Líneas debug opcionales
    debug_lines = ""
    if DEBUG_AREAS:
        # Información básica del método
        if metodo_area:
            debug_lines += f'<div style="font-size:11px;color:#6b7280;margin-bottom:2px;">Método de área: {metodo_area}</div>'
        
        # Información de la capa
        if tipo_capa:
            debug_lines += f'<div style="font-size:11px;color:#6b7280;margin-bottom:2px;">Código: {codigo} · Capa: {tipo_capa}</div>'
        
        # Información de verificación si está disponible
        if verificacion_info:
            if verificacion_info['verificado']:
                debug_lines += f'<div style="font-size:11px;color:#16a34a;margin-bottom:2px;">✓ Área verificada (geodésica)</div>'
            else:
                diff_pct = verificacion_info['diff_pct']
                debug_lines += f'<div style="font-size:11px;color:#dc2626;margin-bottom:2px;">⚠ Mismatch área cache vs draw: {diff_pct:.1f}%</div>'
            
            # Información de geometría
            tipo_geom = verificacion_info['tipo_geom']
            num_anillos = verificacion_info['num_anillos']
            debug_lines += f'<div style="font-size:10px;color:#9ca3af;margin-bottom:4px;">{tipo_geom} ({num_anillos} anillo{"s" if num_anillos != 1 else ""})</div>'

    return f"""
    <div style="font-family: Inter, system-ui; font-size: 14px; line-height: 1.3;">
        <div style="font-weight:600; margin-bottom:8px; font-size:16px;">{codigo}</div>
        {debug_lines}
        
        <!-- Métricas principales (nuevo orden) -->
        <div style="margin-top:8px; font-size:13px; line-height:1.4;">
            <div><strong>Muestras (local):</strong> {cantidad_fmt}</div>
            <div><strong>Días de operación:</strong> {dias_activos}</div>
            <div><strong>Promotores:</strong> {n_promotores}</div>
            <div><strong>Tasa:</strong> {tasa_fmt}</div>
        </div>
        
        <!-- Área + Hogares estimados -->
        <div style="margin-top:6px; font-size:11px; color:#6b7280;">
            Área: {area_m2_fmt} m² ({area_km2_fmt} km²) • Hogares estimados: {hogares_estimados_fmt}
        </div>
    </div>
    """

def _style_cuadrante_padre(feat):
    """
    Estilo más tenue para cuadrantes padre (debajo de los hijos).
    """
    base = _style_cuadrante(feat)
    base.update({'fillOpacity': 0.5, 'weight': 1.5})  # más tenue que los hijos
    return base

def _verificar_area_draw_vs_cache(feature: dict, area_cache: float, tipo_capa: str) -> dict:
    """
    Verifica que el área calculada en draw-time coincida con la del cache.
    Retorna información sobre la verificación para mostrar en popup.
    """
    try:
        # Recalcular área del polígono en tiempo de dibujo
        area_draw = area_m2_geodesic(feature.get('geometry', {}))
        
        # Calcular diferencia porcentual
        if area_cache > 0:
            diff_pct = abs(area_draw - area_cache) / area_cache * 100
        else:
            diff_pct = 0.0
        
        # Información de la geometría
        geom = shape(feature.get('geometry', {}))
        tipo_geom = geom.geom_type
        num_anillos = 0
        if hasattr(geom, 'exterior'):
            num_anillos = 1 + len(list(geom.interiors))
        elif hasattr(geom, 'geoms'):
            num_anillos = sum(1 + len(list(g.interiors)) if hasattr(g, 'interiors') else 1 for g in geom.geoms)
        
        return {
            'area_draw': area_draw,
            'area_cache': area_cache,
            'diff_pct': diff_pct,
            'tipo_geom': tipo_geom,
            'num_anillos': num_anillos,
            'verificado': diff_pct <= 0.5  # Consideramos OK si diferencia <= 0.5%
        }
        
    except Exception as e:
        logging.warning(f"Error en verificación de área para {tipo_capa}: {e}")
        return {
            'area_draw': 0,
            'area_cache': area_cache,
            'diff_pct': 100.0,
            'tipo_geom': 'Error',
            'num_anillos': 0,
            'verificado': False
        }

def compactar_dos_palabras(nombre_completo, pid=""):
    """
    Reglas sobre el string 'apellido' (nombre completo):
    - 1 palabra  -> 1ª
    - 2 palabras -> 1ª + 2ª
    - 3 palabras -> 1ª + 2ª
    - 4+         -> 1ª + 3ª
    Render en minúsculas. Si vacío: 'id {pid}'.
    """
    if not nombre_completo:
        return f"id {pid}".strip()
    tokens = [t.lower() for t in re.split(r"\s+", nombre_completo.strip()) if t]
    n = len(tokens)
    if n == 1:  return tokens[0]
    if n == 2:  return f"{tokens[0]} {tokens[1]}"
    if n == 3:  return f"{tokens[0]} {tokens[1]}"
    return f"{tokens[0]} {tokens[2]}"

def generate_hsv_colors(n):
    """Genera una paleta de colores HSV con mayor contraste."""
    hues = np.linspace(0, 1, n, endpoint=False)
    return [colors.rgb2hex(colors.hsv_to_rgb((hue, 1.0, 1.0))) for hue in hues]

# Paleta determinista (20 colores) para promotores
PALETTE_PROMOTORES = [
    "#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED",
    "#DB2777", "#0D9488", "#1D4ED8", "#B45309", "#065F46",
    "#9333EA", "#EA580C", "#047857", "#9D174D", "#4F46E5",
    "#BE123C", "#0EA5E9", "#6D28D9", "#16A34A", "#B91C1C"
]

def color_for_promotor(centroope: int, id_autor: int) -> str:
    """Color estable por (centroope, id_autor) usando hash md5."""
    try:
        h = md5(f"{centroope}-{int(id_autor)}".encode()).hexdigest()
        idx = int(h, 16) % len(PALETTE_PROMOTORES)
        return PALETTE_PROMOTORES[idx]
    except Exception:
        return "#64748B"

# === PALETA DETERMINISTA PARA PROMOTORES (COLORES ESTABLES) ===
PALETTE_PROMOTORES = [
    "#2563EB", "#DC2626", "#059669", "#D97706", "#7C3AED",
    "#DB2777", "#0D9488", "#1D4ED8", "#B45309", "#065F46",
    "#9333EA", "#EA580C", "#047857", "#9D174D", "#4F46E5",
    "#BE123C", "#0EA5E9", "#6D28D9", "#16A34A", "#B91C1C"
]

def color_for_promotor(centroope: int, id_autor: int) -> str:
    """Devuelve un color determinista estable para un promotor dado un centroope.
    Usa hash md5(centroope-id_autor) mod len(PALETTE_PROMOTORES).
    """
    try:
        key = f"{centroope}-{int(id_autor)}".encode()
        h = md5(key).hexdigest()
        idx = int(h, 16) % len(PALETTE_PROMOTORES)
        return PALETTE_PROMOTORES[idx]
    except Exception:
        return "#64748B"  # Gris fallback

# === Assets para tablas ordenables en leyendas ===
_TA_SORTABLE_ASSETS_ADDED = False

def inject_sort_assets(mapa):
        """Inserta CSS y JS para ordenar tablas (idempotente por proceso)."""
        global _TA_SORTABLE_ASSETS_ADDED
        if _TA_SORTABLE_ASSETS_ADDED:
                return
        css_block = """
        <style id="ta-sortable-css">
        .ta-sortable th { cursor:pointer; white-space:nowrap; }
        .ta-sortable th .ta-sort-arrow { margin-left:6px; opacity:.5; }
        .ta-sortable th.ta-sort-asc  .ta-sort-arrow::after { content:"▲"; opacity:1; }
        .ta-sortable th.ta-sort-desc .ta-sort-arrow::after { content:"▼"; opacity:1; }
        </style>
        """
        js_block = """
        <script id="ta-sortable-js">
        (function(){
            if (window.TASortable) return; // idempotencia
            function normNum(s){
                if (s==null) return NaN;
                s = String(s).trim().toLowerCase();
                if (s==="—" || s==="" || s==="na" || s==="n/d") return NaN;
                s = s.replace(/\s/g,"");
                s = s.replace(/[%,$€]/g,"");
                s = s.replace(/\./g,"");         // quita miles con punto
                s = s.replace(/,/g,".");         // coma -> punto (por si acaso)
                var v = parseFloat(s);
                return isNaN(v) ? NaN : v;
            }
            function getCellVal(td, type){
                const txt = td?.textContent ?? "";
                if (type==="num" || type==="percent" || type==="money") return normNum(txt);
                if (type==="date") return new Date(txt).getTime() || 0;
                return txt.toString().toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu,"");
            }
            function sortTable(tbl, colIdx, type, dir){
                const tbody = tbl.tBodies[0];
                const rows = Array.from(tbody.rows);
                rows.sort((a,b)=>{
                    const va = getCellVal(a.cells[colIdx], type);
                    const vb = getCellVal(b.cells[colIdx], type);
                    if (isNaN(va) && isNaN(vb)) return 0;
                    if (isNaN(va)) return  1;
                    if (isNaN(vb)) return -1;
                    return (va<vb?-1:va>vb?1:0) * (dir==="asc"?1:-1);
                });
                rows.forEach(r=>tbody.appendChild(r));
            }
            function attach(table){
                if (!table || table.__taSortable) return;
                table.__taSortable = true;
                const ths = table.tHead ? Array.from(table.tHead.rows[0].cells) : [];
                ths.forEach((th, i)=>{
                    const type = th.dataset.type || "text";
                    const span = document.createElement("span"); span.className="ta-sort-arrow"; th.appendChild(span);
                    th.addEventListener("click", ()=>{
                        const cur = th.classList.contains("ta-sort-asc") ? "asc" : th.classList.contains("ta-sort-desc") ? "desc" : "";
                        ths.forEach(h=>h.classList.remove("ta-sort-asc","ta-sort-desc"));
                        const dir = (cur==="" || cur==="desc") ? "asc" : "desc";
                        th.classList.add(dir==="asc"?"ta-sort-asc":"ta-sort-desc");
                        sortTable(table, i, type, dir);
                    });
                });
            }
            window.TASortable = { initAll: function(){ document.querySelectorAll("table.ta-sortable").forEach(attach); }, attach };
        })();
        </script>
        """
        try:
                mapa.get_root().html.add_child(folium.Element(css_block))
                mapa.get_root().html.add_child(folium.Element(js_block))
                _TA_SORTABLE_ASSETS_ADDED = True
        except Exception:
                pass

# === Helpers normalizados para leyendas de muestras (promotores / meses) ===
def _build_legend_row_struct(
    etiqueta: str,
    muestras_total: int,
    clientes_total: int,
    dias_habiles: int,
    pct_no_fieles: float,
    pct_contactables: float,
    pct_contactables_nofieles: float,
    area_km2: float | None = None,
    muestras_por_km2: float | None = None,
    muestras_por_dia_habil: float | None = None,
    color_hex: str | None = None,
):
    """Estructura normalizada para una fila de la leyenda de muestras.
    'etiqueta' será el Promotor o el Mes según el contexto.
    """
    import pandas as _pd
    return {
        "etiqueta": etiqueta,
        "muestras_total": int(muestras_total) if _pd.notna(muestras_total) else 0,
        "clientes_total": int(clientes_total) if _pd.notna(clientes_total) else 0,
        "dias_habiles": int(dias_habiles) if _pd.notna(dias_habiles) else 0,
        "pct_no_fieles": float(pct_no_fieles) if _pd.notna(pct_no_fieles) else 0.0,
        "pct_contactables": float(pct_contactables) if _pd.notna(pct_contactables) else 0.0,
        "pct_contactables_nofieles": float(pct_contactables_nofieles) if _pd.notna(pct_contactables_nofieles) else 0.0,
        "area_km2": float(area_km2) if (area_km2 is not None and _pd.notna(area_km2)) else None,
        "muestras_por_km2": float(muestras_por_km2) if (muestras_por_km2 is not None and _pd.notna(muestras_por_km2)) else None,
        "muestras_por_dia_habil": float(muestras_por_dia_habil) if (muestras_por_dia_habil is not None and _pd.notna(muestras_por_dia_habil)) else None,
        "color_hex": color_hex,
    }

def _render_legend_html_muestras(lista_structs: list[dict], titulo: str, label_col: str) -> str:
    """Genera HTML de la leyenda flotante para muestras.
    Orden de columnas fijo:
    label_col | #Muestras | #Clientes | Área km² | Muestras/km² | Muestras/día hábil | % Muestras NO fieles | % Total Muestras contactables | % Contactabilidad No Fieles
    """
    def _fmt_int(v):
        try:
            return f"{int(round(v)):,}".replace(',', '.')
        except Exception:
            return '—'
    def _fmt_pct(v):
        try:
            return f"{float(v):.1f}%"
        except Exception:
            return '—'
    def _fmt_area_km2(v):
        if v is None:
            return '—'
        try:
            # Preservar lógica previa (area_m2/1000 mostrado como km²)
            return f"{float(v):,.0f}".replace(',', '.')
        except Exception:
            return '—'
    def _fmt_muestras_km2(v):
        if v is None:
            return '—'
        try:
            return f"{float(v):,.10f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        except Exception:
            return '—'
    rows_html = []
    for r in lista_structs:
        color_span = ''
        if r.get('color_hex'):
            color_span = f"<span style='display:inline-block;width:12px;height:12px;border-radius:3px;background:{r['color_hex']};'></span>"
        muestras_dia_habil = r.get('muestras_por_dia_habil')
        if muestras_dia_habil is not None:
            try:
                muestras_dia_habil_fmt = _fmt_int(muestras_dia_habil)
            except Exception:
                muestras_dia_habil_fmt = '—'
        else:
            muestras_dia_habil_fmt = '—'
        rows_html.append(f"""
        <tr>
            <td style='padding:6px 8px;display:flex;align-items:center;gap:8px;'>
                {color_span}<span>{r['etiqueta']}</span>
            </td>
            <td style='padding:6px 8px;text-align:right;'>{_fmt_int(r['muestras_total'])}</td>
            <td style='padding:6px 8px;text-align:right;'>{_fmt_int(r['clientes_total'])}</td>
            <td style='padding:6px 8px;text-align:center;'>{_fmt_area_km2(r.get('area_km2'))}</td>
            <td style='padding:6px 8px;text-align:center;'>{_fmt_muestras_km2(r.get('muestras_por_km2'))}</td>
            <td style='padding:6px 8px;text-align:right;'>{muestras_dia_habil_fmt}</td>
            <td style='padding:6px 8px;text-align:right;'>{_fmt_pct(r['pct_no_fieles'])}</td>
            <td style='padding:6px 8px;text-align:right;'>{_fmt_pct(r['pct_contactables'])}</td>
            <td style='padding:6px 8px;text-align:right;'>{_fmt_pct(r['pct_contactables_nofieles'])}</td>
        </tr>
        """)
    return f"""
    <div id='legend-promotores' style='
        position: fixed; bottom: 20px; left: 20px; z-index: 1000;
        background: white; border: 1px solid #e5e7eb; border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,.12); padding: 10px 12px; max-height: 45vh; overflow-y: auto;'>
      <details open>
        <summary style='cursor:pointer;font-weight:600;color:#111;'>{titulo}</summary>
        <div style='margin-top:8px;'>
          <table style='border-collapse:collapse; width:100%; font-size:12px;' class='ta-sortable'>
            <thead>
              <tr>
                <th style='text-align:left; padding:6px 8px; border-bottom:1px solid #eee;'>{label_col}</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' title='# total de muestras' data-type='num'>#Muestras</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' title='# de clientes únicos' data-type='num'>#Clientes</th>
                <th style='text-align:center; padding:6px 4px; border-bottom:1px solid #eee;' data-type='num'>Área km²</th>
                <th style='text-align:center; padding:6px 4px; border-bottom:1px solid #eee;' data-type='num'>Muestras/km²</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' title='Promedio entero de muestras por día hábil' data-type='num'>Muestras/día hábil</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' data-type='percent'>% Muestras NO fieles</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' data-type='percent'>% Total Muestras contactables</th>
                <th style='text-align:right; padding:6px 8px; border-bottom:1px solid #eee;' title='contactables_no_fieles / muestras_total × 100' data-type='percent'>% Contactabilidad No Fieles</th>
              </tr>
            </thead>
            <tbody>
              {''.join(rows_html)}
            </tbody>
          </table>
        </div>
      </details>
    </div>
    """

def get_promotor_display_name(pid, df_filtrado, legend_name_map=None):
    """Función centralizada para obtener el nombre visible del promotor."""
    pid_str = str(pid)
    
    # Si ya existe en el mapa de nombres, usarlo
    if legend_name_map and pid_str in legend_name_map:
        return legend_name_map[pid_str]
    
    # Buscar en el DataFrame filtrado
    datos_promotor = df_filtrado[df_filtrado['id_autor'] == pid]
    if not datos_promotor.empty:
        row = datos_promotor.iloc[0]
        
        # Buscar columna de nombre disponible
        nombre_col = None
        for col in ['apellido', 'apellido_autor', 'promotor_nombre', 'nombre_autor', 'nombre_completo']:
            if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
                nombre_col = col
                break
        
        if nombre_col:
            return compactar_dos_palabras(str(row[nombre_col]), pid_str)
    
    return f"Promotor {pid_str}"

def build_promotores_groups(
    df,
    parent_group,
    colores_promotores_map,
    legend_name_map=None,
    mapa=None,
    grupos_por_promotor=None,
):
    """Construye subgrupos (FeatureGroupSubGroup) por promotor.
    Permite reutilizar un dict precomputado {id_autor: df_sub} para evitar repetidos groupby.
    Devuelve lista de tuplas (nombre_promotor, subgrupo, count, color)."""
    # Fuente de agrupación única
    if grupos_por_promotor is None:
        grupos_por_promotor = dict(tuple(df.groupby('id_autor')))

    # Conteos derivados de grupos_por_promotor
    promotor_counts = {pid: len(df_sub) for pid, df_sub in grupos_por_promotor.items()}
    # Ordenar ids por cantidad desc (criterio original preservado)
    orden_ids = sorted(promotor_counts.keys(), key=promotor_counts.get, reverse=True)

    grupos_promotores = []
    valores_colores = list(colores_promotores_map.values()) or ["#64748B"]
    for idx, pid in enumerate(orden_ids):
        datos_promotor = grupos_por_promotor.get(pid)
        if datos_promotor is None or datos_promotor.empty:
            continue
        count = promotor_counts.get(pid, len(datos_promotor))

        nombre_promotor = get_promotor_display_name(pid, df, legend_name_map)
        color_promotor = (
            colores_promotores_map.get(str(pid))
            or colores_promotores_map.get(pid)
            or valores_colores[idx % len(valores_colores)]
        )

        sg = FeatureGroupSubGroup(parent_group, name=nombre_promotor, show=True)
        if mapa is not None:
            mapa.add_child(sg)

        for _, row in datos_promotor.iterrows():
            lat = row.get('coordenada_latitud', row.get('latitud', None))
            lng = row.get('coordenada_longitud', row.get('longitud', None))
            if lat is None or lng is None:
                continue
            popup_text = f"""
            <b>Promotor:</b> {nombre_promotor}<br>
            <b>ID:</b> {pid}<br>
            <b>Barrio:</b> {row.get('barrio', '-') }<br>
            <b>Fecha:</b> {row.get('fecha_evento', row.get('fecha_muestra', '-'))}
            """
            folium.CircleMarker(
                location=[lat, lng],
                radius=5,
                color=color_promotor,
                fill=True,
                fillColor=color_promotor,
                fillOpacity=0.9,
                popup=folium.Popup(popup_text, max_width=320),
            ).add_to(sg)

        grupos_promotores.append((nombre_promotor, sg, count, color_promotor))

    return grupos_promotores

# build_barrios_groups eliminado (deprecado en flujo Directores)

def generar_mapa_muestras(
    fecha_inicio,
    fecha_fin,
    ciudad,
    barrios=None,
    promotores=None,
    override_fc=None,
    color_mode="Promotores",
    verificar_areas=False,
    clientes_x_muestras: bool = False,
):
    try:
        # Toggle debug areas
        global DEBUG_AREAS
        DEBUG_AREAS_ORIGINAL = DEBUG_AREAS
        if verificar_areas:
            DEBUG_AREAS = True

        # Normalizar ciudad y fechas
        ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        fecha_inicio = str(fecha_inicio)
        fecha_fin = str(fecha_fin)

        # Validación de año único para modo Temporalidad
        if color_mode == "Temporalidad (mes)":
            from datetime import datetime
            try:
                dt_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
                dt_fin = datetime.strptime(fecha_fin, "%Y-%m-%d")
                if dt_inicio.year != dt_fin.year:
                    st.error("❌ Error: El modo 'Temporalidad (mes)' requiere que ambas fechas estén en el mismo año.")
                    mapa = folium.Map(location=[4.7110, -74.0721], zoom_start=12)
                    filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
                    return filename, 0, None
            except ValueError:
                st.error("❌ Error: Formato de fecha inválido para el modo 'Temporalidad (mes)'.")
                mapa = folium.Map(location=[4.7110, -74.0721], zoom_start=12)
                filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
                return filename, 0, None

        # Configuración por ciudad
        rutas_coordenadas = {
            'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
            'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
            'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
            'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
            'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
            'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
            'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv",
        }
        coordenadas_ciudades = {
            'CALI': ([3.4516, -76.5320], 'geojson/rutas/cali/cuadrantes_rutas_cali.geojson'),
            'MEDELLIN': ([6.2442, -75.5812], 'geojson/rutas/medellin/cuadrantes_rutas_medellin.geojson'),
            'MANIZALES': ([5.0672, -75.5174], 'geojson/rutas/manizales/cuadrantes_rutas_manizales.geojson'),
            'PEREIRA': ([4.8087, -75.6906], 'geojson/rutas/pereira/cuadrantes_rutas_pereira.geojson'),
            'BOGOTA': ([4.7110, -74.0721], 'geojson/rutas/bogota/cuadrantes_rutas_bogota.geojson'),
            'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/rutas/barranquilla/cuadrantes_rutas_barranquilla.geojson'),
            'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/rutas/bucaramanga/cuadrantes_rutas_bucaramanga.geojson'),
        }
        centroopes = {'CALI': 2, 'MEDELLIN': 3, 'MANIZALES': 6, 'PEREIRA': 5, 'BOGOTA': 4, 'BARRANQUILLA': 8, 'BUCARAMANGA': 7}
        if ciudad not in rutas_coordenadas:
            logging.error(f"Ciudad no reconocida: {ciudad}")
            mapa = folium.Map(location=[4.7110, -74.0721], zoom_start=12)
            filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
            return filename, 0, None

        centroope = centroopes[ciudad]
        ruta_coordenadas = rutas_coordenadas[ciudad]
        location, geojson_file_path = coordenadas_ciudades[ciudad]

        # Construir DF base
        df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, promotores=promotores)
        if df.empty:
            logging.warning(f"No hay datos para las fechas {fecha_inicio} - {fecha_fin}")
            mapa = folium.Map(location=location, zoom_start=12)
            filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
            return filename, 0, None

        # Preparar columnas de fecha y filtrado
        df['fecha_evento'] = pd.to_datetime(df.get('fecha_evento', df.get('fecha')), errors='coerce')
        df['fecha_dia'] = df['fecha_evento'].dt.date

        # Modo opcional: Clientes x Muestras (una fila por cliente y promotor)
        if clientes_x_muestras and {'id_autor', 'id_contacto'}.issubset(df.columns):
            df = (
                df.sort_values('fecha_evento')
                  .drop_duplicates(subset=['id_autor', 'id_contacto'], keep='last')
            )

        df_filtrado = df.copy()
        if barrios:
            if 'barrio' in df_filtrado.columns:
                df_filtrado = df_filtrado[df_filtrado['barrio'].isin(barrios)]

        # Estadísticas para resumen
        dias_activos_global = _dias_activos_global(df_filtrado)
        cantidad_barrios = df_filtrado['barrio'].nunique() if 'barrio' in df_filtrado.columns else 0
        total_cantidad = df_filtrado.shape[0]
        promedio_muestras = (total_cantidad / dias_activos_global) if dias_activos_global > 0 else 0.0
        promedio_muestras_barrios = (total_cantidad / cantidad_barrios) if cantidad_barrios > 0 else 0.0
        stats_data = {
            'barrios': barrios if barrios else 'Todos',
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'promedio_muestras': promedio_muestras,
            'cantidad_barrios': cantidad_barrios,
            'promedio_muestras_barrios': promedio_muestras_barrios,
            'total_cantidad': total_cantidad,
        }

        # Crear mapa base
        mapa = folium.Map(location=location, zoom_start=12)

        # CSS de z-index para stacking
        zindex_css = """
        <style>
        .leaflet-interactive[style*='stroke-width: 3'] { z-index: 630 !important; }
        .leaflet-interactive[style*='stroke-width: 2'] { z-index: 620 !important; }
        .leaflet-overlay-pane .leaflet-interactive { position: relative; }
        </style>
        """
        mapa.get_root().html.add_child(folium.Element(zindex_css))

        # Grupos base
        comunas_group = folium.FeatureGroup(name="Comunas", show=True).add_to(mapa)
        cuadrantes_padres_group = folium.FeatureGroup(name="Cuadrantes (Padres)", show=True).add_to(mapa)
        cuadrantes_hijos_group = folium.FeatureGroup(name="Cuadrantes (Hijos)", show=True).add_to(mapa)

        # Cargar base geográfica
        if override_fc is not None:
            barrios_geojson = override_fc
        else:
            with open(geojson_file_path, 'r') as f:
                barrios_geojson = json.load(f)

        # Enriquecer y separar features
        features_comunas = []
        features_cuadrantes = []
        for feature in barrios_geojson.get('features', []):
            props = feature.get('properties', {})
            codigo_val = (props.get('codigo') or props.get('CODIGO') or props.get('code') or '').strip()
            props['display_name'] = resolver_nombre_ruta(ciudad, codigo_val, props)
            # Heurística: si tiene 'codigo' => cuadrante, si no => comuna
            if codigo_val:
                if _es_cuadrante_padre(feature) or _es_cuadrante_hijo(feature):
                    features_cuadrantes.append(feature)
                else:
                    features_comunas.append(feature)
            else:
                features_comunas.append(feature)

        # Dibujar comunas
        for feature in features_comunas:
            folium.GeoJson(
                data=feature,
                style_function=lambda x: {'fillColor': 'transparent', 'color': '#000000', 'weight': 1.5, 'fillOpacity': 0.0}
            ).add_to(comunas_group)

        # Preparar DF conteo
        df_for_conteo = df_filtrado.copy()
        df_for_conteo['lat'] = df_for_conteo.apply(lambda r: r.get('coordenada_latitud', r.get('latitud', None)), axis=1)
        df_for_conteo['lon'] = df_for_conteo.apply(lambda r: r.get('coordenada_longitud', r.get('longitud', None)), axis=1)
        df_for_conteo['fecha_dia'] = df_for_conteo['fecha_evento'].dt.date
        df_for_conteo = df_for_conteo.dropna(subset=['lat', 'lon'])
        # Métricas por cuadrante
        features_padres = [f for f in features_cuadrantes if _es_cuadrante_padre(f)]
        features_hijos = [f for f in features_cuadrantes if _es_cuadrante_hijo(f)]
        metricas_cache = {}
        area_map = {}
        for fh in features_hijos:
            met = _calcular_metricas_hijo(fh, df_for_conteo)
            metricas_cache[('HIJO', met['codigo'])] = met
            area_map[met['codigo']] = met['area_m2']
        for fp in features_padres:
            met = _calcular_metricas_padre(fp, features_hijos, metricas_cache, df_for_conteo)
            metricas_cache[('PADRE', met['codigo'])] = met
            area_map[met['codigo']] = met['area_m2']

                

        # Dibujar PADRES
        for feature_padre in features_padres:
            props = feature_padre.get('properties', {})
            codigo = str(props.get('codigo', ''))
            nombre_display = props.get('display_name', codigo)
            m = metricas_cache.get(('PADRE', codigo))
            if not m:
                continue
            metodo_area = m.get('metodo_area') if DEBUG_AREAS else None
            verificacion_info = _verificar_area_draw_vs_cache(feature_padre, m['area_m2'], 'PADRE') if verificar_areas else None
            total_local = m.get('muestras_local', m.get('total_muestras', 0))
            dias_activos = m.get('dias_activos', 0)
            popup_html = _popup_cuadrante_muestras(
                codigo,
                m['area_m2'],
                total_local,
                dias_activos,
                metodo_area=metodo_area,
                tipo_capa='PADRE',
                verificacion_info=verificacion_info,
                ciudad=ciudad,
                n_promotores=None
            )
            layer_padre = folium.GeoJson(
                data=feature_padre,
                style_function=_style_cuadrante_padre,
                popup=folium.Popup(popup_html, max_width=500),
                tooltip=folium.Tooltip(f"<b>{nombre_display}</b>"),
            )
            layer_padre.add_to(cuadrantes_padres_group)

        # Dibujar HIJOS
        for feature_hijo in features_hijos:
            props = feature_hijo.get('properties', {})
            codigo = str(props.get('codigo', ''))
            nombre_display = props.get('display_name', codigo)
            m = metricas_cache.get(('HIJO', codigo))
            if not m:
                continue
            metodo_area = m.get('metodo_area') if DEBUG_AREAS else None
            verificacion_info = _verificar_area_draw_vs_cache(feature_hijo, m['area_m2'], 'HIJO') if verificar_areas else None
            total_local = m.get('muestras_local', m.get('total_muestras', 0))
            dias_activos = m.get('dias_activos', 0)
            popup_html = _popup_cuadrante_muestras(
                codigo,
                m['area_m2'],
                total_local,
                dias_activos,
                metodo_area=metodo_area,
                tipo_capa='HIJO',
                verificacion_info=verificacion_info,
                ciudad=ciudad,
                n_promotores=None
            )
            layer_hijo = folium.GeoJson(
                data=feature_hijo,
                style_function=_style_cuadrante,
                popup=folium.Popup(popup_html, max_width=500),
                tooltip=folium.Tooltip(f"<b>{nombre_display}</b>"),
            )
            layer_hijo.add_to(cuadrantes_hijos_group)

        # Construir nombres de promotor para legendas
        legend_name_map = {}
        nombre_col_candidates = ["nombre_completo_autor", "apellido_autor", "apellido"]
        nombre_col = next((c for c in nombre_col_candidates if c in df_filtrado.columns), None)
        if nombre_col:
            tmp = df_filtrado[["id_autor", nombre_col]].dropna(subset=[nombre_col]).drop_duplicates("id_autor")
            for _, r in tmp.iterrows():
                pid = str(r['id_autor'])
                legend_name_map[pid] = compactar_dos_palabras(r[nombre_col], pid)
        faltantes = [str(pid) for pid in df_filtrado['id_autor'].dropna().unique().tolist() if str(pid) not in legend_name_map]
        if faltantes:
            try:
                from pre_procesamiento.preprocesamiento_muestras import obtener_promotores_por_ids
                fetched = obtener_promotores_por_ids(faltantes) or {}
                for pid in faltantes:
                    legend_name_map[pid] = compactar_dos_palabras(fetched.get(pid), pid)
            except Exception:
                for pid in faltantes:
                    legend_name_map[pid] = f"id {pid}"

        legend_html = ""
        # Modo PROMOTORES
        if color_mode == "Promotores":
            fg_promotores = folium.FeatureGroup(name="PROMOTORES", show=True).add_to(mapa)
            # (Refactor Fase 1) Agrupación única por promotor reutilizable
            grupos_por_promotor = dict(tuple(df_filtrado.groupby('id_autor')))
            promotores_ordenados = sorted(
                grupos_por_promotor.keys(),
                key=lambda pid: len(grupos_por_promotor[pid]),
                reverse=True,
            )
            promotores_ordenados = [int(pid) for pid in promotores_ordenados]
            colores_promotores_map = {str(pid): color_for_promotor(centroope, pid) for pid in promotores_ordenados}
            grupos_promotores = build_promotores_groups(
                df_filtrado,
                parent_group=fg_promotores,
                colores_promotores_map=colores_promotores_map,
                legend_name_map=legend_name_map,
                mapa=mapa,
                grupos_por_promotor=grupos_por_promotor,
            )
            # Control de capas
            if HAS_TREE_CONTROL:
                TreeLayerControl(collapsed=True, position='topright').add_to(mapa)
            else:
                folium.LayerControl(collapsed=True, position='topright').add_to(mapa)
            # Métricas por promotor (muestras)
            # Placeholder: preparar entrada de métricas de área por promotor (sin usar aún)
            try:
                logging.info(
                    f"[AREAS-DEBUG] ciudad={ciudad} centroope={centroope} "
                    f"filas_df_filtrado={len(df_filtrado)} "
                    f"cols={list(df_filtrado.columns)} "
                    f"lat_nonnull={df_filtrado['coordenada_latitud'].notna().sum() if 'coordenada_latitud' in df_filtrado.columns else 'NO_COL'} "
                    f"lon_nonnull={df_filtrado['coordenada_longitud'].notna().sum() if 'coordenada_longitud' in df_filtrado.columns else 'NO_COL'}"
                )
                df_area_prom = metricas_areas_muestras(df_filtrado, centroope)
            except Exception:
                df_area_prom = pd.DataFrame(columns=["id_autor","area_m2","densidad_compacta_promotor"])
            try:
                df_prom = prepo_metricas_promotores_muestras(ciudad=ciudad, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, ids_autor=promotores_ordenados, df_muestras=df_filtrado)
            except Exception as e:
                logging.error(f"Error métricas promotores muestras: {e}")
                df_prom = pd.DataFrame(columns=['id_autor','muestras_total','dias_habiles','muestras_no_fieles','pct_no_fieles','muestras_contactables','pct_contactables','muestras_contactables_nofieles','pct_contactables_nofieles','area_m2','muestras_area'])
            prom_metrics = {int(r['id_autor']): r for _, r in df_prom.iterrows()} if not df_prom.empty else {}
            # Mapa de densidad compacta por promotor (promedio ponderado por puntos)
            densidad_map = {}
            if df_area_prom is not None and not df_area_prom.empty:
                try:
                    for _, r in df_area_prom.iterrows():
                        pidv = r.get('id_autor')
                        if pd.notna(pidv):
                            densidad_map[int(pidv)] = r.get('densidad_compacta_promotor', np.nan)
                except Exception:
                    densidad_map = {}
            # Cálculo de clientes únicos por promotor a partir del DF filtrado actual
            if {'id_autor', 'id_contacto'}.issubset(df_filtrado.columns):
                clientes_por_promotor = df_filtrado.groupby('id_autor')['id_contacto'].nunique()
            else:
                clientes_por_promotor = pd.Series(dtype='int64')
            # Construir estructuras normalizadas y renderizar con helper
            rows_struct = []
            for (nombre_compacto, _sg, count_muestras, color_hex) in grupos_promotores:
                pid_match = None
                for pid_str, disp_name in legend_name_map.items():
                    if disp_name == nombre_compacto:
                        pid_match = int(pid_str)
                        break
                if pid_match is None:
                    try:
                        pid_match = int(str(nombre_compacto).split()[-1])
                    except Exception:
                        continue
                met = prom_metrics.get(pid_match, {})
                muestras_total = int(met.get('muestras_total', count_muestras) or 0)
                try:
                    clientes_total = int(clientes_por_promotor.get(pid_match, 0) or 0)
                except Exception:
                    clientes_total = 0
                dias_habiles = int(met.get('dias_habiles', 0) or 0)
                muestras_por_dia_habil = (muestras_total / dias_habiles) if dias_habiles > 0 else None
                pct_no_fieles = float(met.get('pct_no_fieles', 0.0) or 0.0)
                pct_contactables = float(met.get('pct_contactables', 0.0) or 0.0)
                pct_contactables_nofieles = float(met.get('pct_contactables_nofieles', 0.0) or 0.0)
                area_m2 = met.get('area_m2')
                muestras_area = met.get('muestras_area')
                # Convertir a mismas unidades de presentación (factor 1000 como antes)
                area_km2 = (area_m2 / 1000.0) if (area_m2 is not None and not (isinstance(area_m2, float) and np.isnan(area_m2))) else None
                muestras_por_km2 = (muestras_area * 1000.0) if (muestras_area is not None and not (isinstance(muestras_area, float) and np.isnan(muestras_area))) else None
                rows_struct.append(_build_legend_row_struct(
                    etiqueta=nombre_compacto,
                    muestras_total=muestras_total,
                    clientes_total=clientes_total,
                    dias_habiles=dias_habiles,
                    pct_no_fieles=pct_no_fieles,
                    pct_contactables=pct_contactables,
                    pct_contactables_nofieles=pct_contactables_nofieles,
                    area_km2=area_km2,
                    muestras_por_km2=muestras_por_km2,
                    muestras_por_dia_habil=muestras_por_dia_habil,
                    color_hex=color_hex,
                ))
            legend_html = _render_legend_html_muestras(rows_struct, titulo="Métricas por promotor (muestras)", label_col="Promotor")
        elif color_mode == "Temporalidad (mes)":
            fg_mes = folium.FeatureGroup(name="TEMPORALIDAD", show=True).add_to(mapa)
            df_filtrado['mes'] = df_filtrado['fecha_evento'].dt.month
            df_filtrado['anyo'] = df_filtrado['fecha_evento'].dt.year
            df_filtrado['mes_label'] = df_filtrado['fecha_evento'].dt.strftime('%b').str.title()
            meses_presentes = df_filtrado.groupby(['anyo','mes','mes_label']).size().reset_index().sort_values(['anyo','mes'])
            for _, r in meses_presentes.iterrows():
                mes = r['mes']; anyo = r['anyo']; mes_label = r['mes_label']
                color_mes = PALETA_MESES.get(mes, '#999999')
                sg_mes = FeatureGroupSubGroup(fg_mes, name=f"{mes_label} {anyo}", show=True)
                sg_mes.add_to(mapa)
                datos_mes = df_filtrado[(df_filtrado['mes']==mes)&(df_filtrado['anyo']==anyo)]
                for _, punto in datos_mes.iterrows():
                    try:
                        lat = punto.get('coordenada_latitud', punto.get('latitud'))
                        lon = punto.get('coordenada_longitud', punto.get('longitud'))
                        if pd.notna(lat) and pd.notna(lon):
                            popup_content = f"""
                            <div style='font-family: Arial, sans-serif; font-size: 12px;'>
                                <b>Muestra #{punto.get('id', 'N/A')}</b><br>
                                Fecha: {punto.get('fecha_evento', 'N/A')}<br>
                                Barrio: {punto.get('barrio', 'N/A')}<br>
                                Promotor: {punto.get('id_autor', 'N/A')}
                            </div>
                            """
                            folium.CircleMarker(location=[float(lat), float(lon)], radius=4, popup=folium.Popup(popup_content, max_width=300), color='white', weight=1, fillColor=color_mes, fillOpacity=0.8).add_to(sg_mes)
                    except Exception:
                        continue
            if HAS_TREE_CONTROL:
                TreeLayerControl(collapsed=True, position='topright').add_to(mapa)
            else:
                folium.LayerControl(collapsed=True, position='topright').add_to(mapa)
            # Leyenda mensual normalizada (mismas columnas que promotores)
            rows_struct_mes = []
            from datetime import datetime
            for _, r in meses_presentes.iterrows():
                mes = r['mes']; anyo = r['anyo']; mes_label = r['mes_label']
                color_mes = PALETA_MESES.get(mes, '#999999')
                mask_mes = (df_filtrado['mes']==mes)&(df_filtrado['anyo']==anyo)
                df_mes = df_filtrado.loc[mask_mes]
                # Conteo base: filas del DF en ese mes (depende del modo Clientes/Muestras)
                muestras_mes_df = int(df_mes.shape[0])
                # Dias hábiles: días con >=2 muestras (consistencia con promotores)
                if not df_mes.empty:
                    df_mes['fecha_dia_tmp'] = df_mes['fecha_evento'].dt.date
                    cnt_dia = df_mes.groupby('fecha_dia_tmp').size()
                    dias_hab_mes = int((cnt_dia >= 2).sum())
                else:
                    dias_hab_mes = 0
                # Clientes en el mes (ajustado para que los totales coincidan con la vista por promotor)
                if 'id_contacto' in df_mes.columns:
                    if clientes_x_muestras:
                        clientes_mes = muestras_mes_df  # cada fila es un par promotor–cliente
                    else:
                        clientes_mes = int(df_mes['id_contacto'].nunique())
                else:
                    clientes_mes = 0
                # Rango exacto del mes para métricas de fidelidad/contactabilidad
                primer_dia_mes = f"{anyo}-{mes:02d}-01"
                if mes == 12:
                    ultimo_dia_mes = f"{anyo}-12-31"
                else:
                    next_month = datetime(anyo, mes + 1, 1)
                    ultimo_dia_mes = f"{anyo}-{mes:02d}-{(next_month - pd.Timedelta(days=1)).day}"
                ids_mes = df_mes['id_autor'].dropna().unique().tolist()
                try:
                    df_metrics_mes = prepo_metricas_promotores_muestras(
                        ciudad=ciudad,
                        fecha_inicio=primer_dia_mes,
                        fecha_fin=ultimo_dia_mes,
                        ids_autor=ids_mes,
                        df_muestras=df_mes
                    )
                except Exception:
                    df_metrics_mes = pd.DataFrame()
                if df_metrics_mes is None or df_metrics_mes.empty:
                    muestras_no_fieles_mes = 0
                    muestras_contactables_mes = 0
                    muestras_contactables_nofieles_mes = 0
                else:
                    muestras_no_fieles_mes = int(df_metrics_mes['muestras_no_fieles'].sum())
                    muestras_contactables_mes = int(df_metrics_mes['muestras_contactables'].sum())
                    muestras_contactables_nofieles_mes = int(df_metrics_mes['muestras_contactables_nofieles'].sum())
                # Total de muestras reales del mes según métricas
                if df_metrics_mes is None or df_metrics_mes.empty:
                    muestras_total_mes = muestras_mes_df
                else:
                    if 'muestras_total' in df_metrics_mes.columns:
                        muestras_total_mes = int(df_metrics_mes['muestras_total'].sum())
                    else:
                        muestras_total_mes = muestras_mes_df
                # Definir muestras_mes final según modo
                if clientes_x_muestras:
                    muestras_mes = muestras_total_mes
                else:
                    muestras_mes = muestras_mes_df
                if muestras_mes > 0:
                    pct_no_fieles_mes = 100.0 * muestras_no_fieles_mes / muestras_mes
                    pct_contactables_mes = 100.0 * muestras_contactables_mes / muestras_mes
                else:
                    pct_no_fieles_mes = 0.0
                    pct_contactables_mes = 0.0
                if muestras_no_fieles_mes > 0:
                    pct_contactables_nofieles_mes = 100.0 * muestras_contactables_nofieles_mes / muestras_no_fieles_mes
                else:
                    pct_contactables_nofieles_mes = 0.0
                if dias_hab_mes > 0 and muestras_mes > 0:
                    muestras_por_dia_habil_mes = muestras_mes / dias_hab_mes
                else:
                    muestras_por_dia_habil_mes = None
                etiqueta_mes = f"{mes_label} {anyo}"
                rows_struct_mes.append(_build_legend_row_struct(
                    etiqueta=etiqueta_mes,
                    muestras_total=muestras_mes,
                    clientes_total=clientes_mes,
                    dias_habiles=dias_hab_mes,
                    pct_no_fieles=pct_no_fieles_mes,
                    pct_contactables=pct_contactables_mes,
                    pct_contactables_nofieles=pct_contactables_nofieles_mes,
                    area_km2=None,
                    muestras_por_km2=None,
                    muestras_por_dia_habil=muestras_por_dia_habil_mes,
                    color_hex=color_mes,
                ))
            legend_html = _render_legend_html_muestras(rows_struct_mes, titulo="Métricas por mes (muestras)", label_col="Mes")

        # Agregar leyenda si aplica
        if legend_html:
            # Inyectar assets de ordenamiento si faltan e insertar leyenda
            inject_sort_assets(mapa)
            mapa.get_root().html.add_child(folium.Element(legend_html))
            # Hook de inicialización para tablas ordenables
            mapa.get_root().html.add_child(folium.Element("<script>window.TASortable && window.TASortable.initAll();</script>"))

        # Resumen flotante (arriba a la izquierda)
        html_content = f"""
        <div id='legend-resumen' class='legend-box' style='
            position: fixed; top: 20px; left: 20px; background-color: white; padding: 15px; border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2); z-index: 1000; font-family: Arial, sans-serif; min-width: 250px;'>
            <div class='legend-header' onclick="toggleLegend('legend-resumen')" style='cursor: pointer; display: flex; justify-content: space-between; align-items: center; margin: 0 0 10px 0;'>
                <h4 style='margin: 0; color: #111;'>Resumen de Muestras</h4>
                <span id='legend-resumen-toggle' class='toggle-icon' style='margin-left: 10px; transition: transform 0.3s ease; font-size: 12px; color: #6b7280;'>▼</span>
            </div>
            <div id='legend-resumen-body' class='legend-body'>
                <table style='width: 100%; border-collapse: collapse;'>
                    <tr><td style='padding: 3px 0;'>Fechas:</td><td style='padding: 3px 0;'><b>{stats_data['fecha_inicio']} - {stats_data['fecha_fin']}</b></td></tr>
                    <tr><td style='padding: 3px 0;'>Muestras/día:</td><td style='padding: 3px 0;'><b>{stats_data['promedio_muestras']:.1f}</b></td></tr>
                    <tr style='border-top: 1px solid #eee;'><td style='padding: 5px 0;'><b>Total muestras:</b></td><td style='padding: 5px 0;'><b>{stats_data['total_cantidad']}</b></td></tr>
                </table>
            </div>
        </div>
        <style>
            .legend-box.collapsed .legend-body {{ display: none; }}
            .legend-box.collapsed .toggle-icon {{ transform: rotate(-90deg); }}
            .legend-header:hover {{ background-color: #f9fafb; border-radius: 4px; padding: 2px; }}
            .toggle-icon {{ font-size: 12px; color: #6b7280; }}
        </style>
        <script>
            function toggleLegend(legendId) {{
                const legend = document.getElementById(legendId);
                const toggle = document.getElementById(legendId + '-toggle');
                const body = document.getElementById(legendId + '-body');
                if (legend.classList.contains('collapsed')) {{
                    legend.classList.remove('collapsed'); toggle.style.transform = 'rotate(0deg)'; body.style.display = 'block';
                }} else {{
                    legend.classList.add('collapsed'); toggle.style.transform = 'rotate(-90deg)'; body.style.display = 'none';
                }}
                setTimeout(repositionZoomControls, 100);
            }}
            function repositionZoomControls() {{
                const resumenLegend = document.getElementById('legend-resumen');
                const zoomControl = document.querySelector('.leaflet-control-zoom');
                if (zoomControl && resumenLegend) {{
                    const resumenRect = resumenLegend.getBoundingClientRect();
                    const topPosition = resumenRect.bottom + 10; zoomControl.style.top = topPosition + 'px'; zoomControl.style.left = '20px'; zoomControl.style.position = 'fixed';
                }}
            }}
            document.addEventListener('DOMContentLoaded', function() {{ setTimeout(repositionZoomControls, 500); }});
            window.addEventListener('load', function() {{ setTimeout(repositionZoomControls, 1000); }});
        </script>
        """
        mapa.get_root().html.add_child(folium.Element(html_content))

        # Guardar mapa (centralizado, sin segundo save redundante)
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)

        # CSV exportable
        df_csv = None
        try:
            if not df_filtrado.empty:
                df_csv = df_filtrado.copy()
                df_csv['lat'] = df_csv.apply(lambda r: r.get('coordenada_latitud', r.get('latitud', None)), axis=1)
                df_csv['lot'] = df_csv.apply(lambda r: r.get('coordenada_longitud', r.get('longitud', None)), axis=1)
                if 'fecha_evento' not in df_csv.columns and 'fecha' in df_csv.columns:
                    df_csv['fecha_evento'] = pd.to_datetime(df_csv['fecha'], errors='coerce')
                df_csv = df_csv.dropna(subset=['lat', 'lot'])
                sort_cols = []
                if 'fecha_evento' in df_csv.columns:
                    sort_cols.append('fecha_evento')
                sort_cols.extend(['lat', 'lot'])
                df_csv = df_csv.sort_values(sort_cols, ascending=True)
                df_csv = df_csv.reset_index(drop=True)
                df_csv['id'] = df_csv.index + 1
                df_csv['lon'] = df_csv['lot']
                cod_series = _asignar_cuadrante_a_puntos(df_csv, features_cuadrantes)
                df_csv['cod_cuadrante'] = cod_series
                df_csv['area_m2_cuadrante'] = df_csv['cod_cuadrante'].map(area_map).fillna(0).round().astype(int)
                cols_finales = ['id','fecha_evento','id_autor','lat','lot','lon','cod_cuadrante','area_m2_cuadrante']
                if 'id_contacto' in df_csv.columns:
                    insert_pos = cols_finales.index('id_autor') + 1
                    cols_finales = cols_finales[:insert_pos] + ['id_contacto'] + cols_finales[insert_pos:]
                cols_disponibles = [c for c in cols_finales if c in df_csv.columns]
                df_csv = df_csv[cols_disponibles]
        except Exception as e:
            logging.error(f"Error construyendo DF CSV: {e}")
            df_csv = None

        n_puntos = len(df_filtrado) if not df_filtrado.empty else 0
        return filename, n_puntos, df_csv

    except Exception as e:
        logging.error(f"Error en la generación del mapa: {e}")
        return None, 0, None
    finally:
        if verificar_areas:
            DEBUG_AREAS = DEBUG_AREAS_ORIGINAL