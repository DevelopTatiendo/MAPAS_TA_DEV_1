import folium
import json
import unicodedata
import re
import pandas as pd
import tempfile
import os
import glob
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.prepared import prep
from utils.gestor_mapas import guardar_mapa_controlado
from pre_procesamiento.preprocesamiento_consultores import (
    eventos_por_ruta_en_rango, 
    get_co,
    eventos_con_coordenadas_por_ruta_y_rango,
    ventas_con_coordenadas_por_ruta_y_rango
)
from utils.utilidades_geoespaciales import (
    procesar_consultores_por_cuadrantes,
    validar_consistencia_datos
)
import logging

# Configurar logging
logger = logging.getLogger(__name__)

def _norm_city(ciudad: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

def _norm_token(token: str) -> str:
    """Normalizar token de ruta: sin tildes, espacios → guiones bajos, mayúsculas."""
    if not token:
        return ""
    # Remover tildes
    sin_tildes = ''.join(c for c in unicodedata.normalize('NFD', token) if unicodedata.category(c) != 'Mn')
    # Reemplazar espacios y símbolos con guiones bajos, luego mayúsculas
    normalizado = re.sub(r'[^\w]', '_', sin_tildes).upper()
    return normalizado

def _coords_and_geojson():
    return {
        'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
        'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
        'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
        'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
        'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
        'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
        'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson')
    }

def _es_cuadrante(feature):
    """Verifica si la feature es un cuadrante (codigo empieza por CL_)."""
    codigo = (feature.get('properties', {}).get('codigo') or '').upper()
    return codigo.startswith('CL_')

def _style_cuadrante(feature):
    """Estilo para cuadrantes basado en properties del GeoJSON."""
    p = feature.get('properties', {})
    return {
        'fillColor': p.get('fillColor', '#ffd24d'),
        'color': p.get('color', '#111111'),
        'weight': p.get('weight', 1),
        'fillOpacity': p.get('fillOpacity', 0.35),
    }

def _style_no_cuadrante(_):
    """Estilo para features que no son cuadrantes (contorno transparente)."""
    return {
        'fillColor': 'transparent',
        'color': '#000000',
        'weight': 0.8,
        'fillOpacity': 0.0
    }

def _generar_popup_cuadrante(codigo_cuadrante: str, df_resumen: pd.DataFrame, df_detalle: pd.DataFrame) -> str:
    """
    Genera el HTML del popup para un cuadrante específico.
    
    Args:
        codigo_cuadrante (str): Código del cuadrante
        df_resumen (pd.DataFrame): DataFrame de resumen por cuadrante
        df_detalle (pd.DataFrame): DataFrame de detalle por cuadrante-consultor
        
    Returns:
        str: HTML del popup
    """
    # Verificar que los DataFrames no estén vacíos
    if df_resumen.empty:
        return f"<b>{codigo_cuadrante}</b><br>Sin datos disponibles"
    
    # Buscar datos de resumen para este cuadrante
    resumen_cuadrante = df_resumen[df_resumen['codigo_cuadrante'] == codigo_cuadrante]
    if resumen_cuadrante.empty:
        return f"<b>{codigo_cuadrante}</b><br>Sin datos disponibles"
    
    # Obtener datos del cuadrante
    row = resumen_cuadrante.iloc[0]
    area_m2 = float(row.get('area_m2', 0))
    visitas_tot = float(row.get('visitas_tot', 0))
    
    # Obtener visitas_por_m2 con fallback para compatibilidad
    if 'visitas_por_m2' in row.index:
        visitas_por_m2 = float(row.get('visitas_por_m2', 0))
    else:
        # Fallback: calcular visitas_por_m2 = visitas_tot / area_m2
        visitas_por_m2 = visitas_tot / area_m2 if area_m2 > 0 else 0.0
    
    # Calcular valores derivados para mostrar en ambas unidades
    if area_m2 > 0:
        area_km2 = area_m2 / 1_000_000  # Convertir m² a km²
        visitas_por_km2 = visitas_por_m2 * 1_000_000  # Convertir visitas/m² a visitas/km²
        
        # Formatear valores con los formatos especificados
        area_m2_fmt = f"{area_m2:,.0f}"  # Área en m² con separador de miles, 0 decimales
        area_km2_fmt = f"{area_km2:.2f}"  # Área en km² con 2 decimales
        visitas_m2_fmt = f"{visitas_por_m2:.6f}"  # Visitas/m² con 6 decimales
        visitas_km2_fmt = f"{visitas_por_km2:.1f}"  # Visitas/km² con 1 decimal
        
        area_texto = f"{area_m2_fmt} m² ({area_km2_fmt} km²)"
        densidad_texto = f"{visitas_m2_fmt} (≈ {visitas_km2_fmt} visitas/km²)"
    else:
        # Si area_m2 no está o es 0, mostrar s/d
        area_texto = "s/d"
        densidad_texto = "s/d"
    
    # Obtener detalles por consultor para este cuadrante
    if df_detalle.empty:
        detalle_cuadrante = pd.DataFrame()
    else:
        detalle_cuadrante = df_detalle[df_detalle['codigo_cuadrante'] == codigo_cuadrante].copy()
    
    # Ordenar por visitas descendente
    if not detalle_cuadrante.empty:
        detalle_cuadrante = detalle_cuadrante.sort_values('visitas', ascending=False)
    
    # Construir HTML del popup
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 400px;">
        <h4 style="margin: 0 0 8px 0; color: #2563eb;">{codigo_cuadrante}</h4>
        <p style="margin: 0 0 12px 0; font-size: 12px; color: #6b7280;">
            <b>Área:</b> {area_texto} | <b>Visitas/m²:</b> {densidad_texto}
        </p>
    """
    
    # Agregar tabla de consultores si hay datos
    if not detalle_cuadrante.empty:
        html += """
        <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
            <thead>
                <tr style="background: #f3f4f6; text-align: left;">
                    <th style="padding: 4px 6px; border: 1px solid #d1d5db;">Consultor</th>
                    <th style="padding: 4px 6px; border: 1px solid #d1d5db;">Visitas</th>
                    <th style="padding: 4px 6px; border: 1px solid #d1d5db;">Aperturas</th>
                    <th style="padding: 4px 6px; border: 1px solid #d1d5db;">Ventas</th>
                    <th style="padding: 4px 6px; border: 1px solid #d1d5db;">Total venta</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for _, det_row in detalle_cuadrante.iterrows():
            apellido = str(det_row.get('apellido', 'N/A'))
            visitas = int(float(det_row.get('visitas', 0)))
            aperturas = int(float(det_row.get('aperturas', 0)))
            ventas = int(float(det_row.get('ventas', 0)))
            total_venta = float(det_row.get('total_venta_conIVA', 0))
            
            html += f"""
                <tr>
                    <td style="padding: 3px 6px; border: 1px solid #d1d5db;">{apellido}</td>
                    <td style="padding: 3px 6px; border: 1px solid #d1d5db; text-align: center;">{visitas}</td>
                    <td style="padding: 3px 6px; border: 1px solid #d1d5db; text-align: center;">{aperturas}</td>
                    <td style="padding: 3px 6px; border: 1px solid #d1d5db; text-align: center;">{ventas}</td>
                    <td style="padding: 3px 6px; border: 1px solid #d1d5db; text-align: right;">${total_venta:,.0f}</td>
                </tr>
            """
        
        html += """
            </tbody>
        </table>
        """
    else:
        html += "<p style='color: #6b7280; font-size: 11px; font-style: italic;'>Sin actividad de consultores en este período</p>"
    
    html += "</div>"
    
    return html

def _cargar_geojson_ruta_exacto(ciudadN: str, id_ruta: int) -> dict | None:
    """
    Carga exactamente el archivo subcuadrante_CL_{id_ruta}_00.geojson para una ruta específica.
    
    Args:
        ciudadN (str): Nombre de ciudad normalizado
        id_ruta (int): ID de la ruta
        
    Returns:
        dict | None: FeatureCollection si encuentra el archivo, None si no existe
    """
    # 1) Ruta ABSOLUTA (Windows del usuario)
    base_abs = r"C:\Users\ESP_NEGOCIO\Documents\GitHub\MAPAS_TA_DEV_1\geojson\rutas\cali"
    fname = f"subcuadrante_CL_{id_ruta}_00.geojson"
    path_abs = os.path.join(base_abs, fname)

    # 2) Ruta RELATIVA (por si el programador corre fuera de esa máquina)
    path_rel = os.path.join("geojson", "rutas", ciudadN.lower(), fname)

    for path in (path_abs, path_rel):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    geojson_data = json.load(f)
                logger.info(f"✓ Archivo específico cargado: {path}")
                return geojson_data
            except Exception as e:
                logger.error(f"Error leyendo {path}: {e}")
                continue
    
    logger.info(f"No se encontró archivo específico para ruta {id_ruta} en {ciudadN}")
    return None



def generar_mapa_consultores(fecha_inicio, fecha_fin, ciudad, ruta_id, ruta_nombre, mostrar_fuera: bool = False):
    """
    Genera mapa de consultores con filtro espacial por cuadrantes y popups detallados.
    
    Args:
        fecha_inicio: string formato 'YYYY-MM-DD HH:MM:SS'
        fecha_fin: string formato 'YYYY-MM-DD HH:MM:SS'
        ciudad: nombre de la ciudad
        ruta_id: id_ruta numérico
        ruta_nombre: nombre de la ruta (string mostrado en UI)
        mostrar_fuera: bool para mostrar puntos fuera de cuadrantes en rojo (default: False)
    """
    # 1) Normalizar ciudad y resolver centro
    ciudadN = _norm_city(ciudad)
    centers = _coords_and_geojson()
    if ciudadN not in centers:
        return None
    location, _ = centers[ciudadN]
    
    # 2) Obtener CO y datos de eventos
    co = get_co(ciudadN)
    id_ruta = int(ruta_id) if not isinstance(ruta_id, int) else int(ruta_id)
    df_eventos = eventos_por_ruta_en_rango(co, id_ruta, fecha_inicio, fecha_fin)
    
    total_eventos = len(df_eventos) if df_eventos is not None else 0

    # 3) Cargar GeoJSON: específico por ruta si aplica, sino archivo base
    geojson_a_usar = None
    
    # Si ruta_nombre no es "TODOS" y no está vacío, intentar archivo específico
    if ruta_nombre and ruta_nombre.strip() != "" and ruta_nombre.strip().upper() != "TODOS":
        geojson_a_usar = _cargar_geojson_ruta_exacto(ciudadN, id_ruta)
    
    # Si no se cargó archivo específico, usar archivo base
    if geojson_a_usar is None:
        archivo_base = f"geojson/cuadrantes_{ciudadN.lower()}_rutas_consultores.geojson"
        
        try:
            with open(archivo_base, 'r', encoding='utf-8') as f:
                geojson_a_usar = json.load(f)
            logger.info(f"GeoJSON base cargado exitosamente: {archivo_base}")
        except FileNotFoundError:
            error_msg = f"Error: No se encontró el archivo GeoJSON requerido: {archivo_base}"
            logger.error(error_msg)
            print(error_msg)
            print(f"Por favor, asegúrese de que existe el archivo para la ciudad {ciudad}")
            geojson_a_usar = None
        except Exception as e:
            error_msg = f"Error cargando archivo GeoJSON {archivo_base}: {e}"
            logger.error(error_msg)
            print(error_msg)
            geojson_a_usar = None

    # 4) Obtener DataFrames de agregación para popups
    df_resumen = pd.DataFrame()
    df_detalle = pd.DataFrame()
    
    try:
        # Intentar obtener los datos de agregación usando las funciones del GRANDE 3
        geojson_path = None
        if geojson_a_usar is not None:
            # Guardar GeoJSON temporalmente para el análisis
            with tempfile.NamedTemporaryFile(mode='w', suffix='.geojson', delete=False, encoding='utf-8') as temp_file:
                json.dump(geojson_a_usar, temp_file)
                geojson_path = temp_file.name
        
        df_resumen = obtener_resumen_cuadrantes_consultores(fecha_inicio, fecha_fin, ciudad, ruta_id, geojson_path)
        df_detalle = obtener_detalle_cuadrantes_consultores(fecha_inicio, fecha_fin, ciudad, ruta_id, geojson_path)
        
        # Limpiar archivo temporal si se creó
        if geojson_path:
            try:
                os.unlink(geojson_path)
            except:
                pass
                
        logger.info(f"Datos agregación obtenidos: {len(df_resumen)} cuadrantes, {len(df_detalle)} detalles")
        
    except Exception as e:
        logger.warning(f"No se pudieron obtener datos de agregación para popups: {e}")
    
    # 5) Crear mapa base
    mapa = folium.Map(location, zoom_start=12)
    
    # 6) Dibujar GeoJSON (solo cuadrantes con color, resto transparente)
    if geojson_a_usar is not None:
        fg_contorno = folium.FeatureGroup(name="Contorno", show=True, control=False)
        fg_cuadrantes = folium.FeatureGroup(name="Cuadrantes", show=True)
        
        for feat in geojson_a_usar.get('features', []):
            if _es_cuadrante(feat):
                # Obtener código del cuadrante para el popup
                codigo_cuadrante = feat.get('properties', {}).get('codigo', '')
                
                # Generar popup con datos de agregación
                if not df_resumen.empty and not df_detalle.empty:
                    popup_html = _generar_popup_cuadrante(codigo_cuadrante, df_resumen, df_detalle)
                    popup = folium.Popup(popup_html, max_width=450)
                else:
                    # Popup básico si no hay datos de agregación
                    popup_html = f"<b>{codigo_cuadrante}</b><br>Datos de agregación no disponibles"
                    popup = folium.Popup(popup_html, max_width=300)
                
                # Tooltip para mostrar código al hover
                tooltip = folium.GeoJsonTooltip(
                    fields=[],
                    aliases=[],
                    labels=False,
                    sticky=True,
                    tooltip=f"<b>{codigo_cuadrante}</b>"
                )
                
                folium.GeoJson(
                    data=feat,
                    style_function=_style_cuadrante,
                    popup=popup,
                    tooltip=tooltip
                ).add_to(fg_cuadrantes)
            else:
                # Features no-cuadrante: solo contorno transparente y NO-INTERACTIVO
                folium.GeoJson(
                    data=feat,
                    style_function=_style_no_cuadrante,
                    popup=False,  # Sin popup
                    tooltip=False  # Sin tooltip
                ).add_to(fg_contorno)
        
        # ORDEN IMPORTANTE: contorno primero (abajo), cuadrantes después (arriba)
        fg_contorno.add_to(mapa)
        fg_cuadrantes.add_to(mapa)
    else:
        # Si no hay GeoJSON, mostrar mensaje informativo en el mapa
        info_html = f"""
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 350px; height: 90px; 
                    background-color: rgba(255, 255, 255, 0.9); z-index:9999; 
                    font-size:14px; padding: 10px; border: 2px solid red; border-radius: 5px;">
            <b>⚠️ Archivo GeoJSON no encontrado</b><br>
            <small>No se encontró: cuadrantes_{ciudadN.lower()}_rutas_consultores.geojson<br>
            El mapa mostrará solo los puntos de eventos.</small>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(info_html))

    # 7) Selección de cuadrantes por ruta (soportar ID y NOMBRE)
    cuadrantes_ruta = []
    
    if geojson_a_usar is not None:
        # Normalizar nombre de ruta
        nom = _norm_token(ruta_nombre)
        
        # Construir patrones de búsqueda
        patrones = [
            rf'^CL_{id_ruta}_[0-9]{{2}}$',           # CL_3_01
            rf'^CL_{nom}_[0-9]{{2}}$',               # CL_RUTA_NOMBRE_01  
            rf'^CL_{nom}_{id_ruta}_[0-9]{{2}}$'      # CL_RUTA_NOMBRE_3_01
        ]
        
        def _match_codigo(cod):
            C = (cod or '').upper()
            return any(re.match(p, C) for p in patrones)
        
        for feat in geojson_a_usar.get('features', []):
            codigo = feat.get('properties', {}).get('codigo', '')
            if _match_codigo(codigo):
                cuadrantes_ruta.append(feat)

    # 8) Filtro espacial de eventos (solo puntos interiores)
    df_filtrados = pd.DataFrame()
    
    if df_eventos is not None and not df_eventos.empty and cuadrantes_ruta:
        # Construir unión de polígonos de los cuadrantes de esta ruta
        polygons = []
        for feat in cuadrantes_ruta:
            try:
                geom = shape(feat['geometry'])
                if not geom.is_valid:
                    geom = geom.buffer(0)
                polygons.append(geom)
            except Exception:
                continue
        
        if polygons:
            # Crear unión preparada para consultas rápidas
            union_geom = unary_union(polygons)
            if not union_geom.is_valid:
                union_geom = union_geom.buffer(0)
            prepped_union = prep(union_geom)
            
            # Filtrar eventos que caen dentro de los polígonos
            def punto_dentro(row):
                try:
                    point = Point(float(row['lon']), float(row['lat']))
                    return prepped_union.intersects(point)
                except:
                    return False
            
            mask_in = df_eventos.apply(punto_dentro, axis=1)
            df_filtrados = df_eventos[mask_in].reset_index(drop=True)

    # 9) Pintar SOLO los eventos filtrados (interiores)
    if df_filtrados is not None and not df_filtrados.empty:
        for _, r in df_filtrados.iterrows():
            lat, lon = float(r.lat), float(r.lon)
            popup = folium.Popup(
                f"<b>Evento:</b> {r.id_evento}<br><b>Contacto:</b> {r.id_contacto}<br><b>Fecha:</b> {r.fecha_evento}",
                max_width=300
            )
            folium.CircleMarker(
                location=[lat, lon],
                radius=4,
                color="#374151",  # gris oscuro
                fill=True,
                fillOpacity=0.7,
                popup=popup
            ).add_to(mapa)

        # 9.1) Pintar eventos FUERA de cuadrantes en rojo intenso (solo si mostrar_fuera=True)
        if mostrar_fuera and df_eventos is not None and not df_eventos.empty and geojson_a_usar is not None:
            df_fuera = df_eventos[~mask_in].reset_index(drop=True)
            
            for _, r in df_fuera.iterrows():
                lat, lon = float(r.lat), float(r.lon)
                popup = folium.Popup(
                    f"<b>Evento:</b> {r.id_evento}<br><b>Contacto:</b> {r.id_contacto}<br><b>Fecha:</b> {r.fecha_evento}",
                    max_width=300
                )
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=4,
                    color="#B91C1C",  # rojo intenso
                    fill=True,
                    fillOpacity=0.85,
                    popup=popup
                ).add_to(mapa)

        # 10) Fit bounds a los puntos filtrados
        try:
            coords = [[float(r.lat), float(r.lon)] for _, r in df_filtrados.iterrows()]
            if coords:
                mapa.fit_bounds(coords)
        except Exception:
            pass

    # 11) Leyenda obligatoria (3 líneas exactas con %)
    n_dentro = len(df_filtrados) if df_filtrados is not None else 0
    pct = (100 * n_dentro / total_eventos) if total_eventos > 0 else 0.0
    
    lineas_leyenda = [
        f"<b>Consultores — {ruta_nombre} ({ciudadN})</b>",
        f"Total: {total_eventos}",
        f"Dentro: {n_dentro} ({pct:.1f}%)"
    ]
    
    html_leyenda = f"""
    <div style="position: fixed; top: 20px; left: 20px; background: white; padding: 12px; border-radius: 8px;
                box-shadow: 0 0 10px rgba(0,0,0,.15); z-index: 1000; font-family: Arial, sans-serif;">
      {'<br>'.join(lineas_leyenda)}
    </div>"""
    mapa.get_root().html.add_child(folium.Element(html_leyenda))

    # 12) Guardar y retornar
    folium.LayerControl(collapsed=True, position='topright').add_to(mapa)
    filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_consultores", permitir_multiples=False)
    mapa.save(f"static/maps/{filename}")
    return filename

def analizar_consultores_por_cuadrantes(fecha_inicio: str, fecha_fin: str, ciudad: str, 
                                       ruta_id: int, geojson_path: str = None) -> tuple:
    """
    Realiza análisis geoespacial completo de consultores por cuadrantes.
    
    Args:
        fecha_inicio (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        fecha_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
        ciudad (str): Nombre de la ciudad
        ruta_id (int): ID de la ruta
        geojson_path (str, optional): Ruta al archivo GeoJSON de cuadrantes
    
    Returns:
        tuple: (df_resumen, df_detalle, validacion_resultado)
        - df_resumen: DataFrame con resumen por cuadrante
        - df_detalle: DataFrame con detalle por cuadrante-consultor  
        - validacion_resultado: Dict con resultados de validación
    
    Raises:
        Exception: Si hay errores en el análisis geoespacial
    """
    logger.info(f"Iniciando análisis geoespacial para {ciudad}, ruta {ruta_id}")
    
    try:
        # 1. Obtener datos base
        ciudadN = _norm_city(ciudad)
        co = get_co(ciudadN)
        
        # 2. Determinar archivo GeoJSON
        if geojson_path is None:
            geojson_path = f"geojson/cuadrantes_{ciudadN.lower()}_rutas_consultores.geojson"
        
        # 3. Obtener eventos con coordenadas
        df_eventos = eventos_con_coordenadas_por_ruta_y_rango(co, ruta_id, fecha_inicio, fecha_fin)
        
        # 4. Obtener ventas con coordenadas (opcional)
        try:
            df_ventas = ventas_con_coordenadas_por_ruta_y_rango(co, ruta_id, fecha_inicio, fecha_fin)
        except Exception as e:
            logger.warning(f"No se pudieron obtener datos de ventas: {e}")
            df_ventas = None
        
        # 5. Procesar análisis geoespacial
        df_resumen, df_detalle = procesar_consultores_por_cuadrantes(
            geojson_path, df_eventos, df_ventas
        )
        
        # 6. Validar consistencia
        validacion = validar_consistencia_datos(df_resumen, df_detalle)
        
        logger.info(f"Análisis completado: {len(df_resumen)} cuadrantes, {len(df_detalle)} registros detalle")
        
        return df_resumen, df_detalle, validacion
        
    except Exception as e:
        logger.error(f"Error en análisis geoespacial: {str(e)}")
        raise e

def obtener_resumen_cuadrantes_consultores(fecha_inicio: str, fecha_fin: str, ciudad: str, 
                                          ruta_id: int, geojson_path: str = None) -> pd.DataFrame:
    """
    Función simplificada para obtener solo el resumen por cuadrantes.
    
    Args:
        fecha_inicio (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        fecha_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
        ciudad (str): Nombre de la ciudad
        ruta_id (int): ID de la ruta
        geojson_path (str, optional): Ruta al archivo GeoJSON de cuadrantes
    
    Returns:
        pd.DataFrame: Resumen con columnas ['codigo_cuadrante', 'area_m2', 'visitas_tot', 
                     'visitas_por_m2', 'aperturas_tot', 'ventas_tot', 'total_venta_tot', 'consultores']
    """
    try:
        df_resumen, _, _ = analizar_consultores_por_cuadrantes(
            fecha_inicio, fecha_fin, ciudad, ruta_id, geojson_path
        )
        return df_resumen
    except Exception as e:
        logger.error(f"Error obteniendo resumen: {str(e)}")
        return pd.DataFrame()

def obtener_detalle_cuadrantes_consultores(fecha_inicio: str, fecha_fin: str, ciudad: str, 
                                          ruta_id: int, geojson_path: str = None) -> pd.DataFrame:
    """
    Función simplificada para obtener solo el detalle por cuadrante-consultor.
    
    Args:
        fecha_inicio (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        fecha_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
        ciudad (str): Nombre de la ciudad
        ruta_id (int): ID de la ruta
        geojson_path (str, optional): Ruta al archivo GeoJSON de cuadrantes
    
    Returns:
        pd.DataFrame: Detalle con columnas ['codigo_cuadrante', 'id_consultor', 'apellido', 
                     'visitas', 'aperturas', 'ventas', 'total_venta_conIVA']
    """
    try:
        _, df_detalle, _ = analizar_consultores_por_cuadrantes(
            fecha_inicio, fecha_fin, ciudad, ruta_id, geojson_path
        )
        return df_detalle
    except Exception as e:
        logger.error(f"Error obteniendo detalle: {str(e)}")
        return pd.DataFrame()
