import folium
import json
import pandas as pd
import logging
import unicodedata

from pre_procesamiento.preprocesamiento_muestras import consultar_muestras_db
from pre_procesamiento.metricas_areas import areas_muestras_auditoria
from utils.gestor_mapas import guardar_mapa_controlado

# Diccionario de ciudades para centrar el mapa (solo contexto base)
COORDENADAS_CIUDADES = {
    'CALI': ([3.4516, -76.5320], 'geojson/rutas/cali/cuadrantes_rutas_cali.geojson'),
    'MEDELLIN': ([6.2442, -75.5812], 'geojson/rutas/medellin/cuadrantes_rutas_medellin.geojson'),
    'BOGOTA': ([4.7110, -74.0721], 'geojson/rutas/bogota/cuadrantes_rutas_bogota.geojson'),
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

    # Capa comunas/cuadrantes base
    try:
        with open(path_geojson, 'r', encoding='utf-8') as f:
            gj_base = json.load(f)
        folium.GeoJson(gj_base, name="Base ciudad").add_to(mapa)
    except Exception as e:
        logging.error(f"No se pudo cargar geojson base: {e}")

    # --- Capa de zonas auditoría ---
    capa_auditoria = folium.FeatureGroup(name="Zonas de auditoría")
    for ft in fc.get("features", []):
        props = ft.get("properties", {}) or {}
        area_m2 = props.get('area_m2')
        n_puntos = props.get('n_puntos')
        densidad = None
        try:
            if area_m2 and float(area_m2) > 0 and n_puntos is not None:
                densidad = float(n_puntos) / float(area_m2)
        except Exception:
            densidad = None

        popup_html = f"""
        <b>Subcluster:</b> {props.get('id_subcluster', 'N/A')}<br>
        <b>Área (m²):</b> {props.get('area_m2', 'N/A')}<br>
        <b>Puntos usados:</b> {props.get('n_puntos', 'N/A')}<br>
        <b>Densidad:</b> {densidad if densidad is not None else 'N/A'}
        """

        folium.GeoJson(
            data=ft,
            name="auditoria",
            popup=popup_html,
            style_function=lambda x: {
                "color": "red",
                "fillOpacity": 0.2,
                "weight": 2
            }
        ).add_to(capa_auditoria)

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
