import pandas as pd
import folium
import json
import re
import unicodedata
import logging
import os
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



def generar_mapa_visitas_individuales(ciudad: str, id_ruta: int, nombre_ruta: str, fecha_inicio: str, fecha_fin: str) -> str:
    """
    Genera mapa simplificado con puntos individuales de visitas.
    Filtra por cargos operativos (5: calle, 181: gestores), sin clusters, sin heatmap, sin agregaciones.
    
    Args:
        ciudad (str): Nombre de la ciudad
        id_ruta (int): ID de ruta de cobro (entero de BD)
        nombre_ruta (str): Nombre de la ruta para mostrar en el mapa
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
        
        # Convertir fechas a formato completo para la consulta
        fecha_inicio_completa = f"{fecha_inicio} 00:00:00"
        fecha_fin_completa = f"{fecha_fin} 23:59:59"
        
        logging.info(f"Generando mapa visitas - CO:{centroope}, id_ruta:{id_ruta}, Fechas:{fecha_inicio_completa} a {fecha_fin_completa}")
        
        # Consultar datos de visitas
        df = eventos_visitas_simple(centroope, id_ruta, fecha_inicio_completa, fecha_fin_completa)
        
        if df.empty:
            logging.warning("No se encontraron eventos para los parámetros especificados")
            return None
        
        # Crear mapa centrado en la ciudad
        mapa = folium.Map(location=location, zoom_start=12)
        
        # Cargar y añadir capa de comunas como referencia
        try:
            if os.path.exists(geojson_file_path):
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
            # Usar nombres de columnas de eventos_visitas_simple
            lat = row.get('lat')
            lon = row.get('lon')
            
            if pd.notna(lat) and pd.notna(lon):
                # Preparar información del popup
                id_evento = row.get('id_evento', 'N/A')
                consultor = row.get('apellido', 'Sin consultor')
                fecha_evento = row.get('fecha_evento', 'Sin fecha')
                
                # Formatear fecha si está disponible
                if pd.notna(fecha_evento) and hasattr(fecha_evento, 'strftime'):
                    fecha_str = fecha_evento.strftime('%Y-%m-%d %H:%M')
                else:
                    fecha_str = str(fecha_evento)
                
                popup_text = f"""
                <b>Evento:</b> {id_evento}<br>
                <b>Consultor:</b> {consultor}<br>
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
            <p style="margin: 2px 0;"><b>Ruta:</b> {nombre_ruta}</p>
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


# Alias de compatibilidad para evitar roturas
def generar_mapa_visitas(*args, **kwargs):
    """Alias a la versión simple para evitar roturas"""
    return generar_mapa_visitas_individuales(*args, **kwargs)