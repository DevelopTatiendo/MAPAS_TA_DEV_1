import folium
import json
import pandas as pd
import logging
import unicodedata

from pre_procesamiento.preprocesamiento_muestras import consultar_muestras_db
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
CENTROOPES = {'CALI': 2, 'MEDELLIN': 3, 'BOGOTA': 1}


def _normalizar_ciudad(ciudad: str) -> str:
    # Remueve acentos y deja solo alfanumérico en mayúsculas
    s = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn')
    s = s.upper()
    return ''.join(ch for ch in s if ch.isalnum())


def generar_mapa_muestras_auditoria(
    fecha_inicio: str,
    fecha_fin: str,
    ciudad: str,
    id_promotor: int
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
        Área en m², sin decimales, con separador de miles.
        """
        try:
            if v is None:
                return "N/A"
            val = float(v)
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

    capa_auditoria = folium.FeatureGroup(name="Zonas de auditoría")
    for ft in fc.get("features", []):
        props = ft.get("properties", {}) or {}
        area_m2 = props.get('area_m2')
        perimetro_m = props.get('perimetro_m')
        n_puntos = props.get('n_puntos')

        popup_html = f"""
        <b>Subcluster:</b> {props.get('id_subcluster', 'N/A')}<br>
        <b>Área (m²):</b> {_fmt_area_popup(area_m2)}<br>
        <b>Perímetro (m):</b> {_fmt_perimetro_popup(perimetro_m)}<br>
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
            radius=3,
            color="blue",
            fill=True,
            fill_opacity=0.9,
            popup=f"{row.get('fecha_evento','')} — ID contacto {row.get('id_contacto','')}"
        ).add_to(capa_puntos)

    capa_puntos.add_to(mapa)

    folium.LayerControl().add_to(mapa)

    # --- Guardar ---
    filename = guardar_mapa_controlado(mapa, "mapa_muestras_auditoria", permitir_multiples=False)
    total_puntos = len(df)

    return filename, total_puntos, df_areas
