import numpy as np
import pandas as pd
from typing import Dict, Tuple, Iterable, List
from dataclasses import dataclass

from shapely.geometry import Point, MultiPoint, Polygon, mapping
from shapely.ops import unary_union, triangulate, transform as shp_transform
from sklearn.cluster import KMeans
from sklearn.neighbors import NearestNeighbors
from pyproj import Transformer

# =============================================================
# EPSG por centro de operación (CO)
# Basado en la configuración global CIUDADES (todos usan 32618 por ahora).
# =============================================================
EPSG_UTM_POR_CENTROOPE: dict[int, int] = {
    2: 32618,  # CALI
    3: 32618,  # MEDELLIN
    6: 32618,  # MANIZALES
    5: 32618,  # PEREIRA
    4: 32618,  # BOGOTA
    8: 32618,  # BARRANQUILLA
    7: 32618,  # BUCARAMANGA
}

_TRANSFORMERS_UTM: dict[int, Transformer] = {}


def get_transformer_utm(centroope: int | None) -> Transformer:
    """
    Retorna un Transformer WGS84 -> UTM para el centroope dado.
    Si centroope es None o no está en el diccionario, usa 32618 por defecto.
    """
    epsg = EPSG_UTM_POR_CENTROOPE.get(int(centroope) if centroope is not None else -1, 32618)
    if epsg in _TRANSFORMERS_UTM:
        return _TRANSFORMERS_UTM[epsg]
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    _TRANSFORMERS_UTM[epsg] = transformer
    return transformer

# =============================================================
# Constantes tomadas de la lógica M2 (solo geométricas)
# =============================================================
# Poda global y por subcluster (M2)
P_OUTLIER: float = 0.025
SUBK_P_OUTLIER: float = 0.0

# Selección de K para subclustering (M2)
SUBK_KMAX_ABS: int = 20
SUBK_KMAX_FRAC: float = 0.10
MIN_SUB_FRAC: float = 0.05

# Concave Hull (M2)
MIN_PTS_CONCAVE: int = 5
ALPHA_MODE: str = "fixed"   # "fixed" | "auto"
ALPHA_FIXED: float = 300.0
ALPHA_QNN_PCTL: int = 70
ALPHA_SCALE: float = 1.6
HOLE_MIN_FRAC: float = 0.02
HOLE_MIN_ABS: float = 1500.0
SMOOTHING_BUFFER_M: float = 80.0

# =============================================================
# Helpers internos compartidos
# =============================================================

def _resolver_lat_lon(df: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve un df con columnas '_lat' y '_lon' aseguradas, a partir de las columnas
    estándar usadas en el proyecto: lat, lon, latitud, longitud, coordenada_latitud, coordenada_longitud.
    (Lógica equivalente a la de los scripts M1/M2)
    """
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
    out = df.copy()
    out["_lat"] = pd.to_numeric(out[lat_col], errors="coerce")
    out["_lon"] = pd.to_numeric(out[lon_col], errors="coerce")
    out = out.dropna(subset=["_lat", "_lon"]).copy()
    return out


def _from_lonlat_to_utm(xy: np.ndarray, centroope: int | None) -> np.ndarray:
    """
    Recibe array Nx2 [lon, lat] en grados y devuelve Nx2 [x_m, y_m] en UTM.
    Usa un Transformer dependiente del centroope.
    """
    if xy.size == 0:
        return xy.reshape(0, 2)
    mask_valid = np.isfinite(xy).all(axis=1)
    xy_valid = xy[mask_valid]
    if xy_valid.size == 0:
        return xy.reshape(0, 2)
    transformer = get_transformer_utm(centroope)
    xs, ys = transformer.transform(
        xy_valid[:, 0].astype(float),
        xy_valid[:, 1].astype(float)
    )
    X = np.column_stack([xs, ys])
    return X


def _build_X_por_promotor(df_ll: pd.DataFrame, centroope: int | None) -> Dict[int, np.ndarray]:
    """
    A partir de un df con columnas 'id_autor', '_lat', '_lon',
    devuelve un dict {id_autor: np.ndarray de shape (n_i, 2) en metros}.
    Adjunta también columnas 'x_m', 'y_m' al DataFrame (no retornado).
    """
    if "id_autor" not in df_ll.columns:
        return {}
    # Array lon/lat → UTM con alineación por máscara válida
    lonlat = df_ll[["_lon", "_lat"]].to_numpy(float)
    mask_valid = np.isfinite(lonlat).all(axis=1)
    df_ll = df_ll.loc[df_ll.index[mask_valid]].copy()
    lonlat_valid = lonlat[mask_valid]
    X = _from_lonlat_to_utm(lonlat_valid, centroope)
    df_ll["x_m"] = X[:, 0]
    df_ll["y_m"] = X[:, 1]
    out: Dict[int, np.ndarray] = {}
    for pid, sub in df_ll.groupby("id_autor"):
        try:
            A = sub[["x_m", "y_m"]].to_numpy(float)
            if A.size == 0:
                continue
            out[int(pid)] = A
        except Exception:
            continue
    return out


def _podar_outliers_xy(X: np.ndarray, p: float) -> Tuple[np.ndarray, np.ndarray]:
    """Poda radial respecto al centroide; devuelve (X_filtrado, mask_keep)."""
    n = len(X)
    if p <= 0 or n < 5:
        return X, np.ones(n, dtype=bool)
    c = X.mean(axis=0)
    r = np.sqrt(((X - c) ** 2).sum(axis=1))
    thr = np.quantile(r, 1 - p)
    keep = r <= thr
    return X[keep], keep


def _convex_hull_geom_utm(X: np.ndarray):
    if len(X) == 0:
        return None
    try:
        return MultiPoint([(float(x), float(y)) for x, y in X]).convex_hull
    except Exception:
        return None


def _elbow_min_k(X: np.ndarray, kmax: int) -> Tuple[int, Iterable[float]]:
    """Selecciona k* por 'primer codo' sobre log(WCSS), evaluando k=1..kmax (kmax>=1)."""
    wcss = []
    for k in range(1, int(kmax) + 1):
        km = KMeans(n_clusters=k, n_init="auto", random_state=42)
        km.fit(X)
        wcss.append(float(km.inertia_))
    if len(wcss) == 1:
        return 1, wcss
    y = np.log(np.array(wcss))
    d1 = np.diff(y)
    d2 = np.diff(d1)
    idx_codo = int(np.argmax(d2)) + 2  # +2 por doble diff
    kstar = max(1, min(int(kmax), idx_codo))
    return kstar, wcss


def _alpha_auto_from_nn(X_utm: np.ndarray) -> float:
    n = len(X_utm)
    if n < 2:
        return max(5.0, float(ALPHA_FIXED))
    nn = NearestNeighbors(n_neighbors=min(2, n)).fit(X_utm)
    dists, _ = nn.kneighbors(X_utm)
    d1 = dists[:, 1]
    q = float(np.percentile(d1, ALPHA_QNN_PCTL)) if len(d1) else 0.0
    if q <= 0:
        return max(5.0, float(ALPHA_FIXED))
    alpha_m = float(ALPHA_SCALE * q)
    return max(5.0, alpha_m)


def _filter_small_holes(poly: Polygon, thr_area: float) -> Polygon:
    try:
        holes = []
        for ring in poly.interiors:
            try:
                a = Polygon(ring).area
                if a >= thr_area:
                    holes.append(ring)
            except Exception:
                continue
        return Polygon(poly.exterior, holes).buffer(0)
    except Exception:
        return poly.buffer(0)


def _concave_hull_from_points_utm(X_utm: np.ndarray, alpha_m: float):
    try:
        if len(X_utm) == 0:
            return None
        if len(X_utm) < MIN_PTS_CONCAVE:
            return MultiPoint([(float(x), float(y)) for x, y in X_utm]).convex_hull
        mpt = MultiPoint([(float(x), float(y)) for x, y in X_utm])
        tris = triangulate(mpt)
        keep = []
        a2 = float(alpha_m)
        for t in tris:
            xs, ys = t.exterior.coords.xy
            coords = list(zip(xs, ys))
            edges = [
                np.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
                for i in range(3)
            ]
            max_edge = max(edges)
            if max_edge <= a2:
                keep.append(t)
        if not keep:
            return mpt.convex_hull
        geom = unary_union(keep).buffer(0)
        # Filtrar agujeros pequeños
        try:
            total_area = float(geom.area)
            thr_area = max(HOLE_MIN_FRAC * total_area, float(HOLE_MIN_ABS))
            if getattr(geom, "geom_type", "") == "Polygon":
                geom = _filter_small_holes(geom, thr_area)
            elif getattr(geom, "geom_type", "") == "MultiPolygon":
                parts = []
                for p in geom.geoms:
                    parts.append(_filter_small_holes(p, thr_area))
                geom = unary_union(parts).buffer(0)
        except Exception:
            pass
        # Suavizado opcional de bordes
        if SMOOTHING_BUFFER_M and SMOOTHING_BUFFER_M > 0:
            try:
                geom = geom.buffer(SMOOTHING_BUFFER_M).buffer(-SMOOTHING_BUFFER_M)
            except Exception:
                pass
        return geom
    except Exception:
        return None

@dataclass
class SubclusterM2:
    id_subcluster: int
    area_m2: float
    perimetro_m: float
    n_puntos: int
    X_utm: np.ndarray
    geom_utm: object | None


def _subclusters_m2_detalle(X: np.ndarray) -> List[SubclusterM2]:
    """
    Recibe X en metros (puntos de un promotor) y aplica la lógica M2:
      - poda global
      - selección de k (codo)
      - filtrado de subclusters pequeños
      - concave hull / convex hull
    Devuelve lista de SubclusterM2 con métricas geométricas por subcluster válido.
    """
    n = len(X)
    if n < 3:
        return []
    # Poda global
    Xp, _ = _podar_outliers_xy(X, P_OUTLIER)
    n = len(Xp)
    if n == 0:
        return []
    # k* por elbow (permite k=1)
    kmax_eff = max(1, min(SUBK_KMAX_ABS, int(np.ceil(SUBK_KMAX_FRAC * n))))
    k_opt, _ = _elbow_min_k(Xp, kmax_eff)
    k_opt = int(max(1, k_opt))
    km = KMeans(n_clusters=k_opt, n_init="auto", random_state=42).fit(Xp)
    labels = km.labels_

    # Filtrar subclusters pequeños
    sub_ids = []
    for lab in range(int(k_opt)):
        size_lab = int((labels == lab).sum())
        if size_lab >= max(8, int(MIN_SUB_FRAC * n)):
            sub_ids.append(lab)
    if not sub_ids:
        sub_ids = [0]

    detalles: List[SubclusterM2] = []
    sc_idx = 0
    for lab in sub_ids:
        mask = (labels == lab)
        Xi = Xp[mask]
        # Poda adicional en subcluster
        Xi2, _ = _podar_outliers_xy(Xi, p=SUBK_P_OUTLIER)
        if len(Xi2) == 0:
            Xi2 = Xi
        # Geometría concave/convex
        if ALPHA_MODE == "fixed":
            alpha_m = float(ALPHA_FIXED)
            if alpha_m < 5.0:
                alpha_m = 5.0
        else:
            alpha_m = _alpha_auto_from_nn(Xi2)
        geom = _concave_hull_from_points_utm(Xi2, alpha_m)
        if geom is None:
            continue
        area = float(geom.area)
        perim = float(geom.length)
        detalles.append(SubclusterM2(
            id_subcluster=sc_idx,
            area_m2=area,
            perimetro_m=perim,
            n_puntos=int(len(Xi2)),
            X_utm=Xi2,
            geom_utm=geom,
        ))
        sc_idx += 1
    return detalles


def _geom_utm_to_lonlat(geom_utm, centroope: int | None):
    if geom_utm is None:
        return None
    transformer = get_transformer_utm(centroope)
    def proj_utm_to_ll(x, y, z=None):
        lon, lat = transformer.transform(x, y, direction="INVERSE")
        return (lon, lat)
    try:
        return shp_transform(proj_utm_to_ll, geom_utm)
    except Exception:
        return None

# =============================================================
# API pública
# =============================================================

def _ensure_id_autor(df: pd.DataFrame) -> pd.DataFrame:
    if "id_autor" not in df.columns:
        raise ValueError("El DataFrame debe incluir la columna 'id_autor'.")
    return df


def calcular_areas_por_promotor(
    df: pd.DataFrame,
    centroope: int | None,
) -> pd.DataFrame:
    """
    Calcula la huella de muestreo por promotor (M2) en m².

    - df: DataFrame con al menos columnas de lat/lon estándar y 'id_autor'.
    - centroope: código del centro de operación (2=CALI, 3=MEDELLIN, etc.).
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["id_autor", "area_total_m2", "puntos_usados_total", "puntos_totales"])

    _ensure_id_autor(df)
    df_ll = _resolver_lat_lon(df)
    if df_ll.empty:
        return pd.DataFrame(columns=["id_autor", "area_total_m2", "puntos_usados_total", "puntos_totales"])

    X_por_promotor = _build_X_por_promotor(df_ll, centroope)
    if not X_por_promotor:
        return pd.DataFrame(columns=["id_autor", "area_total_m2", "puntos_usados_total", "puntos_totales"])

    rows: List[dict] = []
    for pid, X in X_por_promotor.items():
        detalles = _subclusters_m2_detalle(X)
        if not detalles:
            area_total = 0.0
            usados = 0
        else:
            area_total = float(sum(sc.area_m2 for sc in detalles))
            usados = int(sum(sc.n_puntos for sc in detalles))
        # puntos_totales = registros originales de este id_autor (con lat/lon válidos)
        puntos_totales = int(len(df_ll[df_ll['id_autor'] == pid]))
        rows.append({
            "id_autor": int(pid),
            "area_total_m2": area_total,
            "puntos_usados_total": usados,
            "puntos_totales": puntos_totales,
        })

    return pd.DataFrame(rows, columns=["id_autor", "area_total_m2", "puntos_usados_total", "puntos_totales"]).drop_duplicates("id_autor")


def generar_geojson_subclusters_promotor(
    df_promotor: pd.DataFrame,
    centroope: int | None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Genera las métricas agregadas y el FeatureCollection GeoJSON
    de los subclusters M2 para un solo promotor.
    """
    if df_promotor is None or df_promotor.empty:
        return (
            pd.DataFrame(columns=["id_autor", "area_total_m2", "puntos_usados_total", "puntos_totales"]),
            {"type": "FeatureCollection", "features": []}
        )

    _ensure_id_autor(df_promotor)
    pids = [int(x) for x in pd.Series(df_promotor['id_autor']).dropna().astype(int).unique().tolist()]
    if len(pids) != 1:
        raise ValueError("df_promotor debe contener datos de un único id_autor.")
    pid = int(pids[0])

    df_ll = _resolver_lat_lon(df_promotor)
    puntos_totales = int(len(df_ll))
    lonlat = df_ll[["_lon", "_lat"]].to_numpy(float)
    mask_valid = np.isfinite(lonlat).all(axis=1)
    lonlat_valid = lonlat[mask_valid]
    X = _from_lonlat_to_utm(lonlat_valid, centroope)

    detalles = _subclusters_m2_detalle(X)
    if not detalles:
        df_metrics = pd.DataFrame([{
            "id_autor": pid,
            "area_total_m2": 0.0,
            "puntos_usados_total": 0,
            "puntos_totales": puntos_totales,
        }])
        return df_metrics, {"type": "FeatureCollection", "features": []}

    area_total = float(sum(sc.area_m2 for sc in detalles))
    usados_total = int(sum(sc.n_puntos for sc in detalles))
    df_metrics = pd.DataFrame([{
        "id_autor": pid,
        "area_total_m2": area_total,
        "puntos_usados_total": usados_total,
        "puntos_totales": puntos_totales,
    }])

    # GeoJSON FeatureCollection
    features: List[dict] = []
    for sc in detalles:
        geom_ll = _geom_utm_to_lonlat(sc.geom_utm, centroope)
        if geom_ll is None:
            continue
        feat = {
            "type": "Feature",
            "geometry": mapping(geom_ll),
            "properties": {
                "id_autor": int(pid),
                "id_subcluster": int(sc.id_subcluster),
                "area_m2": float(sc.area_m2),
                "perimetro_m": float(sc.perimetro_m),
                "n_puntos": int(sc.n_puntos),
            },
        }
        features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    return df_metrics, fc

# =============================================================
# Notas:
# - Este módulo calcula geometrías de subclusters tipo M2 en metros.
# - Provee:
#     * calcular_areas_por_promotor: resumen de área total (m²) por promotor.
#     * generar_geojson_subclusters_promotor: detalle por subcluster + GeoJSON para auditoría.

# =============================================================
# Wrappers específicos para el módulo de Muestras
# =============================================================

def areas_muestras_resumen(
    df: pd.DataFrame,
    centroope: int | None,
) -> pd.DataFrame:
    """
    Punto de entrada pensado para el módulo de Muestras en modo normal
    (llamado desde `mapa_muestras` a través de `preprocesamiento_muestras.metricas_areas_muestras`).

    - Recibe el mismo df que se usa para generar el mapa de muestras.
    - Internamente delega en `calcular_areas_por_promotor` **sin cambiar su lógica**.
    - Devuelve un DataFrame con las columnas:
        * id_autor
        * area_m2    (alias de area_total_m2)

    Este wrapper NO hace ningún filtrado adicional ni cálculos nuevos.
    """
    df_base = calcular_areas_por_promotor(df, centroope)
    if df_base is None or df_base.empty:
        return pd.DataFrame(columns=["id_autor", "area_m2"])

    out = (
        df_base[["id_autor", "area_total_m2"]]
        .copy()
        .rename(columns={"area_total_m2": "area_m2"})
    )
    # Aseguramos tipos limpios
    out["id_autor"] = pd.to_numeric(out["id_autor"], errors="coerce").astype("Int64")
    out["area_m2"] = pd.to_numeric(out["area_m2"], errors="coerce")
    out = out.dropna(subset=["id_autor"]).reset_index(drop=True)
    return out


# Alias explícito para auditoría de Muestras: retorna (df_metrics, feature_collection)
areas_muestras_auditoria = generar_geojson_subclusters_promotor
