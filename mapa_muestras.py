import pandas as pd
import folium
import json
import numpy as np
import logging
import re
from folium import FeatureGroup
from folium.plugins import FeatureGroupSubGroup
from matplotlib import colors
from pre_procesamiento.preprocesamiento_muestras import crear_df, obtener_metricas_pedidos_por_promotores
import unicodedata
from utils.gestor_mapas import guardar_mapa_controlado

# Importar controles de capas disponibles
from folium.plugins import GroupedLayerControl
try:
    from folium.plugins import TreeLayerControl
    HAS_TREE_CONTROL = True
except ImportError:
    HAS_TREE_CONTROL = False


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