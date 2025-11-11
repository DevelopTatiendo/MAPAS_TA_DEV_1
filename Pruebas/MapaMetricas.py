# --- Bootstrap de rutas del proyecto (NO MOVER) ---
import os, sys
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.abspath(os.path.join(CURRENT_DIR, ".."))           # raíz del repo
PREPROC_DIR = os.path.join(BASE_DIR, "pre_procesamiento")

for p in (BASE_DIR, PREPROC_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)
# -----------------------------------------------

import json
import logging
from datetime import datetime
import pandas as pd
import folium

# Constantes de la prueba
CIUDAD = "CALI"
CENTROOPE = 2
FECHA_INICIO = "2025-01-01"
FECHA_FIN    = "2025-12-31"
promotor_num = 2 # 1 = mejor promotor (más muestras), 2 = segundo, etc.

# Usar rutas absolutas desde la raíz del repo
GEOJSON_RUTAS_CALI     = os.path.join(BASE_DIR, "geojson", "rutas", "cali", "cuadrantes_rutas_cali.geojson")
RUTA_COORDENADAS_CALI  = os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv")

# Paleta de fallback si no existe color_for_promotor
FALLBACK_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
    "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#005f73", "#9b2226",
    "#bb3e03", "#0a9396", "#94d2bd", "#ee9b00", "#ca6702", "#ae2012",
    "#b56576", "#6d597a"
]

# Imports del proyecto (ya con sys.path correcto)
from pre_procesamiento.preprocesamiento_muestras import crear_df, obtener_promotores_por_ids

try:
    from mapa_muestras import color_for_promotor
    _HAS_COLOR_FN = True
except Exception:
    _HAS_COLOR_FN = False
    def color_for_promotor(co, pid):
        idx = abs(int(pid)) % len(FALLBACK_COLORS)
        return FALLBACK_COLORS[idx]

RESULTADOS_DIR = os.path.join(BASE_DIR, "Pruebas", "Resultados")
os.makedirs(RESULTADOS_DIR, exist_ok=True)

HTML_OUT = os.path.join(RESULTADOS_DIR, "muestras_simple_CALI_2025.html")
CSV_OUT  = os.path.join(RESULTADOS_DIR, "muestras_CALI_2025.csv")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


def _resolver_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
    # Intentar columnas estándar del proyecto
    lat_col = None
    for c in ["coordenada_latitud", "latitud", "lat"]:
        if c in df.columns:
            lat_col = c
            break
    lon_col = None
    for c in ["coordenada_longitud", "longitud", "lon"]:
        if c in df.columns:
            lon_col = c
            break
    if not lat_col or not lon_col:
        raise ValueError("No se encontraron columnas de lat/lon en el DataFrame.")
    df = df.copy()
    df["_lat"] = pd.to_numeric(df[lat_col], errors="coerce")
    df["_lon"] = pd.to_numeric(df[lon_col], errors="coerce")
    return df.dropna(subset=["_lat", "_lon"])


def _compactar_nombre(nombre: str, pid: str) -> str:
    try:
        parts = [p for p in str(nombre).strip().split() if p]
        if len(parts) >= 2:
            return f"{parts[0]} {parts[1]} {pid}".strip()
        elif parts:
            return f"{parts[0]} {pid}".strip()
    except Exception:
        pass
    return f"id {pid}"


def main():
    logging.info("Iniciando generación de mapa de muestras CALI 2025")
    # Consultar datos base
    if not os.path.exists(RUTA_COORDENADAS_CALI):
        logging.warning(f"No existe archivo de coordenadas: {RUTA_COORDENADAS_CALI}. Continuando sin merge de barrios.")
    try:
        df = crear_df(CENTROOPE, FECHA_INICIO, FECHA_FIN, RUTA_COORDENADAS_CALI, promotores=None)
    except Exception as e:
        logging.error(f"Error al crear DF base: {e}")
        df = pd.DataFrame()

    if df.empty:
        logging.warning("DF vacío: se generará mapa sin puntos.")
        mapa = folium.Map(location=[3.4516, -76.5320], zoom_start=12)
        mapa.save(HTML_OUT)
        pd.DataFrame().to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
        print(f"HTML vacío: {HTML_OUT}")
        print(f"CSV vacío: {CSV_OUT}")
        print("len(df)=0")
        return

    # Normalizar fecha_evento
    if "fecha_evento" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["fecha_evento"]):
        df["fecha_evento"] = pd.to_datetime(df["fecha_evento"], errors="coerce")

    # Resolver lat/lon
    try:
        df = _resolver_lat_lon(df)
    except Exception as e:
        logging.error(f"Abortando: {e}")
        mapa = folium.Map(location=[3.4516, -76.5320], zoom_start=12)
        folium.Marker(location=[3.4516, -76.5320], popup="Sin columnas lat/lon válidas").add_to(mapa)
        mapa.save(HTML_OUT)
        df.to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
        print(f"HTML con error: {HTML_OUT}")
        print(f"CSV (posible parcial): {CSV_OUT}")
        print(f"len(df)={len(df)}")
        return

    # Guardar CSV crudo consultado
    try:
        df.to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
    except Exception as e:
        logging.error(f"No fue posible guardar CSV: {e}")

    # Construir mapa base
    mapa = folium.Map(location=[3.4516, -76.5320], zoom_start=12)

    # Cargar GeoJSON rutas Cali (opcional)
    try:
        if os.path.exists(GEOJSON_RUTAS_CALI):
            with open(GEOJSON_RUTAS_CALI, "r", encoding="utf-8") as f:
                geojson_data = json.load(f)
            folium.GeoJson(geojson_data, name="Rutas Cali").add_to(mapa)
        else:
            logging.warning(f"GeoJSON no encontrado: {GEOJSON_RUTAS_CALI}")
    except Exception as e:
        logging.error(f"Error cargando GeoJSON: {e}")

    # Determinar el promotor en la posición 'promotor_num' por cantidad de muestras
    df_plot = df.copy()
    selected_pid = None
    selected_count = None
    if "id_autor" in df.columns:
        counts = None
        try:
            counts = df["id_autor"].dropna().astype(int).value_counts()
        except Exception as e:
            logging.warning(f"No fue posible calcular el ranking de promotores: {e}")
            counts = pd.Series(dtype=int)

        total_promotores = int(counts.shape[0]) if counts is not None else 0
        if total_promotores == 0:
            raise ValueError("No se encontraron asesores/promotores en el conjunto de datos para el rango solicitado.")

        if promotor_num < 1 or promotor_num > total_promotores:
            raise ValueError(
                f"promotor_num ({promotor_num}) es inválido: hay {total_promotores} asesores encontrados"
            )

        # Seleccionar el N-ésimo promotor (1-indexed)
        selected_pid = int(counts.index[promotor_num - 1])
        selected_count = int(counts.iloc[promotor_num - 1])
        df_plot = df[df["id_autor"].astype("Int64") == selected_pid].copy()

    ids_promotores = [selected_pid] if selected_pid is not None else [int(x) for x in df["id_autor"].dropna().unique().tolist() if str(x).strip()]
    nombre_map = {}
    try:
        fetched = obtener_promotores_por_ids([p for p in ids_promotores if p is not None]) or {}
        for pid in ids_promotores:
            raw_name = fetched.get(str(pid)) or fetched.get(pid)
            nombre_map[str(pid)] = _compactar_nombre(raw_name, str(pid))
    except Exception as e:
        logging.warning(f"Fallo obtener nombres promotores: {e}")
        for pid in ids_promotores:
            nombre_map[str(pid)] = f"id {pid}"

    # Colorear por asesor
    color_cache = {}
    for pid in ids_promotores:
        color_cache[str(pid)] = color_for_promotor(CENTROOPE, pid) if _HAS_COLOR_FN else color_for_promotor(CENTROOPE, pid)

    # Pintar puntos (solo del promotor top si fue identificado)
    for _, row in df_plot.iterrows():
        lat = row["_lat"]
        lon = row["_lon"]
        pid = row.get("id_autor")
        if pd.isna(lat) or pd.isna(lon) or pd.isna(pid):
            continue
        pid_str = str(int(pid))
        color_hex = color_cache.get(pid_str, "#999999")
        nombre_compacto = nombre_map.get(pid_str, f"id {pid_str}")
        barrio = row.get("barrio", "-")
        fecha_txt = row.get("fecha_evento")
        if pd.notna(fecha_txt):
            try:
                fecha_txt = pd.to_datetime(fecha_txt).strftime("%Y-%m-%d %H:%M")
            except Exception:
                fecha_txt = str(fecha_txt)
        popup_html = f"""
        <div style='font-size:12px;'>
          <b>Promotor:</b> {nombre_compacto}<br>
          <b>ID:</b> {pid_str}<br>
          <b>Barrio:</b> {barrio}<br>
          <b>Fecha:</b> {fecha_txt}
        </div>
        """
        folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=4,
            color=color_hex,
            fill=True,
            fillColor=color_hex,
            fillOpacity=0.8,
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(mapa)

    # Guardar HTML
    try:
        mapa.save(HTML_OUT)
    except Exception as e:
        logging.error(f"No fue posible guardar HTML: {e}")

    print(f"HTML generado: {HTML_OUT}")
    print(f"CSV generado: {CSV_OUT}")
    print(f"len(df)={len(df)}; mostrado={len(df_plot)}")
    if selected_pid is not None:
        print(f"Promotor seleccionado (rank={promotor_num}): id={selected_pid}, muestras={selected_count}")


if __name__ == "__main__":
    main()
