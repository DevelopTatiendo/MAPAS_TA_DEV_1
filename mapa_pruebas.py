# Version 12 - Última versión con todos los cambios
import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
from datetime import datetime
import numpy as np
from pre_procesamiento.preprocesamiento_pedidos import crear_df
import unicodedata
from sklearn.cluster import DBSCAN
import os
import logging
from shapely.geometry import Point, Polygon, MultiPolygon
# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuraciones globales
RUTAS_COORDENADAS = {
    'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
    'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
    'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
    'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
    'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
    'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
    'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"
}

COORDENADAS_CIUDADES = {
    'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
    'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
    'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
    'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
    'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
    'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
    'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
}

CENTROOPES = {
    'CALI': 2,
    'MEDELLIN': 3,
    'MANIZALES': 6,
    'PEREIRA': 5,
    'BOGOTA': 4,
    'BARRANQUILLA': 8,
    'BUCARAMANGA': 7
}

def cargar_comunas_geojson(mapa, geojson_file_path):# se puede agregar el atributo de comuna por si se quire aplicar este filtro
    """
    Carga las comunas GeoJSON en el mapa como capas.
    
    Args:
        mapa: Objeto folium.Map
        ciudad: Nombre de la ciudad
    """
     
    # Leer GeoJSON de las comunas y agregar polígonos al mapa
    try:
        with open(geojson_file_path, 'r', encoding='utf-8') as file:
            comunas_geojson = json.load(file)
        # Añadir la capa de límites de barrios usando el GeoJSON
        for feature in comunas_geojson['features']:
            comuna_name = feature['properties']['NOMBRE']
            geom = feature['geometry']
            popup_text = f"{comuna_name}"
            folium.GeoJson(
                data=geom,
                name=comuna_name,
                style_function=lambda feature: {
                    'fillColor': '#ffff00',
                    'color': 'black',
                    'weight': 1,
                    'fillOpacity': 0.1
                },
                popup=folium.Popup(popup_text, parse_html=True)
            ).add_to(mapa)


    

        logger.info("GeoJSON de comunas agregado al mapa .")

    except Exception as e:
        logger.error(f"Error al cargar GeoJSON de comunas: {e}")
    return mapa
def get_cluster_radius(zoom):
    if zoom <= 11:
        return 120  # Radio muy amplio para zoom inicial
    elif zoom <= 12:
        return 80   # Radio amplio para zoom nivel 2
    elif zoom <= 13:
        return 60   # Radio medio para zoom nivel 3
    elif zoom <= 14:
        return 40   # Radio pequeño para zoom más cercano
    else:
        return 30   # Valo

def generar_mapa_pruebas(fecha_inicio, fecha_fin, ciudad, nom_ruta=None):
    ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
    print("Ciudad recibida en generar_mapa_pedidos:", ciudad)

    # Convertir fechas a cadenas si es necesario
    fecha_inicio = str(fecha_inicio)
    fecha_fin = str(fecha_fin)

    if ciudad in RUTAS_COORDENADAS:
        centroope = CENTROOPES[ciudad]
        ruta_coordenadas = RUTAS_COORDENADAS[ciudad]
        location, geojson_file_path = COORDENADAS_CIUDADES[ciudad]

        # Obtener el DataFrame combinado
        df_pedidos = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)
    else:
        print(f"Ciudad no reconocida: {ciudad}")
        return

    # Cargar el archivo GeoJSON de comunas
    print(geojson_file_path)
    with open(geojson_file_path, 'r') as file:
        barrios_geojson = json.load(file)

    if nom_ruta:
        df_pedidos['nom_ruta'] = df_pedidos['nom_ruta'].astype(str)
        df_pedidos = df_pedidos[df_pedidos['nom_ruta'] == nom_ruta]

    if df_pedidos.empty:
        print("No hay datos para las fechas y ruta seleccionadas.")
        return

    # Agrupar los datos por latitud, longitud y barrios
    df_agrupado = df_pedidos.groupby(['latitud', 'longitud', 'barrio', 'nom_ruta']).size().reset_index(name='cantidad')

    # Crear el mapa centrado en la ciudad
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

    # Script para los clusters
    custom_cluster_script_ruta = """
    function(cluster) {
        var markers = cluster.getAllChildMarkers();
        var ruta = markers[0].options.ruta;
        var totalRuta = markers[0].options.totalRuta;
        var zoom = cluster._map.getZoom();
        var clusterCount = markers.length;
        
        // Verificar que todos los marcadores sean de la misma ruta
        if (!markers.every(m => m.options.ruta === ruta)) {
            return null;
        }

        var totalPedidos = markers.reduce((sum, m) => sum + (m.options.pedidoCount || 0), 0);
        
        // Ajustar el estilo basado en el zoom y el número de marcadores
        var style = {
            size: 60,
            opacity: 0.9,
            fontSize: '16px'
        };

        if (zoom <= 12) {
            // Vista general: mostrar total por ruta
            style = {
                size: 60,
                opacity: 0.9,
                fontSize: '16px',
                color: 'rgba(50, 50, 50, 0.9)'
            };
            totalPedidos = totalRuta;
        } else if (zoom <= 13) {
            // Nivel medio: clusters más grandes
            style = {
                size: Math.min(55, Math.max(45, clusterCount + 20)),
                opacity: 0.85,
                fontSize: '14px',
                color: 'rgba(50, 50, 50, 0.85)'
            };
        } else if (zoom <= 14) {
            // Nivel detallado: clusters más pequeños
            style = {
                size: Math.min(45, Math.max(35, clusterCount + 15)),
                opacity: 0.8,
                fontSize: '12px',
                color: 'rgba(50, 50, 50, 0.8)'
            };
        } else {
            // Nivel muy detallado: clusters mínimos
            style = {
                size: Math.min(35, Math.max(30, clusterCount + 10)),
                opacity: 0.75,
                fontSize: '11px',
                color: 'rgba(50, 50, 50, 0.75)'
            };
        }

        return L.divIcon({
            html: `<div style="
                background-color: ${style.color};
                color: white;
                border-radius: 50%;
                width: ${style.size}px;
                height: ${style.size}px;
                line-height: ${style.size}px;
                text-align: center;
                font-size: ${style.fontSize};
                box-shadow: 0 0 0 2px white;
                font-family: Arial;
                display: flex;
                align-items: center;
                justify-content: center;
            ">${totalPedidos}</div>`,
            className: 'marker-cluster-ruta',
            iconSize: L.point(style.size, style.size)
        });
    }
    """

    # Inicializar el diccionario de clusters y calcular totales por ruta
    marker_clusters = {}
    totales_por_ruta = df_agrupado.groupby('nom_ruta')['cantidad'].sum().to_dict()

    # Crear clusters por ruta
    for ruta in df_agrupado['nom_ruta'].unique():
        if pd.isna(ruta) or ruta in ['EMPLEADOS', 'TRANSPORTADORA']:
            continue
        
        marker_clusters[ruta] = MarkerCluster(
            name=f"Puntos de entrega {ruta}",
            icon_create_function=custom_cluster_script_ruta,
            disableClusteringAtZoom=15,
            maxClusterRadius=80,  # Valor fijo que funciona bien para todos los zooms
            spiderfyOnMaxZoom=True,
            chunkedLoading=True,
            zoomToBoundsOnClick=True,
            animate=True,
            animateAddingMarkers=True
        ).add_to(mapa)

    # Añadir los marcadores a sus respectivos clusters
    for _, row in df_agrupado.iterrows():
        if pd.isna(row['nom_ruta']) or row['nom_ruta'] in ['EMPLEADOS', 'TRANSPORTADORA']:
            continue

        popup_text = f"Ruta: {row['nom_ruta']}<br>{row['barrio']}: {row['cantidad']} pedidos"
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
        
        # Añadir información adicional al marcador
        marker.options['pedidoCount'] = row['cantidad']
        marker.options['ruta'] = row['nom_ruta']
        marker.options['totalRuta'] = totales_por_ruta[row['nom_ruta']]
        
        try:
            marker_clusters[row['nom_ruta']].add_child(marker)
        except KeyError:
            print(f"No se encontró cluster para la ruta: {row['nom_ruta']}")

    # Calcular estadísticas
    rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
    cantidad_barrios = df_pedidos['barrio'].nunique()
    total_cantidad = df_pedidos.shape[0]
    promedio_pedidos = total_cantidad / rango_dias if rango_dias > 0 else 0
    promedio_pedidos_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0

    # Preparar datos para las estadísticas
    stats_data = {
        'nom_ruta': nom_ruta if nom_ruta else "Todas",
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'promedio_pedidos': promedio_pedidos,
        'cantidad_barrios': cantidad_barrios,
        'promedio_pedidos_barrios': promedio_pedidos_barrios,
        'total_cantidad': total_cantidad
    }

    # Agregar el label flotante con estadísticas
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
        <h4 style="margin: 0 0 10px 0;">Resumen de Pedidos</h4>
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 3px 0;">Ruta:</td>
                <td style="padding: 3px 0;"><b>{stats_data['nom_ruta']}</b></td>
            </tr>
            <tr>
                <td style="padding: 3px 0;">Fechas:</td>
                <td style="padding: 3px 0;"><b>{stats_data['fecha_inicio']} - {stats_data['fecha_fin']}</b></td>
            </tr>
            <tr>
                <td style="padding: 3px 0;">Pedidos/día:</td>
                <td style="padding: 3px 0;"><b>{stats_data['promedio_pedidos']:.1f}</b></td>
            </tr>
            <tr>
                <td style="padding: 3px 0;">Total barrios:</td>
                <td style="padding: 3px 0;"><b>{stats_data['cantidad_barrios']}</b></td>
            </tr>
            <tr>
                <td style="padding: 3px 0;">Pedidos/barrio:</td>
                <td style="padding: 3px 0;"><b>{stats_data['promedio_pedidos_barrios']:.1f}</b></td>
            </tr>
            <tr style="border-top: 1px solid #eee;">
                <td style="padding: 5px 0;"><b>Total pedidos:</b></td>
                <td style="padding: 5px 0;"><b>{stats_data['total_cantidad']}</b></td>
            </tr>
        </table>
    </div>
    """
    
    mapa.get_root().html.add_child(folium.Element(html_content))

    # Crear el HeatMap
    heat_data = df_agrupado[['latitud', 'longitud', 'cantidad']].values
    heat_data[:, 2] = np.log1p(heat_data[:, 2])
    HeatMap(heat_data, radius=13, blur=7).add_to(mapa)

    # Añadir control de capas
    folium.LayerControl().add_to(mapa)

    # Guardar el mapa
    filename = f"mapa_pruebas.html"
    filepath = f"static/maps/{filename}"
    mapa.save(filepath)
    return filename

def generar_mapa_pruebas_proyeccion(ciudad: str,
                                    ruta_id_ui: int|None,
                                    ruta_nombre_ui: str|None,
                                    fecha_objetivo: str) -> str:
    """
    1) Resolver id_ruta real (mismo flujo que Consultores).
    2) Cargar GeoJSON único por ciudad (mismo flujo que Consultores).
    3) Filtrar features de la ruta (padres/hijos).
    4) Llamar al prepro de proyección para obtener contactos + coords robustas.
    5) Pintar cuadrantes + puntos con popup (id_contacto, fecha_prox, eventos_usados, dispersion_m, confianza).
    6) Fit bounds y devolver path del HTML generado (p.ej. 'mapa_pruebas_proyeccion.html').
    """
    try:
        # Importar utilidades reutilizables de Consultores
        from mapa_consultores import (
            _cargar_geojson_ciudad_unico, filter_features_by_route, 
            resolve_route_id, get_co, _style_cuadrante, _style_no_cuadrante,
            _es_cuadrante, _coords_and_geojson, _norm_city
        )
        from pre_procesamiento.preprocesamiento_proyeccion_visitas import contactos_proyeccion_visitas
        
        logging.info(f"Generando mapa proyección visitas - Ciudad: {ciudad}, ruta_id_ui: {ruta_id_ui}, ruta_nombre_ui: {ruta_nombre_ui}, fecha: {fecha_objetivo}")
        
        # 1) Resolver id_ruta real (mismo flujo que Consultores)
        ruta_result = resolve_route_id(ruta_id_ui, ruta_nombre_ui, ciudad)
        if ruta_result is None:
            logging.warning(f"No se pudo resolver ruta para: id_ui={ruta_id_ui}, nombre_ui={ruta_nombre_ui}")
            raise ValueError("Ruta no resuelta")
        
        id_ruta_real, nombre_ruta_resuelto = ruta_result
        
        # 2) Cargar GeoJSON único por ciudad (mismo flujo que Consultores)
        try:
            geojson_completo = _cargar_geojson_ciudad_unico(ciudad)
        except FileNotFoundError as e:
            logging.warning(f"GeoJSON no encontrado para {ciudad}: {e}")
            raise e
        
        # 3) Filtrar features de la ruta (padres/hijos)
        padres_ruta, hijos_ruta, subset_fc = filter_features_by_route(
            geojson_completo, id_ruta_real, mostrar_todos=False
        )
        
        if not padres_ruta and not hijos_ruta:
            logging.warning(f"No se encontraron cuadrantes para la ruta {id_ruta_real}")
        
        # 4) Llamar al prepro de proyección para obtener contactos + coords robustas
        co = get_co(ciudad)
        df_contactos = contactos_proyeccion_visitas(co, id_ruta_real, fecha_objetivo)
        
        total_contactos = len(df_contactos) if df_contactos is not None and not df_contactos.empty else 0
        contactos_con_coords = 0
        
        if df_contactos is not None and not df_contactos.empty:
            contactos_con_coords = len(df_contactos[
                (df_contactos['lat'].notna()) & (df_contactos['lon'].notna())
            ])
        
        logging.info(f"Contactos encontrados: {total_contactos}, con coordenadas: {contactos_con_coords}")
        
        # 5) Crear mapa base y configurar ubicación
        ciudadN = _norm_city(ciudad)
        centers = _coords_and_geojson()
        location = centers.get(ciudadN, [4.6097, -74.0817])[0]  # Default Bogotá
        
        mapa = folium.Map(location=location, zoom_start=12)
        
        # 6) Pintar cuadrantes filtrados (mismo estilo/leyenda que Consultores)
        if subset_fc.get('features'):
            for feature in subset_fc['features']:
                if _es_cuadrante(feature):
                    # Es un cuadrante: aplicar estilo normal
                    folium.GeoJson(
                        data=feature,
                        style_function=lambda f: _style_cuadrante(f),
                        popup=folium.Popup(
                            f"<b>Cuadrante:</b> {feature.get('properties', {}).get('codigo', 'Sin código')}",
                            max_width=200
                        )
                    ).add_to(mapa)
                else:
                    # No es cuadrante: estilo transparente
                    folium.GeoJson(
                        data=feature,
                        style_function=_style_no_cuadrante,
                        popup=folium.Popup(
                            f"Comuna: {feature.get('properties', {}).get('NOMBRE', 'Sin nombre')}",
                            max_width=200
                        )
                    ).add_to(mapa)
        
        # 7) Pintar puntos (CircleMarker) por contacto con colores por confianza
        if df_contactos is not None and not df_contactos.empty:
            bounds_coords = []
            
            for _, contacto in df_contactos.iterrows():
                lat = contacto.get('lat')
                lon = contacto.get('lon')
                
                if pd.notna(lat) and pd.notna(lon):
                    bounds_coords.append([lat, lon])
                    
                    # Colores por confianza: alta → verde, media → naranja, baja → rojo
                    confianza = contacto.get('confianza', 'sin_datos')
                    if confianza == 'alta':
                        color = 'green'
                    elif confianza == 'media':
                        color = 'orange'
                    else:  # baja o sin_datos
                        color = 'red'
                    
                    # Popup: id_contacto, fecha_prox_visita_venta, eventos_usados, dispersion_m (m), confianza_coord
                    id_contacto = contacto.get('id_contacto', 'N/A')
                    fecha_prox = contacto.get('fecha_prox_visita_venta', fecha_objetivo)
                    eventos_usados = contacto.get('k_eventos_usados', 0)
                    dispersion = contacto.get('dispersion_m')
                    dispersion_str = f"{dispersion:.1f} m" if dispersion is not None else "N/A"
                    nombre = contacto.get('nombre_contacto', 'Sin nombre')
                    telefono = contacto.get('telefono', 'Sin teléfono')
                    
                    popup_text = f"""
                    <b>ID Contacto:</b> {id_contacto}<br>
                    <b>Nombre:</b> {nombre}<br>
                    <b>Teléfono:</b> {telefono}<br>
                    <b>Fecha próx visita:</b> {fecha_prox}<br>
                    <b>Eventos usados:</b> {eventos_usados}<br>
                    <b>Dispersión:</b> {dispersion_str}<br>
                    <b>Confianza:</b> {confianza}
                    """
                    
                    folium.CircleMarker(
                        location=[lat, lon],
                        radius=7,
                        color=color,
                        fill=True,
                        fillColor=color,
                        fillOpacity=0.7,
                        weight=2,
                        popup=folium.Popup(popup_text, max_width=300)
                    ).add_to(mapa)
            
            # Fit bounds compacto si hay puntos
            if bounds_coords:
                if len(bounds_coords) == 1:
                    # Un solo punto: centrar con zoom moderado
                    mapa.location = bounds_coords[0]
                    mapa.zoom_start = 15
                else:
                    # Múltiples puntos: fit bounds
                    mapa.fit_bounds(bounds_coords, padding=(20, 20))
        
        # 8) Banner si no hay puntos
        mensaje_contactos = f"{contactos_con_coords} contactos" if contactos_con_coords > 0 else "Sin contactos para la fecha seleccionada"
        
        # 9) Leyenda con información
        nombre_ruta_display = nombre_ruta_resuelto or ruta_nombre_ui or f"Ruta {id_ruta_real}"
        html_leyenda = f"""
        <div style="position: fixed; top: 20px; left: 20px; background: white; padding: 15px; border-radius: 8px;
                    box-shadow: 0 0 10px rgba(0,0,0,.15); z-index: 1000; font-family: Arial, sans-serif; min-width: 280px;">
            <h4 style="margin: 0 0 10px 0; color: #2563eb;">Proyección Visitas - {nombre_ruta_display}</h4>
            <p style="margin: 2px 0;"><b>Ciudad:</b> {ciudad}</p>
            <p style="margin: 2px 0;"><b>Fecha objetivo:</b> {fecha_objetivo}</p>
            <p style="margin: 2px 0;"><b>Contactos:</b> {mensaje_contactos}</p>
            <hr style="margin: 8px 0;">
            <p style="margin: 2px 0; font-size: 12px;"><span style="color: green;">●</span> Alta confianza</p>
            <p style="margin: 2px 0; font-size: 12px;"><span style="color: orange;">●</span> Media confianza</p>
            <p style="margin: 2px 0; font-size: 12px;"><span style="color: red;">●</span> Baja confianza</p>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(html_leyenda))
        
        # 10) Guardar con filename único y limpio
        filename = "mapa_pruebas_proyeccion.html"
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        
        logging.info(f"Mapa proyección visitas generado: {filename} con {contactos_con_coords} contactos")
        return filename
        
    except ValueError as e:
        logging.error(f"Error de parámetros en mapa proyección visitas: {str(e)}")
        raise e
    except Exception as e:
        logging.error(f"Error generando mapa proyección visitas: {str(e)}")
        raise e