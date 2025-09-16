import os
import pandas as pd
import mysql.connector
import unicodedata
import logging
import time
import math
from datetime import date, datetime
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path=dotenv_path, override=False)
else:
    print(f"⚠️ Advertencia: Archivo .env no encontrado en {dotenv_path}")

# --- Resolver CO por ciudad (reusar mapping de otros módulos) ---
CENTROOPES = {'CALI':2,'MEDELLIN':3,'MANIZALES':6,'PEREIRA':5,'BOGOTA':4,'BARRANQUILLA':8,'BUCARAMANGA':7}
def get_co(ciudadN:str)->int:
    return CENTROOPES[ciudadN]

def _norm_city(ciudad: str) -> str:
    """Normalizar ciudad removiendo acentos y convirtiendo a mayúsculas."""
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

def _conn():
    """Crear conexión a MySQL validando variables de entorno obligatorias."""
    # Variables obligatorias
    required_vars = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if not value or value.strip() == "":
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"Variables de entorno faltantes para conexión BD: {', '.join(missing_vars)}")
    
    # Obtener valores
    host = os.getenv("DB_HOST").strip()
    user = os.getenv("DB_USER").strip()
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME").strip()
    
    # Puerto opcional (sin requerirlo)
    port = int(os.getenv("DB_PORT", "3306"))
    
    # Log de configuración (enmascarando contraseña)
    user_masked = user[:2] + '*' * (len(user) - 2) if len(user) > 2 else user
    logging.info(f"Conectando BD - Host: {host}, DB: {database}, Usuario: {user_masked}")
    
    try:
        return mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port
        )
    except mysql.connector.Error as e:
        logging.error(f"Error de conexión BD: {e}")
        raise

def contactos_en_ruta_y_fecha(id_centroope: int, id_ruta: int, fecha_objetivo: str) -> pd.DataFrame:
    """
    Devuelve solo la lista base de contactos del día objetivo.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro (entero de BD)
        fecha_objetivo (str): Fecha objetivo en formato 'YYYY-MM-DD'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_contacto', 'id_ruta', 'ruta', 'nombre_contacto', 
                     'telefono', 'fecha_prox_visita_venta']
    """
    q = """
    SELECT DISTINCT
        c.id                     AS id_contacto,
        r.id                     AS id_ruta,
        r.ruta                   AS ruta,
        c.nombre                 AS nombre_contacto,
        c.ext1                   AS telefono,
        c.fecha_prox_visita_venta AS fecha_prox_visita_venta
    FROM fullclean_contactos.vwContactos c
    JOIN fullclean_contactos.barrios b            ON b.id = c.id_barrio
    JOIN fullclean_contactos.rutas_cobro_zonas rc ON rc.id_barrio = b.id
    JOIN fullclean_contactos.rutas_cobro r        ON r.id = rc.id_ruta_cobro
    WHERE c.estado = 1
      AND c.estado_cxc IN (0,1)
      AND r.id_centroope = %s
      AND r.id = %s
      AND DATE(c.fecha_prox_visita_venta) = %s
    ORDER BY c.fecha_prox_visita_venta ASC, c.id ASC;
    """
    
    try:
        cn = _conn()
        params = [int(id_centroope), int(id_ruta), str(fecha_objetivo)]
        df = pd.read_sql(q, cn, params=params)
        cn.close()
        
        logging.info(f"contactos_en_ruta_y_fecha: {len(df)} contactos encontrados para CO:{id_centroope}, ruta:{id_ruta}, fecha:{fecha_objetivo}")
        return df
        
    except Exception as e:
        logging.error(f"Error en contactos_en_ruta_y_fecha: {str(e)}")
        raise e

def eventos_top5_por_contacto(ids_contacto: list[int]) -> pd.DataFrame:
    """
    Devuelve hasta 5 eventos más recientes por contacto con coordenadas válidas y id_cargo IN (181,5).
    
    Args:
        ids_contacto (list[int]): Lista de IDs de contactos
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_contacto', 'lat', 'lon', 'fecha_evento']
    """
    if not ids_contacto:
        return pd.DataFrame()
    
    # Construir la consulta con window function para MySQL 8+
    ids_str = ','.join(str(id_c) for id_c in ids_contacto)
    
    q = """
    SELECT id_contacto, lat, lon, fecha_evento
    FROM (
      SELECT
          e.id_contacto,
          e.coordenada_latitud  AS lat,
          e.coordenada_longitud AS lon,
          e.fecha_evento,
          ROW_NUMBER() OVER (PARTITION BY e.id_contacto ORDER BY e.fecha_evento DESC) AS rn
      FROM fullclean_contactos.vwEventos e
      JOIN fullclean_personal.personal p ON p.id = e.id_autor
      JOIN fullclean_personal.cargos  ca ON ca.Id_cargo = p.id_cargo
      WHERE e.id_contacto IN ({})
        AND e.coordenada_latitud  IS NOT NULL
        AND e.coordenada_longitud IS NOT NULL
        AND e.coordenada_latitud  <> 0
        AND e.coordenada_longitud <> 0
        AND e.coordenada_latitud  BETWEEN -5  AND 13
        AND e.coordenada_longitud BETWEEN -81 AND -66
        AND ca.Id_cargo IN (181, 5)
        AND e.fecha_evento >= (CURRENT_DATE - INTERVAL 365 DAY)
    ) t
    WHERE rn <= 5
    ORDER BY id_contacto, fecha_evento DESC;
    """.format(ids_str)
    
    try:
        cn = _conn()
        df = pd.read_sql(q, cn)
        cn.close()
        
        logging.info(f"eventos_top5_por_contacto: {len(df)} eventos encontrados para {len(ids_contacto)} contactos")
        return df
        
    except Exception as e:
        # Fallback: usar consulta por contacto individual si no soporta window functions
        logging.warning(f"Window function falló, usando fallback por contacto individual: {e}")
        return _eventos_top5_fallback(ids_contacto)

def _eventos_top5_fallback(ids_contacto: list[int]) -> pd.DataFrame:
    """Fallback para MySQL sin window functions: consulta por contacto individual."""
    if not ids_contacto:
        return pd.DataFrame()
    
    q_individual = """
    SELECT 
        e.id_contacto,
        e.coordenada_latitud  AS lat,
        e.coordenada_longitud AS lon,
        e.fecha_evento
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_personal.personal p ON p.id = e.id_autor
    JOIN fullclean_personal.cargos  ca ON ca.Id_cargo = p.id_cargo
    WHERE e.id_contacto = %s
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
      AND e.coordenada_latitud  BETWEEN -5  AND 13
      AND e.coordenada_longitud BETWEEN -81 AND -66
      AND ca.Id_cargo IN (181, 5)
      AND e.fecha_evento >= (CURRENT_DATE - INTERVAL 365 DAY)
    ORDER BY e.fecha_evento DESC
    LIMIT 5;
    """
    
    df_eventos_todos = []
    
    for id_contacto in ids_contacto:
        try:
            cn = _conn()
            df_contacto = pd.read_sql(q_individual, cn, params=[int(id_contacto)])
            cn.close()
            df_eventos_todos.append(df_contacto)
        except Exception as e:
            logging.error(f"Error obteniendo eventos para contacto {id_contacto}: {e}")
            continue
    
    if df_eventos_todos:
        df_final = pd.concat(df_eventos_todos, ignore_index=True)
        logging.info(f"eventos_top5_fallback: {len(df_final)} eventos encontrados para {len(ids_contacto)} contactos")
        return df_final
    else:
        return pd.DataFrame()

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia Haversine en kilómetros entre dos puntos."""
    R = 6371.0  # Radio de la Tierra en km
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def coordenada_robusta_por_contacto(df_eventos: pd.DataFrame) -> tuple[float|None, float|None, str, int, float|None]:
    """
    Aplica mejor tríada si k≥3 (min suma de distancias Haversine internas) y devuelve mediana(lat), mediana(lon).
    
    Args:
        df_eventos (pd.DataFrame): DataFrame con eventos del contacto ['lat', 'lon', 'fecha_evento']
    
    Returns:
        tuple: (lat, lon, confianza_str, k_usados, dispersion_m)
        - lat/lon: Coordenadas asignadas (o None si no se pudo)
        - confianza_str: String describiendo la confianza ('alta', 'media', 'baja', 'sin_datos')
        - k_usados: Número de eventos utilizados para el cálculo
        - dispersion_m: Dispersión en metros de los puntos usados (o None)
    """
    if df_eventos.empty:
        return None, None, 'sin_datos', 0, None
    
    # Convertir a float y limpiar
    df_eventos = df_eventos.copy()
    df_eventos['lat'] = pd.to_numeric(df_eventos['lat'], errors='coerce')
    df_eventos['lon'] = pd.to_numeric(df_eventos['lon'], errors='coerce')
    df_eventos = df_eventos.dropna(subset=['lat', 'lon'])
    
    k = len(df_eventos)
    
    if k == 0:
        return None, None, 'sin_datos', 0, None
    elif k == 1:
        # Un solo evento: usar esas coordenadas
        row = df_eventos.iloc[0]
        return float(row['lat']), float(row['lon']), 'baja', 1, 0.0
    elif k == 2:
        # Dos eventos: punto medio
        lat_medio = df_eventos['lat'].mean()
        lon_medio = df_eventos['lon'].mean()
        
        # Calcular dispersión
        p1_lat, p1_lon = df_eventos.iloc[0]['lat'], df_eventos.iloc[0]['lon']
        p2_lat, p2_lon = df_eventos.iloc[1]['lat'], df_eventos.iloc[1]['lon']
        dispersion = _haversine_km(p1_lat, p1_lon, p2_lat, p2_lon) * 1000  # en metros
        
        return float(lat_medio), float(lon_medio), 'baja', 2, dispersion
    else:
        # k ≥ 3: encontrar mejor tríada (mínima suma de distancias internas)
        lat_final, lon_final, dispersion = _mejor_triada_mediana(df_eventos)
        confianza = 'alta' if k >= 5 else 'media'
        return lat_final, lon_final, confianza, min(k, 3), dispersion

def _mejor_triada_mediana(df_eventos: pd.DataFrame) -> tuple[float, float, float]:
    """
    Encuentra la mejor tríada (3 puntos con mínima suma de distancias internas) y retorna su mediana.
    """
    import itertools
    
    if len(df_eventos) < 3:
        # Fallback: usar todos los puntos disponibles
        lat_mediana = df_eventos['lat'].median()
        lon_mediana = df_eventos['lon'].median()
        # Calcular dispersión de todos los puntos
        dispersion = _calcular_dispersion(df_eventos)
        return float(lat_mediana), float(lon_mediana), dispersion
    
    mejor_suma = float('inf')
    mejor_triada_idx = None
    
    # Probar todas las combinaciones de 3 puntos
    for i, j, k in itertools.combinations(range(len(df_eventos)), 3):
        p1 = df_eventos.iloc[i]
        p2 = df_eventos.iloc[j]
        p3 = df_eventos.iloc[k]
        
        # Calcular suma de distancias internas de la tríada
        d12 = _haversine_km(p1['lat'], p1['lon'], p2['lat'], p2['lon'])
        d13 = _haversine_km(p1['lat'], p1['lon'], p3['lat'], p3['lon'])
        d23 = _haversine_km(p2['lat'], p2['lon'], p3['lat'], p3['lon'])
        
        suma_distancias = d12 + d13 + d23
        
        if suma_distancias < mejor_suma:
            mejor_suma = suma_distancias
            mejor_triada_idx = (i, j, k)
    
    # Usar la mejor tríada encontrada
    if mejor_triada_idx:
        indices = list(mejor_triada_idx)
        df_triada = df_eventos.iloc[indices]
        
        lat_mediana = df_triada['lat'].median()
        lon_mediana = df_triada['lon'].median()
        dispersion = _calcular_dispersion(df_triada)
        
        return float(lat_mediana), float(lon_mediana), dispersion
    else:
        # Fallback
        lat_mediana = df_eventos['lat'].median()
        lon_mediana = df_eventos['lon'].median()
        dispersion = _calcular_dispersion(df_eventos)
        return float(lat_mediana), float(lon_mediana), dispersion

def _calcular_dispersion(df_puntos: pd.DataFrame) -> float:
    """Calcula la dispersión máxima entre puntos en metros."""
    if len(df_puntos) < 2:
        return 0.0
    
    max_distancia = 0.0
    
    for i in range(len(df_puntos)):
        for j in range(i+1, len(df_puntos)):
            p1 = df_puntos.iloc[i]
            p2 = df_puntos.iloc[j]
            distancia = _haversine_km(p1['lat'], p1['lon'], p2['lat'], p2['lon']) * 1000  # en metros
            max_distancia = max(max_distancia, distancia)
    
    return max_distancia

def contactos_proyeccion_visitas(id_centroope: int, id_ruta: int, fecha_objetivo: str) -> pd.DataFrame:
    """
    Retorna lista de contactos con proyección de visitas para fecha objetivo usando funciones modulares.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro (entero de BD)
        fecha_objetivo (str): Fecha objetivo en formato 'YYYY-MM-DD'
    
    Returns:
        pd.DataFrame: DataFrame con contactos y coordenadas asignadas incluyendo columna 'dispersion_m'
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando proyección visitas para CO:{id_centroope}, ruta:{id_ruta}, fecha:{fecha_objetivo}")
    
    try:
        # 1. Obtener lista base de contactos
        df_contactos = contactos_en_ruta_y_fecha(id_centroope, id_ruta, fecha_objetivo)
        
        if df_contactos.empty:
            logging.warning("No se encontraron contactos para los parámetros dados")
            return pd.DataFrame()
        
        # 2. Obtener eventos top-5 para todos los contactos en batch
        ids_contacto = df_contactos['id_contacto'].tolist()
        df_eventos = eventos_top5_por_contacto(ids_contacto)
        
        # 3. Asignar coordenadas robustas a cada contacto
        resultados_coords = []
        
        for _, contacto in df_contactos.iterrows():
            id_contacto = contacto['id_contacto']
            
            # Filtrar eventos de este contacto
            eventos_contacto = df_eventos[df_eventos['id_contacto'] == id_contacto]
            
            # Calcular coordenada robusta
            lat, lon, confianza, k_usados, dispersion = coordenada_robusta_por_contacto(eventos_contacto)
            
            if lat is not None and lon is not None:
                # Agregar información al contacto
                contacto_dict = contacto.to_dict()
                contacto_dict['lat'] = lat
                contacto_dict['lon'] = lon
                contacto_dict['confianza_coord'] = confianza
                contacto_dict['eventos_usados'] = k_usados
                contacto_dict['dispersion_m'] = dispersion
                
                resultados_coords.append(contacto_dict)
        
        # 4. Crear DataFrame resultado
        df_resultado = pd.DataFrame(resultados_coords)
        
        # Logging de tiempo de ejecución y tamaño
        tiempo_ejecucion = time.time() - inicio_tiempo
        contactos_con_coord = len(df_resultado)
        logging.info(f"contactos_proyeccion_visitas completada en {tiempo_ejecucion:.2f}s - {contactos_con_coord} contactos con coordenadas para CO:{id_centroope}, id_ruta:{id_ruta}")
        
        return df_resultado
        
    except Exception as e:
        logging.error(f"Error en contactos_proyeccion_visitas: {str(e)}")
        raise e



# === FUNCIONES DE COMPATIBILIDAD HACIA ATRÁS ===

def listar_rutas_simple(ciudad: str) -> pd.DataFrame:
    """
    Compatibility wrapper que usa la función de preprocesamiento_consultores.
    """
    from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple as listar_consultores
    return listar_consultores(ciudad)