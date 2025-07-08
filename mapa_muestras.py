import pandas as pd
import folium
import json
import numpy as np
from folium import FeatureGroup
from matplotlib import cm, colors
from pre_procesamiento.preprocesamiento_muestras import crear_df
import unicodedata

import pandas as pd
import folium
import json
import numpy as np
import logging
from folium import FeatureGroup
from matplotlib import colors
from pre_procesamiento.preprocesamiento_muestras import crear_df
import unicodedata


# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_hsv_colors(n):
    """Genera una paleta de colores HSV con mayor contraste."""
    hues = np.linspace(0, 1, n, endpoint=False)
    return [colors.rgb2hex(colors.hsv_to_rgb((hue, 1.0, 1.0))) for hue in hues]

def generar_mapa_muestras(fecha_inicio, fecha_fin,ciudad, barrios=None):
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
        df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)

        if df.empty:
            logging.warning(f"No hay datos para las fechas {fecha_inicio} - {fecha_fin}")
            return None
   
        # Cargar archivo GeoJSON
        try:
            with open(geojson_file_path, 'r') as file:
                barrios_geojson = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error al cargar GeoJSON: {e}")
            return None

        # Filtrar por fechas
        df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
        df_filtrado = df #[(df['fecha_evento'] >= fecha_inicio) & (df['fecha_evento'] <= fecha_fin)]

        if df_filtrado.empty:
            logging.warning("No hay datos después del filtrado por fecha.")
            return None

        # Si se selecciona una ruta, filtrar también por ruta
        if barrios:
            df_filtrado = df_filtrado[df_filtrado['barrio'].isin(barrios)]
            # print(barrios)

          # Crear mapa
        mapa = folium.Map(location=location, zoom_start=12)

            # Calcular estadísticas
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

        # Generar colores únicos para cada barrio
        unique_barrios = df_filtrado['barrio'].dropna().unique()
        barrio_colors = {barrio: color for barrio, color in zip(unique_barrios, generate_hsv_colors(len(unique_barrios)))}

      

        for feature in barrios_geojson['features']:
            folium.GeoJson(
                data=feature,
                style_function=lambda feature: {
                    'fillColor': 'transparent',  # 🔥 No se pinta el relleno
                    'color': 'black',  # ✅ Solo bordes negros
                    'weight': 1.5,  # Un poco más grueso si lo deseas
                    'fillOpacity': 0  # 🔥 Asegura que no haya relleno
                }
            ).add_to(mapa)

        # Añadir puntos al mapa agrupados por barrio con colores únicos
        for barrio in unique_barrios:
            barrio_group = FeatureGroup(name=barrio).add_to(mapa)
            barrio_data = df_filtrado[df_filtrado['barrio'] == barrio]

            for _, row in barrio_data.iterrows():
                folium.CircleMarker(
                    location=[row['coordenada_latitud'], row['coordenada_longitud']],
                    radius=5,
                    color=barrio_colors[barrio],
                    fill=True,
                    fill_opacity=0.7,
                    popup=f"{row['barrio']}: {row['fecha_evento']}"
                ).add_to(barrio_group)

        # Agregar control de capas
        folium.LayerControl().add_to(mapa)



        # Guardar mapa
        filepath = "static/maps/mapa_muestras.html"
        mapa.save(filepath)
        logging.info(f"Mapa guardado en {filepath}")

        return filepath

    except Exception as e:
        logging.error(f"Error en la generación del mapa: {e}")
        return None