import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
from datetime import datetime
import numpy as np
from pre_procesamiento.preprocesamiento_pedidos import crear_df
import unicodedata

def get_dynamic_gradient(cobertura_values):
    """
    Genera un gradiente dinámico optimizado para valores muy pequeños de cobertura
    """
    min_val = np.min(cobertura_values)
    max_val = np.max(cobertura_values)
    
    print(f"{min_val} {max_val}")
    
    # Para valores muy pequeños, usar una transformación especial
    transformed_values = np.copy(cobertura_values)
    
    # Si el rango es muy pequeño, usar una transformación exponencial
    if max_val < 1:
        # Transformación exponencial para amplificar diferencias pequeñas
        transformed_values = np.power(cobertura_values/max_val, 0.3)
        
        # Definir puntos de corte específicos para valores pequeños
        cuts = [0, 0.2, 0.4, 0.6, 0.75, 0.9, 1.0]
        percentiles = [np.percentile(transformed_values, cut * 100) for cut in cuts]
    else:
        # Para valores normales, usar percentiles regulares
        cuts = [0, 0.2, 0.4, 0.6, 0.75, 0.9, 1.0]
        percentiles = [np.percentile(cobertura_values, cut * 100) for cut in cuts]
    
    # Crear el gradiente usando los puntos de corte
    gradient = {}
    colors = ['#08306b', '#08519c', '#2171b5', '#4292c6', '#fee090', '#fc8d59', '#800026']
    
    for i, percentile in enumerate(percentiles):
        gradient[float(cuts[i])] = colors[i]
    
    return gradient, transformed_values

def generar_mapa_cobertura(ciudad):
    fecha_inicio = '2024-01-01'
    fecha_fin = '2024-06-31'

    # Ruta de coordenadas para cada ciudad
    rutas_coordenadas = {
        'CALI': "densidades/CALI_DEN.xlsx",
        'MEDELLIN': "densidades/MEDELLIN_DEN.xlsx",
        'MANIZALES': "densidades/MANIZALES_DEN.xlsx",
        'PEREIRA': "densidades/PEREIRA_DEN.xlsx",
        'BOGOTA': "densidades/BOGOTA_DEN.xlsx",
        'BARRANQUILLA': "densidades/BARRANQUILLA_DEN.xlsx", 
        'BUCARAMANGA': "densidades/BUCARAMANGA_DEN.xlsx",
        
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

    if ciudad in rutas_coordenadas:
        
        ruta_coordenadas = rutas_coordenadas[ciudad]
        location, geojson_file_path = coordenadas_ciudades[ciudad]

        # Obtener el DataFrame combinado
        df_cobertura = pd.read_excel(ruta_coordenadas) 

        # # Aquí puedes continuar con la lógica para generar el mapa...
        # print(f"DataFrame para {ciudad}:")
        # print(df_pedidos.head())
    else:
        print(f"Ciudad no reconocida: {ciudad}")
        return

            

    custom_cluster_script = """
    function(cluster) {
        var markers = cluster.getAllChildMarkers();
        var totalcobertura = 0;
        var count = 0;

        // Calcular el promedio de cobertura en el clúster
        markers.forEach(function(marker) {
            if (marker.options.cobertura) {
                totalcobertura += marker.options.cobertura;
                count++;
            }
        });

        var promedio = count > 0 ? (totalcobertura / count).toFixed(2) : 0;

        return L.divIcon({
            html: '<div style="background-color:rgba(50, 50, 50, 0.8); ' +
                  'color:white; border-radius:50%; padding:5px; ' +
                  'width:50px; height:50px; ' +
                  'display:flex; align-items:center; justify-content:center; ' +
                  'font-size:12px;">' + promedio + '</div>',
            className: 'marker-cluster',
            iconSize: L.point(50, 50)
        });
    }
    """

    # Cargar el archivo GeoJSON
    print(geojson_file_path)
    with open(geojson_file_path, 'r') as file:
        barrios_geojson = json.load(file)

    # Cargar los datos de pruebas
    # df_pedidos = pd.read_csv("data/CALI/PEDIDOS_COMPLETOS_CALI_2023_2024.csv")
    # # print(df_pedidos.columns)
    # df_pedidos['fecha_hora_entrega'] = pd.to_datetime(df_pedidos['fecha_hora_entrega'])

    # # Filtrar los datos por fechas seleccionadas
    # df_pedidos = df_pedidos[
    #     (df_pedidos['fecha_hora_entrega'] >= fecha_inicio) &
    #     (df_pedidos['fecha_hora_entrega'] <= fecha_fin)
    # ]
    # print(df_pedidos["nom_ruta"].unique())

    # Si se selecciona una ruta, filtrar también por ruta



    # Agrupar los datos por latitud, longitud y barrios
    df_agrupado = df_cobertura

    # Obtener el valor máximo de cantidad para determinar el color de los marcadores
    max_val = df_agrupado['cobertura'].max()

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

    # Actualizar estadísticas y etiqueta flotante
    cantidad_barrios = df_cobertura['barrio'].nunique()
    promedio_cobertura = df_cobertura['cobertura'].mean()
   
    float_label = folium.DivIcon(html=f"""
    <div style="position: absolute;
            top: -150px;
            right: -450px;
            background-color: rgba(255, 255, 255, 0.8);
            padding: 10px;
            border-radius: 5px;
            font-size: 12px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
            z-index: 9999;
            width: 200px;">
        <b>cobertura por Barrios</b><br>
        <span>Rango de fechas: <b>{fecha_inicio} - {fecha_fin}</b></span><br>
        <span>Cantidad barrios: <b>{cantidad_barrios}</b></span><br>
        <span>Promedio cobertura: <b>{promedio_cobertura:.2f}</b></span>
    </div>
    """)

    folium.Marker(location, icon=float_label).add_to(mapa)

    # Obtener el gradiente dinámico y valores transformados
    gradient, transformed_values = get_dynamic_gradient(df_cobertura['cobertura'].values)
    
    # Preparar datos para el heatmap
    heat_data = df_cobertura[['latitud', 'longitud']].copy()
    heat_data['intensity'] = transformed_values
    heat_data = heat_data.values
    
    HeatMap(
        heat_data,
        radius=15,
        blur=7,
        min_opacity=0.5,
        gradient=gradient
    ).add_to(mapa)

    # Crear el MarkerCluster con el nuevo script
    marker_cluster = MarkerCluster(icon_create_function=custom_cluster_script).add_to(mapa)


    # Añadir marcadores individuales con popup y cantidad en un círculo
    for _, row in df_cobertura.iterrows():
        popup_text = f"Barrio: {row['barrio']} {row['cobertura']:.2f}"
        marker = folium.Marker(
            location=[row['latitud'], row['longitud']],
            icon=folium.DivIcon(html=f"""
                <div style="background-color:rgba(50, 50, 50, 0.8);
                     color:white;
                     border-radius:50%;
                     text-align:center;
                     width:40px;
                     height:40px;
                     display:flex;
                     align-items:center;
                     justify-content:center;
                     font-size:11px;">
                    {row['cobertura']:.2f}
                </div>"""),
            popup=folium.Popup(popup_text, parse_html=True)
        )
        marker.options['cobertura'] = row['cobertura']
        marker.add_to(marker_cluster)
    
    filename = f"mapa_cobertura_{ciudad}.html"
    filepath = f"static/maps_densidad/cobertura/{filename}"
    mapa.save(filepath)
    return filename  

lista = ['CALI', 'MEDELLIN', 'MANIZALES', 'PEREIRA', 'BOGOTA', 'BUCARAMANGA']

for ciudad in lista:
    filename = generar_mapa_cobertura(ciudad)





