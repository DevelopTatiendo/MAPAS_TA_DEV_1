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
import glob
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.metrics import davies_bouldin_score, calinski_harabasz_score
from pyproj import Transformer


# === Configuración multi-ciudad ===
CIUDADES = {
    "CALI": {
        "centroope": 2,
        "center": [3.4516, -76.5320],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "cali", "cuadrantes_rutas_cali.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "MEDELLIN": {
        "centroope": 3,
        "center": [6.2442, -75.5812],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "medellin", "cuadrantes_rutas_medellin.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "MANIZALES": {
        "centroope": 6,
        "center": [5.0672, -75.5174],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "manizales", "cuadrantes_rutas_manizales.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "PEREIRA": {
        "centroope": 5,
        "center": [4.8087, -75.6906],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "pereira", "cuadrantes_rutas_pereira.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "BOGOTA": {
        "centroope": 4,
        "center": [4.7110, -74.0721],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "bogota", "cuadrantes_rutas_bogota.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "BARRANQUILLA": {
        "centroope": 8,
        "center": [10.9720, -74.7962],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "barranquilla", "cuadrantes_rutas_barranquilla.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv"),
        "epsg_utm": "EPSG:32618",
    },
    "BUCARAMANGA": {
        "centroope": 7,
        "center": [7.1193, -73.1227],
        "geojson": os.path.join(BASE_DIR, "geojson", "rutas", "bucaramanga", "cuadrantes_rutas_bucaramanga.geojson"),
        "csv_rutas": os.path.join(BASE_DIR, "pre_procesamiento", "data", "BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"),
        "epsg_utm": "EPSG:32618",
    },
}

# Selección de ciudad (solo cambia esta línea para alternar)
CIUDAD = "PEREIRA"  # "MEDELLIN" | "MANIZALES" | "PEREIRA" | "BOGOTA" | "BARRANQUILLA" | "BUCARAMANGA" | "CALI"
if CIUDAD not in CIUDADES:
    raise ValueError(f"Ciudad inválida: {CIUDAD}. Disponibles: {list(CIUDADES)}")

# Derivados de la ciudad
_cfg = CIUDADES[CIUDAD]
CENTROOPE = _cfg["centroope"]

FECHA_INICIO = "2025-01-01"
FECHA_FIN    = "2025-12-31"
promotor_num = 4
MANUAL_k = False
K_target = 4

RESULTADOS_DIR = os.path.join(BASE_DIR, "Pruebas", "Resultados")
os.makedirs(RESULTADOS_DIR, exist_ok=True)
HTML_OUT        = os.path.join(RESULTADOS_DIR, f"muestras_simple_{CIUDAD}_2025.html")
CSV_OUT         = os.path.join(RESULTADOS_DIR, f"muestras_{CIUDAD}_2025.csv")
HTML_OUT_CLUST  = os.path.join(RESULTADOS_DIR, f"muestras_simple_{CIUDAD}_2025_clusters.html")
ELBOW_PNG       = os.path.join(RESULTADOS_DIR, "codo.png")
METRICS_CSV     = os.path.join(RESULTADOS_DIR, "metricas_clusters.csv")
METRICAS_K_CSV  = os.path.join(RESULTADOS_DIR, "metricas_por_k.csv")
TAU_ELBOW       = 0.12

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


# ==== Helpers de clustering y proyección (UTM por ciudad) ====
def _to_utm_xy(df_plot):
    """Convierte lon/lat → x/y (m) según EPSG UTM configurado por ciudad."""
    transformer = Transformer.from_crs("EPSG:4326", _cfg["epsg_utm"], always_xy=True)
    xs, ys = transformer.transform(df_plot["_lon"].astype(float).values,
                                   df_plot["_lat"].astype(float).values)
    X = np.column_stack([xs, ys])
    return X, transformer

def _from_utm_to_lonlat(centroids_xy, transformer):
    """Convierte centroides x/y (m) → lon/lat (para folium)."""
    lon, lat = transformer.transform(centroids_xy[:,0], centroids_xy[:,1], direction="INVERSE")
    return np.column_stack([lat, lon])  # folium: [lat, lon]

def _k_range(n_points):
    return list(range(2, max(2, min(12, n_points - 1)) + 1))

def _format_decimal_comma(df, decimals=3):
    """
    Convierte TODAS las columnas numéricas a string con coma decimal.
    NaN -> cadena vacía. No agrega separador de miles.
    """
    import numpy as _np
    import pandas as _pd

    out = df.copy()
    # detectar columnas numéricas
    num_cols = [c for c in out.columns if _np.issubdtype(out[c].dtype, _np.number)]
    fmt = "{:." + str(decimals) + "f}"
    for c in num_cols:
        out[c] = out[c].apply(
            lambda x: "" if _pd.isna(x) else fmt.format(float(x)).replace(".", ",")
        )
    return out

def _curva_elbow_y_metricas(X, resultados_dir, elbow_png, csv_por_k_path):
    """Calcula inertia (SSE) por K y métricas complementarias (Davies-Bouldin, Calinski-Harabasz).
    Guarda: codo.png y metricas_por_k.csv (siempre sobreescritos)."""
    ks = _k_range(X.shape[0])
    inertias, dbis, chis = [], [], []
    use_mini = X.shape[0] > 5000

    for k in ks:
        km = (MiniBatchKMeans(n_clusters=k, random_state=42, batch_size=2048, n_init="auto")
              if use_mini else
              KMeans(n_clusters=k, random_state=42, n_init="auto"))
        labels = km.fit_predict(X)
        inertias.append(km.inertia_)
        try:
            dbis.append(davies_bouldin_score(X, labels))
        except Exception:
            dbis.append(np.nan)
        try:
            chis.append(calinski_harabasz_score(X, labels))
        except Exception:
            chis.append(np.nan)

    fig = plt.figure()
    plt.plot(ks, inertias, marker="o")
    plt.xlabel("K"); plt.ylabel("SSE / Inertia"); plt.title("Gráfica de codo")
    fig.tight_layout(); fig.savefig(elbow_png, dpi=150); plt.close(fig)

    import pandas as _pd
    dfk = _pd.DataFrame({
        "K": ks,
        "inertia": inertias,
        "davies_bouldin": dbis,
        "calinski_harabasz": chis
    })
    # Forzar coma decimal
    dfk = _format_decimal_comma(dfk, decimals=3)
    dfk.to_csv(csv_por_k_path, index=False, sep=";", encoding="utf-8-sig")

    return ks, inertias

def _k_por_codo_threshold(ks, inertias, tau=0.12):
    """Umbral de mejora relativa: primer K donde la mejora cae por debajo de tau.
    Devuelve el K ANTERIOR a ese punto (el 'piso' antes de que deje de mejorar)."""
    rel = []
    for i in range(1, len(inertias)):
        prev, cur = inertias[i-1], inertias[i]
        rel.append((prev - cur) / max(prev, 1e-9))
    for i, r in enumerate(rel, start=1):
        if r < tau:
            return ks[i-1]
    return ks[-1]

def _k_por_curvatura(ks, inertias):
    """Heurística de curvatura discreta (segunda diferencia) sobre inertia normalizada."""
    import numpy as _np
    y = _np.asarray(inertias, dtype=float)
    if y.max() - y.min() > 0:
        y = (y - y.min()) / (y.max() - y.min())
    curv = _np.zeros_like(y)
    curv[1:-1] = y[:-2] - 2*y[1:-1] + y[2:]
    idx = int(_np.argmax(curv))
    return ks[idx]

def _elegir_k_elbow(ks, inertias, tau=0.12):
    """
    Regla final SOLO-CODO: prioriza el 'piso del codo'.
    Si piso (umbral) y curvatura discrepan, toma el MÁS ALTO (codo tardío).
    """
    k_tau  = _k_por_codo_threshold(ks, inertias, tau=tau)
    k_curv = _k_por_curvatura(ks, inertias)
    return max(k_tau, k_curv)

def _compute_metrics_csv(X, labels, km, transformer, out_csv_path):
    """Genera CSV con métricas globales y por cluster (sin silhouette, siempre sobreescribe)."""
    try:
        dbi = davies_bouldin_score(X, labels)
    except Exception:
        dbi = np.nan
    try:
        chi = calinski_harabasz_score(X, labels)
    except Exception:
        chi = np.nan

    rmse_global = float(np.sqrt(km.inertia_ / X.shape[0])) if X.shape[0] else np.nan  # m

    glob = {
        "scope": "global",
        "n_points": int(X.shape[0]),
        "k": int(km.n_clusters),
        "inertia_m2": float(km.inertia_),  # m^2
        "rmse_global_m": rmse_global,
        "davies_bouldin": float(dbi) if dbi==dbi else np.nan,
        "calinski_harabasz": float(chi) if chi==chi else np.nan
    }

    # Por cluster
    rows = [glob]
    centers = km.cluster_centers_
    # Distancias al centroide
    d2 = np.sum((X - centers[labels])**2, axis=1)  # distancia^2
    d  = np.sqrt(d2)

    for cl in sorted(np.unique(labels)):
        mask = (labels == cl)
        Xi = X[mask]
        di = d[mask]  # distancias punto-centroide en m
        ni = Xi.shape[0]
        pct = ni / X.shape[0] if X.shape[0] else np.nan

        sse = float(np.sum((Xi - centers[cl])**2))             # m^2
        mean_d = float(np.mean(di)) if ni else np.nan          # m
        med_d  = float(np.median(di)) if ni else np.nan        # m
        max_d  = float(np.max(di)) if ni else np.nan           # m

        # Nuevas métricas interpretables
        rmse_m = float(np.sqrt(sse / ni)) if ni else np.nan    # m
        p50 = float(np.percentile(di, 50)) if ni else np.nan    # m
        p80 = float(np.percentile(di, 80)) if ni else np.nan    # m
        p90 = float(np.percentile(di, 90)) if ni else np.nan    # m
        p95 = float(np.percentile(di, 95)) if ni else np.nan    # m

        stdx   = float(np.std(Xi[:,0])) if ni else np.nan
        stdy   = float(np.std(Xi[:,1])) if ni else np.nan
        bbox_w = float(np.max(Xi[:,0]) - np.min(Xi[:,0])) if ni else np.nan
        bbox_h = float(np.max(Xi[:,1]) - np.min(Xi[:,1])) if ni else np.nan
        bbox_diag = float(np.sqrt(bbox_w**2 + bbox_h**2)) if ni else np.nan

        # Centroide en lat/lon y WKT
        cent_ll = _from_utm_to_lonlat(centers[[cl]], transformer)[0]  # [lat, lon]
        cent_wkt = f"POINT({cent_ll[1]} {cent_ll[0]})"                # lon lat

        rows.append({
            "scope": "cluster",
            "cluster": int(cl),
            "n_points": int(ni),
            "pct_points": round(pct, 6),

            # Centroide en grados y UTM
            "centroid_lat": float(cent_ll[0]),
            "centroid_lon": float(cent_ll[1]),
            "centroid_x_m": float(centers[cl,0]),
            "centroid_y_m": float(centers[cl,1]),
            "centroid_wkt": cent_wkt,

            # Tamaño/formas
            "bbox_w_m": bbox_w,
            "bbox_h_m": bbox_h,
            "bbox_diag_m": bbox_diag,

            # Dispersión y errores
            "sse_cluster_m2": sse,
            "rmse_m": rmse_m,
            "mean_dist_m": mean_d,
            "median_dist_m": med_d,
            "p80_dist_m": p80,
            "p90_dist_m": p90,
            "p95_dist_m": p95,
            "max_dist_m": max_d,
            "std_x_m": stdx,
            "std_y_m": stdy,
        })

    import pandas as _pd
    dfm = _pd.DataFrame(rows)
    # columnas en km derivadas (opcional)
    for col in ["rmse_m","mean_dist_m","median_dist_m","p80_dist_m","p90_dist_m","p95_dist_m",
                "max_dist_m","bbox_w_m","bbox_h_m","bbox_diag_m","std_x_m","std_y_m"]:
        if col in dfm.columns:
            dfm[col.replace("_m","_km")] = dfm[col] / 1000.0
    # Forzar coma decimal en todo el DataFrame
    dfm = _format_decimal_comma(dfm, decimals=3)
    # Guardado Excel-friendly
    dfm.to_csv(out_csv_path, index=False, sep=";", encoding="utf-8-sig")

def _cluster_and_draw(df_plot, resultados_dir, mapa, cluster_palette):
    """Aplica KMeans sobre df_plot (promotor filtrado), pinta puntos por cluster y centroides negros."""
    n = len(df_plot)
    if n < 3:
        logging.warning("Muy pocos puntos para clustering (n<3). Se omite clustering.")
        return df_plot

    # 1) Proyección a metros
    X, transformer = _to_utm_xy(df_plot)

    # 2) Selección de K SOLO por codo (manual u automático)
    if MANUAL_k:
        valid_ks = _k_range(X.shape[0])
        k_req = int(K_target)
        k_clamped = max(valid_ks[0], min(valid_ks[-1], k_req))
        if k_clamped != k_req:
            logging.warning(f"K_target={k_req} fuera de rango válido {valid_ks}. Se ajusta a {k_clamped}.")
        k_best = k_clamped
        logging.info(f"K manual seleccionado (solo codo): {k_best}")
    else:
        ks, inertias = _curva_elbow_y_metricas(X, resultados_dir, ELBOW_PNG, METRICAS_K_CSV)
        k_best = _elegir_k_elbow(ks, inertias, tau=TAU_ELBOW)
        logging.info(f"K seleccionado (solo codo): {k_best}  |  piso por tau={TAU_ELBOW}")

    # 3) Fit final
    use_mini = X.shape[0] > 5000
    km = (MiniBatchKMeans(n_clusters=k_best, random_state=42, batch_size=2048, n_init="auto")
          if use_mini else
          KMeans(n_clusters=k_best, random_state=42, n_init="auto"))
    labels = km.fit_predict(X)
    df_plot = df_plot.copy()
    df_plot["cluster"] = labels

    # 4) Métricas → CSV (siempre último resultado)
    _compute_metrics_csv(X, labels, km, transformer, METRICS_CSV)

    # 5) Centroides en lat/lon
    cent_latlon = _from_utm_to_lonlat(km.cluster_centers_, transformer)  # shape (k, 2)

    # 6) Pintar puntos por cluster
    uniq = sorted(np.unique(labels).tolist())
    color_map = {cl: cluster_palette[cl % len(cluster_palette)] for cl in uniq}

    for _, row in df_plot.iterrows():
        lat = float(row["_lat"]) ; lon = float(row["_lon"]) ; cl = int(row["cluster"]) 
        c = color_map[cl]
        folium.CircleMarker(
            location=[lat, lon],
            radius=4, color=c, fill=True, fillColor=c, fillOpacity=0.85,
            popup=folium.Popup(f"<b>Cluster:</b> {cl}", max_width=200)
        ).add_to(mapa)

    # 7) Centroides en negro
    for cl, (lat, lon) in enumerate(cent_latlon):
        folium.CircleMarker(
            location=[float(lat), float(lon)],
            radius=7, color="black", fill=True, fillColor="black", fillOpacity=0.95,
            popup=folium.Popup(f"<b>Centroide</b> cluster {cl}", max_width=200)
        ).add_to(mapa)

    return df_plot, k_best


def main():
    logging.info(f"Iniciando generación de mapa de muestras {CIUDAD} 2025")
    # Consultar datos base
    if not os.path.exists(_cfg["csv_rutas"]):
        logging.warning(f"No existe archivo de coordenadas: {_cfg['csv_rutas']}. Continuando sin merge de barrios.")
    try:
        df = crear_df(CENTROOPE, FECHA_INICIO, FECHA_FIN, _cfg["csv_rutas"], promotores=None)
    except Exception as e:
        logging.error(f"Error al crear DF base: {e}")
        df = pd.DataFrame()

    if df.empty:
        logging.warning("DF vacío: se generará mapa sin puntos.")
        mapa = folium.Map(location=_cfg["center"], zoom_start=12)
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
        mapa = folium.Map(location=_cfg["center"], zoom_start=12)
        folium.Marker(location=_cfg["center"], popup="Sin columnas lat/lon válidas").add_to(mapa)
        mapa.save(HTML_OUT)
        df.to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
        print(f"HTML con error: {HTML_OUT}")
        print(f"CSV (posible parcial): {CSV_OUT}")
        print(f"len(df)={len(df)}")
        return

    # Limpiar salidas previas de clustering (mantener solo último resultado)
    for pat in ("codo*.png", "*_clusters.html", "metricas_clusters*.csv", "metricas_por_k*.csv"):
        for f in glob.glob(os.path.join(RESULTADOS_DIR, pat)):
            try:
                os.remove(f)
            except Exception:
                pass

    # Guardar CSV crudo consultado
    try:
        df.to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
    except Exception as e:
        logging.error(f"No fue posible guardar CSV: {e}")

    # Construir mapa base
    mapa = folium.Map(location=_cfg["center"], zoom_start=12)

    # Cargar GeoJSON de rutas de la ciudad (opcional)
    try:
        if os.path.exists(_cfg["geojson"]):
            with open(_cfg["geojson"], "r", encoding="utf-8") as f:
                geojson_data = json.load(f)
            folium.GeoJson(geojson_data, name=f"Rutas {CIUDAD.title()}").add_to(mapa)
        else:
            logging.warning(f"GeoJSON no encontrado: {_cfg['geojson']}")
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

    # Paleta categórica para clusters (independiente del color por asesor)
    CLUSTER_PALETTE = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b",
        "#e377c2", "#7f7f7f", "#bcbd22", "#17becf", "#393b79", "#637939"
    ]

    # Ejecutar clustering (añade df_plot['cluster'], pinta puntos y centroides)
    df_plot, k_chosen = _cluster_and_draw(df_plot, RESULTADOS_DIR, mapa, CLUSTER_PALETTE)

    # Actualizar CSV crudo para incluir 'cluster' (sobre-escritura, último resultado)
    try:
        df_out = df.copy()
        if 'cluster' in df_plot.columns:
            df_out.loc[df_plot.index, "cluster"] = df_plot["cluster"].values
        df_out.to_csv(CSV_OUT, index=False, sep=";", encoding="utf-8-sig")
    except Exception as e:
        logging.warning(f"No fue posible actualizar CSV con clusters: {e}")

    # Guardar HTML
    try:
        mapa.save(HTML_OUT)
        mapa.save(HTML_OUT_CLUST)
    except Exception as e:
        logging.error(f"No fue posible guardar HTML: {e}")

    print(f"HTML generado: {HTML_OUT}")
    print(f"HTML (clusters): {HTML_OUT_CLUST}")
    print(f"CSV generado: {CSV_OUT}")
    print(f"len(df)={len(df)}; mostrado={len(df_plot)}")
    if selected_pid is not None:
        print(f"Promotor seleccionado (rank={promotor_num}): id={selected_pid}, muestras={selected_count}")
    if 'k_chosen' in locals():
        print(f"K elegido (clusters): {k_chosen}")
    if os.path.exists(ELBOW_PNG):
        print(f"Codo: {ELBOW_PNG}")
    if os.path.exists(METRICS_CSV):
        print(f"Métricas: {METRICS_CSV}")
    if os.path.exists(METRICAS_K_CSV):
        print(f"Tabla por K: {METRICAS_K_CSV}")


if __name__ == "__main__":
    main()
