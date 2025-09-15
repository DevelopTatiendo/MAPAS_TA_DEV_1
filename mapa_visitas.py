import pandas as pd
import folium
import json
import re
import unicodedata
import logging
from pre_procesamiento.preprocesamiento_visitas import eventos_visitas_simple
from utils.gestor_mapas import guardar_mapa_controlado


# Mapeo de ciudades para resolver centroope
CENTROOPES = {
    'CALI': 2,
    'MEDELLIN': 3,
    'MANIZALES': 6,
    'PEREIRA': 5,
    'BOGOTA': 4,
    'BARRANQUILLA': 8,
    'BUCARAMANGA': 7
}

# Coordenadas y archivos GeoJSON por ciudad
COORDENADAS_CIUDADES = {
    'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
    'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
    'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
    'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
    'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
    'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
    'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
}


def _normalizar_ciudad(ciudad: str) -> str:
    """Normalizar ciudad removiendo acentos y convirtiendo a mayúsculas."""
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()


def _resolver_id_ruta(ruta_cobro: str) -> int:
    """
    Resuelve el ID de ruta desde diferentes formatos de entrada.
    
    Args:
        ruta_cobro: Puede ser texto como "16 PALMIRA", número como string, o vacío
        
    Returns:
        int: ID de ruta numérico
        
    Raises:
        ValueError: Si no se puede resolver la ruta
    """
    if not ruta_cobro or ruta_cobro.strip() == "":
        raise ValueError("Debe seleccionar una ruta válida")
    
    # Convertir a string por seguridad
    ruta_str = str(ruta_cobro).strip()
    
    # Si es numérico puro
    if ruta_str.isdigit():
        id_ruta = int(ruta_str)
        logging.info(f"Ruta numérica directa '{ruta_str}' → {id_ruta}")
        return id_ruta
    
    # Normalizar texto para caso especial (sin acentos, mayúsculas)
    texto_normalizado = ''.join(c for c in unicodedata.normalize('NFD', ruta_str) if unicodedata.category(c) != 'Mn').upper().strip()
    
    # Caso especial: "16 PALMIRA" → 780
    if texto_normalizado == "16 PALMIRA":
        logging.info(f"Caso especial '{ruta_str}' → 780")
        return 780
    
    # Extraer número inicial con regex
    match = re.match(r'^(\d+)', ruta_str.strip())
    if match:
        id_ruta = int(match.group(1))
        logging.info(f"Regex extraído de '{ruta_str}' → {id_ruta}")
        return id_ruta
    
    # No se pudo resolver
    raise ValueError(f"No se pudo resolver la ruta: '{ruta_str}'")


def generar_mapa_visitas_individuales(ciudad: str, ruta_cobro: str, fecha_inicio: str, fecha_fin: str) -> str:
    """
    Genera mapa simplificado con puntos individuales de visitas.
    Solo consultores en calle (cargo = 5), sin clusters, sin heatmap, sin agregaciones.
    
    Args:
        ciudad (str): Nombre de la ciudad
        ruta_cobro (str): Ruta de cobro (texto o número)
        fecha_inicio (str): Fecha inicio en formato 'YYYY-MM-DD'
        fecha_fin (str): Fecha fin en formato 'YYYY-MM-DD'
    
    Returns:
        str: Nombre del archivo del mapa generado
        
    Raises:
        ValueError: Si hay errores en los parámetros
        Exception: Si hay errores en la generación del mapa
    """
    try:
        # Normalizar ciudad
        ciudad_norm = _normalizar_ciudad(ciudad)
        
        # Validar ciudad
        if ciudad_norm not in CENTROOPES:
            raise ValueError(f"Ciudad no reconocida: {ciudad}")
        
        if ciudad_norm not in COORDENADAS_CIUDADES:
            raise ValueError(f"No hay coordenadas configuradas para: {ciudad}")
        
        # Resolver centroope y coordenadas
        centroope = CENTROOPES[ciudad_norm]
        location, geojson_file_path = COORDENADAS_CIUDADES[ciudad_norm]
        
        # Resolver ID de ruta
        id_ruta = _resolver_id_ruta(ruta_cobro)
        
        # Convertir fechas a formato completo para la consulta
        fecha_inicio_completa = f"{fecha_inicio} 00:00:00"
        fecha_fin_completa = f"{fecha_fin} 23:59:59"
        
        logging.info(f"Generando mapa visitas individuales - Ciudad: {ciudad_norm}, CO: {centroope}, Ruta: {id_ruta}, Fechas: {fecha_inicio_completa} a {fecha_fin_completa}")
        
        # Consultar datos de visitas
        df = eventos_visitas_simple(centroope, id_ruta, fecha_inicio_completa, fecha_fin_completa)
        
        if df.empty:
            logging.warning("No hay datos de visitas para los parámetros seleccionados")
            raise ValueError("No se encontraron visitas para la ruta y fechas seleccionadas")
        
        # Crear mapa centrado en la ciudad
        mapa = folium.Map(location=location, zoom_start=12)
        
        # Cargar y añadir capa de comunas como referencia
        try:
            with open(geojson_file_path, 'r', encoding='utf-8') as file:
                comunas_geojson = json.load(file)
            
            for feature in comunas_geojson['features']:
                comuna_name = feature['properties']['NOMBRE']
                geom = feature['geometry']
                folium.GeoJson(
                    data=geom,
                    name=comuna_name,
                    style_function=lambda feature: {
                        'fillColor': '#ffff00',
                        'color': 'gray',
                        'weight': 1,
                        'fillOpacity': 0.05
                    },
                    popup=folium.Popup(f"Comuna: {comuna_name}", parse_html=True)
                ).add_to(mapa)
        except Exception as e:
            logging.warning(f"No se pudo cargar el archivo GeoJSON de comunas: {e}")

        # Añadir cada evento como punto individual (sin clusters ni heatmaps)
        total_eventos = 0
        for _, row in df.iterrows():
            lat = row.get('lat')
            lon = row.get('lon') 
            
            if pd.notna(lat) and pd.notna(lon):
                # Preparar información del popup
                id_evento = row.get('id_evento', 'N/A')
                apellido = row.get('apellido', 'Sin consultor')
                fecha_evento = row.get('fecha_evento', 'Sin fecha')
                
                # Formatear fecha si está disponible
                if pd.notna(fecha_evento) and hasattr(fecha_evento, 'strftime'):
                    fecha_str = fecha_evento.strftime('%Y-%m-%d %H:%M')
                else:
                    fecha_str = str(fecha_evento)
                
                popup_text = f"""
                <b>Evento:</b> {id_evento}<br>
                <b>Consultor:</b> {apellido}<br>
                <b>Fecha:</b> {fecha_str}
                """
                
                # Añadir marcador simple (sin cluster)
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color='red',
                    fill=True,
                    fillColor='red',
                    fillOpacity=0.7,
                    weight=2,
                    popup=folium.Popup(popup_text, max_width=250)
                ).add_to(mapa)
                
                total_eventos += 1

        # Añadir etiqueta flotante con información básica
        html_info = f"""
        <div style="
            position: fixed;
            top: 20px;
            left: 20px;
            background-color: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2);
            z-index: 1000;
            font-family: Arial, sans-serif;
            min-width: 200px;
        ">
            <h4 style="margin: 0 0 8px 0;">Visitas Individuales</h4>
            <p style="margin: 2px 0;"><b>Ciudad:</b> {ciudad_norm}</p>
            <p style="margin: 2px 0;"><b>Ruta:</b> {ruta_cobro}</p>
            <p style="margin: 2px 0;"><b>Período:</b> {fecha_inicio} - {fecha_fin}</p>
            <p style="margin: 2px 0;"><b>Total eventos:</b> {total_eventos}</p>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(html_info))
        
        # Guardar mapa
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_visitas_individuales", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        
        logging.info(f"Mapa de visitas individuales generado: {filename} con {total_eventos} eventos")
        return filename
        
    except ValueError as e:
        logging.error(f"Error de parámetros en mapa visitas individuales: {str(e)}")
        raise e
    except Exception as e:
        logging.error(f"Error generando mapa visitas individuales: {str(e)}")
        raise e
                comunas_geojson = json.load(file)
            
            for feature in comunas_geojson['features']:
                comuna_name = feature['properties']['NOMBRE']
                geom = feature['geometry']
                folium.GeoJson(
                    data=geom,
                    name=comuna_name,
                    style_function=lambda feature: {
                        'fillColor': '#ffff00',
                        'color': 'gray',
                        'weight': 1,
                        'fillOpacity': 0.05
                    },
                    popup=folium.Popup(f"Comuna: {comuna_name}", parse_html=True)
                ).add_to(mapa)
        except Exception as e:
            logging.warning(f"No se pudo cargar el archivo GeoJSON de comunas: {e}")

        # Añadir cada evento como punto individual
        total_eventos = 0
        for _, row in df.iterrows():
            # Manejar diferentes estructuras de columnas según la función usada
            lat = row.get('lat') or row.get('coordenada_latitud')
            lon = row.get('lon') or row.get('coordenada_longitud') 
            
            if pd.notna(lat) and pd.notna(lon):
                # Preparar información del popup
                id_evento = row.get('id_evento', 'N/A')
                barrio = row.get('barrio', 'Sin barrio')
                fecha_evento = row.get('fecha_evento', 'Sin fecha')
                consultor = row.get('apellido', 'Sin consultor')
                
                # Formatear fecha si está disponible
                if pd.notna(fecha_evento) and hasattr(fecha_evento, 'strftime'):
                    fecha_str = fecha_evento.strftime('%Y-%m-%d %H:%M')
                else:
                    fecha_str = str(fecha_evento)
                
                popup_text = f"""
                <b>Evento:</b> {id_evento}<br>
                <b>Consultor:</b> {consultor}<br>
                <b>Barrio:</b> {barrio}<br>
                <b>Fecha:</b> {fecha_str}
                """
                
                # Añadir marcador simple
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color='red',
                    fill=True,
                    fillColor='red',
                    fillOpacity=0.7,
                    weight=2,
                    popup=folium.Popup(popup_text, max_width=250)
                ).add_to(mapa)
                
                total_eventos += 1

        # Añadir información básica en esquina superior izquierda
        html_info = f"""
        <div style="
            position: fixed;
            top: 20px;
            left: 20px;
            background-color: white;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2);
            z-index: 1000;
            font-family: Arial, sans-serif;
            min-width: 200px;
        ">
            <h4 style="margin: 0 0 8px 0;">Visitas Individuales</h4>
            <p style="margin: 2px 0;"><b>Ruta:</b> {rutas_cobro or 'Todas'}</p>
            <p style="margin: 2px 0;"><b>Período:</b> {fecha_inicio} - {fecha_fin}</p>
            <p style="margin: 2px 0;"><b>Total eventos:</b> {total_eventos}</p>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(html_info))

        # Guardar mapa
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_visitas_simple", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        
        logging.info(f"Mapa de visitas simple generado: {filename} con {total_eventos} eventos")
        return filename

    except Exception as e:
        logging.error(f"Error generando mapa de visitas simple: {str(e)}")
        return None



    """
    Genera mapa de visitas con dos modos:
    - Agrupado: Mapa con heatmap, clusters y estadísticas
    - No agrupado: Mapa simplificado solo con puntos individuales
    """
    ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
    
    # Configuración común para ambos modos
    coordenadas_ciudades = {
        'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
        'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
        'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
        'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
        'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
        'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
        'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
    }
    
    centroopes = {
        'CALI': 2,
        'MEDELLIN': 3,
        'MANIZALES': 6,
        'PEREIRA': 5,
        'BOGOTA': 4,
        'BARRANQUILLA': 8,
        'BUCARAMANGA': 7
    }
    
    if ciudad not in coordenadas_ciudades:
        logging.error(f"Ciudad no reconocida: {ciudad}")
        return None
        
    centroope = centroopes[ciudad]
    location, geojson_file_path = coordenadas_ciudades[ciudad]
    
    # Convertir fechas a cadenas si es necesario
    fecha_inicio = str(fecha_inicio)
    fecha_fin = str(fecha_fin)
    
    if tipo_agrupacion == "No agrupado":
        # Usar consulta SQL fija (ignorar filtros de UI: rutas_cobro, fecha_inicio, fecha_fin)
        logging.info("Modo No agrupado seleccionado: ignorando filtros de UI y usando consulta SQL fija")
        return generar_mapa_visitas_no_agrupado_fijo(location, geojson_file_path)
    
    elif tipo_agrupacion == "Agrupado":
        # Ruta de coordenadas para cada ciudad (mantenido para compatibilidad)
        rutas_coordenadas = {
            'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
            'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
            'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
            'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
            'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
            'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
            'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"
        }

        # Obtener el DataFrame usando función de compatibilidad (maneja múltiples rutas)
        ruta_coordenadas = rutas_coordenadas.get(ciudad, "")
        df = crear_df(centroope, rutas_cobro or "TODOS", fecha_inicio, fecha_fin, ruta_coordenadas)
        
        if df.empty:
            logging.warning("No hay datos de visitas para las fechas y ruta seleccionadas en modo agrupado.")
            return None


        custom_cluster_script = """
            function(cluster) {
            var markers = cluster.getAllChildMarkers();
            var totalPedidos = 0;

            // Sumar la cantidad de pedidos en el clúster
            markers.forEach(function(marker) {
                var markerData = marker.options.pedidoCount || 0;
                totalPedidos += markerData;
            });

            return L.divIcon({
                html: '<div style="background-color:rgba(50, 50, 50, 0.8); color:white; border-radius:50%; padding:5px;">' + totalPedidos + '</div>',
                className: 'marker-cluster',
                iconSize: L.point(40, 40)
            });
        }

            """
        
        # Cargar el archivo GeoJSON
        try:
            with open(geojson_file_path, 'r', encoding='utf-8') as file:
                barrios_geojson = json.load(file)
        except Exception as e:
            logging.warning(f"No se pudo cargar el archivo GeoJSON: {e}")
            barrios_geojson = None

        # Verificar que tengamos datos después del filtrado por ruta (ya manejado en crear_df)
        if df.empty:
            logging.warning("No hay datos para las fechas y ruta seleccionadas.")
            return None

        # Determinar las columnas correctas para agrupación
        lat_col = 'latitud' if 'latitud' in df.columns else 'lat'
        lon_col = 'longitud' if 'longitud' in df.columns else 'lon'
        barrio_col = 'barrio' if 'barrio' in df.columns else 'barrio'
        
        # Agrupar los datos por latitud, longitud y barrios
        try:
            df_agrupado = df.groupby([lat_col, lon_col, barrio_col]).size().reset_index(name='cantidad')
        except KeyError as e:
            logging.error(f"Error agrupando datos - columna faltante: {e}")
            logging.info(f"Columnas disponibles: {list(df.columns)}")
            return None

        # Obtener el valor máximo de cantidad para determinar el color de los marcadores
        max_val = df_agrupado['cantidad'].max()

        # Crear el mapa
        mapa = folium.Map(location, zoom_start=12)
        
        # Añadir capa de barrios si está disponible
        if barrios_geojson:
            for feature in barrios_geojson['features']:
                barrio_name = feature['properties']['NOMBRE']
                geom = feature['geometry']
                popup_text = f"{barrio_name}"
                folium.GeoJson(
                    data=geom,
                    name=barrio_name,
                    style_function=lambda feature: {
                        'fillColor': '#ffff00',
                        'color': 'black',
                        'weight': 1,
                        'fillOpacity': 0.1
                    },
                    popup=folium.Popup(popup_text, parse_html=True)
                ).add_to(mapa)
            
        
        # Calcular estadísticas
        rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
        cantidad_barrios = df[barrio_col].nunique() if barrio_col in df.columns else 0
        total_cantidad = df.shape[0]
        promedio_muestras = total_cantidad / rango_dias if rango_dias > 0 else 0
        promedio_muestras_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0
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
            <h4 style="margin: 0 0 10px 0;">Resumen de Visitas</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 3px 0;">Rutas:</td>
                    <td style="padding: 3px 0;"><b>{rutas_cobro if rutas_cobro else "Todas"}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Fechas:</td>
                    <td style="padding: 3px 0;"><b>{fecha_inicio} - {fecha_fin}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Visitas/día:</td>
                    <td style="padding: 3px 0;"><b>{promedio_muestras:.2f}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Total barrios:</td>
                    <td style="padding: 3px 0;"><b>{cantidad_barrios}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Visitas/barrio:</td>
                    <td style="padding: 3px 0;"><b>{promedio_muestras_barrios:.2f}</b></td>
                </tr>
                <tr style="border-top: 1px solid #eee;">
                    <td style="padding: 5px 0;"><b>Total visitas:</b></td>
                    <td style="padding: 5px 0;"><b>{total_cantidad}</b></td>
                </tr>
            </table>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(html_content))
            

        # Crear el HeatMap con los datos filtrados
        heat_data = df_agrupado[[lat_col, lon_col, 'cantidad']].values
        heat_data[:, 2] = np.log1p(heat_data[:, 2])  # Aplicar escala logarítmica
        HeatMap(heat_data, radius=13, blur=7).add_to(mapa)

        # Crear el MarkerCluster personalizado
        marker_cluster = MarkerCluster(icon_create_function=custom_cluster_script).add_to(mapa)

        # Añadir marcadores individuales con popup y cantidad
        for _, row in df_agrupado.iterrows():
            popup_text = f"{row[barrio_col]}: {row['cantidad']} visitas"
            marker = folium.Marker(
                location=[row[lat_col], row[lon_col]],
                icon=folium.DivIcon(html=f"""<div style="background-color:rgba(50, 50, 50, 0.8); 
                                            color:white; 
                                            border-radius:50%; 
                                            text-align:center; 
                                            padding:5px; 
                                            width:30px; 
                                            height:30px; 
                                            line-height:30px;">
                                    {row['cantidad']}
                                </div>"""),
                popup=popup_text
            )
            marker.options['pedidoCount'] = row['cantidad']
            marker.add_to(marker_cluster)


        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_visitas", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        return filename
    
    else:
        logging.error(f"Tipo de agrupación no reconocido: {tipo_agrupacion}")
        return None
