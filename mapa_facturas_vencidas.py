import pandas as pd
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
from datetime import datetime
import numpy as np
from pre_procesamiento.preprocesamiento_facturas_vencidas import crear_df
import unicodedata
import os
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cargar_comunas_geojson(mapa, geojson_file_path):
    try:
        comunas_group = folium.FeatureGroup(name="Comunas", show=True, control=False)
        with open(geojson_file_path, 'r', encoding='utf-8') as file:
            comunas_geojson = json.load(file)
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
            ).add_to(comunas_group)
        comunas_group.add_to(mapa)
        logger.info("GeoJSON de comunas agregado al mapa.")
    except Exception as e:
        logger.error(f"Error al cargar GeoJSON de comunas: {e}")
    return mapa

def generar_mapa_facturas_vencidas(ciudad, edad_min, edad_max, ruta_cobro=None, fecha_inicio=None, fecha_fin=None):
    try:
        logger.info(f"Iniciando generación de mapa para {ciudad} con edades {edad_min}-{edad_max}")
        ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        edad_min = int(edad_min)
        edad_max = int(edad_max)

        ruta_cobro_coordenadas = {
            'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
            'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
            'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
            'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
            'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
            'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
            'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"
        }

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

        if ciudad not in ruta_cobro_coordenadas:
            logger.error(f"Ciudad no reconocida: {ciudad}")
            return

        centroope = centroopes[ciudad]
        ruta_coordenadas = ruta_cobro_coordenadas[ciudad]
        location, geojson_file_path = coordenadas_ciudades[ciudad]

        df_fac = crear_df(centroope, edad_min, edad_max, ruta_coordenadas)
        if fecha_inicio and fecha_fin:
            df_fac = df_fac[(df_fac['fecha_venta'] >= fecha_inicio) & (df_fac['fecha_venta'] <= fecha_fin)]

        if df_fac.empty:
            logger.warning("No hay datos para los parámetros seleccionados.")
            return

        df_fac['nom_ruta'] = df_fac['ruta_cobro']
        if ruta_cobro:
            df_fac['ruta_cobro'] = df_fac['ruta_cobro'].astype(str)
            df_fac = df_fac[df_fac['ruta_cobro'] == ruta_cobro]

        df_agrupado = df_fac.groupby(['latitud', 'longitud', 'barrio', 'nom_ruta']).agg({'valor_mora': 'sum'}).reset_index()

        mapa = folium.Map(location, zoom_start=12)
        cargar_comunas_geojson(mapa, geojson_file_path)

        custom_cluster_script_ruta = """
        function(cluster) {
            var markers = cluster.getAllChildMarkers();
            var ruta = markers[0].options.ruta;
            var totalRuta = 0;
            var zoom = cluster._map.getZoom();
            markers.forEach(function(marker) {
                totalRuta += marker.options.moraValue || 0;
            });
            if (zoom <= 12) {
                var displayValue = totalRuta >= 1000000 ? (totalRuta / 1000000).toFixed(1) + 'M' : (totalRuta / 1000).toFixed(0) + 'K';
                return L.divIcon({
                    html: '<div style="background-color:rgba(50, 50, 50, 0.9); color:white; border-radius:50%; padding:10px; width:55px; height:55px; line-height:35px; text-align:center; display:flex; align-items:center; justify-content:center;">' + displayValue + '</div>',
                    className: 'marker-cluster-ruta-total',
                    iconSize: L.point(55, 55)
                });
            } else if (zoom <= 14) {
                var size = Math.min(50, Math.max(35, Math.log(totalRuta) * 3));
                var displayValue = (totalRuta / 1000000).toFixed(1) + 'M';
                return L.divIcon({
                    html: '<div style="background-color:rgba(50, 50, 50, 0.8); color:white; border-radius:50%; padding:5px; width:' + size + 'px; height:' + size + 'px; line-height:' + size + 'px; text-align:center;">' + displayValue + '</div>',
                    className: 'marker-cluster-ruta-subgroup',
                    iconSize: L.point(size, size)
                });
            } else {
                return null;
            }
        }
        """

        marker_clusters = {}
        totales_por_ruta = df_agrupado.groupby('nom_ruta')['valor_mora'].sum().to_dict()
        for ruta in df_agrupado['nom_ruta'].unique():
            if pd.isna(ruta) or ruta in ['EMPLEADOS', 'TRANSPORTADORA']:
                continue
            marker_clusters[ruta] = MarkerCluster(
                name=f"Puntos de cobro {ruta}",
                icon_create_function=custom_cluster_script_ruta,
                disableClusteringAtZoom=14,
                maxClusterRadius=2000,
                spiderfyOnMaxZoom=False,
                chunkedLoading=True,
                zoomToBoundsOnClick=True
            ).add_to(mapa)

        for _, row in df_agrupado.iterrows():
            if pd.isna(row['nom_ruta']) or row['nom_ruta'] in ['EMPLEADOS', 'TRANSPORTADORA']:
                continue
            popup_text = f"<b>Ruta:</b> {row['nom_ruta']}<br><b>Barrio:</b> {row['barrio']}<br><b>Mora:</b> ${row['valor_mora']:,.0f}"
            marker = folium.Marker(
                location=[row['latitud'], row['longitud']],
                icon=folium.DivIcon(html=f"""
                    <div style=\"background-color:rgba(50, 50, 50, 0.8); color:white; border-radius:50%; text-align:center; padding:5px; width:30px; height:30px; line-height:20px; font-size: 12px;\">
                        {row['valor_mora']/1000000:.1f}M
                    </div>"""),
                popup=folium.Popup(popup_text, max_width=300)
            )
            marker.options['moraValue'] = row['valor_mora']
            marker.options['ruta'] = row['nom_ruta']
            marker.options['totalRuta'] = totales_por_ruta[row['nom_ruta']]
            try:
                marker_clusters[row['nom_ruta']].add_child(marker)
            except KeyError:
                logger.warning(f"No se encontró cluster para la ruta: {row['nom_ruta']}")

        rango_dias = (df_fac['fecha_venta'].max() - df_fac['fecha_venta'].min()).days + 1 if not df_fac['fecha_venta'].isna().all() else 0
        total_mora = df_agrupado['valor_mora'].sum()
        cantidad_barrios = df_fac['barrio'].nunique()
        promedio_deuda_barrio = total_mora/cantidad_barrios if cantidad_barrios > 0 else 0
        promedio_mora_dia = total_mora / rango_dias if rango_dias > 0 else 0
        total_facturas = len(df_fac)

        
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
            <h4 style="margin: 0 0 10px 0;">Resumen de Facturas Vencidas</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 3px 0;">Ruta:</td>
                    <td style="padding: 3px 0;"><b>{ruta_cobro if ruta_cobro else "Todas"}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Rango de edad:</td>
                    <td style="padding: 3px 0;"><b>{edad_min} - {edad_max} días</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Prom. mora/día:</td>
                    <td style="padding: 3px 0;"><b>${promedio_mora_dia:,.0f}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Total barrios:</td>
                    <td style="padding: 3px 0;"><b>{cantidad_barrios}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Prom. mora/barrio:</td>
                    <td style="padding: 3px 0;"><b>${promedio_deuda_barrio:,.0f}</b></td>
                </tr>
                <tr>
                    <td style="padding: 3px 0;">Total facturas:</td>
                    <td style="padding: 3px 0;"><b>{total_facturas}</b></td>
                </tr>
                <tr style="border-top: 1px solid #eee;">
                    <td style="padding: 5px 0;"><b>Mora total:</b></td>
                    <td style="padding: 5px 0;"><b>${total_mora:,.0f}</b></td>
                </tr>
            </table>
        </div>
        """


        mapa.get_root().html.add_child(folium.Element(html_content))


        heat_data = df_agrupado[['latitud', 'longitud', 'valor_mora']].values
        heat_data[:, 2] = np.log1p(heat_data[:, 2])
        HeatMap(heat_data, radius=13, blur=7).add_to(mapa)

        folium.LayerControl().add_to(mapa)
        filename = f"mapa_facturas_vencidas.html"
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        logger.info(f"Mapa guardado exitosamente en {filepath}")
        return filename

    except Exception as e:
        logger.error(f"Error al generar mapa de facturas: {e}")
        return None
