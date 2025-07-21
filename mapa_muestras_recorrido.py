import pandas as pd
import folium
import numpy as np
import json
import os
import logging
from datetime import datetime
from pre_procesamiento.preprocesamiento_muestras import crear_df
from utils.gestor_mapas import guardar_mapa_controlado
from matplotlib import colors



# Configuración de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_unique_colors(n):
    """Genera n colores HSV para distinguir asesores."""
    hues = np.linspace(0, 1, n, endpoint=False)
    return [colors.rgb2hex(colors.hsv_to_rgb((hue, 1.0, 1.0))) for hue in hues]

def generar_mapa_muestras_recorrido(
    fecha_inicio,
    fecha_fin,
    ciudad,
    barrios=None,
    asesores=None,
    modo_visualizacion="recorrido",
):
    """
    Genera un mapa de muestras con visualización por asesor y modo seleccionado.
    """
    try:
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
            print(f"❌ Ciudad no reconocida: {ciudad}")
            return None
    
        # 1. Obtener datos
        centroope = centroopes[ciudad]
        ruta_coordenadas = rutas_coordenadas[ciudad]
        location, geojson_file_path = coordenadas_ciudades[ciudad]

        df = crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, asesores)
        if df.empty:
            print("⚠️ No hay datos de muestras para los parámetros dados.")
            return None
        
        # Cargar archivo GeoJSON
        try:
            with open(geojson_file_path, 'r') as file:
                barrios_geojson = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error al cargar GeoJSON: {e}")
            return None
        
        # 2. Filtrar por asesores
        if asesores:
            df = df[df['id_autor'].isin(asesores)]

        if df.empty:
            print("⚠️ No hay datos luego de aplicar filtros por asesor.")
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
        if asesores:
            df_filtrado = df_filtrado[df_filtrado['id_autor'].isin(asesores)]
            # print(barrios)
        # 3. Crear mapa
        mapa = folium.Map(location=location, zoom_start=12)

        # Calcular estadísticas
        rango_dias = (pd.to_datetime(fecha_fin) - pd.to_datetime(fecha_inicio)).days + 1
        cantidad_barrios = df_filtrado['barrio'].nunique()
        cantidad_asesores = df_filtrado['id_autor'].nunique()  # NUEVO
        total_cantidad = df_filtrado.shape[0]
        promedio_muestras = total_cantidad / rango_dias if rango_dias > 0 else 0
        promedio_muestras_barrios = total_cantidad / cantidad_barrios if cantidad_barrios > 0 else 0
        promedio_muestras_asesores = total_cantidad / cantidad_asesores if cantidad_asesores > 0 else 0  # NUEVO

        # Preparar datos para las estadísticas
        stats_data = {
            'barrios': barrios if barrios else "Todos",
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'rango_dias': rango_dias,  # NUEVO
            'promedio_muestras': promedio_muestras,
            'cantidad_barrios': cantidad_barrios,
            'cantidad_asesores': cantidad_asesores,  # NUEVO
            'promedio_muestras_barrios': promedio_muestras_barrios,
            'promedio_muestras_asesores': promedio_muestras_asesores,  # NUEVO
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
                min-width: 280px;
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
                        <td style="padding: 3px 0;">Rango de días:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['rango_dias']}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Cant. asesores:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['cantidad_asesores']}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Muestras/día:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['promedio_muestras']:.1f}</b></td>
                    </tr>
                    <tr>
                        <td style="padding: 3px 0;">Muestras/asesor:</td>
                        <td style="padding: 3px 0;"><b>{stats_data['promedio_muestras_asesores']:.1f}</b></td>
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

        # ====== FUNCIONALIDAD PRINCIPAL ======
        
        # 1. Generar colores únicos para cada asesor (excluyendo verde y rojo)
        asesores_unicos = df_filtrado['id_autor'].unique()
        colores_disponibles = ['blue', 'purple', 'orange', 'darkblue', 'pink', 'cadetblue', 'darkpurple', 'darkgreen']
        # Extender colores si hay más asesores
        if len(asesores_unicos) > len(colores_disponibles):
            colores_adicionales = generate_unique_colors(len(asesores_unicos) - len(colores_disponibles))
            colores_disponibles.extend(colores_adicionales)
        
        colores_asesores = {asesor: colores_disponibles[i] for i, asesor in enumerate(asesores_unicos)}
        
        # 2. Crear arreglo de tiempo único (días únicos ordenados)
        df_filtrado['fecha_solo'] = df_filtrado['fecha_evento'].dt.date
        dias_unicos = sorted(df_filtrado['fecha_solo'].unique())
        
        print(f"📅 Días únicos encontrados: {dias_unicos}")
        print(f"🎨 Modo de visualización: {modo_visualizacion}")
        
        # ====== LÓGICA CONDICIONAL POR MODO ======
        
        if modo_visualizacion == "recorrido":
            # MODO RECORRIDO: Puntos + líneas + marcadores especiales
            print("🔄 Ejecutando modo RECORRIDO...")
            
            # 3. Por cada día, procesar cada asesor
            for dia in dias_unicos:
                print(f"\n🔄 Procesando día: {dia}")
                
                # Filtrar datos del día
                df_dia = df_filtrado[df_filtrado['fecha_solo'] == dia].copy()
                
                # Agrupar por asesor
                for asesor_id, df_asesor_dia in df_dia.groupby('id_autor'):
                    
                    # Ordenar por fecha_evento (hora)
                    df_asesor_dia = df_asesor_dia.sort_values('fecha_evento')
                    
                    if len(df_asesor_dia) == 0:
                        continue
                    
                    # Obtener coordenadas y datos
                    coordenadas = list(zip(
                        df_asesor_dia['coordenada_latitud'].astype(float), 
                        df_asesor_dia['coordenada_longitud'].astype(float)
                    ))
                    fechas_hora = df_asesor_dia['fecha_evento'].dt.strftime('%H:%M:%S').tolist()
                    
                    # Color del asesor
                    color_asesor = colores_asesores.get(asesor_id, 'blue')
                    
                    print(f"  👤 Asesor {asesor_id}: {len(coordenadas)} puntos, color: {color_asesor}")
                    
                    # Pintar puntos
                    for i, (lat, lon) in enumerate(coordenadas):
                        popup_text = f"Asesor: {asesor_id}<br>Día: {dia}<br>Hora: {fechas_hora[i]}"
                        
                        if i == 0:  # INICIO del día - Verde
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=6,
                                color='green',
                                fill=True,
                                fillColor='green',
                                fillOpacity=0.8,
                                popup=f"🚀 INICIO {popup_text}"
                            ).add_to(mapa)
                        elif i == len(coordenadas) - 1:  # FIN del día - Rojo
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=6,
                                color='red',
                                fill=True,
                                fillColor='red',
                                fillOpacity=0.8,
                                popup=f"🏁 FIN {popup_text}"
                            ).add_to(mapa)
                        else:  # PUNTOS INTERMEDIOS - Color del asesor
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=4,
                                color=color_asesor,
                                fill=True,
                                fillColor=color_asesor,
                                fillOpacity=0.7,
                                popup=popup_text
                            ).add_to(mapa)
                    
                    # Pintar líneas entre puntos consecutivos
                    for i in range(len(coordenadas) - 1):
                        start = coordenadas[i]
                        end = coordenadas[i + 1]
                        
                        if all(np.isfinite(start)) and all(np.isfinite(end)):
                            folium.PolyLine(
                                locations=[start, end],
                                color=color_asesor,
                                weight=3,
                                opacity=0.8,
                                tooltip=f"Asesor {asesor_id} - {dia} ({fechas_hora[i]} → {fechas_hora[i+1]})"
                            ).add_to(mapa)
                            
        elif modo_visualizacion == "puntos":
            # MODO PUNTOS: Solo puntos por asesor sin líneas
            print("📍 Ejecutando modo PUNTOS...")
            
            # Agrupar por asesor (sin separar por días)
            for asesor_id, df_asesor in df_filtrado.groupby('id_autor'):
                
                # Color del asesor
                color_asesor = colores_asesores.get(asesor_id, 'blue')
                
                print(f"  👤 Asesor {asesor_id}: {len(df_asesor)} puntos, color: {color_asesor}")
                
                # Pintar todos los puntos del asesor
                for idx, row in df_asesor.iterrows():
                    lat = float(row['coordenada_latitud'])
                    lon = float(row['coordenada_longitud'])
                    fecha_hora = row['fecha_evento'].strftime('%Y-%m-%d %H:%M:%S')
                    barrio = row.get('barrio', 'N/A')
                    
                    popup_text = f"Asesor: {asesor_id}<br>Fecha: {fecha_hora}<br>Barrio: {barrio}"
                    
                    folium.CircleMarker(
                        location=[lat, lon],
                        radius=5,
                        color=color_asesor,
                        fill=True,
                        fillColor=color_asesor,
                        fillOpacity=0.8,
                        popup=popup_text
                    ).add_to(mapa)
                    
        else:
            print(f"❌ Modo de visualización no reconocido: {modo_visualizacion}")
            return None
        
        # Agregar bordes de barrios
        for feature in barrios_geojson['features']:
            folium.GeoJson(
                data=feature,
                style_function=lambda feature: {
                    'fillColor': 'transparent',
                    'color': 'black',
                    'weight': 1.5,
                    'fillOpacity': 0
                }
            ).add_to(mapa)
        
        # Agregar control de capas
        folium.LayerControl().add_to(mapa)

        # Guardar mapa
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_recorrido", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        return filename

    except Exception as e:
        logging.error(f"Error en la generación del mapa: {e}")
        return None

# if __name__ == "__main__":
#     print("🧪 Ejecutando mapa_muestras_recorrido desde consola...")

#     fecha_inicio = "2025-07-13"
#     fecha_fin = "2025-07-15"
#     ciudad = "MANIZALES"
#     barrios = None #"VILLA MARIA"
#     asesores = None #[17430 ,17506]
#     modo = "puntos"  # o "recorrido"

#     resultado = generar_mapa_muestras_recorrido(
#         fecha_inicio=fecha_inicio,
#         fecha_fin=fecha_fin,
#         ciudad=ciudad,
#         barrios=barrios,
#         asesores=asesores,
#         modo_visualizacion=modo
#     )

    # if resultado is not None:
    #     print("✅ Mapa generado correctamente (o DataFrame procesado).")
    #     print(resultado.columns)
    #     print(resultado.shape)
    #     print(resultado["id_autor"].unique())
    #     print(resultado["id_autor"].value_counts())

    # else:
    #     print("❌ No se pudo generar el mapa.")
