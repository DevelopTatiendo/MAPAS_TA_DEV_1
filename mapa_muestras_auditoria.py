import folium
import json
import pandas as pd
import logging
import unicodedata

from pre_procesamiento.preprocesamiento_muestras import consultar_muestras_db, obtener_nombre_promotor
from pre_procesamiento.metricas_areas import areas_muestras_auditoria
from utils.gestor_mapas import guardar_mapa_controlado

# Diccionario de ciudades para centrar el mapa (solo contexto base)
# En modo auditoría ya NO usamos rutas/cuadrantes, sino comunas por ciudad.
COORDENADAS_CIUDADES = {
    'CALI': ([3.4516, -76.5320], 'geojson/comunas_cali.geojson'),
    'MEDELLIN': ([6.2442, -75.5812], 'geojson/comunas_medellin.geojson'),
    'MANIZALES': ([5.0672, -75.5174], 'geojson/comunas_manizales.geojson'),
    'PEREIRA': ([4.8087, -75.6906], 'geojson/comunas_pereira.geojson'),
    'BOGOTA': ([4.7110, -74.0721], 'geojson/comunas_bogota.geojson'),
    'BARRANQUILLA': ([10.9720, -74.7962], 'geojson/comunas_barranquilla.geojson'),
    'BUCARAMANGA': ([7.1193, -73.1227], 'geojson/comunas_bucaramanga.geojson'),
}

# Centroope de cada ciudad (según especificación del usuario)
CENTROOPES = {'CALI': 2, 'MEDELLIN': 3, 'BOGOTA': 1, 'BARRANQUILLA': 4, 'BUCARAMANGA': 5, 'MANIZALES': 6, 'PEREIRA': 7}


def _normalizar_ciudad(ciudad: str) -> str:
    # Remueve acentos y deja solo alfanumérico en mayúsculas
    s = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn')
    s = s.upper()
    return ''.join(ch for ch in s if ch.isalnum())


def generar_mapa_muestras_auditoria(
    fecha_inicio: str,
    fecha_fin: str,
    ciudad: str,
    id_promotor: int,
    clientes_x_muestras: bool = False,
):
    """
    Genera el mapa de auditoría para UN promotor.
    1) Consulta BD real
    2) Calcula áreas/geojson con metricas_areas
    3) Renderiza mapa Folium
    """
    # --- Normalizar ciudad ---
    ciudad_norm = _normalizar_ciudad(ciudad)
    if ciudad_norm not in CENTROOPES:
        raise ValueError(f"Ciudad no soportada para auditoría: {ciudad}")

    centroope = CENTROOPES[ciudad_norm]
    (center_point, path_geojson) = COORDENADAS_CIUDADES[ciudad_norm]

    # --- 1) CONSULTA REAL BD (UN solo promotor) ---
    df = consultar_muestras_db(
        centroope=centroope,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        promotores=[id_promotor]
    )

    if df is None or df.empty:
        # mapa vacío pero válido
        mapa = folium.Map(location=center_point, zoom_start=13)
        filename = guardar_mapa_controlado(mapa, "mapa_muestras_auditoria", permitir_multiples=False)
        return filename, 0, None

    # Normalizar columnas mínimas
    df = df.copy()
    df = df.dropna(subset=['coordenada_latitud', 'coordenada_longitud'])

    # Nombre del promotor vía función centralizada
    nombre_promotor_ui = obtener_nombre_promotor(id_promotor) or f"ID promotor {id_promotor}"

    # ==============================
    #  Modo opcional: Clientes x Muestras
    #  (una fila por cliente para este promotor)
    # ==============================
    if clientes_x_muestras and 'id_contacto' in df.columns:
        df = (
            df.sort_values('fecha_evento')
              .drop_duplicates(subset=['id_contacto'], keep='last')
        )
    # ==============================

    # --- 2) CALCULAR ÁREAS + GEOJSON ---
    # subclusters, áreas, perímetros, n_puntos, geojson completo
    df_areas, fc = areas_muestras_auditoria(df, centroope)

    # --- 3) CREAR MAPA ---
    mapa = folium.Map(location=center_point, zoom_start=13)

    # Capa base de comunas de la ciudad
    try:
        with open(path_geojson, 'r', encoding='utf-8') as f:
            gj_base = json.load(f)
        folium.GeoJson(
            gj_base,
            name="Base ciudad",
            style_function=lambda feature: {
                "color": "black",     # borde negro
                "weight": 1,            # grosor de línea
                "fillOpacity": 0.0      # sin relleno
            }
        ).add_to(mapa)
    except Exception as e:
        logging.error(f"No se pudo cargar geojson base: {e}")

    # --- Capa de zonas auditoría ---
    def _fmt_area_popup(v):
        """
        Área en miles de m² (area_m2 / 1000), sin decimales, con separador de miles.
        """
        try:
            if v is None:
                return "N/A"
            val = float(v) / 1000.0
            return f"{int(round(val)):,}"
        except Exception:
            return "N/A"

    def _fmt_perimetro_popup(v):
        """
        Perímetro en metros, con 2 decimales y separador de miles.
        """
        try:
            if v is None:
                return "N/A"
            val = float(v)
            return f"{val:,.2f}"
        except Exception:
            return "N/A"
    def _fmt_densidad_km2(v):
        """Densidad compuesta (factor 1000), 6 decimales."""
        try:
            if v is None:
                return "N/A"
            return f"{float(v)*1000:,.6f}"
        except Exception:
            return "N/A"

    capa_auditoria = folium.FeatureGroup(name="Zonas de auditoría")
    for ft in fc.get("features", []):
        props = ft.get("properties", {}) or {}
        area_m2 = props.get('area_m2')
        perimetro_m = props.get('perimetro_m')
        n_puntos = props.get('n_puntos')
        densidad_compacta = props.get('densidad_compacta')
        compacidad = props.get('compacidad')

        popup_html = f"""
        <b>Subcluster:</b> {props.get('id_subcluster', 'N/A')}<br>
        <b>Área (miles de m²):</b> {_fmt_area_popup(area_m2)}<br>
        <b>Perímetro (m):</b> {_fmt_perimetro_popup(perimetro_m)}<br>
        <b>Puntos en el área:</b> {n_puntos if n_puntos is not None else 'N/A'}<br>
        <b>Densidad compuesta:</b> {_fmt_densidad_km2(densidad_compacta)}<br>
        <b>Compacidad:</b> {compacidad if compacidad is not None else 'N/A'}
        """
        #<b>Puntos en el área:</b> {n_puntos if n_puntos is not None else 'N/A'}

        # Crear la geometría
        gj = folium.GeoJson(
            data=ft,
            name="auditoria",
            style_function=lambda x: {
                # Borde rojo, sin relleno (relleno incoloro)
                "color": "red",
                "fillOpacity": 0.0,
                "weight": 2
            }
        )

        # Adjuntar el popup a la geometría
        gj.add_child(folium.Popup(popup_html, max_width=300))

        # Añadir la geometría a la capa de auditoría
        gj.add_to(capa_auditoria)

    capa_auditoria.add_to(mapa)

    # --- Capa puntos del promotor ---
    capa_puntos = folium.FeatureGroup(name="Puntos del promotor")
    for _, row in df.iterrows():
        try:
            lat = float(row['coordenada_latitud'])
            lon = float(row['coordenada_longitud'])
        except Exception:
            continue
        folium.CircleMarker(
            location=[lat, lon],
            radius=5,
            color="blue",
            fill=True,
            fill_opacity=0.9,
            popup=f"{row.get('fecha_evento','')} — ID contacto {row.get('id_contacto','')}"
        ).add_to(capa_puntos)

    capa_puntos.add_to(mapa)

    folium.LayerControl().add_to(mapa)

    # --- Leyenda de resumen para auditoría ---
    try:
        descripcion_modo = "Clientes x muestras" if clientes_x_muestras else "Todas las muestras del promotor"
        html_resumen = f"""
        <div id='legend-resumen-auditoria' style='
            position: fixed; top: 20px; left: 20px;
            background-color: white; padding: 15px; border-radius: 5px;
            box-shadow: 0 0 10px rgba(0,0,0,0.2); z-index: 1000;
            font-family: Arial, sans-serif; min-width: 260px; font-size: 12px;'>
            <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;'>
                <h4 style='margin:0; font-size:13px; color:#111;'>Resumen Auditoría Muestras</h4>
            </div>
            <table style='width: 100%; border-collapse: collapse;'>
                <tr>
                    <td style='padding: 3px 0;'>Promotor/a:</td>
                    <td style='padding: 3px 0;'><b>{nombre_promotor_ui}</b></td>
                </tr>
                <tr>
                    <td style='padding: 3px 0;'>Fechas:</td>
                    <td style='padding: 3px 0;'><b>{fecha_inicio} - {fecha_fin}</b></td>
                </tr>
                <tr>
                    <td style='padding: 3px 0;'>Puntos en mapa:</td>
                    <td style='padding: 3px 0;'><b>{len(df)}</b></td>
                </tr>
                <tr>
                    <td colspan='2' style='padding: 4px 0; font-size:11px; color:#6b7280;'>
                        {descripcion_modo}
                    </td>
                </tr>
            </table>
        </div>
        """
        mapa.get_root().html.add_child(folium.Element(html_resumen))
    except Exception as e:
        logging.warning(f"No se pudo insertar leyenda de resumen en auditoría: {e}")

    # --- Guardar ---
    filename = guardar_mapa_controlado(mapa, "mapa_muestras_auditoria", permitir_multiples=False)
    total_puntos = len(df)

    return filename, total_puntos, df_areas
