import pandas as pd
import folium
from folium.plugins import HeatMap, MarkerCluster
import json
import numpy as np
from folium import FeatureGroup
from matplotlib import cm, colors
from pre_procesamiento.preprocesamiento_visitas import crear_df
import unicodedata
from utils.gestor_mapas import guardar_mapa_controlado


def generar_mapa_visitas(fecha_inicio,fecha_fin,tipo_agrupacion,ciudad,rutas_cobro =None):
    ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

    if tipo_agrupacion == "Agrupado":
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

        if ciudad in rutas_coordenadas:
            centroope = centroopes[ciudad]
            ruta_coordenadas = rutas_coordenadas[ciudad]
            location, geojson_file_path = coordenadas_ciudades[ciudad]

            # Obtener el DataFrame combinado
            df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)

            # Aquí puedes continuar con la lógica para generar el mapa...
            # print(f"DataFrame para {ciudad}:")
            # print(df.head())
        else:
            print(f"Ciudad no reconocida: {ciudad}")


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
        with open(geojson_file_path, 'r') as file:
            barrios_geojson = json.load(file)

      
         # Si se selecciona una ruta, filtrar también por ruta
        if rutas_cobro:
            df = df[df['ruta_cobro'] == rutas_cobro]

        if df.empty:
            print("No hay datos para las fechas y ruta seleccionadas.")
            return  # Si no hay datos, se detiene la generación del mapa

        # Agrupar los datos por latitud, longitud y barrios
        df_agrupado = df.groupby(['latitud', 'longitud', 'barrio']).size().reset_index(name='cantidad')

        # Obtener el valor máximo de cantidad para determinar el color de los marcadores
        max_val = df_agrupado['cantidad'].max()

        # Cargar el archivo GeoJSON
        mapa = folium.Map(location, zoom_start=12)
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
            
        
        # Calcular el rango de días seleccionados
        rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
        # Cantidad de barrios únicos
        cantidad_barrios = df['barrio'].nunique()
        # Añadir la etiqueta flotante con el total de pedidos
        total_cantidad = df.shape[0]
        # Promedio de pedidos por día
        promedio_muestras = total_cantidad / rango_dias if rango_dias > 0 else 0
        promedio_muestras_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0#crear etiqueta flotante
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
        heat_data = df_agrupado[['latitud', 'longitud', 'cantidad']].values
        heat_data[:, 2] = np.log1p(heat_data[:, 2])  # Aplicar escala logarítmica al valor de mora
        HeatMap(heat_data,  radius=13, blur=7).add_to(mapa)

        # Crear el MarkerCluster personalizado para sumar los pedidos
        marker_cluster = MarkerCluster(icon_create_function=custom_cluster_script).add_to(mapa)

         # Añadir marcadores individuales con popup y cantidad en un círculo
        for _, row in df_agrupado.iterrows():
            popup_text = f"{row['barrio']}: {row['cantidad']} visitas"
            marker = folium.Marker(
                location=[row['latitud'], row['longitud']],
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
            marker.options['pedidoCount'] = row['cantidad']  # Asignar correctamente el atributo
            marker.add_to(marker_cluster)


        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_visitas", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        return filename
    else:
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

        if ciudad in rutas_coordenadas:
            centroope = centroopes[ciudad]
            ruta_coordenadas = rutas_coordenadas[ciudad]
            location, geojson_file_path = coordenadas_ciudades[ciudad]

            # Obtener el DataFrame combinado
            df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)

            # Aquí puedes continuar con la lógica para generar el mapa...
            # print(f"DataFrame para {ciudad}:")
            # print(df.head())
        else:
            print(f"Ciudad no reconocida: {ciudad}")
            
                        # Cargar el archivo GeoJSON
        with open(geojson_file_path, 'r') as file:
            barrios_geojson = json.load(file)

        if rutas_cobro:
            df['ruta_cobro'] = df['ruta_cobro'].astype(str)
            df = df[df['ruta_cobro'] == rutas_cobro]


        if df.empty:
            print("No hay datos para las fechas y ruta seleccionadas.")
            return  # Si no hay datos, se detiene la generación del mapa


        # Crear el mapa centrado en Cali
        mapa = folium.Map(location, zoom_start=12)

        # Añadir la capa de límites de barrios usando el GeoJSON
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

        # Generar una paleta de colores en espacio HSV
        # Generar una paleta de colores en espacio HSV con mayor contraste
        def generate_hsv_colors(n):
            hues = np.linspace(0, 1, n, endpoint=False)  # Evita el cierre del espectro
            return [colors.rgb2hex(colors.hsv_to_rgb((hue, 1.0, 1.0))) for hue in hues]

        # Generar colores únicos para cada barrio
        unique_barrios = df['barrio'].unique()
        barrio_colors = {barrio: color for barrio, color in zip(unique_barrios, generate_hsv_colors(len(unique_barrios)))}


        # Calcular el rango de días seleccionados
        rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
        # Cantidad de barrios únicos
        cantidad_barrios = df['barrio'].nunique()
        # Añadir la etiqueta flotante con el total de muestras
        total_cantidad = df.shape[0]
        # Promedio de muestras por día
        promedio_muestras = total_cantidad / rango_dias if rango_dias > 0 else 0
        # promedio cantidad de pedidos por barrios
        promedio_muestras_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0
        # Crear el mapa centrado en Cali
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


        # Añadir los puntos al mapa, agrupados por barrio y con colores únicos
        for barrio in unique_barrios:
            barrio_group = FeatureGroup(name=barrio).add_to(mapa)
            barrio_data = df[df['barrio'] == barrio]
            for _, row in barrio_data.iterrows():
                if not pd.isna(row['coordenada_latitud']) and not pd.isna(row['coordenada_longitud']):
                    folium.CircleMarker(
                        location=[row['coordenada_latitud'], row['coordenada_longitud']],
                        radius=5,
                        color=barrio_colors[barrio],
                        fill=True,
                        fill_opacity=0.7,
                        popup=f"{row['barrio']}: {row['fecha_evento']}"
                    ).add_to(barrio_group)
        folium.LayerControl().add_to(mapa)



        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_facturas_vencidas", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        return filename
