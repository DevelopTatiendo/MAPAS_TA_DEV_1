#!/usr/bin/env python3
"""
Pipeline completo: datos → clusters → seeds → mapas (ruta 3)
Voronoi V2 - Selección automática de seeds por métricas + auditoría

Este módulo implementa un pipeline completo para:
1. Cargar eventos de consultores desde BD
2. Filtrar por cuadrantes de ruta específica (CL_3_01, CL_3_02, etc.)
3. Aplicar clustering DBSCAN adaptativo por cuadrante
4. Calcular métricas de calidad por cluster
5. Seleccionar seeds automáticamente usando función objetivo
6. Generar mapas de visualización con auditoría

Autor: MAPAS_TA_DEV_1
Fecha: Septiembre 2025
"""

import os
import sys
import re
import math
import warnings
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.prepared import prep
from shapely.ops import unary_union
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics import silhouette_samples
import folium
from folium.plugins import MarkerCluster
import json
from dotenv import load_dotenv

# Importar funciones existentes del proyecto
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pre_procesamiento.preprocesamiento_consultores import eventos_con_coordenadas_por_ruta_y_rango

# Suprimir warnings de deprecation
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)

# ============================================================================
# CARGA DE CONFIGURACIÓN DE ENTORNO (.env)
# ============================================================================

def cargar_configuracion_entorno():
    """Carga robusta del archivo .env con validación completa."""
    # Resolver ruta absoluta del .env
    dotenv_path_abs = Path(__file__).resolve().parents[1] / ".env"
    
    if not dotenv_path_abs.exists():
        sys.exit(f"❌ Error: Archivo .env no encontrado en {dotenv_path_abs}")
    
    # Cargar variables de entorno
    load_dotenv(dotenv_path=dotenv_path_abs, override=False)
    
    # Variables obligatorias (DB_PORT es opcional)
    required_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if not value or value.strip() == "":
            missing_vars.append(var)
    
    if missing_vars:
        sys.exit(f"❌ Variables de entorno faltantes en .env: {', '.join(missing_vars)}")
    
    # Validación específica de DB_HOST
    db_host = os.getenv("DB_HOST").strip()
    if db_host == "." or db_host == "":
        sys.exit("❌ Error: DB_HOST no puede ser '.' o vacío. Usa TCP, p. ej. 127.0.0.1 o el host de Aurora")
    
    # Log de configuración (enmascarando contraseña)
    db_port = os.getenv("DB_PORT", "3306")  # Default si no está definido
    print(f"🔧 Configuración BD cargada:")
    print(f"   Host: {db_host}")
    print(f"   Puerto: {db_port}")
    print(f"   Base de datos: {os.getenv('DB_NAME')}")
    print(f"   Usuario: {os.getenv('DB_USER')}")
    print(f"   Contraseña: {'*' * len(os.getenv('DB_PASSWORD'))}")
    
    return True

def ping_db():
    """Prueba de conexión a la base de datos antes de consultar."""
    from pre_procesamiento.preprocesamiento_consultores import ping_db as ping_db_prepro
    return ping_db_prepro()

# Cargar configuración al inicio
cargar_configuracion_entorno()

# ============================================================================
# CONFIGURACIÓN GLOBAL - EDITABLES
# ============================================================================

# Modo de operación
MODO = "diagnostico"  # "diagnostico" o "pipeline_completo"

# Configuración de datos
CO = 2  # Centro de operaciones Cali
ID_RUTA = 9  # ID real de la ruta en BD
RUTA_NOMBRE = "3"  # Nombre de ruta para prefijo CL_3_

# Rango temporal
FECHA_INI = "2024-08-01 00:00:00"
FECHA_FIN = "2025-09-01 23:59:59"

# Rutas de archivos
CUADRANTES_PATH = "../geojson/cuadrantes_cali_rutas_consultores.geojson"
PRUEBAS_DIR = "../pruebas"

# Configuración geoespacial
PROJ_CRS = "EPSG:32618"  # UTM Zone 18N para Cali (metros)
RANDOM_STATE = 42

# ============================================================================
# CONFIGURACIÓN MODO DIAGNÓSTICO
# ============================================================================

# Configuración de fuente de datos
DATA_SOURCE = "bd"  # "csv" | "bd" (default "bd" en diagnóstico)
INPUT_CSV = "../pruebas/pts_ruta3_reales.csv"  # (o Parquet)

# Anchors de clúster (estables) - coordenadas métricas EPSG:32618
MANUAL_ANCHORS = {
    "CL_3_01": [
        (335437.993, 382487.017),
        (334840.853, 383453.152),
        (333811.975, 383505.382),
        (333239.418, 384049.795),
        (333156.695, 383166.243),
        (333702.172, 384408.940)
    ],
    "CL_3_02": []
}
R_MATCH = 200.0  # metros para match de anchors

# Clusters manuales a replicar (legacy - se reemplazará por anchors)
SELECTED_CLUSTERS_MAP = {
    "CL_3_01": [39, 13, 11, 1, 53, 26],
    "CL_3_02": []  # dejar lista vacía si aún no hay manuales
}

# Parámetros DBSCAN determinista (réplica manual)
EPS_FOR_REBUILD = 44.123  # metros
MS_FOR_REBUILD = 90  # min_samples (forzado en diagnóstico)
METRIC_FOR_REBUILD = "manhattan"

# Parámetros de clustering por cuadrante
KNN_K = 5  # K para calcular eps base
EPS_FACTORS = (0.9, 1.0, 1.1, 1.25, 1.5)  # Factores multiplicativos para eps
MIN_SAMPLES_RULE = "sqrt"  # Regla: max(5, round(sqrt(n)))
MIN_CLUSTER_SIZE_ABS = 5  # Tamaño mínimo absoluto de cluster válido

# Parámetros de selección de seeds (función objetivo)
SCORE_WEIGHTS = {
    'w_densidad': 0.35,     # Densidad de puntos por m²
    'w_tamano': 0.25,       # Tamaño del cluster (log n)
    'w_silhouette': 0.10,   # Silhouette score
    'w_compacidad': 0.05,   # Compacidad geométrica
    'w_separacion': 0.15,   # Separación entre clusters
    'w_borde': 0.05,        # Distancia al borde (ahora suma: favorece lejos del borde)
    'w_area': 0.10,         # Penalización anti-microclúster (suma: favorece áreas grandes)
    'w_estabilidad': 0.05   # Estabilidad (si no se calcula, 0)
}

LAMBDA_PENAL = 0.0  # En diagnóstico no seleccionamos K; sólo rankeamos
D_MIN_M = 200       # Distancia mínima entre seeds (metros)
R_M = 150          # Radio de cobertura para auditoría (metros)

# Filtro de área mínima para ranking en diagnóstico
AREA_MIN_DIAG = 10000  # m² - opcional, alternativa a w_area

# Exportar mapas HTML del Top-1 por cuadrante
EXPORTAR_TOP1_HTML = True  # Si False, no generar mapas HTML

# Performance y seguridad
MAX_SAMPLES_SILHOUETTE = 10000  # Muestreo si >10k puntos por cuadrante

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def log_info(emoji: str, mensaje: str) -> None:
    """Log con emoji y timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {emoji} {mensaje}")

def crear_directorio_pruebas():
    """Crear directorio de pruebas si no existe."""
    pruebas_path = Path(PRUEBAS_DIR)
    if not pruebas_path.exists():
        pruebas_path.mkdir(parents=True, exist_ok=True)
        log_info("📁", f"Directorio creado: {PRUEBAS_DIR}")
    else:
        log_info("📁", f"Directorio existe: {PRUEBAS_DIR}")

def cargar_datos_sinteticos():
    """Genera datos sintéticos para pruebas del pipeline."""
    np.random.seed(RANDOM_STATE)
    
    # Coordenadas aproximadas de Cali para cuadrantes CL_3_01, CL_3_02, CL_3_03
    cuadrantes_config = [
        {'codigo': 'CL_3_01', 'lat_center': 3.453, 'lon_center': -76.515, 'n_eventos': 120},
        {'codigo': 'CL_3_02', 'lat_center': 3.447, 'lon_center': -76.510, 'n_eventos': 80},
        {'codigo': 'CL_3_03', 'lat_center': 3.440, 'lon_center': -76.525, 'n_eventos': 60}
    ]
    
    eventos = []
    evento_id = 1
    
    for config in cuadrantes_config:
        # Generar eventos agrupados (clusters naturales)
        n_clusters = np.random.randint(2, 4)  # 2-3 clusters por cuadrante
        eventos_por_cluster = config['n_eventos'] // n_clusters
        
        for i in range(n_clusters):
            # Centro del cluster con offset del cuadrante
            cluster_lat = config['lat_center'] + np.random.normal(0, 0.008)
            cluster_lon = config['lon_center'] + np.random.normal(0, 0.008)
            
            # Generar eventos alrededor del centro del cluster
            for j in range(eventos_por_cluster):
                evento = {
                    'id': evento_id,
                    'lat': cluster_lat + np.random.normal(0, 0.003),
                    'lon': cluster_lon + np.random.normal(0, 0.003),
                    'fecha': pd.Timestamp('2024-08-15') + pd.Timedelta(days=np.random.randint(0, 30))
                }
                eventos.append(evento)
                evento_id += 1
        
        # Agregar algunos eventos de ruido
        n_ruido = config['n_eventos'] - (n_clusters * eventos_por_cluster)
        for i in range(n_ruido):
            evento = {
                'id': evento_id,
                'lat': config['lat_center'] + np.random.normal(0, 0.015),
                'lon': config['lon_center'] + np.random.normal(0, 0.015),
                'fecha': pd.Timestamp('2024-08-15') + pd.Timedelta(days=np.random.randint(0, 30))
            }
            eventos.append(evento)
            evento_id += 1
    
    df = pd.DataFrame(eventos)
    log_info("🧪", f"Generados {len(df)} eventos sintéticos para prueba")
    
    return df

def cargar_datos_configurados():
    """
    Carga datos según configuración DATA_SOURCE.
    
    Returns:
        pd.DataFrame: DataFrame con eventos (lat, lon, fecha, ...)
    """
    if DATA_SOURCE == "csv":
        return cargar_datos_desde_csv()
    elif DATA_SOURCE == "bd":
        return cargar_datos_desde_bd()
    else:
        raise ValueError(f"DATA_SOURCE inválido: {DATA_SOURCE}. Use 'csv' o 'bd'")

def cargar_datos_desde_csv():
    """
    Carga datos desde archivo CSV configurado.
    
    Returns:
        pd.DataFrame: DataFrame con eventos
    """
    csv_path = Path(INPUT_CSV)
    if not csv_path.exists():
        log_info("❌", f"Archivo CSV no encontrado: {INPUT_CSV}")
        return pd.DataFrame()
    
    try:
        # Detectar formato del archivo
        if csv_path.suffix.lower() == '.parquet':
            df = pd.read_parquet(csv_path)
        else:
            df = pd.read_csv(csv_path)
        
        log_info("📥", f"CSV cargado: {len(df):,} registros desde {INPUT_CSV}")
        
        # Validar columnas requeridas
        required_cols = ['lat', 'lon']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            log_info("❌", f"Columnas faltantes en CSV: {missing_cols}")
            return pd.DataFrame()
        
        # Renombrar fecha_evento -> fecha si existe
        if 'fecha_evento' in df.columns:
            df = df.rename(columns={'fecha_evento': 'fecha'})
        
        return df
        
    except Exception as e:
        log_info("❌", f"Error leyendo CSV: {e}")
        return pd.DataFrame()

def cargar_datos_desde_bd():
    """
    Carga datos desde base de datos usando preprocesamiento_consultores.
    En modo diagnóstico, si falla la BD, termina con sys.exit().
    
    Returns:
        pd.DataFrame: DataFrame con eventos
    """
    # Verificar conectividad antes de intentar la consulta
    if not ping_db():
        sys.exit("BD no disponible en diagnóstico")
    
    log_info("🔌", "Ping BD OK")
    
    try:
        # Usar directamente la función correcta del módulo
        df_eventos = eventos_con_coordenadas_por_ruta_y_rango(CO, ID_RUTA, FECHA_INI, FECHA_FIN)
        
        if df_eventos.empty:
            log_info("⚠️", "Consulta BD exitosa pero sin eventos en el rango especificado")
            # En diagnóstico continuamos para mostrar que no hay datos
            return df_eventos
        
        # Logs de validación y sanity check
        n_eventos = len(df_eventos)
        lat_min, lat_max = df_eventos['lat'].min(), df_eventos['lat'].max()
        lon_min, lon_max = df_eventos['lon'].min(), df_eventos['lon'].max()
        
        log_info("📥", f"Eventos cargados: {n_eventos:,}")
        log_info("📍", f"lat[{lat_min:.6f},{lat_max:.6f}], lon[{lon_min:.6f},{lon_max:.6f}]")
        
        # Validación de rangos de Cali
        if not (3.3 <= lat_min <= 3.6 and 3.3 <= lat_max <= 3.6):
            log_info("⚠️", "Latitudes fuera del rango esperado para Cali [3.3, 3.6]")
        if not (-76.6 <= lon_min <= -76.4 and -76.6 <= lon_max <= -76.4):
            log_info("⚠️", "Longitudes fuera del rango esperado para Cali [-76.6, -76.4]")
            
        return df_eventos
        
    except Exception as e:
        log_info("❌", f"Error en consulta BD: {e}")
        sys.exit(f"BD no disponible en diagnóstico: {e}")

def cargar_datos_sinteticos_diagnostico():
    """Genera datos sintéticos realistas para modo diagnóstico basados en coordenadas reales."""
    np.random.seed(RANDOM_STATE)
    
    # Coordenadas reales extraídas del GeoJSON de cuadrantes
    # CL_3_01: área aproximada basada en el polígono real
    cuadrantes_bounds = {
        'CL_3_01': {
            'lat_min': 3.459, 'lat_max': 3.478,
            'lon_min': -76.509, 'lon_max': -76.479,
            'n_clusters_target': 70, 'n_eventos': 6000
        },
        'CL_3_02': {
            'lat_min': 3.481, 'lat_max': 3.494, 
            'lon_min': -76.535, 'lon_max': -76.510,
            'n_clusters_target': 40, 'n_eventos': 3500
        }
    }
    
    eventos = []
    evento_id = 1
    
    for codigo, config in cuadrantes_bounds.items():
        # Calcular centros de área
        lat_center = (config['lat_min'] + config['lat_max']) / 2
        lon_center = (config['lon_min'] + config['lon_max']) / 2
        lat_range = config['lat_max'] - config['lat_min']
        lon_range = config['lon_max'] - config['lon_min']
        
        # Distribuir eventos en múltiples clusters pequeños
        eventos_por_cluster = max(MS_FOR_REBUILD + 5, 25)  # Clusters de ~20-30 eventos
        
        for i in range(config['n_clusters_target']):
            # Centro del cluster dentro del área del cuadrante
            cluster_lat = lat_center + np.random.uniform(-lat_range*0.4, lat_range*0.4)
            cluster_lon = lon_center + np.random.uniform(-lon_range*0.4, lon_range*0.4)
            
            # Asegurar que está dentro de bounds
            cluster_lat = np.clip(cluster_lat, config['lat_min'] + 0.001, config['lat_max'] - 0.001)
            cluster_lon = np.clip(cluster_lon, config['lon_min'] + 0.001, config['lon_max'] - 0.001)
            
            # Generar cluster compacto para que DBSCAN los detecte
            for j in range(eventos_por_cluster):
                # Dispersión pequeña para cluster cohesivo (~40m para que eps=44m funcione)
                evento = {
                    'id': evento_id,
                    'lat': cluster_lat + np.random.normal(0, 0.0004),  # ~40m de dispersión
                    'lon': cluster_lon + np.random.normal(0, 0.0004), 
                    'fecha': pd.Timestamp('2024-08-15') + pd.Timedelta(days=np.random.randint(0, 30))
                }
                # Asegurar dentro de bounds
                evento['lat'] = np.clip(evento['lat'], config['lat_min'], config['lat_max'])
                evento['lon'] = np.clip(evento['lon'], config['lon_min'], config['lon_max'])
                eventos.append(evento)
                evento_id += 1
        
        # Agregar eventos de ruido dispersos
        n_ruido = config['n_eventos'] - (config['n_clusters_target'] * eventos_por_cluster)
        for i in range(n_ruido):
            evento = {
                'id': evento_id,
                'lat': np.random.uniform(config['lat_min'], config['lat_max']),
                'lon': np.random.uniform(config['lon_min'], config['lon_max']),
                'fecha': pd.Timestamp('2024-08-15') + pd.Timedelta(days=np.random.randint(0, 30))
            }
            eventos.append(evento)
            evento_id += 1
    
    df = pd.DataFrame(eventos)
    log_info("🧪", f"Generados {len(df)} eventos sintéticos realistas para diagnóstico")
    
    return df

# ============================================================================
# FUNCIONES PRINCIPALES
# ============================================================================

def cargar_eventos_pre_consultores(co: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Carga eventos de consultores usando preprocesamiento_consultores.
    
    Args:
        co: Centro de operaciones
        id_ruta: ID de la ruta
        f_ini: Fecha inicio (formato 'YYYY-MM-DD HH:MM:SS')
        f_fin: Fecha fin (formato 'YYYY-MM-DD HH:MM:SS')
    
    Returns:
        DataFrame con eventos validados (lat, lon float; fecha_evento datetime)
    """
    log_info("🧭", f"Cargando eventos CO={co}, ruta={id_ruta}, rango={f_ini} a {f_fin}")
    
    try:
        df = eventos_con_coordenadas_por_ruta_y_rango(co, id_ruta, f_ini, f_fin)
        
        if df.empty:
            log_info("⚠️", "No se encontraron eventos en el rango especificado")
            return pd.DataFrame()
        
        # Enforce tipos de datos
        df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
        df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
        df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
        
        # Drop nulos
        df_inicial = len(df)
        df = df.dropna(subset=['lat', 'lon', 'fecha_evento'])
        
        log_info("📊", f"Eventos cargados: {len(df)} válidos de {df_inicial} totales")
        return df
        
    except Exception as e:
        log_info("⚠️", f"Error cargando eventos: {str(e)}")
        return pd.DataFrame()

def crear_cuadrantes_sinteticos():
    """Crear cuadrantes sintéticos para pruebas."""
    from shapely.geometry import Polygon
    
    # Crear cuadrantes rectangulares para Cali
    cuadrantes = []
    
    configs = [
        {'codigo': 'CL_3_01', 'lat_center': 3.453, 'lon_center': -76.515},
        {'codigo': 'CL_3_02', 'lat_center': 3.447, 'lon_center': -76.510},
        {'codigo': 'CL_3_03', 'lat_center': 3.440, 'lon_center': -76.525}
    ]
    
    for config in configs:
        # Crear polígono rectangular de ~1km x 1km
        delta = 0.005  # Aproximadamente 500m en cada dirección
        lat_c, lon_c = config['lat_center'], config['lon_center']
        
        polygon = Polygon([
            (lon_c - delta, lat_c - delta),  # SW
            (lon_c + delta, lat_c - delta),  # SE
            (lon_c + delta, lat_c + delta),  # NE
            (lon_c - delta, lat_c + delta),  # NW
            (lon_c - delta, lat_c - delta)   # Close
        ])
        
        cuadrantes.append({
            'codigo': config['codigo'],
            'geometry': polygon
        })
    
    # Crear GeoDataFrame
    gdf = gpd.GeoDataFrame(cuadrantes, crs='EPSG:4326')
    log_info("🧪", f"Creados {len(gdf)} cuadrantes sintéticos")
    
    return gdf

def detectar_y_normalizar_codigo(cuadrantes_path: str, usar_sinteticos: bool = True) -> gpd.GeoDataFrame:
    """
    Detecta campo identificador de cuadrantes y normaliza a 'codigo'.
    
    Args:
        cuadrantes_path: Ruta al archivo GeoJSON
        usar_sinteticos: Si True, usa cuadrantes sintéticos si falla la carga
    
    Returns:
        GeoDataFrame con campo 'codigo' normalizado (CRS=4326)
    """
    
    if usar_sinteticos:
        # Para pruebas, usar cuadrantes sintéticos
        log_info("🧭", "Usando cuadrantes sintéticos para prueba")
        return crear_cuadrantes_sinteticos()
    
    log_info("🧭", f"Cargando cuadrantes desde: {cuadrantes_path}")
    
    try:
        gdf = gpd.read_file(cuadrantes_path)
        
        if gdf.empty:
            raise ValueError("El archivo de cuadrantes está vacío")
        
        # Detectar campo identificador
        posibles_campos = ['codigo', 'CODIGO', 'NOMBRE', 'nombre', 'id', 'ID']
        campo_codigo = None
        
        for campo in posibles_campos:
            if campo in gdf.columns:
                campo_codigo = campo
                break
        
        if campo_codigo is None:
            raise ValueError(f"No se encontró campo identificador en: {gdf.columns.tolist()}")
        
        # Normalizar a 'codigo'
        if campo_codigo != 'codigo':
            gdf = gdf.rename(columns={campo_codigo: 'codigo'})
        
        # Asegurar tipo string
        gdf['codigo'] = gdf['codigo'].astype(str)
        
        # Asegurar CRS=4326
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326')
        elif gdf.crs != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        
        log_info("📊", f"Cuadrantes cargados: {len(gdf)} features, campo '{campo_codigo}' → 'codigo'")
        return gdf
        
    except Exception as e:
        log_info("⚠️", f"Error cargando cuadrantes: {str(e)}")
        if usar_sinteticos:
            log_info("🧭", "Fallback: usando cuadrantes sintéticos")
            return crear_cuadrantes_sinteticos()
        return gpd.GeoDataFrame()

def filtrar_cuadrantes_ruta(gdf_cuad: gpd.GeoDataFrame, ruta_nombre: str) -> gpd.GeoDataFrame:
    """
    Filtra cuadrantes por ruta específica usando patrón CL_{ruta_nombre}_.
    
    Args:
        gdf_cuad: GeoDataFrame de cuadrantes
        ruta_nombre: Nombre de la ruta (ej: "3")
    
    Returns:
        GeoDataFrame filtrado solo con cuadrantes de la ruta
    """
    log_info("🧭", f"Filtrando cuadrantes para ruta '{ruta_nombre}'")
    
    if gdf_cuad.empty:
        return gdf_cuad
    
    try:
        # Patrón: CL_{ruta_nombre}_XX (ej: CL_3_01, CL_3_02)
        patron = f"^CL_{ruta_nombre}_\\d{{2}}$"
        
        # Filtrar por patrón
        mask = gdf_cuad['codigo'].str.match(patron, na=False)
        gdf_ruta = gdf_cuad[mask].copy()
        
        if gdf_ruta.empty:
            log_info("⚠️", f"No se encontraron cuadrantes con patrón '{patron}'")
            # Mostrar códigos disponibles para debug
            codigos_disponibles = gdf_cuad['codigo'].unique()[:10]  # Primeros 10
            log_info("📊", f"Códigos disponibles (muestra): {codigos_disponibles}")
            return gpd.GeoDataFrame()
        
        codigos_encontrados = sorted(gdf_ruta['codigo'].unique())
        log_info("📊", f"Cuadrantes de ruta {ruta_nombre}: {len(gdf_ruta)} features")
        log_info("📊", f"Códigos: {codigos_encontrados}")
        
        return gdf_ruta
        
    except Exception as e:
        log_info("⚠️", f"Error filtrando cuadrantes: {str(e)}")
        return gpd.GeoDataFrame()

def recortar_eventos_por_cuadrantes(df: pd.DataFrame, gdf_cuad_ruta: gpd.GeoDataFrame) -> tuple:
    """
    Filtra eventos que están dentro de los cuadrantes de la ruta.
    
    Args:
        df: DataFrame de eventos con lat, lon
        gdf_cuad_ruta: GeoDataFrame de cuadrantes de la ruta
    
    Returns:
        Tupla (df_filtrado, gdf_cuad_ruta) donde df_filtrado tiene eventos dentro de cuadrantes
    """
    log_info("🧭", f"Recortando {len(df)} eventos por cuadrantes")
    
    if df.empty or gdf_cuad_ruta.empty:
        log_info("⚠️", "Datos vacíos para recorte")
        return pd.DataFrame(), gdf_cuad_ruta
    
    try:
        # Crear geometrías de puntos
        geometry = [Point(lon, lat) for lon, lat in zip(df['lon'], df['lat'])]
        gdf_eventos = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
        
        # Unión de todos los polígonos de la ruta
        union_cuadrantes = unary_union(gdf_cuad_ruta.geometry)
        prepared_union = prep(union_cuadrantes)
        
        # Filtrar puntos dentro de la unión (usando covers para incluir bordes)
        mask_dentro = gdf_eventos.geometry.apply(lambda geom: prepared_union.covers(geom))
        df_filtrado = df[mask_dentro].copy()
        
        log_info("📊", f"Eventos dentro de cuadrantes: {len(df_filtrado)} de {len(df)}")
        
        return df_filtrado, gdf_cuad_ruta
        
    except Exception as e:
        log_info("⚠️", f"Error en recorte espacial: {str(e)}")
        return pd.DataFrame(), gdf_cuad_ruta

def asignar_cuadrantes_a_eventos(df: pd.DataFrame, gdf_cuad_ruta: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Asigna código de cuadrante a cada evento.
    
    Args:
        df: DataFrame de eventos filtrados
        gdf_cuad_ruta: GeoDataFrame de cuadrantes
    
    Returns:
        DataFrame con columna 'codigo' asignada
    """
    log_info("🧭", "Asignando códigos de cuadrante a eventos")
    
    if df.empty or gdf_cuad_ruta.empty:
        return df
    
    try:
        # Crear GeoDataFrame de eventos
        geometry = [Point(lon, lat) for lon, lat in zip(df['lon'], df['lat'])]
        gdf_eventos = gpd.GeoDataFrame(df, geometry=geometry, crs='EPSG:4326')
        
        # Spatial join para asignar código
        gdf_con_codigo = gpd.sjoin(gdf_eventos, gdf_cuad_ruta[['codigo', 'geometry']], 
                                  how='left', predicate='within')
        
        # Mantener solo las columnas originales + codigo, eliminando duplicados
        columnas_originales = df.columns.tolist()
        df_resultado = gdf_con_codigo[columnas_originales + ['codigo']].copy()
        
        # Drop eventos sin código asignado
        df_resultado = df_resultado.dropna(subset=['codigo'])
        
        # Eliminar duplicados manteniendo el primer match
        df_resultado = df_resultado.drop_duplicates(subset=columnas_originales, keep='first')
        
        log_info("📊", f"Eventos con código asignado: {len(df_resultado)}")
        
        # Mostrar distribución por cuadrante
        distribucion = df_resultado['codigo'].value_counts().sort_index()
        for codigo, count in distribucion.items():
            log_info("📊", f"  {codigo}: {count} eventos")
        
        return df_resultado
        
    except Exception as e:
        log_info("⚠️", f"Error asignando códigos: {str(e)}")
        return df

def calcular_eps_adaptativo(df_cuad: pd.DataFrame, k: int = KNN_K) -> float:
    """
    Calcula eps adaptativo usando k-NN distance.
    
    Args:
        df_cuad: DataFrame de eventos de un cuadrante
        k: Número de vecinos más cercanos
    
    Returns:
        Valor eps en metros (proyección métrica)
    """
    if len(df_cuad) < k + 1:
        return 100.0  # Default para pocos puntos
    
    try:
        # Convertir a coordenadas métricas
        coords_metricas = convertir_a_metricas(df_cuad[['lat', 'lon']].values)
        
        # k-NN
        nbrs = NearestNeighbors(n_neighbors=k+1).fit(coords_metricas)
        distances, _ = nbrs.kneighbors(coords_metricas)
        
        # Tomar k-ésima distancia (excluyendo el punto mismo)
        k_distances = distances[:, k]
        eps_base = np.median(k_distances)
        
        return max(50.0, eps_base)  # Mínimo 50m
        
    except Exception:
        return 100.0

def convertir_a_metricas(coords_wgs84: np.ndarray) -> np.ndarray:
    """
    Convierte coordenadas WGS84 a métricas usando proyección simple.
    
    Args:
        coords_wgs84: Array de coordenadas [[lat, lon], ...]
    
    Returns:
        Array de coordenadas métricas [[x, y], ...]
    """
    # Conversión aproximada para Cali (lat ~3.4°)
    # 1 grado lat ≈ 111320 m
    # 1 grado lon ≈ 111320 * cos(lat) ≈ 111200 m
    
    lats, lons = coords_wgs84[:, 0], coords_wgs84[:, 1]
    
    # Usar punto de referencia cercano a Cali
    lat_ref, lon_ref = 3.4, -76.5
    
    x = (lons - lon_ref) * 111200  # metros este
    y = (lats - lat_ref) * 111320  # metros norte
    
    return np.column_stack([x, y])

def clusterizar_por_cuadrante_dbscan(df_filtrado: pd.DataFrame, proj_crs: str, knn_k: int, 
                                   eps_factors: tuple, min_samples_rule: str, 
                                   min_cluster_size_abs: int, max_samples_silhouette: int) -> tuple:
    """
    Clustering DBSCAN adaptativo por cuadrante con selección basada en silhouette.
    
    Args:
        df_filtrado: DataFrame con eventos filtrados por cuadrantes
        proj_crs: Sistema de coordenadas proyectado (métrico)
        knn_k: K para calcular eps base usando k-NN
        eps_factors: Factores multiplicativos para probar diferentes eps
        min_samples_rule: Regla para min_samples ("sqrt" -> max(5, round(sqrt(n))))
        min_cluster_size_abs: Tamaño mínimo absoluto de cluster válido
        max_samples_silhouette: Máximo de puntos para cálculo de silhouette
    
    Returns:
        Tupla (df_lab, resumen_clusters):
        - df_lab: DataFrame original + columna cluster_id (-1=ruido, ≥0=cluster)
        - resumen_clusters: DataFrame con resumen por (codigo, cluster_id)
    """
    log_info("🧭", "Clustering DBSCAN por cuadrante con selección por silhouette")
    
    if df_filtrado.empty:
        return df_filtrado, pd.DataFrame()
    
    df_lab = df_filtrado.copy()
    df_lab['cluster_id'] = -1  # Default: ruido
    resumen_data = []
    
    for codigo in df_filtrado['codigo'].unique():
        log_info("📊", f"Clustering en cuadrante {codigo}")
        
        mask_cuad = df_filtrado['codigo'] == codigo
        df_cuad = df_filtrado[mask_cuad].copy()
        
        if len(df_cuad) < min_cluster_size_abs:
            log_info("⚠️", f"  Pocos puntos ({len(df_cuad)}) - omitir clustering")
            continue
        
        # Proyectar a coordenadas métricas
        gdf_cuad = gpd.GeoDataFrame(df_cuad, 
                                   geometry=[Point(lon, lat) for lon, lat in zip(df_cuad['lon'], df_cuad['lat'])], 
                                   crs='EPSG:4326')
        gdf_cuad = gdf_cuad.to_crs(proj_crs)
        
        coords_metricas = np.column_stack([gdf_cuad.geometry.x, gdf_cuad.geometry.y])
        
        # Calcular eps base usando k-NN
        if len(df_cuad) >= knn_k + 1:
            nbrs = NearestNeighbors(n_neighbors=knn_k+1).fit(coords_metricas)
            distances, _ = nbrs.kneighbors(coords_metricas)
            eps_base = np.median(distances[:, knn_k])  # k-ésima distancia
        else:
            eps_base = 100.0  # Default para pocos puntos
        
        # Calcular min_samples según regla
        if min_samples_rule == "sqrt":
            min_samples = max(5, round(math.sqrt(len(df_cuad))))
        else:
            min_samples = 5  # Default
        
        mejor_config = None
        mejor_silhouette = -2  # Silhouette está en [-1, 1]
        
        # Probar diferentes factores eps
        for factor in eps_factors:
            eps_actual = eps_base * factor
            
            dbscan = DBSCAN(eps=eps_actual, min_samples=min_samples, n_jobs=-1)
            labels = dbscan.fit_predict(coords_metricas)
            
            # Filtrar clusters pequeños
            unique_labels, counts = np.unique(labels, return_counts=True)
            for label, count in zip(unique_labels, counts):
                if label != -1 and count < min_cluster_size_abs:
                    labels[labels == label] = -1
            
            n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
            
            if n_clusters >= 1:
                # Calcular silhouette L1 si hay suficientes clusters
                silhouette_score = 0
                
                if n_clusters >= 2:
                    try:
                        # Muestrear si hay demasiados puntos
                        if len(coords_metricas) > max_samples_silhouette:
                            sample_idx = np.random.choice(len(coords_metricas), max_samples_silhouette, replace=False)
                            coords_sample = coords_metricas[sample_idx]
                            labels_sample = labels[sample_idx]
                        else:
                            coords_sample = coords_metricas
                            labels_sample = labels
                        
                        # Solo puntos clusterizados para silhouette
                        mask_clustered = labels_sample >= 0
                        if np.sum(mask_clustered) >= 2:
                            coords_clustered = coords_sample[mask_clustered]
                            labels_clustered = labels_sample[mask_clustered]
                            
                            if len(np.unique(labels_clustered)) >= 2:
                                silhouette_scores = silhouette_samples(coords_clustered, labels_clustered, 
                                                                     metric='manhattan')
                                silhouette_score = np.mean(silhouette_scores)
                    except:
                        silhouette_score = 0
                
                # Guardar si es mejor
                if silhouette_score > mejor_silhouette:
                    mejor_silhouette = silhouette_score
                    mejor_config = {
                        'labels': labels.copy(),
                        'eps': eps_actual,
                        'min_samples': min_samples,
                        'n_clusters': n_clusters,
                        'silhouette': silhouette_score
                    }
        
        # Aplicar mejor configuración
        if mejor_config is not None:
            labels_finales = mejor_config['labels']
            
            # Renumerar clusters válidos consecutivamente
            valid_labels = sorted([l for l in np.unique(labels_finales) if l != -1])
            label_map = {old_label: new_label for new_label, old_label in enumerate(valid_labels)}
            
            for old_label, new_label in label_map.items():
                labels_finales[labels_finales == old_label] = new_label
            
            # Asignar al DataFrame resultado
            indices_cuad = df_filtrado.index[mask_cuad].tolist()
            if len(indices_cuad) == len(labels_finales):
                df_lab.loc[indices_cuad, 'cluster_id'] = labels_finales
            
            # Crear resumen por cluster
            for cluster_id in sorted(np.unique(labels_finales)):
                if cluster_id >= 0:  # Solo clusters válidos
                    n_puntos = np.sum(labels_finales == cluster_id)
                    resumen_data.append({
                        'codigo': codigo,
                        'cluster_id': cluster_id,
                        'n': n_puntos,
                        'eps': mejor_config['eps'],
                        'min_samples': mejor_config['min_samples']
                    })
            
            n_clusters_final = mejor_config['n_clusters']
            n_noise_final = np.sum(labels_finales == -1)
            
            log_info("✅", f"  {codigo}: {n_clusters_final} clusters, {n_noise_final} ruido, "
                          f"eps={mejor_config['eps']:.1f}m, silhouette={mejor_silhouette:.3f}")
        else:
            log_info("⚠️", f"  {codigo}: No se pudo generar clustering válido")
    
    resumen_clusters = pd.DataFrame(resumen_data)
    
    # Estadísticas generales
    total_clusters = len(df_lab[df_lab['cluster_id'] >= 0])
    total_ruido = len(df_lab[df_lab['cluster_id'] == -1])
    
    log_info("📊", f"Clustering completado: {total_clusters} puntos clusterizados, {total_ruido} ruido")
    
    return df_lab, resumen_clusters

def calcular_metricas_clusters(df_lab: pd.DataFrame, gdf_cuad_ruta: gpd.GeoDataFrame, 
                              proj_crs: str, usar_alpha_shape: bool = True, 
                              alpha_km: float = 0.5) -> pd.DataFrame:
    """
    Calcula métricas detalladas por cluster usando alpha-shapes y medoids L1.
    
    Args:
        df_lab: DataFrame con columnas codigo, cluster_id, lat, lon
        gdf_cuad_ruta: GeoDataFrame con cuadrantes de la ruta
        proj_crs: Sistema de coordenadas proyectado para cálculos métricos
        usar_alpha_shape: Si usar alpha-shape (concave hull) vs convex hull
        alpha_km: Parámetro alpha en kilómetros para alpha-shape
    
    Returns:
        DataFrame con métricas por (codigo, cluster_id≥0)
    """
    log_info("🧭", "Calculando métricas detalladas de clusters")
    
    if df_lab.empty:
        return pd.DataFrame()
    
    metricas = []
    
    for codigo in df_lab['codigo'].unique():
        log_info("📊", f"Métricas para {codigo}")
        
        df_cuad = df_lab[df_lab['codigo'] == codigo].copy()
        clusters_validos = df_cuad[df_cuad['cluster_id'] >= 0]['cluster_id'].unique()
        
        if len(clusters_validos) == 0:
            continue
        
        # Proyectar puntos a coordenadas métricas
        gdf_cuad = gpd.GeoDataFrame(df_cuad, 
                                   geometry=[Point(lon, lat) for lon, lat in zip(df_cuad['lon'], df_cuad['lat'])], 
                                   crs='EPSG:4326')
        gdf_cuad = gdf_cuad.to_crs(proj_crs)
        
        coords_metricas = np.column_stack([gdf_cuad.geometry.x, gdf_cuad.geometry.y])
        df_cuad['x_m'] = coords_metricas[:, 0]
        df_cuad['y_m'] = coords_metricas[:, 1]
        
        # Obtener geometría del cuadrante para distancia al borde
        geom_cuadrante = None
        if codigo in gdf_cuad_ruta['codigo'].values:
            geom_cuad_orig = gdf_cuad_ruta[gdf_cuad_ruta['codigo'] == codigo].geometry.iloc[0]
            # Proyectar cuadrante a métrico
            gdf_temp = gpd.GeoDataFrame([1], geometry=[geom_cuad_orig], crs='EPSG:4326')
            gdf_temp = gdf_temp.to_crs(proj_crs)
            geom_cuadrante = gdf_temp.geometry.iloc[0]
        
        for cluster_id in clusters_validos:
            df_cluster = df_cuad[df_cuad['cluster_id'] == cluster_id].copy()
            n = len(df_cluster)
            
            if n < 3:  # Mínimo para formar polígono
                continue
            
            # Medoid L1 (punto que minimiza suma de distancias Manhattan)
            cluster_coords = df_cluster[['x_m', 'y_m']].values
            
            # Buscar medoid: punto que minimiza suma de distancias L1
            min_sum_dist = float('inf')
            medoid_idx = 0
            
            for i, point in enumerate(cluster_coords):
                sum_dist = np.sum(np.abs(cluster_coords - point).sum(axis=1))
                if sum_dist < min_sum_dist:
                    min_sum_dist = sum_dist
                    medoid_idx = i
            
            medoid_x_m = cluster_coords[medoid_idx][0]
            medoid_y_m = cluster_coords[medoid_idx][1]
            seed_lat = df_cluster.iloc[medoid_idx]['lat']
            seed_lon = df_cluster.iloc[medoid_idx]['lon']
            
            # Calcular área y perímetro
            try:
                if usar_alpha_shape and n >= 4:
                    # Intentar alpha-shape (requiere alpha_shape library o implementación manual)
                    try:
                        # Fallback a convex hull por simplicidad
                        from scipy.spatial import ConvexHull
                        hull = ConvexHull(cluster_coords)
                        area_m2 = hull.volume  # En 2D, volume = area
                        # Perímetro
                        hull_points = cluster_coords[hull.vertices]
                        perimetro_m = np.sum([np.linalg.norm(hull_points[i] - hull_points[(i+1) % len(hull_points)])
                                             for i in range(len(hull_points))])
                    except:
                        # Fallback simple
                        x_range = cluster_coords[:, 0].max() - cluster_coords[:, 0].min()
                        y_range = cluster_coords[:, 1].max() - cluster_coords[:, 1].min()
                        area_m2 = x_range * y_range
                        perimetro_m = 2 * (x_range + y_range)
                else:
                    # Convex hull
                    from scipy.spatial import ConvexHull
                    hull = ConvexHull(cluster_coords)
                    area_m2 = hull.volume
                    hull_points = cluster_coords[hull.vertices]
                    perimetro_m = np.sum([np.linalg.norm(hull_points[i] - hull_points[(i+1) % len(hull_points)])
                                         for i in range(len(hull_points))])
            except:
                # Fallback: aproximar como círculo
                center = cluster_coords.mean(axis=0)
                distances = np.linalg.norm(cluster_coords - center, axis=1)
                radio_aprox = np.mean(distances)
                area_m2 = math.pi * radio_aprox ** 2
                perimetro_m = 2 * math.pi * radio_aprox
            
            # Métricas básicas
            densidad_pts_m2 = n / max(area_m2, 1.0)
            compacidad = 4 * math.pi * area_m2 / (perimetro_m ** 2) if perimetro_m > 0 else 0
            compacidad = min(1.0, max(0.0, compacidad))  # Normalizar a [0,1]
            
            # Distancia al borde del cuadrante
            dist_borde_m = np.nan
            if geom_cuadrante is not None:
                try:
                    punto_medoid = Point(medoid_x_m, medoid_y_m)
                    dist_borde_m = punto_medoid.distance(geom_cuadrante.boundary)
                except:
                    pass
            
            # Silhouette L1 (solo si hay múltiples clusters válidos)
            silhouette_l1 = np.nan
            if len(clusters_validos) >= 2:
                try:
                    X_cuad = df_cuad[['x_m', 'y_m']].values
                    labels_cuad = df_cuad['cluster_id'].values
                    
                    # Solo puntos clusterizados
                    mask_clustered = labels_cuad >= 0
                    if np.sum(mask_clustered) >= 2:
                        X_clustered = X_cuad[mask_clustered]
                        labels_clustered = labels_cuad[mask_clustered]
                        
                        if len(np.unique(labels_clustered)) >= 2:
                            silhouette_scores = silhouette_samples(X_clustered, labels_clustered, 
                                                                 metric='manhattan')
                            cluster_mask = labels_clustered == cluster_id
                            if np.sum(cluster_mask) > 0:
                                silhouette_l1 = np.mean(silhouette_scores[cluster_mask])
                except:
                    pass
            
            # Separación global (distancia L1 al medoid más cercano)
            sep_global_m = np.nan
            if len(clusters_validos) >= 2:
                otros_clusters = [c for c in clusters_validos if c != cluster_id]
                min_dist = float('inf')
                
                for otro_cluster in otros_clusters:
                    df_otro = df_cuad[df_cuad['cluster_id'] == otro_cluster]
                    if len(df_otro) > 0:
                        # Calcular medoid del otro cluster
                        otros_coords = df_otro[['x_m', 'y_m']].values
                        min_sum_dist_otro = float('inf')
                        otro_medoid_idx = 0
                        
                        for i, point in enumerate(otros_coords):
                            sum_dist = np.sum(np.abs(otros_coords - point).sum(axis=1))
                            if sum_dist < min_sum_dist_otro:
                                min_sum_dist_otro = sum_dist
                                otro_medoid_idx = i
                        
                        otro_medoid = otros_coords[otro_medoid_idx]
                        
                        # Distancia L1 entre medoids
                        dist_l1 = abs(medoid_x_m - otro_medoid[0]) + abs(medoid_y_m - otro_medoid[1])
                        min_dist = min(min_dist, dist_l1)
                
                if min_dist != float('inf'):
                    sep_global_m = min_dist
            
            # Agregar métrica
            metricas.append({
                'codigo': codigo,
                'cluster_id': cluster_id,
                'n': n,
                'area_m2': area_m2,
                'perimetro_m': perimetro_m,
                'densidad_pts_m2': densidad_pts_m2,
                'compacidad': compacidad,
                'medoid_x_m': medoid_x_m,
                'medoid_y_m': medoid_y_m,
                'seed_lat': seed_lat,
                'seed_lon': seed_lon,
                'dist_borde_m': dist_borde_m,
                'silhouette_l1': silhouette_l1,
                'sep_global_m': sep_global_m
            })
    
    df_metricas = pd.DataFrame(metricas)
    
    if not df_metricas.empty:
        log_info("✅", f"Métricas calculadas para {len(df_metricas)} clusters")
        log_info("📊", f"Clusters por cuadrante: {df_metricas.groupby('codigo').size().to_dict()}")
    
    return df_metricas

def score_clusters(metricas_df: pd.DataFrame, pesos: dict, lambda_penal: float, 
                  seleccion_actual: pd.DataFrame = None, por_cuadrante: bool = True) -> pd.DataFrame:
    """
    Calcula scores con Z-scores por cuadrante y margen con penalización.
    
    Args:
        metricas_df: DataFrame con métricas por cluster
        pesos: Diccionario con pesos de la función objetivo
        lambda_penal: Penalización por seed adicional
        seleccion_actual: Seeds ya seleccionados (para sep_to_selected_m)
        por_cuadrante: Si calcular Z-scores por cuadrante o global
    
    Returns:
        DataFrame con score_total y margen por cluster
    """
    log_info("🧭", "Calculando scores con Z-scores normalizados")
    
    if metricas_df.empty:
        return pd.DataFrame()
    
    df_scores = metricas_df.copy()
    
    # Determinar qué métrica de separación usar
    if seleccion_actual is not None and not seleccion_actual.empty:
        # Calcular sep_to_selected_m: distancia mínima a seeds ya seleccionados
        df_scores['sep_to_selected_m'] = np.nan
        
        for idx, row in df_scores.iterrows():
            min_dist_selected = float('inf')
            for _, seed in seleccion_actual.iterrows():
                dist = abs(row['medoid_x_m'] - seed['medoid_x_m']) + abs(row['medoid_y_m'] - seed['medoid_y_m'])
                min_dist_selected = min(min_dist_selected, dist)
            
            if min_dist_selected != float('inf'):
                df_scores.loc[idx, 'sep_to_selected_m'] = min_dist_selected
        
        sep_col = 'sep_to_selected_m'
    else:
        sep_col = 'sep_global_m'
    
    # Calcular Z-scores por cuadrante o global
    if por_cuadrante:
        # Z-scores por cuadrante
        for codigo in df_scores['codigo'].unique():
            mask = df_scores['codigo'] == codigo
            df_cuad = df_scores[mask]
            
            if len(df_cuad) <= 1:
                continue  # No se pueden calcular Z-scores con un solo punto
            
            # Calcular log(area_m2) para penalización anti-microclúster
            if 'area_m2' in df_cuad.columns:
                df_scores.loc[mask, 'log_area_m2'] = np.log(df_cuad['area_m2'].clip(lower=1.0))
            
            # Z-scores para cada métrica (incluir log_area_m2)
            for col in ['densidad_pts_m2', 'n', 'silhouette_l1', 'compacidad', sep_col, 'dist_borde_m', 'log_area_m2']:
                if col in df_cuad.columns:
                    values = df_cuad[col].dropna()
                    if len(values) > 1 and values.std() > 0:
                        z_scores = (values - values.mean()) / values.std()
                        df_scores.loc[mask & df_scores[col].notna(), f'z_{col}'] = z_scores
                    else:
                        df_scores.loc[mask, f'z_{col}'] = 0.0
    else:
        # Z-scores globales
        if 'area_m2' in df_scores.columns:
            df_scores['log_area_m2'] = np.log(df_scores['area_m2'].clip(lower=1.0))
        
        for col in ['densidad_pts_m2', 'n', 'silhouette_l1', 'compacidad', sep_col, 'dist_borde_m', 'log_area_m2']:
            if col in df_scores.columns:
                values = df_scores[col].dropna()
                if len(values) > 1 and values.std() > 0:
                    z_scores = (values - values.mean()) / values.std()
                    df_scores.loc[df_scores[col].notna(), f'z_{col}'] = z_scores
                else:
                    df_scores[f'z_{col}'] = 0.0
    
    # Rellenar NaN en Z-scores con 0
    for col in [f'z_{c}' for c in ['densidad_pts_m2', 'n', 'silhouette_l1', 'compacidad', sep_col, 'dist_borde_m', 'log_area_m2']]:
        if col in df_scores.columns:
            df_scores[col] = df_scores[col].fillna(0.0)
    
    # Calcular score_total (corregido: sumar borde y área)
    df_scores['score_total'] = (
        pesos['w_densidad'] * df_scores.get(f'z_densidad_pts_m2', 0) +
        pesos['w_tamano'] * df_scores.get(f'z_n', 0) +
        pesos['w_silhouette'] * df_scores.get(f'z_silhouette_l1', 0) +
        pesos['w_compacidad'] * df_scores.get(f'z_compacidad', 0) +
        pesos['w_separacion'] * df_scores.get(f'z_{sep_col}', 0) +
        pesos['w_borde'] * df_scores.get(f'z_dist_borde_m', 0) +  # Suma: favorece clusters lejos del borde
        pesos['w_area'] * df_scores.get(f'z_log_area_m2', 0) +    # Suma: penaliza microclústers (favorece áreas grandes)
        pesos['w_estabilidad'] * 0.0  # Placeholder
    )
    
    # Calcular margen (score_total - lambda_penal)
    df_scores['margen'] = df_scores['score_total'] - lambda_penal
    
    log_info("✅", f"Scores calculados para {len(df_scores)} clusters")
    
    return df_scores

def seleccionar_seeds_greedy(scores_df: pd.DataFrame, lambda_penal: float, d_min_m: float,
                           max_seeds: int = None) -> tuple:
    """
    Selección greedy de seeds por cuadrante con fusión de colisiones.
    
    Args:
        scores_df: DataFrame con scores por cluster
        lambda_penal: Penalización por seed adicional (ya aplicada en margen)
        d_min_m: Distancia mínima entre seeds en metros
        max_seeds: Máximo de seeds por cuadrante (None = sin límite)
    
    Returns:
        Tupla (seeds_df, log_df):
        - seeds_df: DataFrame con seeds seleccionados
        - log_df: DataFrame con log de decisiones
    """
    log_info("🧭", "Selección greedy de seeds por cuadrante")
    
    if scores_df.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    seeds_seleccionados = []
    log_decisiones = []
    
    for codigo in scores_df['codigo'].unique():
        log_info("📊", f"Seleccionando seeds para {codigo}")
        
        df_cuad = scores_df[scores_df['codigo'] == codigo].copy()
        if df_cuad.empty:
            continue
        
        # Ordenar por margen descendente
        df_cuad = df_cuad.sort_values('margen', ascending=False)
        
        seeds_cuad = []
        
        for _, candidato in df_cuad.iterrows():
            if max_seeds and len(seeds_cuad) >= max_seeds:
                log_decisiones.append({
                    'codigo': codigo,
                    'cluster_id': candidato['cluster_id'],
                    'accion': 'rechazado_max_seeds',
                    'margen': candidato['margen'],
                    'score_total': candidato['score_total']
                })
                break
            
            # Verificar margen positivo
            if candidato['margen'] <= 0 and len(seeds_cuad) > 0:
                log_decisiones.append({
                    'codigo': codigo,
                    'cluster_id': candidato['cluster_id'],
                    'accion': 'rechazado_margen_negativo',
                    'margen': candidato['margen'],
                    'score_total': candidato['score_total']
                })
                continue
            
            # Verificar distancia mínima
            conflicto_seed = None
            for i, seed_prev in enumerate(seeds_cuad):
                dist_m = math.sqrt((candidato['medoid_x_m'] - seed_prev['medoid_x_m'])**2 + 
                                 (candidato['medoid_y_m'] - seed_prev['medoid_y_m'])**2)
                
                if dist_m < d_min_m:
                    conflicto_seed = i
                    break
            
            if conflicto_seed is not None:
                # Fusionar con el seed existente manteniendo el de mayor score_total
                seed_existente = seeds_cuad[conflicto_seed]
                
                if candidato['score_total'] > seed_existente['score_total']:
                    # Reemplazar seed existente
                    seeds_cuad[conflicto_seed] = candidato.to_dict()
                    
                    log_decisiones.append({
                        'codigo': codigo,
                        'cluster_id': candidato['cluster_id'],
                        'accion': 'fusion_reemplaza',
                        'margen': candidato['margen'],
                        'score_total': candidato['score_total'],
                        'reemplaza_cluster': seed_existente['cluster_id'],
                        'distancia_m': dist_m
                    })
                else:
                    log_decisiones.append({
                        'codigo': codigo,
                        'cluster_id': candidato['cluster_id'],
                        'accion': 'fusion_rechazado',
                        'margen': candidato['margen'],
                        'score_total': candidato['score_total'],
                        'conflicto_cluster': seed_existente['cluster_id'],
                        'distancia_m': dist_m
                    })
            else:
                # Agregar seed sin conflicto
                seeds_cuad.append(candidato.to_dict())
                
                log_decisiones.append({
                    'codigo': codigo,
                    'cluster_id': candidato['cluster_id'],
                    'accion': 'seleccionado',
                    'margen': candidato['margen'],
                    'score_total': candidato['score_total']
                })
        
        log_info("✅", f"  {codigo}: {len(seeds_cuad)} seeds seleccionados")
        seeds_seleccionados.extend(seeds_cuad)
    
    seeds_df = pd.DataFrame(seeds_seleccionados)
    log_df = pd.DataFrame(log_decisiones)
    
    if not seeds_df.empty:
        log_info("📊", f"Total seeds seleccionados: {len(seeds_df)}")
        
        # Estadísticas por cuadrante
        distribucion = seeds_df.groupby('codigo').size()
        for codigo, count in distribucion.items():
            log_info("📊", f"  {codigo}: {count} seeds")
    
    return seeds_df, log_df

def clustering_deterministico_diagnostico(df_eventos: pd.DataFrame, gdf_cuad_ruta: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Clustering DBSCAN determinístico para replicar corrida manual.
    Fuerza parámetros exactos: eps=44.123, min_samples=90, metric="manhattan"
    Ordena por x_m, y_m antes de fit para garantizar determinismo.
    
    Args:
        df_eventos: DataFrame con eventos filtrados por cuadrantes
        gdf_cuad_ruta: GeoDataFrame con cuadrantes de ruta
        
    Returns:
        DataFrame con cluster_id asignados de forma determinística y coordenadas x_m, y_m
    """
    log_info("🔬", f"CLUSTERING DETERMINÍSTICO - eps={EPS_FOR_REBUILD}m, min_samples={MS_FOR_REBUILD}, metric={METRIC_FOR_REBUILD}")
    
    df_result = df_eventos.copy()
    df_result['cluster_id'] = -1  # Default: ruido
    # Inicializar columnas x_m, y_m
    df_result['x_m'] = np.nan
    df_result['y_m'] = np.nan
    
    for codigo in sorted(df_eventos['codigo'].unique()):
        mask_cuad = df_eventos['codigo'] == codigo
        df_cuad = df_eventos[mask_cuad].copy()
        
        n_eventos_cuadrante = len(df_cuad)
        log_info("📍", f"  {codigo}: Procesando {n_eventos_cuadrante:,} eventos")
        
        if len(df_cuad) < MS_FOR_REBUILD:
            log_info("⚠️", f"  {codigo}: Pocos puntos ({len(df_cuad)}) para clustering (min_samples={MS_FOR_REBUILD})")
            continue
        
        # Añadir columna de índices originales ANTES de ordenar
        df_cuad['orig_idx'] = df_cuad.index
        
        # Proyectar a coordenadas métricas
        gdf_cuad = gpd.GeoDataFrame(df_cuad, 
                                   geometry=[Point(lon, lat) for lon, lat in zip(df_cuad['lon'], df_cuad['lat'])], 
                                   crs='EPSG:4326')
        gdf_cuad = gdf_cuad.to_crs(PROJ_CRS)
        
        # Agregar coordenadas métricas
        df_cuad['x_m'] = gdf_cuad.geometry.x
        df_cuad['y_m'] = gdf_cuad.geometry.y
        
        # Propagar x_m, y_m a df_result inmediatamente
        df_result.loc[df_cuad.index, ['x_m', 'y_m']] = df_cuad[['x_m', 'y_m']].values
        
        # ORDEN DETERMINÍSTICO: ordenar por (x_m, y_m) manteniendo orig_idx
        df_cuad_sorted = df_cuad.sort_values(['x_m', 'y_m']).reset_index(drop=True)
        coords_sorted = df_cuad_sorted[['x_m', 'y_m']].values
        
        # Aplicar DBSCAN con parámetros EXACTOS de corrida manual
        dbscan = DBSCAN(eps=EPS_FOR_REBUILD, min_samples=MS_FOR_REBUILD, metric=METRIC_FOR_REBUILD)
        labels = dbscan.fit_predict(coords_sorted)
        
        # Asignar cluster_id usando orig_idx (sin aproximaciones de coordenadas)
        for i, label in enumerate(labels):
            orig_idx = df_cuad_sorted.iloc[i]['orig_idx']
            df_result.loc[orig_idx, 'cluster_id'] = label
        
        # Estadísticas de clustering
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_ruido = np.sum(labels == -1)
        log_info("📊", f"  {codigo}: {n_clusters} clusters encontrados, {n_ruido:,} puntos de ruido")
        
    return df_result

def calcular_medoid_l1(coords_xy):
    """
    Calcula el medoid L1 (Manhattan) de un conjunto de coordenadas.
    
    Args:
        coords_xy: array-like de coordenadas [(x, y), ...]
        
    Returns:
        tuple: (medoid_x, medoid_y)
    """
    coords_arr = np.array(coords_xy)
    
    if len(coords_arr) == 1:
        return tuple(coords_arr[0])
    
    # Calcular distancias L1 desde cada punto hacia todos los demás
    distances = []
    for i in range(len(coords_arr)):
        dist_sum = np.sum(np.abs(coords_arr - coords_arr[i]), axis=1).sum()
        distances.append(dist_sum)
    
    # Punto con menor suma de distancias L1
    medoid_idx = np.argmin(distances)
    return tuple(coords_arr[medoid_idx])

def matchear_anchors_con_clusters(df_clusters: pd.DataFrame) -> dict:
    """
    Matchea anchors manuales con clusters detectados usando medoids L1.
    Robustez: recalcula x_m/y_m si no están presentes.
    
    Args:
        df_clusters: DataFrame con clusters y sus coordenadas (lat, lon, cluster_id)
        
    Returns:
        dict: {codigo: [(anchor_i, cluster_id, distancia, n_puntos), ...]}
    """
    log_info("🎯", "Iniciando matcheo de anchors con clusters")
    matches_por_codigo = {}
    
    # Verificar/recalcular coordenadas métricas si faltan
    df_work = df_clusters.copy()
    
    if not {'x_m', 'y_m'}.issubset(df_work.columns) or df_work[['x_m', 'y_m']].isna().any().any():
        log_info("🔧", "Recalculando coordenadas métricas para matching")
        
        # Proyectar a coordenadas métricas
        geometry = [Point(lon, lat) for lon, lat in zip(df_work['lon'], df_work['lat'])]
        gdf_temp = gpd.GeoDataFrame(df_work, geometry=geometry, crs='EPSG:4326')
        gdf_temp = gdf_temp.to_crs(PROJ_CRS)
        
        df_work['x_m'] = gdf_temp.geometry.x
        df_work['y_m'] = gdf_temp.geometry.y
    
    for codigo in sorted(df_work['codigo'].unique()):
        log_info("📍", f"Matching anchors para {codigo}")
        
        if codigo not in MANUAL_ANCHORS or not MANUAL_ANCHORS[codigo]:
            log_info("📊", f"  {codigo}: Sin anchors definidos")
            matches_por_codigo[codigo] = []
            continue
            
        # Filtrar clusters de este cuadrante (no ruido)
        mask_cuad = (df_work['codigo'] == codigo) & (df_work['cluster_id'] >= 0)
        df_cuad_clusters = df_work[mask_cuad].copy()
        
        if df_cuad_clusters.empty:
            log_info("⚠️", f"  {codigo}: Sin clusters válidos para matching")
            matches_por_codigo[codigo] = []
            continue
        
        # Calcular medoids L1 por cluster
        cluster_medoids = {}
        for cluster_id in df_cuad_clusters['cluster_id'].unique():
            mask_cluster = df_cuad_clusters['cluster_id'] == cluster_id
            coords_cluster = df_cuad_clusters[mask_cluster][['x_m', 'y_m']].values
            
            if len(coords_cluster) > 0:
                medoid = calcular_medoid_l1(coords_cluster)
                cluster_medoids[cluster_id] = medoid
        
        # Matchear cada anchor con el cluster más cercano
        matches_codigo = []
        anchors_codigo = MANUAL_ANCHORS[codigo]
        
        for i, (anchor_x, anchor_y) in enumerate(anchors_codigo):
            mejor_cluster = None
            mejor_distancia = float('inf')
            nearest_cluster = None
            nearest_distancia = float('inf')
            
            # Buscar el mejor match dentro de R_MATCH y el más cercano en general
            for cluster_id, (medoid_x, medoid_y) in cluster_medoids.items():
                distancia = abs(anchor_x - medoid_x) + abs(anchor_y - medoid_y)  # L1
                
                # Mejor match dentro del radio
                if distancia <= R_MATCH and distancia < mejor_distancia:
                    mejor_cluster = cluster_id
                    mejor_distancia = distancia
                
                # Cluster más cercano en general (para debug)
                if distancia < nearest_distancia:
                    nearest_cluster = cluster_id
                    nearest_distancia = distancia
            
            if mejor_cluster is not None:
                # Contar puntos en el cluster matcheado
                n_puntos = len(df_cuad_clusters[df_cuad_clusters['cluster_id'] == mejor_cluster])
                matches_codigo.append((i, mejor_cluster, mejor_distancia, n_puntos))
                log_info("🎯", f"  Anchor {i} → cluster_id {mejor_cluster} (dist={mejor_distancia:.1f}m, n={n_puntos})")
            else:
                # Debug extendido: reportar el cluster más cercano aunque esté fuera de R_MATCH
                if nearest_cluster is not None:
                    n_nearest = len(df_cuad_clusters[df_cuad_clusters['cluster_id'] == nearest_cluster])
                    log_info("⚠️", f"  Anchor {i} ({anchor_x:.1f}, {anchor_y:.1f}) sin match en {codigo}")
                    log_info("🔍", f"    Nearest: cluster_id {nearest_cluster} (dist={nearest_distancia:.1f}m, n={n_nearest}) [R_MATCH={R_MATCH}m]")
                else:
                    log_info("⚠️", f"  Anchor {i} ({anchor_x:.1f}, {anchor_y:.1f}) sin match en {codigo} - no hay clusters")
        
        # Resumen por cuadrante
        n_anchors = len(anchors_codigo)
        n_matched = len(matches_codigo)
        log_info("📊", f"  {codigo}: Matched {n_matched} / {n_anchors} anchors")
        
        matches_por_codigo[codigo] = matches_codigo
    
    return matches_por_codigo

def imprimir_tabla_metricas(df_metricas: pd.DataFrame, titulo: str, max_rows: int = None):
    """Imprime tabla de métricas formateada en consola."""
    if df_metricas.empty:
        log_info("📊", f"{titulo}: Sin datos")
        return
    
    print(f"\n{titulo}")
    print("=" * len(titulo))
    
    # Seleccionar y formatear columnas
    cols_display = ['codigo', 'cluster_id', 'n', 'area_m2', 'densidad_pts_m2', 
                   'compacidad', 'dist_borde_m', 'sep_global_m', 'silhouette_l1', 
                   'score_total', 'rank_en_cuadrante']
    
    df_display = df_metricas[cols_display].copy() if max_rows is None else df_metricas[cols_display].head(max_rows).copy()
    
    # Formatear números
    for col in df_display.columns:
        if col in ['area_m2']:
            df_display[col] = df_display[col].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "N/A")
        elif col in ['densidad_pts_m2']:
            df_display[col] = df_display[col].apply(lambda x: f"{x:.2e}" if pd.notna(x) and x != 0 else "N/A")
        elif col in ['compacidad', 'dist_borde_m', 'sep_global_m', 'silhouette_l1', 'score_total']:
            df_display[col] = df_display[col].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "N/A")
        elif col in ['n', 'cluster_id', 'rank_en_cuadrante']:
            df_display[col] = df_display[col].apply(lambda x: f"{x}" if pd.notna(x) else "N/A")
    
    print(df_display.to_string(index=False))

def mapa_clusters_y_seeds(df_filtrado: pd.DataFrame, gdf_cuad_todos: gpd.GeoDataFrame,
                         gdf_cuad_ruta: gpd.GeoDataFrame, seeds_df: pd.DataFrame, 
                         html_out_path: str) -> str:
    """
    Genera mapa Folium con reglas visuales específicas.
    
    Args:
        df_filtrado: DataFrame con eventos filtrados
        gdf_cuad_todos: GeoDataFrame con todos los cuadrantes
        gdf_cuad_ruta: GeoDataFrame con cuadrantes de ruta activa
        seeds_df: DataFrame con seeds seleccionados
        html_out_path: Ruta de salida del archivo HTML
    
    Returns:
        Nombre del archivo generado
    """
    log_info("🧭", "Generando mapa con reglas visuales específicas")
    
    # Determinar centro del mapa
    if not seeds_df.empty:
        centro_lat = seeds_df['seed_lat'].mean()
        centro_lon = seeds_df['seed_lon'].mean()
    elif not df_filtrado.empty:
        centro_lat = df_filtrado['lat'].mean()
        centro_lon = df_filtrado['lon'].mean()
    else:
        centro_lat, centro_lon = 3.45, -76.52  # Default Cali
    
    # Crear mapa base
    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=13,
        tiles='CartoDB positron'
    )
    
    # Determinar códigos de ruta activa
    codigos_ruta_activa = gdf_cuad_ruta['codigo'].unique() if not gdf_cuad_ruta.empty else []
    
    # Añadir todos los cuadrantes con reglas visuales
    for _, cuadrante in gdf_cuad_todos.iterrows():
        codigo = cuadrante['codigo']
        
        # Regla visual: ruta activa vs resto
        if codigo in codigos_ruta_activa:
            # Ruta activa: mantener color (determinístico si no hay color en GeoJSON)
            # Generar color determinístico basado en código
            import hashlib
            hash_codigo = int(hashlib.md5(codigo.encode()).hexdigest()[:6], 16)
            color_fill = f"#{hash_codigo % 0xFFFFFF:06x}"
            
            style = {
                'fillColor': color_fill,
                'color': color_fill,
                'weight': 2,
                'fillOpacity': 0.3
            }
        else:
            # Resto: solo contorno negro, sin relleno
            style = {
                'fillColor': 'transparent',
                'color': '#000000',
                'weight': 1,
                'fillOpacity': 0.0
            }
        
        folium.GeoJson(
            cuadrante.geometry,
            style_function=lambda feature, style=style: style,
            popup=folium.Popup(f"Cuadrante: {codigo}", parse_html=True),
            tooltip=folium.Tooltip(codigo)
        ).add_to(mapa)
    
    # Añadir puntos (eventos) en gris
    if not df_filtrado.empty:
        for _, evento in df_filtrado.iterrows():
            folium.CircleMarker(
                location=[evento['lat'], evento['lon']],
                radius=2,
                popup=f"Evento: {evento.get('codigo', 'N/A')}",
                color='gray',
                fill=True,
                fillColor='gray',
                fillOpacity=0.6,
                weight=1
            ).add_to(mapa)
    
    # Añadir seeds en azul oscuro
    if not seeds_df.empty:
        for _, seed in seeds_df.iterrows():
            folium.CircleMarker(
                location=[seed['seed_lat'], seed['seed_lon']],
                radius=7,
                popup=f"""
                <b>Seed {seed['codigo']}</b><br>
                Cluster: {seed['cluster_id']}<br>
                Puntos: {seed['n']}<br>
                Score: {seed.get('score_total', 0):.3f}<br>
                Margen: {seed.get('margen', 0):.3f}
                """,
                tooltip=f"{seed['codigo']} · Cluster {seed['cluster_id']}",
                color='#0b3d91',
                fill=True,
                fillColor='#0b3d91',
                fillOpacity=0.8,
                weight=2
            ).add_to(mapa)
    
    # Ajustar bounds con cuadrantes + puntos + seeds
    bounds_coords = []
    
    # Añadir bounds de cuadrantes
    if not gdf_cuad_todos.empty:
        for _, cuad in gdf_cuad_todos.iterrows():
            bounds = cuad.geometry.bounds
            bounds_coords.extend([(bounds[1], bounds[0]), (bounds[3], bounds[2])])
    
    # Añadir puntos
    if not df_filtrado.empty:
        for _, evento in df_filtrado.iterrows():
            bounds_coords.append((evento['lat'], evento['lon']))
    
    # Añadir seeds
    if not seeds_df.empty:
        for _, seed in seeds_df.iterrows():
            bounds_coords.append((seed['seed_lat'], seed['seed_lon']))
    
    # Aplicar fit_bounds si hay coordenadas
    if bounds_coords:
        mapa.fit_bounds(bounds_coords, padding=[20, 20])
    
    # Guardar mapa
    filepath = Path(html_out_path)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    mapa.save(str(filepath))
    
    log_info("✅", f"Mapa generado: {filepath.name}")
    return filepath.name

def generar_reporte_auditoria(df_seeds: pd.DataFrame, df_eventos: pd.DataFrame, 
                            r_cobertura: float = R_M) -> dict:
    """
    Genera reporte de auditoría de cobertura y equilibrio de carga.
    
    Args:
        df_seeds: DataFrame con seeds seleccionados
        df_eventos: DataFrame con eventos
        r_cobertura: Radio de cobertura (metros)
    
    Returns:
        Diccionario con métricas de auditoría
    """
    log_info("🧭", "Generando reporte de auditoría")
    
    if df_seeds.empty or df_eventos.empty:
        return {}
    
    try:
        # Convertir coordenadas a métricas
        coords_seeds = convertir_a_metricas(df_seeds[['seed_lat', 'seed_lon']].values)
        coords_eventos = convertir_a_metricas(df_eventos[['lat', 'lon']].values)
        
        # Calcular cobertura (eventos dentro del radio de algún seed)
        eventos_cubiertos = 0
        
        for i, evento_coord in enumerate(coords_eventos):
            cubierto = False
            for j, seed_coord in enumerate(coords_seeds):
                distancia = np.linalg.norm(evento_coord - seed_coord)
                if distancia <= r_cobertura:
                    cubierto = True
                    break
            
            if cubierto:
                eventos_cubiertos += 1
        
        cobertura_pct = (eventos_cubiertos / len(df_eventos)) * 100
        
        # Equilibrio de carga (distribución de eventos por cuadrante)
        eventos_por_cuad = df_eventos.groupby('codigo').size().to_dict()
        seeds_por_cuad = df_seeds.groupby('codigo').size().to_dict()
        
        # Estadísticas de equilibrio
        ratios_carga = []
        for codigo in eventos_por_cuad.keys():
            n_eventos = eventos_por_cuad[codigo]
            n_seeds = seeds_por_cuad.get(codigo, 0)
            if n_seeds > 0:
                ratio = n_eventos / n_seeds
                ratios_carga.append(ratio)
        
        equilibrio_cv = np.std(ratios_carga) / np.mean(ratios_carga) if ratios_carga else 0
        
        reporte = {
            'total_events': len(df_eventos),
            'total_seeds': len(df_seeds),
            'coverage_pct': cobertura_pct,
            'covered_events': eventos_cubiertos,
            'uncovered_events': len(df_eventos) - eventos_cubiertos,
            'load_balance_cv': equilibrio_cv,  # Coeficiente de variación (menor = más equilibrado)
            'events_per_quadrant': eventos_por_cuad,
            'seeds_per_quadrant': seeds_por_cuad,
            'avg_events_per_seed': np.mean(ratios_carga) if ratios_carga else 0
        }
        
        log_info("📊", f"Auditoría completada:")
        log_info("📊", f"  Cobertura: {cobertura_pct:.1f}% ({eventos_cubiertos}/{len(df_eventos)} eventos)")
        log_info("📊", f"  Balance de carga CV: {equilibrio_cv:.3f}")
        log_info("📊", f"  Promedio eventos/seed: {reporte['avg_events_per_seed']:.1f}")
        
        return reporte
        
    except Exception as e:
        log_info("⚠️", f"Error en auditoría: {str(e)}")
        return {}

def exportar_top1_por_cuadrante_html(scores_df: pd.DataFrame, df_lab: pd.DataFrame, 
                                    gdf_cuadrantes: gpd.GeoDataFrame, pruebas_dir: str, 
                                    tiles: str = "CartoDB positron") -> list:
    """
    Exporta mapas HTML del clúster Top-1 por cuadrante.
    
    Args:
        scores_df: DataFrame con scores (score_total, rank_en_cuadrante)
        df_lab: Puntos etiquetados (lat, lon, codigo, cluster_id, x_m, y_m)
        gdf_cuadrantes: GeoDataFrame filtrado (CL_3_01, CL_3_02)
        pruebas_dir: Directorio donde guardar los HTML
        tiles: Tile layer para Folium
        
    Returns:
        Lista de rutas de archivos HTML generados
    """
    import folium
    from shapely.geometry import Point, MultiPoint
    from shapely.ops import unary_union
    import numpy as np
    from datetime import datetime
    import os
    
    log_info("📊", "Iniciando exportación de mapas HTML Top-1")
    
    # Verificar que df_lab tiene x_m, y_m; si no, calcularlos
    df_work = df_lab.copy()
    if 'x_m' not in df_work.columns or 'y_m' not in df_work.columns or df_work[['x_m', 'y_m']].isna().any().any():
        log_info("🔧", "Calculando x_m, y_m from lat/lon")
        gdf_temp = gpd.GeoDataFrame(df_work, geometry=gpd.points_from_xy(df_work.lon, df_work.lat), crs="EPSG:4326")
        gdf_temp = gdf_temp.to_crs(PROJ_CRS)
        df_work['x_m'] = gdf_temp.geometry.x
        df_work['y_m'] = gdf_temp.geometry.y
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    html_files = []
    
    # Paleta de colores determinística por código
    def get_cuadrante_color(codigo):
        """Genera color determinístico basado en código"""
        hash_val = hash(codigo) % 360
        return f"hsl({hash_val}, 70%, 50%)"
    
    # Procesar cada cuadrante
    for codigo in gdf_cuadrantes['codigo'].unique():
        cuad_scores = scores_df[scores_df['codigo'] == codigo]
        
        if cuad_scores.empty:
            log_info("⚠️", f"Cuadrante {codigo}: sin clústeres, saltando HTML")
            continue
            
        # Top-1 por score_total
        if 'score_total' not in cuad_scores.columns:
            log_info("⚠️", f"Cuadrante {codigo}: columna 'score_total' no encontrada")
            continue
        
        top1_idx = cuad_scores['score_total'].idxmax()
        top1 = cuad_scores.loc[top1_idx]
        
        # Debug: verificar columnas
        if 'cluster_id' not in top1.index:
            log_info("⚠️", f"Cuadrante {codigo}: columna 'cluster_id' no encontrada. Columnas: {list(top1.index)}")
            continue
        
        top1_cluster_id = top1['cluster_id']
        
        log_info("🔍", f"Cuadrante {codigo}: Top-1 cluster_id={top1_cluster_id}, score={top1['score_total']:.3f}")
        
        # Debug: verificar tipos
        log_info("🔧", f"Tipo de top1_cluster_id: {type(top1_cluster_id)}, valor: {top1_cluster_id}")
        
        # Geometría del cuadrante
        geom_cuadrante = gdf_cuadrantes[gdf_cuadrantes['codigo'] == codigo].iloc[0].geometry
        
        # Puntos del cuadrante
        puntos_cuad = df_work[df_work['codigo'] == codigo].copy()
        if puntos_cuad.empty:
            log_info("⚠️", f"Cuadrante {codigo}: sin puntos etiquetados")
            continue
        
        # Debug: verificar columnas de puntos_cuad
        log_info("🔧", f"Columnas en puntos_cuad: {list(puntos_cuad.columns)}")
        if 'cluster_id' not in puntos_cuad.columns:
            log_info("⚠️", f"Cuadrante {codigo}: puntos sin columna 'cluster_id'")
            continue
            
        # Puntos del clúster Top-1
        puntos_top1 = puntos_cuad[puntos_cuad['cluster_id'] == top1_cluster_id].copy()
        log_info("🔧", f"Puntos top1 encontrados: {len(puntos_top1)}")
        
        # Otros puntos (muestrear para rendimiento)
        puntos_otros = puntos_cuad[puntos_cuad['cluster_id'] != top1_cluster_id].copy()
        max_otros = max(2000, int(len(puntos_otros) * 0.01))  # Máx 2000 o 1%
        if len(puntos_otros) > max_otros:
            puntos_otros = puntos_otros.sample(n=max_otros, random_state=42)
        
        # Crear mapa
        centro_lat = geom_cuadrante.centroid.y
        centro_lon = geom_cuadrante.centroid.x
        
        m = folium.Map(location=[centro_lat, centro_lon], zoom_start=13, tiles=tiles)
        
        # Añadir cuadrantes
        for _, cuad_row in gdf_cuadrantes.iterrows():
            cuad_codigo = cuad_row['codigo']
            
            if cuad_codigo == codigo:
                # Cuadrante activo: con relleno
                color = get_cuadrante_color(cuad_codigo)
                folium.GeoJson(
                    cuad_row.geometry,
                    style_function=lambda x, color=color: {
                        'fillColor': color,
                        'color': '#000',
                        'weight': 2,
                        'fillOpacity': 0.3
                    },
                    tooltip=f"Cuadrante: {cuad_codigo}"
                ).add_to(m)
            else:
                # Otros cuadrantes: solo contorno
                folium.GeoJson(
                    cuad_row.geometry,
                    style_function=lambda x: {
                        'fillColor': 'none',
                        'color': '#000',
                        'weight': 1,
                        'fillOpacity': 0
                    },
                    tooltip=f"Cuadrante: {cuad_row['codigo']}"
                ).add_to(m)
        
        # Añadir otros puntos (gris claro)
        if not puntos_otros.empty:
            for _, punto in puntos_otros.iterrows():
                folium.CircleMarker(
                    location=[punto['lat'], punto['lon']],
                    radius=2,
                    color='#999',
                    fillColor='#ccc',
                    weight=1,
                    fillOpacity=0.6
                ).add_to(m)
        
        # Añadir puntos del clúster Top-1 (azul medio)
        if not puntos_top1.empty:
            for _, punto in puntos_top1.iterrows():
                folium.CircleMarker(
                    location=[punto['lat'], punto['lon']],
                    radius=3,
                    color='#0066cc',
                    fillColor='#4da6ff',
                    weight=1,
                    fillOpacity=0.8
                ).add_to(m)
        
        # Contorno del clúster (convex hull)
        if len(puntos_top1) > 2:
            coords_top1 = [(row['x_m'], row['y_m']) for _, row in puntos_top1.iterrows()]
            multi_point = MultiPoint([Point(x, y) for x, y in coords_top1])
            convex_hull = multi_point.convex_hull
            
            # Convertir a lat/lon para Folium
            gdf_hull = gpd.GeoDataFrame([1], geometry=[convex_hull], crs=PROJ_CRS)
            gdf_hull_wgs84 = gdf_hull.to_crs("EPSG:4326")
            
            folium.GeoJson(
                gdf_hull_wgs84.iloc[0].geometry,
                style_function=lambda x: {
                    'fillColor': '#4da6ff',
                    'color': '#0066cc',
                    'weight': 2,
                    'fillOpacity': 0.2
                },
                tooltip=f"Contorno Cluster {top1_cluster_id}"
            ).add_to(m)
        
        # Medoid L1 y marcador
        if len(puntos_top1) > 0:
            coords_top1_utm = [(row['x_m'], row['y_m']) for _, row in puntos_top1.iterrows()]
            medoid_x, medoid_y = calcular_medoid_l1(coords_top1_utm)
            
            # Convertir medoid a lat/lon
            gdf_medoid = gpd.GeoDataFrame([1], geometry=[Point(medoid_x, medoid_y)], crs=PROJ_CRS)
            gdf_medoid_wgs84 = gdf_medoid.to_crs("EPSG:4326")
            medoid_lat = gdf_medoid_wgs84.geometry.y.iloc[0]
            medoid_lon = gdf_medoid_wgs84.geometry.x.iloc[0]
            
            # Popup con métricas
            metricas_text = f"""
            <b>Cluster ID:</b> {top1['cluster_id']}<br>
            <b>Puntos (n):</b> {top1['n']:,}<br>
            <b>Área:</b> {top1['area_m2']:,.0f} m²<br>
            <b>Densidad:</b> {top1['densidad_pts_m2']:.2e} pts/m²<br>
            <b>Compacidad:</b> {top1['compacidad']:.3f}<br>
            <b>Dist. Borde:</b> {top1['dist_borde_m']:.1f} m<br>
            <b>Sep. Global:</b> {top1['sep_global_m']:.1f} m<br>
            <b>Silhouette L1:</b> {top1['silhouette_l1']:.3f}<br>
            <b>Score Total:</b> {top1['score_total']:.3f}<br>
            <b>Rank:</b> {top1['rank_en_cuadrante']}/5
            """
            
            folium.CircleMarker(
                location=[medoid_lat, medoid_lon],
                radius=8,
                color='#cc0000',
                fillColor='#ff6666',
                weight=2,
                fillOpacity=0.8,
                tooltip=f"Medoid Cluster {top1_cluster_id}",
                popup=folium.Popup(metricas_text, max_width=300)
            ).add_to(m)
        
        # Ajustar vista
        if len(puntos_top1) > 0:
            # Bounds del cuadrante + cluster
            bounds_cuad = geom_cuadrante.bounds  # (minx, miny, maxx, maxy)
            bounds_cluster = [
                puntos_top1['lat'].min(), puntos_top1['lon'].min(),
                puntos_top1['lat'].max(), puntos_top1['lon'].max()
            ]
            
            # Unir bounds
            min_lat = min(bounds_cuad[1], bounds_cluster[0])
            min_lon = min(bounds_cuad[0], bounds_cluster[1])
            max_lat = max(bounds_cuad[3], bounds_cluster[2])
            max_lon = max(bounds_cuad[2], bounds_cluster[3])
            
            m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
        
        # Guardar HTML
        html_filename = f"v2_diag_top1_{codigo}_{timestamp}.html"
        html_path = os.path.join(pruebas_dir, html_filename)
        m.save(html_path)
        html_files.append(html_path)
        
        print(f"💾 HTML Top-1 {codigo}: {html_path}")
    
    log_info("✅", f"Exportación HTML completada: {len(html_files)} archivos generados")
    return html_files

def exportar_comparativo_manual_vs_top5(scores_df: pd.DataFrame, matches_dict: dict, 
                                       pruebas_dir: str) -> list:
    """
    Exporta tabla comparativa "Manual vs Top-5" por cuadrante.
    
    Args:
        scores_df: DataFrame con scores y rankings
        matches_dict: Dict con matches de anchors por cuadrante
        pruebas_dir: Directorio donde guardar CSVs
        
    Returns:
        Lista de rutas CSV generadas
    """
    from datetime import datetime
    import os
    
    log_info("📊", "Iniciando exportación comparativa Manual vs Top-5")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    csv_files = []
    
    for codigo in scores_df['codigo'].unique():
        # Top-5 del cuadrante
        top5_cuad = scores_df[scores_df['codigo'] == codigo].nlargest(5, 'score_total').copy()
        
        # Anchors matcheadas del cuadrante
        matches_cuad = matches_dict.get(codigo, [])
        
        # Crear tabla comparativa
        comparativo = []
        
        # Añadir anchors matcheadas
        for i, (anchor_i, cluster_id, distancia, n_puntos) in enumerate(matches_cuad):
            anchor_row = scores_df[
                (scores_df['codigo'] == codigo) & (scores_df['cluster_id'] == cluster_id)
            ]
            
            if not anchor_row.empty:
                row = anchor_row.iloc[0].copy()
                row['tipo'] = 'Manual (Anchor)'
                row['anchor_index'] = anchor_i
                row['match_distance_m'] = distancia
                comparativo.append(row)
        
        # Añadir Top-5
        for i, (_, row) in enumerate(top5_cuad.iterrows()):
            row_copy = row.copy()
            row_copy['tipo'] = f'Top-{i+1} Score'
            row_copy['anchor_index'] = None
            row_copy['match_distance_m'] = None
            comparativo.append(row_copy)
        
        if not comparativo:
            log_info("⚠️", f"Cuadrante {codigo}: sin datos para comparativo")
            continue
        
        # Crear DataFrame y ordenar
        df_comparativo = pd.DataFrame(comparativo)
        df_comparativo = df_comparativo.sort_values(['tipo', 'score_total'], ascending=[True, False])
        
        # Seleccionar columnas relevantes
        cols_export = [
            'codigo', 'cluster_id', 'tipo', 'anchor_index', 'match_distance_m',
            'n', 'area_m2', 'densidad_pts_m2', 'compacidad', 'dist_borde_m', 
            'sep_global_m', 'silhouette_l1', 'score_total', 'rank_en_cuadrante'
        ]
        
        # Filtrar columnas existentes
        cols_disponibles = [col for col in cols_export if col in df_comparativo.columns]
        df_export = df_comparativo[cols_disponibles].copy()
        
        # Formatear números con manejo de errores
        try:
            if 'area_m2' in df_export.columns:
                df_export['area_m2'] = pd.to_numeric(df_export['area_m2'], errors='coerce').round(0).astype('Int64')
            if 'match_distance_m' in df_export.columns:
                df_export['match_distance_m'] = pd.to_numeric(df_export['match_distance_m'], errors='coerce').round(1)
        except Exception as e:
            log_info("⚠️", f"Error formateando números: {str(e)}")
        
        # Guardar CSV
        csv_filename = f"v2_diag_comparativo_manual_vs_top5_{codigo}_{timestamp}.csv"
        csv_path = os.path.join(pruebas_dir, csv_filename)
        df_export.to_csv(csv_path, index=False)
        csv_files.append(csv_path)
        
        print(f"💾 Comparativo {codigo}: {csv_path}")
        log_info("📊", f"  {codigo}: {len(df_export)} filas exportadas")
    
    log_info("✅", f"Exportación comparativa completada: {len(csv_files)} archivos")
    return csv_files

def main_diagnostico():
    """Función principal en modo diagnóstico."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    
    log_info("🔬", "=== MODO DIAGNÓSTICO - VORONOI V2 ===")
    
    # Log de configuración detallada
    if DATA_SOURCE == "bd":
        db_host = os.getenv("DB_HOST")
        db_port = os.getenv("DB_PORT") or "3306"  # Default si no está definido
        log_info("📋", f"DATA_SOURCE=bd, host={db_host}, port={db_port}")
    else:
        log_info("📋", f"DATA_SOURCE={DATA_SOURCE}")
    
    log_info("📋", f"DBSCAN: eps={EPS_FOR_REBUILD}m, min_samples={MS_FOR_REBUILD}, metric={METRIC_FOR_REBUILD}")
    log_info("📋", f"Configuración: CO={CO}, RUTA={ID_RUTA} ('{RUTA_NOMBRE}'), {FECHA_INI} a {FECHA_FIN}")
    
    crear_directorio_pruebas()
    
    try:
        # 1. Cargar eventos según configuración de fuente
        log_info("1️⃣", f"CARGA DE EVENTOS - FUENTE: {DATA_SOURCE}")
        df_eventos = cargar_datos_configurados()
        
        if df_eventos.empty:
            log_info("❌", "No hay eventos para procesar")
            return
        
        log_info("�", f"Eventos cargados: {len(df_eventos):,}")
        
        # 2. Cargar y filtrar cuadrantes (solo CL_3_01 y CL_3_02)
        log_info("2️⃣", "CARGA DE CUADRANTES")
        gdf_cuad = detectar_y_normalizar_codigo(CUADRANTES_PATH, usar_sinteticos=False)
        gdf_cuad_ruta = filtrar_cuadrantes_ruta(gdf_cuad, RUTA_NOMBRE)
        
        if gdf_cuad_ruta.empty:
            log_info("❌", f"No hay cuadrantes para ruta '{RUTA_NOMBRE}'")
            return
        
        # Verificar que tenemos CL_3_01 y CL_3_02
        codigos_disponibles = set(gdf_cuad_ruta['codigo'].unique())
        required_cuadrantes = {'CL_3_01', 'CL_3_02'}
        missing_cuadrantes = required_cuadrantes - codigos_disponibles
        
        if missing_cuadrantes:
            log_info("❌", f"Cuadrantes críticos faltantes: {missing_cuadrantes}")
            log_info("📊", f"Disponibles: {codigos_disponibles}")
            return
        
        log_info("✅", f"Cuadrantes críticos encontrados: {sorted(codigos_disponibles)}")
        
        # 3. Recortar eventos a cuadrantes CL_3_01 y CL_3_02
        log_info("3️⃣", "RECORTE A CUADRANTES CL_3_01 y CL_3_02")
        df_filtrado, gdf_cuad_ruta = recortar_eventos_por_cuadrantes(df_eventos, gdf_cuad_ruta)
        df_etq = asignar_cuadrantes_a_eventos(df_filtrado, gdf_cuad_ruta)
        
        if df_etq.empty:
            log_info("❌", "No hay eventos dentro de los cuadrantes")
            return
        
        log_info("✂️", f"Eventos en cuadrantes: {len(df_etq):,}")
        for codigo in sorted(df_etq['codigo'].unique()):
            n_eventos = len(df_etq[df_etq['codigo'] == codigo])
            log_info("📊", f"  {codigo}: {n_eventos:,} eventos")
        
        # 4. Clustering determinístico 
        log_info("4️⃣", "CLUSTERING DETERMINÍSTICO")
        df_clustered = clustering_deterministico_diagnostico(df_etq, gdf_cuad_ruta)
        
        # 5. Matcheo de anchors con clusters
        log_info("5️⃣", "MATCHEO DE ANCHORS")
        matches_anchors = matchear_anchors_con_clusters(df_clustered)
        
        # 6. Calcular métricas
        log_info("6️⃣", "CÁLCULO DE MÉTRICAS")
        df_metricas = calcular_metricas_clusters(df_clustered, gdf_cuad_ruta, PROJ_CRS)
        
        if df_metricas.empty:
            log_info("❌", "No se pudieron calcular métricas")
            return
        
        # 7. Calcular scores y ranking
        log_info("7️⃣", "SCORING Y RANKING")
        df_scores = score_clusters(df_metricas, SCORE_WEIGHTS, LAMBDA_PENAL, por_cuadrante=True)
        
        # Agregar ranking por cuadrante
        df_scores['rank_en_cuadrante'] = df_scores.groupby('codigo')['score_total'].rank(method='dense', ascending=False).astype(int)
        
        # 8. ANÁLISIS Y SALIDAS
        log_info("8️⃣", "ANÁLISIS COMPARATIVO")
        
        # 8.1 Métricas de clusters que matchearon anchors
        for codigo, matches in matches_anchors.items():
            if not matches:  # Sin matches
                log_info("📊", f"Sin anchors matcheados para {codigo}")
                continue
                
            # Obtener cluster_ids que matchearon
            cluster_ids_matcheados = [match[1] for match in matches]  # match[1] = cluster_id
            
            mask_matcheados = (df_scores['codigo'] == codigo) & (df_scores['cluster_id'].isin(cluster_ids_matcheados))
            df_matcheados = df_scores[mask_matcheados].sort_values('cluster_id')
            
            if df_matcheados.empty:
                log_info("⚠️", f"No se encontraron métricas para clusters matcheados en {codigo}")
                continue
            
            # Imprimir tabla
            imprimir_tabla_metricas(df_matcheados, f"🔎 Métricas — {codigo} (anchors matcheados)")
            
            # Guardar CSV
            csv_manuales = Path(PRUEBAS_DIR) / f"v2_diag_metricas_manuales_{codigo}_{timestamp}.csv"
            df_matcheados.to_csv(csv_manuales, index=False)
            log_info("💾", f"CSV manuales {codigo}: {csv_manuales.name}")
        
        # 8.2 Top-5 por score (comparativo)
        for codigo in sorted(df_scores['codigo'].unique()):
            df_cuad = df_scores[df_scores['codigo'] == codigo]
            df_top5 = df_cuad.nlargest(5, 'score_total')
            
            # Imprimir tabla
            imprimir_tabla_metricas(df_top5, f"🏆 Top-5 por Score — {codigo} (comparativo)")
            
            # Guardar CSV (corregir bug del nombre para CL_3_02)
            csv_top5 = Path(PRUEBAS_DIR) / f"v2_diag_top5_score_{codigo}_{timestamp}.csv"
            df_top5.to_csv(csv_top5, index=False)
            log_info("💾", f"CSV top-5 {codigo}: {csv_top5.name}")
        
        # Exportar mapas HTML Top-1 (si está habilitado)
        if EXPORTAR_TOP1_HTML:
            try:
                log_info("🔧", f"df_scores columnas: {list(df_scores.columns)}")
                log_info("🔧", f"df_etq columnas: {list(df_etq.columns)}")
                
                html_files = exportar_top1_por_cuadrante_html(
                    scores_df=df_scores,
                    df_lab=df_etq,
                    gdf_cuadrantes=gdf_cuad_ruta,
                    pruebas_dir=str(PRUEBAS_DIR)
                )
                log_info("🗺️", f"Mapas HTML generados: {len(html_files)}")
            except Exception as e:
                import traceback
                log_info("⚠️", f"Error generando mapas HTML: {str(e)}")
                log_info("⚠️", f"Traceback: {traceback.format_exc()}")
        
        # Exportar tabla comparativa Manual vs Top-5
        try:
            csv_comp_files = exportar_comparativo_manual_vs_top5(
                scores_df=df_scores,
                matches_dict=matches_anchors,
                pruebas_dir=str(PRUEBAS_DIR)
            )
            log_info("📊", f"Comparativos generados: {len(csv_comp_files)}")
        except Exception as e:
            log_info("⚠️", f"Error generando comparativos: {str(e)}")
        
        # Resumen final
        log_info("✅", "=== DIAGNÓSTICO COMPLETADO ===")
        log_info("📊", f"Eventos analizados: {len(df_etq):,}")
        log_info("📊", f"Clusters totales: {len(df_metricas)}")
        for codigo in sorted(df_scores['codigo'].unique()):
            n_clusters = len(df_scores[df_scores['codigo'] == codigo])
            log_info("📊", f"  {codigo}: {n_clusters} clusters")
            
    except Exception as e:
        log_info("❌", f"Error en diagnóstico: {str(e)}")
        raise

def main(usar_datos_sinteticos=True):
    """Función principal del pipeline."""
    
    # Determinar modo de ejecución
    if MODO == "diagnostico":
        return main_diagnostico()
    
    # Modo pipeline completo (código original)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    warnings_list = []
    start_time = datetime.now()
    
    log_info("🚀", "=== PIPELINE VORONOI V2 - RUTA 3 ===")
    log_info("📋", f"Configuración: CO={CO}, RUTA={ID_RUTA} ('{RUTA_NOMBRE}'), {FECHA_INI} a {FECHA_FIN}")
    
    # Crear directorio de salida
    crear_directorio_pruebas()
    
    try:
        # 1. Cargar eventos
        log_info("1️⃣", "CARGA DE DATOS")
        if usar_datos_sinteticos:
            df_eventos = cargar_datos_sinteticos()
            log_info("📥", f"Eventos cargados: {len(df_eventos):,} (datos sintéticos)")
        else:
            df_eventos = cargar_eventos_pre_consultores(CO, ID_RUTA, FECHA_INI, FECHA_FIN)
            if not df_eventos.empty:
                fecha_min = df_eventos['fecha'].min().strftime('%Y-%m-%d') if 'fecha' in df_eventos else "N/A"
                fecha_max = df_eventos['fecha'].max().strftime('%Y-%m-%d') if 'fecha' in df_eventos else "N/A"
                log_info("📥", f"Eventos cargados: {len(df_eventos):,} (rango {fecha_min} → {fecha_max})")
        
        if df_eventos.empty:
            log_info("❌", "No hay eventos para procesar")
            return
        
        # Log con formato requerido
        fecha_min = df_eventos['fecha'].min().strftime('%Y-%m-%d') if 'fecha' in df_eventos else "N/A"
        fecha_max = df_eventos['fecha'].max().strftime('%Y-%m-%d') if 'fecha' in df_eventos else "N/A"
        log_info("📥", f"Eventos cargados: {len(df_eventos):,} (rango {fecha_min} → {fecha_max})")
        
        # 2. Cargar y filtrar cuadrantes
        log_info("2️⃣", "PROCESAMIENTO GEOESPACIAL")
        gdf_cuad = detectar_y_normalizar_codigo(CUADRANTES_PATH, usar_datos_sinteticos)
        gdf_cuad_ruta = filtrar_cuadrantes_ruta(gdf_cuad, RUTA_NOMBRE)
        
        if gdf_cuad_ruta.empty:
            log_info("❌", f"No hay cuadrantes para la ruta '{RUTA_NOMBRE}'")
            return
        
        # Log de cuadrantes detectados
        codigos_cuad = sorted(gdf_cuad_ruta['codigo'].unique())
        log_info("🧭", f"Cuadrantes ruta {RUTA_NOMBRE} detectados: {', '.join(codigos_cuad)}")
        
        # 3. Recortar eventos por cuadrantes
        df_filtrado, gdf_cuad_ruta = recortar_eventos_por_cuadrantes(df_eventos, gdf_cuad_ruta)
        
        if df_filtrado.empty:
            log_info("❌", "No hay eventos dentro de los cuadrantes")
            return
        
        log_info("✂️", f"Puntos dentro de ruta: {len(df_filtrado):,}")
        
        # 4. Asignar códigos de cuadrante
        df_etq = asignar_cuadrantes_a_eventos(df_filtrado, gdf_cuad_ruta)
        
        if df_etq.empty:
            log_info("❌", "No se pudieron asignar códigos de cuadrante")
            return
        
        # 5. Aplicar clustering con logs detallados por cuadrante
        log_info("3️⃣", "CLUSTERING DBSCAN")
        df_lab, resumen_clusters = clusterizar_por_cuadrante_dbscan(
            df_etq, PROJ_CRS, KNN_K, EPS_FACTORS, MIN_SAMPLES_RULE, 
            MIN_CLUSTER_SIZE_ABS, MAX_SAMPLES_SILHOUETTE
        )
        
        # Logs detallados por cuadrante (formato requerido)
        for codigo in sorted(df_etq['codigo'].unique()):
            df_cuad = df_etq[df_etq['codigo'] == codigo]
            df_clusters = df_lab[df_lab['codigo'] == codigo]
            n_clusters = len(df_clusters[df_clusters['cluster_id'] >= 0]['cluster_id'].unique()) if len(df_clusters) > 0 else 0
            log_info("🤖", f"DBSCAN {codigo}: n={len(df_cuad):,} → clusters válidos: {n_clusters}")
        
        # 6. Calcular métricas
        log_info("4️⃣", "CÁLCULO DE MÉTRICAS")
        df_metricas = calcular_metricas_clusters(df_lab, gdf_cuad_ruta, PROJ_CRS)
        
        if df_metricas.empty:
            warnings_list.append("No se pudieron calcular métricas")
            log_info("⚠️", "No se pudieron calcular métricas")
        
        # 7. Calcular scores
        log_info("5️⃣", "CÁLCULO DE SCORES")
        df_scores = score_clusters(df_metricas, SCORE_WEIGHTS, LAMBDA_PENAL, por_cuadrante=True)
        
        # 8. Seleccionar seeds
        log_info("6️⃣", "SELECCIÓN DE SEEDS")
        df_seeds, log_seleccion = seleccionar_seeds_greedy(df_scores, LAMBDA_PENAL, D_MIN_M)
        
        if df_seeds.empty:
            log_info("❌", "No se pudieron seleccionar seeds")
            return
        
        # Logs de seeds seleccionados por cuadrante
        for codigo in sorted(df_seeds['codigo'].unique()):
            n_seeds = len(df_seeds[df_seeds['codigo'] == codigo])
            log_info("📊", f"Seeds seleccionadas: {n_seeds} ({codigo})")
            
        total_seeds = len(df_seeds)
        log_info("📊", f"Total seeds seleccionadas: {total_seeds}")
        
        # 9. Generar mapa
        log_info("7️⃣", "GENERACIÓN DE MAPA")
        html_filename = f"v2_mapa_ruta{RUTA_NOMBRE}_{timestamp}.html"
        html_path = Path(PRUEBAS_DIR) / html_filename
        
        filename = mapa_clusters_y_seeds(df_etq, gdf_cuad, gdf_cuad_ruta, df_seeds, str(html_path))
        
        # 10. Auditoría
        log_info("8️⃣", "AUDITORÍA DE COBERTURA")
        reporte = generar_reporte_auditoria(df_seeds, df_etq, R_M)
        
        # 11. GUARDAR TODAS LAS SALIDAS OBLIGATORIAS
        log_info("9️⃣", "GUARDANDO SALIDAS")
        
        # CSV 1: Resumen clusters
        if not resumen_clusters.empty:
            clusters_file = Path(PRUEBAS_DIR) / f"v2_clusters_ruta{RUTA_NOMBRE}_{timestamp}.csv"
            resumen_clusters.to_csv(clusters_file, index=False)
            log_info("💾", f"CSV clusters: {clusters_file.name}")
        
        # CSV 2: Métricas
        if not df_metricas.empty:
            metricas_file = Path(PRUEBAS_DIR) / f"v2_metricas_ruta{RUTA_NOMBRE}_{timestamp}.csv"
            df_metricas.to_csv(metricas_file, index=False)
            log_info("💾", f"CSV métricas: {metricas_file.name}")
        
        # CSV 3: Scores
        if not df_scores.empty:
            scores_file = Path(PRUEBAS_DIR) / f"v2_scores_ruta{RUTA_NOMBRE}_{timestamp}.csv"
            df_scores.to_csv(scores_file, index=False)
            log_info("💾", f"CSV scores: {scores_file.name}")
        
        # CSV 4: Seeds
        seeds_file = Path(PRUEBAS_DIR) / f"v2_seeds_ruta{RUTA_NOMBRE}_{timestamp}.csv"
        df_seeds.to_csv(seeds_file, index=False)
        log_info("💾", f"CSV seeds: {seeds_file.name}")
        
        # CSV 5: Log selección greedy
        if not log_seleccion.empty:
            log_file = Path(PRUEBAS_DIR) / f"v2_log_ruta{RUTA_NOMBRE}_{timestamp}.csv"
            log_seleccion.to_csv(log_file, index=False)
            log_info("💾", f"CSV log: {log_file.name}")
        
        # GeoJSON: Seeds en WGS84
        gdf_seeds = gpd.GeoDataFrame(df_seeds, geometry=gpd.points_from_xy(df_seeds['seed_lon'], df_seeds['seed_lat']))
        gdf_seeds.crs = 'EPSG:4326'  # WGS84
        geojson_file = Path(PRUEBAS_DIR) / f"v2_seeds_ruta{RUTA_NOMBRE}_{timestamp}.geojson"
        gdf_seeds.to_file(geojson_file, driver='GeoJSON')
        log_info("💾", f"GeoJSON seeds: {geojson_file.name}")
        
        # Archivo de texto con resumen
        txt_file = Path(PRUEBAS_DIR) / f"v2_run_ruta{RUTA_NOMBRE}_{timestamp}.txt"
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(f"=== VORONOI V2 - RUTA {RUTA_NOMBRE} ===\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Duración: {datetime.now() - start_time}\n\n")
            f.write(f"PARÁMETROS:\n")
            f.write(f"CO: {CO}\n")
            f.write(f"ID_RUTA: {ID_RUTA}\n")
            f.write(f"RUTA_NOMBRE: {RUTA_NOMBRE}\n")
            f.write(f"FECHA_INI: {FECHA_INI}\n")
            f.write(f"FECHA_FIN: {FECHA_FIN}\n")
            f.write(f"PROJ_CRS: {PROJ_CRS}\n")
            f.write(f"D_MIN_M: {D_MIN_M}\n")
            f.write(f"R_M: {R_M}\n\n")
            f.write(f"CONTEOS:\n")
            f.write(f"Eventos crudos: {len(df_eventos):,}\n")
            f.write(f"Tras recorte: {len(df_filtrado):,}\n")
            f.write(f"Por cuadrante:\n")
            for codigo in sorted(df_etq['codigo'].unique()):
                n_eventos = len(df_etq[df_etq['codigo'] == codigo])
                n_clusters = len(df_metricas[df_metricas['codigo'] == codigo]) if not df_metricas.empty else 0
                n_seeds = len(df_seeds[df_seeds['codigo'] == codigo])
                f.write(f"  {codigo}: {n_eventos:,} eventos → {n_clusters} clusters → {n_seeds} seeds\n")
            f.write(f"Total clusters: {len(df_metricas) if not df_metricas.empty else 0}\n")
            f.write(f"Total seeds: {len(df_seeds)}\n\n")
            if warnings_list:
                f.write(f"WARNINGS:\n")
                for w in warnings_list:
                    f.write(f"  - {w}\n")
        
        log_info("💾", f"TXT resumen: {txt_file.name}")
        
        # Resumen final
        log_info("✅", "=== PIPELINE COMPLETADO ===")
        log_info("📊", f"Eventos procesados: {len(df_etq):,}")
        log_info("📊", f"Clusters generados: {len(df_metricas) if not df_metricas.empty else 0}")
        log_info("📊", f"Seeds seleccionados: {len(df_seeds)}")
        
        if filename:
            log_info("�", f"HTML: {html_path}")
        
        if reporte:
            log_info("📊", f"Cobertura: {reporte.get('coverage_pct', 0):.1f}%")

        
    except Exception as e:
        log_info("❌", f"Error crítico en pipeline: {str(e)}")
        
        # Guardar log de error
        error_file = Path(PRUEBAS_DIR) / f"v2_error_ruta{RUTA_NOMBRE}_{timestamp}.txt"
        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(f"=== ERROR EN PIPELINE VORONOI V2 ===\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Error: {str(e)}\n")
            f.write(f"Tipo: {type(e).__name__}\n")
            f.write(f"Duración antes del error: {datetime.now() - start_time}\n")
        
        log_info("💾", f"Log de error: {error_file.name}")
        raise

def test_html_generation():
    """Función de prueba para debug de mapas HTML"""
    try:
        # Simular datos temporales
        df_scores_test = pd.DataFrame([
            {'codigo': 'CL_3_01', 'cluster_id': 21, 'score_total': 1.553, 'n': 91, 'area_m2': 923,
             'densidad_pts_m2': 0.098, 'compacidad': 0.448, 'dist_borde_m': 263.8, 'sep_global_m': 156.6,
             'silhouette_l1': 0.854, 'rank_en_cuadrante': 1}
        ])
        
        df_lab_test = pd.DataFrame([
            {'lat': 3.45, 'lon': -76.5, 'codigo': 'CL_3_01', 'cluster_id': 21},
            {'lat': 3.46, 'lon': -76.51, 'codigo': 'CL_3_01', 'cluster_id': 21},
            {'lat': 3.47, 'lon': -76.52, 'codigo': 'CL_3_01', 'cluster_id': 22}
        ])
        
        # Crear cuadrante simple
        from shapely.geometry import Polygon
        test_geom = Polygon([(-76.6, 3.4), (-76.4, 3.4), (-76.4, 3.6), (-76.6, 3.6)])
        gdf_test = gpd.GeoDataFrame([{'codigo': 'CL_3_01', 'geometry': test_geom}], crs="EPSG:4326")
        
        print("🔧 Iniciando test HTML...")
        html_files = exportar_top1_por_cuadrante_html(
            scores_df=df_scores_test,
            df_lab=df_lab_test,
            gdf_cuadrantes=gdf_test,
            pruebas_dir=str(PRUEBAS_DIR)
        )
        print(f"✅ Test completado: {len(html_files)} archivos generados")
        
    except Exception as e:
        print(f"❌ Error en test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Uncomment para test HTML:
    # test_html_generation()
    main()
