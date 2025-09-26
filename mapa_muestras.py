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
from pre_procesamiento.preprocesamiento_muestras import crear_df, obtener_metricas_pedidos_por_promotores
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

# Importar controles de capas disponibles
from folium.plugins import GroupedLayerControl
try:
    from folium.plugins import TreeLayerControl
    HAS_TREE_CONTROL = True
except ImportError:
    HAS_TREE_CONTROL = False


# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === FUNCIONES UTILITARIAS PARA POPUPS DE CUADRANTES ===

# Calculadora geodésica para áreas exactas
_GEOD = Geod(ellps="WGS84")

def area_m2_geodesic(geom_geojson: dict) -> float:
    """Calcula área geodésica exacta en m² usando WGS84."""
    geom = shape(geom_geojson)
    area, _ = _GEOD.geometry_area_perimeter(geom)  # m² (puede ser negativa por orientación)
    return abs(area)

# === FUNCIONES DE FORMATEO ES-CO ===

def fmt_int_miles(n: float) -> str:
    """Formateo entero con punto como separador de miles (ES-CO): 501331 -> '501.331'"""
    return f"{int(round(n)):,}".replace(",", ".")

def fmt_dec_es(n: float, nd: int = 2) -> str:
    """Formateo decimal con coma (ES-CO): 0.5 -> '0,50'"""
    return f"{n:.{nd}f}".replace(".", ",")

def fmt_densidad_es(densidad_m2: float, nd: int = 6) -> str:
    """Formateo densidad con coma decimal (ES-CO): 0.000471 -> '0,000471'"""
    return f"{densidad_m2:.{nd}f}".replace(".", ",")

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
    """
    Fallback para calcular área usando shapely si no viene en properties.
    Usa aproximación WebMercator para convertir a metros.
    """
    try:
        geom = shape(geom_geojson)
        # Aproximación simple: usar bounds para calcular factor de conversión a metros
        bounds = geom.bounds
        lat_center = (bounds[1] + bounds[3]) / 2
        
        # Factor de conversión aproximado de grados a metros en esta latitud
        lat_rad = math.radians(lat_center)
        meters_per_degree_lat = 111000  # aprox constante
        meters_per_degree_lon = 111000 * math.cos(lat_rad)
        
        # Calcular área aproximada en m²
        width_degrees = bounds[2] - bounds[0]
        height_degrees = bounds[3] - bounds[1]
        width_meters = width_degrees * meters_per_degree_lon
        height_meters = height_degrees * meters_per_degree_lat
        
        # Para polígonos más complejos, usar el área de shapely pero escalada
        area_degrees_sq = geom.area
        bbox_area_degrees = width_degrees * height_degrees
        
        if bbox_area_degrees > 0:
            area_ratio = area_degrees_sq / bbox_area_degrees
            area_m2 = (width_meters * height_meters) * area_ratio
        else:
            area_m2 = 0.0
            
        return abs(area_m2)
    except Exception:
        return 0.0

def _calcular_metricas_hijo(feature: dict, df_filtrado: pd.DataFrame, rango_dias: int) -> dict:
    """
    Calcula métricas para un cuadrante hijo (subcuadrante).
    """
    props = feature.get('properties', {})
    codigo = props.get('codigo', '')
    
    # 1. Área (priorizar geodésica exacta)
    try:
        area_m2 = area_m2_geodesic(feature.get('geometry', {}))
    except Exception:
        # Fallback: usar properties si existe
        area_m2 = props.get('area_m2')
        if area_m2 is None:
            # Último fallback: aproximación con shapely
            area_m2 = _calcular_area_m2_fallback(feature.get('geometry', {}))
        else:
            area_m2 = float(area_m2)
    
    # 2. Contar muestras dentro del polígono
    total_muestras = 0
    if not df_filtrado.empty:
        try:
            geom = shape(feature.get('geometry', {}))
            prep_geom = prep(geom)
            
            for _, row in df_filtrado.iterrows():
                lat = row.get('lat')
                lon = row.get('lon')
                if lat is not None and lon is not None:
                    punto = Point(float(lon), float(lat))
                    if prep_geom.contains(punto):
                        total_muestras += 1
        except Exception:
            total_muestras = 0
    
    return {
        'codigo': codigo,
        'area_m2': area_m2,
        'total_muestras': total_muestras,
        'rango_dias': rango_dias
    }

def _calcular_metricas_padre(feature_padre: dict, features_hijos: list, metricas_hijos: dict, rango_dias: int) -> dict:
    """
    Calcula métricas para un cuadrante padre sumando las de sus hijos.
    """
    props_padre = feature_padre.get('properties', {})
    codigo_padre = props_padre.get('codigo', '')
    
    # Encontrar hijos de este padre
    hijos_del_padre = []
    for feature_hijo in features_hijos:
        props_hijo = feature_hijo.get('properties', {})
        codigo_hijo = props_hijo.get('codigo', '')
        codigo_padre_hijo = props_hijo.get('codigo_padre', '')
        
        # Verificar si este hijo pertenece al padre
        if codigo_padre_hijo == codigo_padre:
            hijos_del_padre.append(codigo_hijo)
        elif codigo_hijo.startswith(codigo_padre.replace('_00', '_')) and codigo_hijo != codigo_padre:
            # Fallback por patrón de código
            hijos_del_padre.append(codigo_hijo)
    
    # Sumar métricas de los hijos
    area_total = 0.0
    muestras_total = 0
    
    for codigo_hijo in hijos_del_padre:
        if codigo_hijo in metricas_hijos:
            metricas = metricas_hijos[codigo_hijo]
            area_total += metricas['area_m2']
            muestras_total += metricas['total_muestras']
    
    return {
        'codigo': codigo_padre,
        'area_m2': area_total,
        'total_muestras': muestras_total,
        'rango_dias': rango_dias
    }

def _popup_cuadrante_muestras(codigo: str, area_m2: float, total_local: int, dias_rango: int) -> str:
    """
    Genera popup HTML para cuadrantes con 4 métricas: área, índice de cobertura, cantidad y muestras/día.
    """
    # Verificación y alertas de área inusual
    area_km2 = area_m2 / 1_000_000 if area_m2 > 0 else 0.0
    if area_km2 < 0.005:
        st.warning(f"Área muy pequeña detectada en {codigo}: {area_km2:.6f} km²")
    elif area_km2 > 5.0:
        st.warning(f"Área muy grande detectada en {codigo}: {area_km2:.2f} km²")
    
    # Cálculo del índice de cobertura (0-1) contra meta
    densidad_m2 = (total_local / area_m2) if area_m2 > 0 else 0.0
    dens_1000 = densidad_m2 * DENSIDAD_BASE_M2
    cobertura = min(1.0, dens_1000 / OBJETIVO_X_1000M2) if area_m2 > 0 else 0.0
    
    dias = max(1, int(dias_rango))
    mxdia = total_local / dias

    # Formateo ES-CO con punto como separador de miles y coma como decimal
    area_m2_fmt = fmt_int_miles(area_m2)  # "501.331"
    area_km2_fmt = fmt_dec_es(area_km2, nd=2)  # "0,50"
    cobertura_txt = f"{cobertura:.2f}".replace(".", ",")
    cantidad_fmt = str(int(total_local))  # cantidad como entero
    mxdia_fmt = fmt_dec_es(mxdia, nd=1)  # "59,0"

    return f"""
    <div style="font-family: Inter, system-ui; font-size: 12px; line-height: 1.2;">
      <div style="font-weight:600; margin-bottom:6px;">{codigo}</div>
      <table style="border-collapse: collapse; width: 100%;">
        <tbody>
          <tr><td style="padding:4px 6px; border:1px solid #d1d5db;">Área</td>
              <td style="padding:4px 6px; border:1px solid #d1d5db; text-align:right;">
                {area_m2_fmt} m² ({area_km2_fmt} km²)
              </td></tr>
          <tr><td style="padding:4px 6px; border:1px solid #d1d5db;">Índice de cobertura</td>
              <td style="padding:4px 6px; border:1px solid #d1d5db; text-align:right;">
                {cobertura_txt}
              </td></tr>
          <tr><td style="padding:4px 6px; border:1px solid #d1d5db;">Cantidad de muestras (local)</td>
              <td style="padding:4px 6px; border:1px solid #d1d5db; text-align:right;">
                {cantidad_fmt}
              </td></tr>
          <tr><td style="padding:4px 6px; border:1px solid #d1d5db;">Muestras/día (local)</td>
              <td style="padding:4px 6px; border:1px solid #d1d5db; text-align:right;">
                {mxdia_fmt}
              </td></tr>
        </tbody>
      </table>
    </div>
    """

def _style_cuadrante_padre(feat):
    """
    Estilo más tenue para cuadrantes padre (debajo de los hijos).
    """
    base = _style_cuadrante(feat)
    base.update({'fillOpacity': 0.15, 'weight': 1.5})  # más tenue que los hijos
    return base

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

def build_promotores_groups(df, parent_group, colores_promotores_map, legend_name_map=None, mapa=None):
    """Construye subgrupos (FeatureGroupSubGroup) por promotor, ordenados desc.
    Devuelve lista de tuplas (nombre_promotor, subgrupo, count, color)."""
    promotor_counts = df.groupby('id_autor').size().sort_values(ascending=False)

    grupos_promotores = []
    for idx, (pid, count) in enumerate(promotor_counts.items()):
        datos_promotor = df[df['id_autor'] == pid]
        if datos_promotor.empty:
            continue

        nombre_promotor = get_promotor_display_name(pid, df, legend_name_map)
        color_promotor = colores_promotores_map.get(str(pid)) or colores_promotores_map.get(pid) or list(colores_promotores_map.values())[idx % max(1, len(colores_promotores_map))]

        # Subgrupo dentro de PROMOTORES (visible por defecto)
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
            <b>Barrio:</b> {row.get('barrio', '-')}<br>
            <b>Fecha:</b> {row.get('fecha_evento', row.get('fecha_muestra', '-'))}
            """

            folium.CircleMarker(
                location=[lat, lng],
                radius=5,
                color=color_promotor,
                fill=True,
                fillColor=color_promotor,
                fillOpacity=0.7,
                popup=folium.Popup(popup_text, max_width=320),
            ).add_to(sg)

        grupos_promotores.append((nombre_promotor, sg, count, color_promotor))

    return grupos_promotores

def build_barrios_groups(df, parent_group, legend_name_map=None, mapa=None):
    """Construye subgrupos (FeatureGroupSubGroup) por barrio, solo participantes, ordenados desc.
    Devuelve lista de tuplas (barrio, subgrupo, count)."""
    barrio_counts = df.groupby('barrio').size().sort_values(ascending=False)

    grupos_barrios = []
    color_barrio = '#9aa0a6'  # Gris neutro

    for barrio, count in barrio_counts.items():
        if pd.isna(barrio) or str(barrio).strip() == '' or count == 0:
            continue

        datos_barrio = df[df['barrio'] == barrio]

        # Subgrupo dentro de BARRIOS (apagado por defecto)
        sg = FeatureGroupSubGroup(parent_group, name=str(barrio), show=False)
        if mapa is not None:
            mapa.add_child(sg)

        for _, row in datos_barrio.iterrows():
            lat = row.get('coordenada_latitud', row.get('latitud', None))
            lng = row.get('coordenada_longitud', row.get('longitud', None))
            if lat is None or lng is None:
                continue

            nombre_promotor = get_promotor_display_name(row['id_autor'], df, legend_name_map)
            popup_text = f"""
            <b>Barrio:</b> {barrio}<br>
            <b>Promotor:</b> {nombre_promotor}<br>
            <b>ID:</b> {row['id_autor']}<br>
            <b>Fecha:</b> {row.get('fecha_evento', row.get('fecha_muestra', '-'))}
            """

            folium.CircleMarker(
                location=[lat, lng],
                radius=4,
                color=color_barrio,
                fill=True,
                fillColor=color_barrio,
                fillOpacity=0.55,
                popup=folium.Popup(popup_text, max_width=320),
            ).add_to(sg)

        grupos_barrios.append((str(barrio), sg, count))

    return grupos_barrios

def generar_mapa_muestras(fecha_inicio, fecha_fin, ciudad, barrios=None, promotores=None, override_fc=None):
    try:
        ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        logging.info(f"Generando mapa para la ciudad: {ciudad}")

        # Convertir fechas a cadenas si es necesario
        fecha_inicio = str(fecha_inicio)
        fecha_fin = str(fecha_fin)

        # Ruta de coordenadas para cada ciudad
        rutas_coordenadas = {
            'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
            'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
            'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
            'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
            'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
            'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
            'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"
        }

        # Coordenadas para el centro del mapa y archivo GeoJSON
        coordenadas_ciudades = {
            'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
            'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
            'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
            'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
            'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
            'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
            'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
        }

        # Centroope asociado a cada ciudad
        centroopes = {
            'CALI': 2,
            'MEDELLIN': 3,
            'MANIZALES': 6,
            'PEREIRA': 5,
            'BOGOTA': 4,
            'BARRANQUILLA': 8,
            'BUCARAMANGA': 7
        }
        if ciudad not in rutas_coordenadas:
            logging.error(f"Ciudad no reconocida: {ciudad}")
            return None
    
        centroope = centroopes[ciudad]
        ruta_coordenadas = rutas_coordenadas[ciudad]
        location, geojson_file_path = coordenadas_ciudades[ciudad]

        # Obtener el DataFrame combinado
        df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, promotores=promotores)

        if df.empty:
            logging.warning(f"No hay datos para las fechas {fecha_inicio} - {fecha_fin}")
            # Crear mapa vacío y retornar con 0 puntos
            mapa = folium.Map(location=location, zoom_start=12)
            filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
            filepath = f"static/maps/{filename}"
            mapa.save(filepath)
            return filename, 0
   
        # Selección de base geográfica
        if override_fc is not None:
            # Usar FeatureCollection personalizado
            barrios_geojson = override_fc
            logging.info("Usando GeoJSON personalizado como base")
        else:
            # Cargar archivo GeoJSON por defecto de la ciudad
            try:
                with open(geojson_file_path, 'r') as file:
                    barrios_geojson = json.load(file)
                logging.info(f"Usando GeoJSON por defecto: {geojson_file_path}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                logging.error(f"Error al cargar GeoJSON: {e}")
                return None

        # Filtrar por fechas
        df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
        df_filtrado = df #[(df['fecha_evento'] >= fecha_inicio) & (df['fecha_evento'] <= fecha_fin)]

        if df_filtrado.empty:
            logging.warning("No hay datos después del filtrado por fecha.")
            # Crear mapa vacío y retornar con 0 puntos
            mapa = folium.Map(location=location, zoom_start=12)
            filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
            filepath = f"static/maps/{filename}"
            mapa.save(filepath)
            return filename, 0

        # Si se selecciona una ruta, filtrar también por ruta
        if barrios:
            df_filtrado = df_filtrado[df_filtrado['barrio'].isin(barrios)]
            # print(barrios)

          # Crear mapa
        mapa = folium.Map(location=location, zoom_start=12)

        # === GRUPOS SEPARADOS PARA STACKING CORRECTO ===
        # Grupos separados para togglear si se desea
        cuadrantes_padres_group = folium.FeatureGroup(name="Cuadrantes (Padres)", show=True).add_to(mapa)
        cuadrantes_hijos_group  = folium.FeatureGroup(name="Cuadrantes (Hijos)",  show=True).add_to(mapa)

            # Calcular estadísticas
        #print(df_filtrado.head(4))
        rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
        cantidad_barrios = df_filtrado['barrio'].nunique()
        total_cantidad = df_filtrado.shape[0]
        promedio_muestras = total_cantidad / rango_dias if rango_dias > 0 else 0
        promedio_muestras_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0

        # Preparar datos para las estadísticas
        stats_data = {
            'barrios': barrios if barrios else "Todos",
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'promedio_muestras': promedio_muestras,
            'cantidad_barrios': cantidad_barrios,
            'promedio_muestras_barrios': promedio_muestras_barrios,
            'total_cantidad': total_cantidad
        }

        # Agregar el cuadro fijo de estadísticas en la parte superior izquierda
        html_content = f"""
            <div style="
                position: fixed;
                top: 20px;
                left: 20px;
                background-color: white;
                padding: 15px;
                border-radius: 5px;
                box-shadow: 0 0 10px rgba(0,0,0,0.2);
                z-index: 1000;
                font-family: Arial, sans-serif;
                min-width: 250px;
            ">
                <h4 style="margin: 0 0 10px 0;">Resumen de Muestras</h4>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 3px 0;">Barrios:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['barrios']}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Fechas:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['fecha_inicio']} - {stats_data['fecha_fin']}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Muestras/día:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['promedio_muestras']:.1f}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Total barrios:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['cantidad_barrios']}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Muestras/barrio:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['promedio_muestras_barrios']:.1f}</b></td>
                    </tr>
                    <tr style="border-top: 1px solid #eee;">
                        <td style="padding: 5px 0;"><b>Total muestras:</b></td>
                        <td style="padding: 5px 0;"><b>{stats_data['total_cantidad']}</b></td>
                    </tr>
                </table>
            </div>
            """

        mapa.get_root().html.add_child(folium.Element(html_content))

        # 1) Preparar etiquetas de promotor
        def _label_promotor(row):
            for k in ["apellido_autor", "promotor_nombre", "nombre_autor"]:
                if k in row and pd.notna(row[k]) and str(row[k]).strip():
                    return f"{row[k]} · {row['id_autor']}"
            return f"ID {row['id_autor']}"

        df_filtrado["id_autor_str"] = df_filtrado["id_autor"].astype(str)
        label_map = df_filtrado.drop_duplicates("id_autor_str").set_index("id_autor_str").apply(_label_promotor, axis=1).to_dict()

        # 2) Generar colores por promotor (no por barrio)
        promotores_unicos = df_filtrado["id_autor_str"].unique()
        promotor_colors = {pid: col for pid, col in zip(promotores_unicos, generate_hsv_colors(len(promotores_unicos)))}

        # Construir nombres compactados solo para la leyenda
        # 1) intentar tomar el nombre completo desde el DF (si ya viene)
        nombre_col_candidates = ["nombre_completo_autor", "apellido_autor", "apellido"]  # en ese orden
        nombre_col = next((c for c in nombre_col_candidates if c in df_filtrado.columns), None)

        legend_name_map = {}
        if nombre_col:
            tmp = (df_filtrado[["id_autor", nombre_col]]
                   .dropna(subset=[nombre_col])
                   .drop_duplicates(subset=["id_autor"]))
            for _, row in tmp.iterrows():
                pid = str(row["id_autor"])
                legend_name_map[pid] = compactar_dos_palabras(row[nombre_col], pid)

        # 2) si faltan algunos ids o no existe la columna, consultar solo los pendientes
        faltantes = [pid for pid in map(str, promotores_unicos) if pid not in legend_name_map]
        if faltantes:
            try:
                from pre_procesamiento.preprocesamiento_muestras import obtener_promotores_por_ids
                fetched = obtener_promotores_por_ids(faltantes) or {}
                for pid in faltantes:
                    full = fetched.get(pid)
                    legend_name_map[pid] = compactar_dos_palabras(full, pid)
            except Exception:
                # Fallback duro a id si no se pudo consultar
                for pid in faltantes:
                    legend_name_map[pid] = f"id {pid}"

        # Crear FeatureGroups para capas base
        comunas_group = FeatureGroup(name="Comunas").add_to(mapa)
        # cuadrantes_group = FeatureGroup(name="Cuadrantes").add_to(mapa)  # REMOVIDO: usamos grupos separados

        # === DETECCIÓN Y POPUPS DE CUADRANTES ===
        
        # Preparar DataFrame con columnas lat/lon para conteo de muestras por polígono
        df_for_conteo = df_filtrado.copy()
        df_for_conteo['lat'] = df_for_conteo.apply(
            lambda row: row.get('coordenada_latitud', row.get('latitud', None)), axis=1
        )
        df_for_conteo['lon'] = df_for_conteo.apply(
            lambda row: row.get('coordenada_longitud', row.get('longitud', None)), axis=1
        )
        # Filtrar puntos válidos
        df_for_conteo = df_for_conteo.dropna(subset=['lat', 'lon'])
        
        # Separar features en comunas y cuadrantes
        features_comunas = []
        features_cuadrantes = []
        
        for feature in barrios_geojson['features']:
            props = feature.get('properties', {})
            
            # Detectar si es comuna usando heurística original
            is_comuna = any(
                key.lower() in ['nombre', 'barrio'] 
                for key in props.keys()
            )
            
            if is_comuna:
                features_comunas.append(feature)
            else:
                # Verificar si es cuadrante válido (padre o hijo)
                if _es_cuadrante_padre(feature) or _es_cuadrante_hijo(feature):
                    features_cuadrantes.append(feature)
                else:
                    # Si no es cuadrante reconocido, tratarlo como comuna
                    features_comunas.append(feature)
        
        # Dibujar comunas (sin popup)
        for feature in features_comunas:
            folium.GeoJson(
                data=feature,
                style_function=lambda x: {
                    'fillColor': 'transparent',
                    'color': '#000000',
                    'weight': 1.5,
                    'fillOpacity': 0.0
                }
            ).add_to(comunas_group)
        
        # === CÁLCULO DE MÉTRICAS POR CUADRANTE ===
        
        # Separar padres e hijos
        features_padres = [f for f in features_cuadrantes if _es_cuadrante_padre(f)]
        features_hijos = [f for f in features_cuadrantes if _es_cuadrante_hijo(f)]
        
        # Cache de métricas para evitar recálculos
        metricas_cache = {}
        
        # 1. Calcular métricas para hijos
        for feature_hijo in features_hijos:
            metricas = _calcular_metricas_hijo(feature_hijo, df_for_conteo, rango_dias)
            metricas_cache[metricas['codigo']] = metricas
        
        # 2. Calcular métricas para padres (suma de hijos)
        for feature_padre in features_padres:
            metricas = _calcular_metricas_padre(feature_padre, features_hijos, metricas_cache, rango_dias)
            metricas_cache[metricas['codigo']] = metricas
        
        logging.info(f"Métricas calculadas para {len(metricas_cache)} cuadrantes ({len(features_hijos)} hijos, {len(features_padres)} padres)")
        
        # === DIBUJAR CUADRANTES CON POPUPS Y STACKING CORRECTO ===
        
        # --- PADRES (debajo) ---
        for feature_padre in features_padres:
            props  = feature_padre.get('properties', {})
            codigo = props.get('codigo', '')
            if codigo in metricas_cache:
                m = metricas_cache[codigo]
                popup_html = _popup_cuadrante_muestras(codigo, m['area_m2'], m['total_muestras'], m['rango_dias'])
                layer_padre = folium.GeoJson(
                    data=feature_padre,
                    style_function=_style_cuadrante_padre,
                    popup=folium.Popup(popup_html, max_width=500),
                    tooltip=folium.Tooltip(f"<b>{codigo}</b>"),
                )
                layer_padre.add_to(cuadrantes_padres_group)

        # --- HIJOS (encima) ---
        for feature_hijo in features_hijos:
            props  = feature_hijo.get('properties', {})
            codigo = props.get('codigo', '')
            if codigo in metricas_cache:
                m = metricas_cache[codigo]
                popup_html = _popup_cuadrante_muestras(codigo, m['area_m2'], m['total_muestras'], m['rango_dias'])
                layer_hijo = folium.GeoJson(
                    data=feature_hijo,
                    style_function=_style_cuadrante,
                    popup=folium.Popup(popup_html, max_width=500),
                    tooltip=folium.Tooltip(f"<b>{codigo}</b>"),
                )
                layer_hijo.add_to(cuadrantes_hijos_group)

                # Forzar que el HIJO quede al frente (bringToFront) sin panes
                mapa.get_root().html.add_child(folium.Element(
                    f"<script>{layer_hijo.get_name()}.bringToFront();</script>"
                ))

        # 3) Crear carpetas (padres) y subgrupos ordenados
        # Carpeta PROMOTORES (ON por defecto) - SOLO PROMOTORES EN EL CONTROL
        fg_promotores = FeatureGroup(name="PROMOTORES", show=True).add_to(mapa)

        # Definir colores por promotor en el orden de conteo
        promotor_counts = df_filtrado.groupby('id_autor').size().sort_values(ascending=False)
        promotores_ordenados = [int(pid) for pid in promotor_counts.index]
        palette = generate_hsv_colors(len(promotores_ordenados))
        colores_promotores_map = {str(pid): palette[i] for i, pid in enumerate(promotores_ordenados)}

        # Construir subgrupos SOLO para promotores
        grupos_promotores = build_promotores_groups(
            df_filtrado, parent_group=fg_promotores, colores_promotores_map=colores_promotores_map,
            legend_name_map=legend_name_map, mapa=mapa
        )

        # NO crear grupos de barrios para el control

        # --- CONTROL DE CAPAS (ÁRBOL) - PROMOTORES, COMUNAS, CUADRANTES ---
        if HAS_TREE_CONTROL:
            # TreeLayerControl automático detecta FeatureGroup + FeatureGroupSubGroup
            TreeLayerControl(collapsed=True, position='topright').add_to(mapa)
        else:
            # Fallback simple
            folium.LayerControl(collapsed=True, position='topright').add_to(mapa)

        # 5) Obtener métricas de ventas y construir leyenda tabular
        
        # ids en el orden del control/leyenda
        promotores_ordenados = [int(pid) for pid in promotor_counts.index]

        df_metrics = obtener_metricas_pedidos_por_promotores(
            centroope=centroope,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            ids_promotores=promotores_ordenados
        )

        # Mapear: id_vendedor -> (cant_pedidos, valor_conIVA)
        metrics_map = {int(r["id_vendedor"]): (int(r["cant_pedidos"]), float(r.get("valor_conIVA", 0.0)))
                       for _, r in df_metrics.iterrows()}

        def fmt_cop(valor):
            try:
                # miles con punto y sin decimales (ej: $1.234.567)
                return "$" + f"{valor:,.0f}".replace(",", ".")
            except Exception:
                return "$0"

        # Construir lista de datos por promotor fusionando todas las fuentes
        promotor_data = []
        
        for (nombre, _sg, _count_muestras, color) in grupos_promotores:
            # recuperar el id real del promotor a partir del nombre:
            # usamos el reverse de legend_name_map
            pid_match = None
            for pid_str, disp_name in legend_name_map.items():
                if disp_name == nombre:
                    pid_match = int(pid_str)
                    break

            # Obtener datos de muestras, pedidos y valor
            muestras = _count_muestras
            cant_ped, valor_ped = (0, 0.0)
            if pid_match is not None and pid_match in metrics_map:
                cant_ped, valor_ped = metrics_map[pid_match]
            
            # Calcular efectividad
            efectividad = (cant_ped / muestras * 100) if muestras > 0 else 0.0
            
            promotor_data.append({
                'id': pid_match,
                'nombre': nombre,
                'color': color,
                'muestras': muestras,
                'pedidos': cant_ped,
                'valor': valor_ped,
                'efectividad': efectividad
            })
        
        # Ordenar por pedidos descendente
        promotor_data.sort(key=lambda x: x['pedidos'], reverse=True)
        
        # Construir filas HTML con el nuevo orden
        rows_html = []
        for data in promotor_data:
            rows_html.append(f"""
                <tr>
                    <td style="padding:6px 8px;display:flex;align-items:center;gap:8px;">
                        <span style="display:inline-block;width:12px;height:12px;border-radius:3px;background:{data['color']};"></span>
                        <span>{data['nombre']}</span>
                    </td>
                    <td style="padding:6px 8px;text-align:right;">{data['pedidos']}</td>
                    <td style="padding:6px 8px;text-align:right;">{data['muestras']}</td>
                    <td style="padding:6px 8px;text-align:right;">{data['efectividad']:.1f}%</td>
                    <td style="padding:6px 8px;text-align:right;">{fmt_cop(data['valor'])}</td>
                </tr>
            """)

        legend_html = f"""
        <div style="
            position: fixed; bottom: 20px; left: 20px; z-index: 1000;
            background: white; border: 1px solid #e5e7eb; border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,.12); padding: 10px 12px; max-height: 45vh; overflow-y: auto;">
          <details open>
            <summary style="cursor:pointer;font-weight:600;color:#111;">Pedidos por promotor (mismo rango)</summary>
            <div style="margin-top:8px;">
              <table style="border-collapse:collapse; width:100%; font-size:12px;">
                <thead>
                  <tr>
                    <th style="text-align:left; padding:6px 8px; border-bottom:1px solid #eee;">Promotor</th>
                    <th style="text-align:right; padding:6px 8px; border-bottom:1px solid #eee;">Pedidos</th>
                    <th style="text-align:right; padding:6px 8px; border-bottom:1px solid #eee;">Muestras</th>
                    <th style="text-align:right; padding:6px 8px; border-bottom:1px solid #eee;">Efectividad</th>
                    <th style="text-align:right; padding:6px 8px; border-bottom:1px solid #eee;">Valor con IVA</th>
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
        mapa.get_root().html.add_child(folium.Element(legend_html))



        # Guardar mapa
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_muestras", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        
        # Retornar filename y número de puntos para el warning
        n_puntos = len(df_filtrado) if not df_filtrado.empty else 0
        return filename, n_puntos

    except Exception as e:
        logging.error(f"Error en la generación del mapa: {e}")
        return None, 0