"""
Módulo "Pruebas" - Genera mapas con eventos sobre cuadrantes de rutas.
Sin métricas, solo puntos con MarkerCluster sobre base GeoJSON de rutas.
"""

import os
import json
import unicodedata
import time
import logging
from pathlib import Path
from datetime import datetime
import folium
import pandas as pd

from pre_procesamiento.preprocesamiento_consultores import (
    get_co, eventos_por_ruta_en_rango
)

# Configurar logging
logger = logging.getLogger(__name__)

STATIC_MAPS = Path("static/maps")

# --- Centros y fallback de GeoJSON por ciudad (provistos por Camilo) ---
COORDENADAS_CIUDADES = {
    'CALI': ([3.4516, -76.5320], 'geojson/pap/cali_base.geojson'),
    'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
    'MANIZALES': ([5.0672, -75.5174], 'geojson/pap/manizales_base.geojson'),  # Usar archivo estándar
    'PEREIRA': ([4.8087, -75.6906], 'geojson/pap/pereira_base.geojson'),
    'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
    'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
    'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
}

def _slug_ciudad(nombre: str) -> str:
    """Convierte nombre de ciudad a slug (minúsculas, sin tildes)."""
    s = ''.join(c for c in unicodedata.normalize('NFD', nombre) if unicodedata.category(c) != 'Mn')
    return s.lower()

def _city_key(nombre: str) -> str:
    """Normaliza a clave de diccionario (MAYÚSCULAS sin tildes)."""
    s = ''.join(c for c in unicodedata.normalize('NFD', nombre) if unicodedata.category(c) != 'Mn')
    return s.upper()

def _city_center(ciudad: str, df: pd.DataFrame | None) -> list[float]:
    """Centro del mapa: primero diccionario, si no existe usa bounding box de los datos."""
    k = _city_key(ciudad)
    if k in COORDENADAS_CIUDADES:
        return COORDENADAS_CIUDADES[k][0]
    if df is not None and not df.empty:
        return [ (df["lat"].min() + df["lat"].max())/2, (df["lon"].min() + df["lon"].max())/2 ]
    # fallback Colombia
    return [4.65, -74.1]

def _geojson_rutas_path(ciudad: str) -> Path:
    """Retorna path al GeoJSON de rutas para la ciudad."""
    slug = _slug_ciudad(ciudad)
    return Path(f"geojson/rutas/{slug}/cuadrantes_rutas_{slug}.geojson")

def _geojson_fallback_por_ciudad(ciudad: str) -> Path | None:
    """Devuelve el GeoJSON de la tabla como fallback si existe; si no, None."""
    k = _city_key(ciudad)
    if k in COORDENADAS_CIUDADES:
        p = Path(COORDENADAS_CIUDADES[k][1])
        return p if p.exists() else None
    return None

def _style_cuadrante(feature):
    """Estilo de cuadrantes usando colores del GeoJSON (igual que Consultores)."""
    p = feature.get('properties', {}) or {}
    return {
        'fillColor': p.get('fillColor', '#ffd24d'),
        'color': p.get('color', '#111111'),
        'weight': p.get('weight', 1),
        'fillOpacity': p.get('fillOpacity', 0.35),
    }

def _label_cuadrante_from_props(props: dict) -> str:
    """
    Retorna el texto a mostrar en el tooltip del cuadrante.
    Prioridad: texto opcional -> nombre/label/etiqueta -> codigo.
    """
    if not props:
        return ""
    for k in ("texto", "texto_opc", "texto_opcional", "nombre", "label", "etiqueta"):
        v = (props.get(k) or "").strip()
        if v:
            return v
    v = str(props.get("codigo", "")).strip()
    return v or "N/D"

def _color_evento(tipo):
    """Retorna color para evento según tipo (verde para ventas 57/58, gris para resto)."""
    try:
        t = int(tipo) if tipo is not None else None
    except Exception:
        t = None
    if t in (57, 58):
        return "#16a34a"   # verde (ventas en ruta)
    return "#374151"       # gris oscuro

def _build_legend(ciudad: str, id_ruta: int | str, fi_str: str, ff_str: str, total: int) -> str:
    """HTML de tarjeta fija arriba-izquierda con resumen."""
    fi_d = (fi_str or "")[:10]
    ff_d = (ff_str or "")[:10]
    rango = fi_d if fi_d == ff_d else f"{fi_d} – {ff_d}"
    return f"""
    <div style="
      position: fixed; top: 12px; left: 12px; z-index: 9999;
      background: rgba(255,255,255,0.95); border: 1px solid #e5e7eb;
      border-radius: 8px; padding: 10px 12px; box-shadow: 0 1px 6px rgba(0,0,0,.15);
      font: 13px/1.3 Arial, sans-serif; min-width: 220px;">
      <div style="font-weight: 700; margin-bottom: 4px;">
        Consultores — {str(ciudad).upper()}
      </div>
      <div><b>Ruta:</b> {id_ruta}</div>
      <div><b>Fechas:</b> {rango}</div>
      <div><b>Total puntos:</b> {total}</div>
    </div>
    """

def generar_mapa_pruebas(ciudad: str, id_ruta: int, fecha_inicio, fecha_fin) -> tuple[str, int]:
    """
    Genera mapa Folium con eventos (consultores) sobre base GeoJSON de RUTAS de la ciudad.
    
    Características:
    - Sin cálculo por cuadrante
    - Sin comunas (solo rutas o basemap)
    - MarkerCluster para puntos
    - Colores por tipo de evento
    
    Args:
        ciudad (str): Nombre de la ciudad (con acentos)
        id_ruta (int): ID de la ruta de cobro
        fecha_inicio (date): Fecha de inicio
        fecha_fin (date): Fecha de fin
    
    Returns:
        tuple[str, int]: (filename, n_puntos)
        - filename: Nombre del archivo HTML generado
        - n_puntos: Total de eventos renderizados
    
    Raises:
        Exception: Si hay errores en la generación del mapa
    """
    try:
        # Asegurar que existe el directorio de salida
        STATIC_MAPS.mkdir(parents=True, exist_ok=True)
        
        # 1) Normalizar ciudad y obtener centro de operaciones
        ciudadN = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        co = get_co(ciudadN)
        
        # 2) Convertir fechas date → strings con horarios completos
        if hasattr(fecha_inicio, 'strftime'):
            fi = f"{fecha_inicio.strftime('%Y-%m-%d')} 00:00:00"
        else:
            fi = f"{fecha_inicio} 00:00:00"
            
        if hasattr(fecha_fin, 'strftime'):
            ff = f"{fecha_fin.strftime('%Y-%m-%d')} 23:59:59"
        else:
            ff = f"{fecha_fin} 23:59:59"
        
        # 3) Consultar eventos con coordenadas
        logger.info(f"[PRUEBAS] Consultando eventos - CO:{co}, Ruta:{id_ruta}, Fechas:{fi} a {ff}")
        df = eventos_por_ruta_en_rango(co, int(id_ruta), fi, ff)
        
        # 4) Si no hay datos, generar mapa dummy
        if df is None or df.empty:
            logger.warning(f"[PRUEBAS] Sin datos para CO:{co}, Ruta:{id_ruta}, Fechas:{fi}-{ff}")
            # Centro usando diccionario o fallback
            m_center = _city_center(ciudad, None)
            m = folium.Map(location=m_center, zoom_start=12)
            folium.Marker(
                m_center, 
                tooltip="Sin datos en el rango especificado",
                icon=folium.Icon(color='gray', icon='info-sign')
            ).add_to(m)
            
            # Agregar leyenda con total 0
            m.get_root().html.add_child(folium.Element(_build_legend(ciudad, id_ruta, fi, ff, 0)))
            
            # Guardar
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"pruebas_{_slug_ciudad(ciudad)}_{id_ruta}_{ts}.html"
            m.save(STATIC_MAPS / filename)
            
            logger.info(f"[PRUEBAS] Mapa generado (sin datos): {filename}")
            return filename, 0
        
        # 5) Centro del mapa desde diccionario; si no, desde datos
        m_center = _city_center(ciudad, df)
        
        # 6) Crear mapa base (OSM por defecto, como Consultores)
        m = folium.Map(location=m_center, zoom_start=12)
        
        # 7) Cargar GeoJSON de RUTAS; si no existe, usar fallback por ciudad
        gj_path = _geojson_rutas_path(ciudad)
        geojson_loaded = False
        
        # 7.1 Intento 1: RUTAS
        if gj_path.exists():
            try:
                with open(gj_path, "r", encoding="utf-8") as f:
                    gj = json.load(f)
                
                # Crear FeatureGroup para las rutas
                fg_rutas = folium.FeatureGroup(name="Cuadrantes de Rutas", show=True).add_to(m)
                
                # Iterar por cada feature para agregar tooltip personalizado
                for feat in gj.get("features", []):
                    props = feat.get("properties", {}) or {}
                    label = _label_cuadrante_from_props(props)
                    
                    folium.GeoJson(
                        data=feat,
                        style_function=_style_cuadrante,
                        highlight_function=lambda x: {"weight": 2.0, "color": "#5B21B6"},
                        tooltip=folium.Tooltip(f"<b>{label}</b>", sticky=True, direction="top")
                    ).add_to(fg_rutas)
                
                logger.info(f"✓ GeoJSON de rutas cargado: {gj_path}")
                geojson_loaded = True
            except Exception as e:
                logger.warning(f"⚠️ Error cargando rutas {gj_path}: {e}")
        
        # 7.2 Intento 2: Fallback por ciudad (pap/comunas que definiste)
        if not geojson_loaded:
            fb = _geojson_fallback_por_ciudad(ciudad)
            if fb is not None:
                try:
                    with open(fb, "r", encoding="utf-8") as f:
                        gj = json.load(f)
                    
                    # Crear FeatureGroup para el fallback
                    fg_fallback = folium.FeatureGroup(name="Base ciudad", show=True).add_to(m)
                    
                    # Iterar por cada feature para agregar tooltip personalizado
                    for feat in gj.get("features", []):
                        props = feat.get("properties", {}) or {}
                        label = _label_cuadrante_from_props(props)
                        
                        folium.GeoJson(
                            data=feat,
                            style_function=_style_cuadrante,
                            highlight_function=lambda x: {"weight": 2.0, "color": "#5B21B6"},
                            tooltip=folium.Tooltip(f"<b>{label}</b>", sticky=True, direction="top")
                        ).add_to(fg_fallback)
                    
                    logger.info(f"✓ GeoJSON fallback cargado: {fb}")
                    geojson_loaded = True
                except Exception as e:
                    logger.warning(f"⚠️ Error cargando fallback {fb}: {e}")
        
        if not geojson_loaded:
            logger.warning("⚠️ No se encontró base geográfica (rutas ni fallback); se mostrará solo basemap.")
        
        # 8) Renderizar puntos individuales (sin cluster)
        n_puntos = 0
        for _, r in df.iterrows():
            try:
                lat = float(r["lat"])
                lon = float(r["lon"])
                
                # Determinar tipo de evento y color
                tipo = r.get("id_evento_tipo")
                color = _color_evento(tipo)
                
                # Determinar tipo de evento (texto + id si existe)
                tipo_txt = r.get('tipo_evento')
                tipo_id = r.get('id_evento_tipo')
                if pd.notna(tipo_txt) and str(tipo_txt).strip():
                    tipo_line = str(tipo_txt).strip()
                    if pd.notna(tipo_id):
                        tipo_line = f"{tipo_line} (#{int(tipo_id)})"
                else:
                    # Fallback: solo id o 'N/D'
                    tipo_line = f"#{int(tipo_id)}" if pd.notna(tipo_id) else "N/D"
                
                # Formatear fecha
                fecha_evento = r.get('fecha_evento', 'Sin fecha')
                if pd.notna(fecha_evento) and hasattr(fecha_evento, 'strftime'):
                    fecha_str = fecha_evento.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    fecha_str = str(fecha_evento)
                
                popup_html = f"""
                <div style="font-family: Arial, sans-serif; font-size: 12px; min-width: 220px;">
                  <b>Tipo:</b> {tipo_line}<br>
                  <b>Fecha:</b> {fecha_str}<br>
                  <b>Consultor:</b> {r.get('apellido', 'Sin nombre')}<br>
                  <b>ID Contacto:</b> {int(r['id_contacto']) if pd.notna(r.get('id_contacto')) else 'N/A'}
                </div>
                """
                
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color=color,
                    weight=1,
                    fill=True,
                    fillColor=color,
                    fillOpacity=0.8,
                    popup=folium.Popup(popup_html, max_width=320)
                ).add_to(m)
                
                n_puntos += 1
            except Exception as e:
                logger.warning(f"Error procesando punto {n_puntos}: {e}")
                continue
        
        # Añadir leyenda final con total de puntos renderizados
        m.get_root().html.add_child(folium.Element(_build_legend(ciudad, id_ruta, fi, ff, n_puntos)))
        
        # 9) Añadir control de capas
        folium.LayerControl(collapsed=True).add_to(m)
        
        # 10) Guardar HTML
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"pruebas_{_slug_ciudad(ciudad)}_{id_ruta}_{ts}.html"
        m.save(STATIC_MAPS / filename)
        
        logger.info(f"✓ Mapa Pruebas generado: {filename} con {n_puntos} puntos")
        
        return filename, n_puntos
        
    except Exception as e:
        logger.error(f"[PRUEBAS] Error generando mapa: {str(e)}")
        raise
