import folium
import json
import unicodedata
import re
import pandas as pd
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.prepared import prep
from utils.gestor_mapas import guardar_mapa_controlado
from pre_procesamiento.preprocesamiento_consultores import eventos_por_ruta_en_rango, get_co

def _norm_city(ciudad: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

def _norm_token(token: str) -> str:
    """Normalizar token de ruta: sin tildes, espacios → guiones bajos, mayúsculas."""
    if not token:
        return ""
    # Remover tildes
    sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', token) if unicodedata.category(c) != 'Mn')
    # Reemplazar espacios y símbolos con guiones bajos, luego mayúsculas
    normalizado = re.sub(r'[^\w]', '_', sin_tildes).upper()
    return normalizado

def _coords_and_geojson():
    return {
        'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
        'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
        'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
        'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
        'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
        'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
        'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
    }

def _es_cuadrante(feature):
    """Verifica si la feature es un cuadrante (codigo empieza por CL_)."""
    codigo = (feature.get('properties', {}).get('codigo') or '').upper()
    return codigo.startswith('CL_')

def _style_cuadrante(feature):
    """Estilo para cuadrantes basado en properties del GeoJSON."""
    p = feature.get('properties', {})
    return {
        'fillColor': p.get('fillColor', '#ffd24d'),
        'color': p.get('color', '#111111'),
        'weight': p.get('weight', 1),
        'fillOpacity': p.get('fillOpacity', 0.35),
    }

def _style_no_cuadrante(_):
    """Estilo para features que no son cuadrantes (contorno transparente)."""
    return {
        'fillColor': 'transparent',
        'color': '#000000',
        'weight': 0.8,
        'fillOpacity': 0.0
    }

def generar_mapa_consultores(fecha_inicio, fecha_fin, ciudad, ruta_id, ruta_nombre, override_fc=None):
    """
    Genera mapa de consultores con filtro espacial por cuadrantes.
    
    Args:
        fecha_inicio: string formato 'YYYY-MM-DD HH:MM:SS'
        fecha_fin: string formato 'YYYY-MM-DD HH:MM:SS'
        ciudad: nombre de la ciudad
        ruta_id: id_ruta numérico
        ruta_nombre: nombre de la ruta (string mostrado en UI)
        override_fc: GeoJSON subido por usuario (opcional)
    """
    # 1) Normalizar ciudad y resolver centro
    ciudadN = _norm_city(ciudad)
    centers = _coords_and_geojson()
    if ciudadN not in centers:
        return None
    location, _ = centers[ciudadN]
    
    # 2) Obtener CO y datos de eventos
    co = get_co(ciudadN)
    id_ruta = int(ruta_id) if not isinstance(ruta_id, int) else int(ruta_id)
    df_eventos = eventos_por_ruta_en_rango(co, id_ruta, fecha_inicio, fecha_fin)
    
    total_eventos = len(df_eventos) if df_eventos is not None else 0

    # 3) Determinar qué GeoJSON usar como base
    geojson_a_usar = None
    if override_fc is not None:
        # Usuario subió archivo - usar ese
        geojson_a_usar = override_fc
    else:
        # No hay archivo subido - usar archivo base para esta ciudad
        archivo_base = f"geojson/cuadrantes_{ciudadN.lower()}_rutas_consultores.geojson"
        try:
            with open(archivo_base, 'r', encoding='utf-8') as f:
                geojson_a_usar = json.load(f)
        except FileNotFoundError:
            geojson_a_usar = None
        except Exception as e:
            print(f"Error cargando archivo base: {e}")
            geojson_a_usar = None

    # 4) Crear mapa base
    mapa = folium.Map(location, zoom_start=12)
    
    # 5) Dibujar GeoJSON (solo cuadrantes con color, resto transparente)
    if geojson_a_usar is not None:
        fg_cuadrantes = folium.FeatureGroup(name="Cuadrantes", show=True)
        fg_contorno = folium.FeatureGroup(name="Contorno", show=True, control=False)
        
        for feat in geojson_a_usar.get('features', []):
            if _es_cuadrante(feat):
                folium.GeoJson(
                    data=feat,
                    style_function=_style_cuadrante
                ).add_to(fg_cuadrantes)
            else:
                # Features no-cuadrante: solo contorno transparente (opcional)
                folium.GeoJson(
                    data=feat,
                    style_function=_style_no_cuadrante
                ).add_to(fg_contorno)
        
        fg_cuadrantes.add_to(mapa)
        fg_contorno.add_to(mapa)

    # 6) Selección de cuadrantes por ruta (soportar ID y NOMBRE)
    cuadrantes_ruta = []
    
    if geojson_a_usar is not None:
        # Normalizar nombre de ruta
        nom = _norm_token(ruta_nombre)
        
        # Construir patrones de búsqueda
        patrones = [
            rf'^CL_{id_ruta}_[0-9]{{2}}$',           # CL_3_01
            rf'^CL_{nom}_[0-9]{{2}}$',               # CL_RUTA_NOMBRE_01  
            rf'^CL_{nom}_{id_ruta}_[0-9]{{2}}$'      # CL_RUTA_NOMBRE_3_01
        ]
        
        def _match_codigo(cod):
            C = (cod or '').upper()
            return any(re.match(p, C) for p in patrones)
        
        for feat in geojson_a_usar.get('features', []):
            codigo = feat.get('properties', {}).get('codigo', '')
            if _match_codigo(codigo):
                cuadrantes_ruta.append(feat)

    # 7) Filtro espacial de eventos (solo puntos interiores)
    df_filtrados = pd.DataFrame()
    
    if df_eventos is not None and not df_eventos.empty and cuadrantes_ruta:
        # Construir unión de polígonos de los cuadrantes de esta ruta
        polygons = []
        for feat in cuadrantes_ruta:
            try:
                geom = shape(feat['geometry'])
                if not geom.is_valid:
                    geom = geom.buffer(0)
                polygons.append(geom)
            except Exception:
                continue
        
        if polygons:
            # Crear unión preparada para consultas rápidas
            union_geom = unary_union(polygons)
            if not union_geom.is_valid:
                union_geom = union_geom.buffer(0)
            prepped_union = prep(union_geom)
            
            # Filtrar eventos que caen dentro de los polígonos
            def punto_dentro(row):
                try:
                    point = Point(float(row['lon']), float(row['lat']))
                    return prepped_union.intersects(point)
                except:
                    return False
            
            mask_in = df_eventos.apply(punto_dentro, axis=1)
            df_filtrados = df_eventos[mask_in].reset_index(drop=True)

    # 8) Pintar SOLO los eventos filtrados (interiores)
    if df_filtrados is not None and not df_filtrados.empty:
        for _, r in df_filtrados.iterrows():
            lat, lon = float(r.lat), float(r.lon)
            popup = folium.Popup(
                f"<b>Evento:</b> {r.id_evento}<br><b>Contacto:</b> {r.id_contacto}<br><b>Fecha:</b> {r.fecha_evento}",
                max_width=300
            )
            folium.CircleMarker(
                location=[lat, lon],
                radius=4,
                color="#374151",  # gris oscuro
                fill=True,
                fillOpacity=0.7,
                popup=popup
            ).add_to(mapa)

        # 9) Fit bounds a los puntos filtrados
        try:
            coords = [[float(r.lat), float(r.lon)] for _, r in df_filtrados.iterrows()]
            if coords:
                mapa.fit_bounds(coords)
        except Exception:
            pass

    # 10) Leyenda obligatoria (3 líneas exactas con %)
    n_dentro = len(df_filtrados) if df_filtrados is not None else 0
    pct = (100 * n_dentro / total_eventos) if total_eventos > 0 else 0.0
    
    lineas_leyenda = [
        f"<b>Consultores — {ruta_nombre} ({ciudadN})</b>",
        f"Total: {total_eventos}",
        f"Dentro: {n_dentro} ({pct:.1f}%)"
    ]
    
    html_leyenda = f"""
    <div style="position: fixed; top: 20px; left: 20px; background: white; padding: 12px; border-radius: 8px;
                box-shadow: 0 0 10px rgba(0,0,0,.15); z-index: 1000; font-family: Arial, sans-serif;">
      {'<br>'.join(lineas_leyenda)}
    </div>"""
    mapa.get_root().html.add_child(folium.Element(html_leyenda))

    # 11) Guardar y retornar
    folium.LayerControl(collapsed=True, position='topright').add_to(mapa)
    filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_consultores", permitir_multiples=False)
    mapa.save(f"static/maps/{filename}")
    return filename
