import pandas as pd
import folium
import json
import numpy as np
import logging
import re
from folium import FeatureGroup
from matplotlib import colors
from pre_procesamiento.preprocesamiento_muestras import crear_df
import unicodedata
from utils.gestor_mapas import guardar_mapa_controlado


# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
        cuadrantes_group = FeatureGroup(name="Cuadrantes").add_to(mapa)

        # Dibujar features con detección de tipo
        for feature in barrios_geojson['features']:
            props = feature.get('properties', {})
            
            # Detectar si es comuna o cuadrante
            is_comuna = any(
                key.lower() in ['nombre', 'barrio'] 
                for key in props.keys()
            )
            
            if is_comuna:
                # Estilo para comunas (fijo, no interactivo)
                folium.GeoJson(
                    data=feature,
                    style_function=lambda x: {
                        'fillColor': 'transparent',
                        'color': '#000000',
                        'weight': 1.5,
                        'fillOpacity': 0.0
                    }
                ).add_to(comunas_group)
            else:
                # Estilo para cuadrantes (respeta properties con defaults)
                def cuadrante_style(feat):
                    p = feat.get('properties', {})
                    return {
                        'fillColor': p.get('fillColor', '#3388ff'),
                        'color': p.get('color', '#1f2937'),
                        'weight': p.get('weight', 2),
                        'fillOpacity': p.get('fillOpacity', 0.45)
                    }
                
                folium.GeoJson(
                    data=feature,
                    style_function=cuadrante_style
                ).add_to(cuadrantes_group)

        # 3) Crear FeatureGroups por promotor (en vez de por barrio)
        for pid in promotores_unicos:
            label = label_map.get(pid, f"ID {pid}")
            grupo = FeatureGroup(name=label).add_to(mapa)  # aparecerá en el LayerControl
            datos_prom = df_filtrado[df_filtrado["id_autor_str"] == pid]
            color = promotor_colors[pid]

            for _, row in datos_prom.iterrows():
                folium.CircleMarker(
                    location=[row['coordenada_latitud'], row['coordenada_longitud']],
                    radius=5,
                    color=color,
                    fill=True,
                    fill_opacity=0.7,
                    popup=f"Promotor: {label}<br>Barrio: {row.get('barrio','-')}<br>{row['fecha_evento']}<br>{row['tipo_evento']} ({row.get('tipo_categoria','-')})"
                ).add_to(grupo)

        # Agregar control de capas
        folium.LayerControl().add_to(mapa)

        # 4) Leyenda flotante colapsable (sin JS externo)
        items_html = "".join(
            f"""<div style='display:flex;align-items:center;margin:4px 0;'>
                   <span style='display:inline-block;width:12px;height:12px;border-radius:3px;background:{promotor_colors[pid]};margin-right:8px;'></span>
                   <span style='font-size:12px;color:#111;'>{legend_name_map.get(str(pid), f"id {pid}")}</span>
                </div>"""
            for pid in promotores_unicos
        )
        legend_html = f"""
        <div style="
            position: fixed; bottom: 20px; left: 20px; z-index: 1000;
            background: white; border: 1px solid #e5e7eb; border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,.12); padding: 10px 12px; max-height: 40vh; overflow-y: auto;">
            <details open>
              <summary style="cursor:pointer;font-weight:600;color:#111;">Leyenda de promotores</summary>
              <div style="margin-top:8px;">{items_html}</div>
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