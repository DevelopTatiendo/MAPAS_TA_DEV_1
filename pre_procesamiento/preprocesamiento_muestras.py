import pandas as pd
from dotenv import load_dotenv
import os
import mysql.connector
import warnings
from typing import List, Dict
import logging
import re
import unicodedata
from .db_utils import sql_read
from utils.spatial_ops import assign_quadrant_to_points, area_m2_geodesic
from ism_config import get_city_key, compute_hogares_por_m2, resolve_hogares_por_m2
from .preprocesamiento_consultores import listar_rutas_simple, get_co
from pathlib import Path

# Silenciar warnings de pandas sobre MySQL
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

# Constante para categorías de Adquisición y Recuperación
CATEGORIAS_ADQ_RECU = (10, 22, 38)  # Nuevos + Recuperación + Perdidos reactivados
CATEGORIAS_FIELES = (1, 43, 40, 41)  # Fieles
# Cargar variables de entorno
load_dotenv()

# Credenciales desde el archivo .env
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def _normalize_eventos_columns(df: pd.DataFrame, tz: str = 'America/Bogota') -> pd.DataFrame:
    """
    Normaliza un DataFrame de eventos asegurando columnas mínimas y tipos correctos.
    
    Args:
        df: DataFrame de eventos desde la base de datos
        tz: Zona horaria para normalización de fechas (default: 'America/Bogota')
        
    Returns:
        pd.DataFrame: Copia del DataFrame con columnas garantizadas y normalizadas:
                     - 'lat' (float): latitud de coordenadas
                     - 'lon' (float): longitud de coordenadas  
                     - 'fecha_evento' (datetime): timestamp del evento
                     - 'fecha_dia' (date): fecha sin hora en zona horaria local
                     - 'id_autor' (conserva tipo original)
                     - 'id_contacto' (conserva tipo original)
                     
    Notes:
        - Si fecha_evento es naive (sin timezone), asume que está en tz local
        - Si fecha_evento tiene timezone, convierte a tz especificado
        - No modifica ni deduplica otros campos
        - Garantiza que lat/lon sean float para operaciones geoespaciales
        
    Raises:
        ValueError: Si faltan columnas críticas en el DataFrame original
    """
    if df.empty:
        return df.copy()
    
    # Verificar columnas mínimas requeridas
    required_base = ['fecha_evento', 'id_autor', 'id_contacto']
    missing = [col for col in required_base if col not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")
    
    # Verificar columnas de coordenadas (pueden tener nombres alternativos)
    lat_cols = ['coordenada_latitud', 'latitud', 'lat']
    lon_cols = ['coordenada_longitud', 'longitud', 'lon']
    
    lat_col = next((col for col in lat_cols if col in df.columns), None)
    lon_col = next((col for col in lon_cols if col in df.columns), None)
    
    if not lat_col or not lon_col:
        raise ValueError(f"No se encontraron columnas de coordenadas. Disponibles: {list(df.columns)}")
    
    # Crear copia para no modificar original
    result = df.copy()
    
    # Normalizar coordenadas a 'lat' y 'lon'
    if lat_col != 'lat':
        result['lat'] = pd.to_numeric(result[lat_col], errors='coerce')
    else:
        result['lat'] = pd.to_numeric(result['lat'], errors='coerce')
        
    if lon_col != 'lon':
        result['lon'] = pd.to_numeric(result[lon_col], errors='coerce')
    else:
        result['lon'] = pd.to_numeric(result['lon'], errors='coerce')
    
    # Normalizar fecha_evento con manejo de timezone
    if not pd.api.types.is_datetime64_any_dtype(result['fecha_evento']):
        result['fecha_evento'] = pd.to_datetime(result['fecha_evento'], errors='coerce')
    
    # Manejar timezone: si es naive, asumir local; si tiene tz, convertir
    if result['fecha_evento'].dt.tz is None:
        # Naive datetime: asumir que está en tz local
        result['fecha_evento'] = result['fecha_evento'].dt.tz_localize(tz, ambiguous='infer')
    else:
        # Ya tiene timezone: convertir a tz especificado
        result['fecha_evento'] = result['fecha_evento'].dt.tz_convert(tz)
    
    # Crear fecha_dia (fecha sin hora en timezone local)
    result['fecha_dia'] = result['fecha_evento'].dt.date
    
    return result

def listar_promotores():
    """
    Devuelve DataFrame con columnas id_autor, apellido a partir de:
    SELECT p.id AS id_autor, p.apellido
    FROM fullclean_personal.personal p
    WHERE p.id_cargo = 39;
    """
    query = """
    SELECT 
        p.id AS id_autor, 
        p.apellido
    FROM 
        fullclean_personal.personal p
    WHERE 
        p.id_cargo = 39
    ORDER BY 
        p.apellido;
    """
    
    df = sql_read(query, schema="fullclean_personal")
    
    # Asegurar tipos de datos apropiados
    if not df.empty:
        df['id_autor'] = df['id_autor'].astype('int64')
        df['apellido'] = df['apellido'].fillna('').astype(str)
    
    return df

def filtrar_ids_por_cargo(ids, cargo=39):
    """Devuelve solo los IDs cuyo p.id_cargo == cargo en fullclean_personal.personal."""
    if not ids: 
        return []
    
    param_dict = {f'id_{i}': int(v) for i, v in enumerate(ids)}
    placeholders = ",".join([f":id_{i}" for i in range(len(ids))])
    query = f"""
      SELECT p.id
      FROM fullclean_personal.personal p
      WHERE p.id IN ({placeholders}) AND p.id_cargo = :cargo
    """
    param_dict['cargo'] = cargo
    df = sql_read(query, params=param_dict, schema="fullclean_personal")
    return df['id'].astype(int).tolist() if not df.empty else []

def consultar_muestras_db(centroope, fecha_inicio, fecha_fin, promotores=None):
    """
    Consulta la base de datos para obtener los eventos de muestras filtrados por centroope y fechas.
    Solo incluye autores que sean promotores (cargo = 39).
    Retorna un DataFrame.
    """
    # Si se pasan promotores, filtrar solo los que sean cargo=39
    if promotores is not None and len(promotores) > 0:
        promotores = filtrar_ids_por_cargo(promotores, 39)
        if not promotores:
            # Si ninguno es promotor, retornar DataFrame vacío
            return pd.DataFrame(columns=[
                'id_muestra', 'id_contacto', 'fecha_evento', 'id_autor',
                'coordenada_longitud', 'coordenada_latitud', 'medio_contacto',
                'tipo_evento', 'tipo_categoria', 'id_barrio', 'apellido_autor'
            ])
    
    # Construir consulta base con INNER JOIN a personal para filtrar cargo=39
    query = """
    SELECT 
        e.idEvento AS id_muestra,
        e.id_contacto,
        e.fecha_evento, 
        e.id_evento_tipo,
        e.id_autor,
        e.coordenada_longitud, 
        e.coordenada_latitud,
        e.medio_contacto,
        e.tipo_evento,
        e.tipo_categoria,
        con.id_categoria AS id_contacto_categoria,
        con.id_barrio AS id_barrio,
        per.apellido AS apellido_autor
        
    FROM 
        fullclean_contactos.vwEventos e
    INNER JOIN 
        fullclean_contactos.vwContactos con ON e.id_contacto = con.id
    LEFT JOIN 
        fullclean_contactos.barrios bar ON bar.id = con.id_barrio
    LEFT JOIN 
        fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
    INNER JOIN 
        fullclean_personal.personal per ON per.id = e.id_autor AND per.id_cargo = 39
    WHERE 
        e.fecha_evento BETWEEN :fecha_inicio AND :fecha_fin
        AND e.id_evento_tipo = 15
        AND ciu.id_centroope = :centroope
        AND e.coordenada_longitud <> 0 
        AND e.coordenada_latitud <> 0
        AND e.id_autor NOT IN (17415, 17466, 17556, 17597, 17393, 17261) 
        """
    
    # Parámetros base con nombres
    param_dict = {
        'fecha_inicio': f'{fecha_inicio} 00:00:00',
        'fecha_fin': f'{fecha_fin} 23:59:59',
        'centroope': centroope
    }
    
    # Agregar filtro dinámico por promotores si se especifica
    if promotores is not None and len(promotores) > 0:
        placeholders_named = ",".join([f":promotor_{i}" for i in range(len(promotores))])
        query += f" AND e.id_autor IN ({placeholders_named})"
        for i, pid in enumerate(promotores):
            param_dict[f'promotor_{i}'] = pid
    
    query += ";"
    
    df = sql_read(query, params=param_dict, schema="fullclean_contactos")
    return df


def crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, promotores=None, agentes=None):
    """
    Crea un DataFrame final al combinar los datos de la base de datos con las coordenadas de los barrios.
    Retorna un DataFrame listo para usar.
    """
    # Obtener datos de muestras desde la base de datos
    df_muestras = consultar_muestras_db(centroope, fecha_inicio, fecha_fin, promotores)

    # Agregar columna id_muestra al inicio
    #df_muestras.insert(0, 'id_muestra', range(len(df_muestras)))

    # Leer el archivo de coordenadas
    df_coord = pd.read_csv(ruta_coordenadas)

    # Realizar el merge por 'id_barrio'
    df_muestras_completo = pd.merge(df_muestras, df_coord, how='left', on='id_barrio')

    # Verifica las columnas disponibles
    #print("Columnas después del merge:", df_muestras_completo.columns.tolist())

    # Asegurar tipos básicos requeridos por nuevas métricas
    if 'fecha_evento' in df_muestras_completo.columns and not pd.api.types.is_datetime64_any_dtype(df_muestras_completo['fecha_evento']):
        df_muestras_completo['fecha_evento'] = pd.to_datetime(df_muestras_completo['fecha_evento'], errors='coerce')

    # Lista de columnas deseadas mínimas garantizadas para métricas nuevas
    columnas_minimas = [
        'id_autor', 'fecha_evento', 'id_evento_tipo', 'id_contacto',
        'id_contacto_categoria', 'coordenada_latitud', 'coordenada_longitud'
    ]

    # Lista ampliada de columnas útiles para otros flujos existentes
    columnas_deseadas = columnas_minimas + [
        'id_muestra', 'tipo_evento', 'tipo_categoria', 'id_barrio', 'barrio', 'id_estrato',
        'latitud', 'longitud', 'ruta_cobro', 'nom_ruta'
    ]
    # Filtra solo las columnas que existen
    columnas_existentes = [col for col in columnas_deseadas if col in df_muestras_completo.columns]
    df_muestras_completo = df_muestras_completo[columnas_existentes]

    # Crear columnas faltantes mínimas como NaN/None para garantizar esquema
    for col in columnas_minimas:
        if col not in df_muestras_completo.columns:
            df_muestras_completo[col] = pd.NA

    
    # Si el CSV tiene 'barrio' y no 'barrio_x', no necesitas renombrar
    # Si tienes 'barrio_x', renómbralo a 'barrio'
    if 'barrio_x' in df_muestras_completo.columns:
        df_muestras_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)

    return df_muestras_completo

def metricas_muestras_por_promotor(df_muestras: pd.DataFrame, fecha_inicio: str, fecha_fin: str, co=None, ids_autor=None) -> pd.DataFrame:
    """
    Calcula métricas base de muestras por promotor en un rango de fechas.

    Retorna por id_autor:
      - muestras_total
      - dias_habiles (días con >= 2 muestras del promotor)
      - muestras_no_fieles (id_contacto_categoria NOT IN CATEGORIAS_FIELES)
      - pct_no_fieles
    """
    if df_muestras is None or df_muestras.empty:
        return pd.DataFrame(columns=['id_autor', 'muestras_total', 'dias_habiles', 'muestras_no_fieles', 'pct_no_fieles'])

    df = df_muestras.copy()

    # Normalizar fecha_evento a datetime naive
    if not pd.api.types.is_datetime64_any_dtype(df['fecha_evento']):
        df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')

    f_ini = pd.to_datetime(f"{fecha_inicio} 00:00:00", errors='coerce')
    f_fin = pd.to_datetime(f"{fecha_fin} 23:59:59", errors='coerce')
    df = df[(df['fecha_evento'] >= f_ini) & (df['fecha_evento'] <= f_fin)]

    # Filtro opcional por promotores
    if ids_autor:
        ids_set = {int(x) for x in ids_autor if str(x).strip()}
        df = df[df['id_autor'].astype('Int64').isin(list(ids_set))]

    if df.empty:
        return pd.DataFrame(columns=['id_autor', 'muestras_total', 'dias_habiles', 'muestras_no_fieles', 'pct_no_fieles'])

    # Base: total por promotor
    totales = df.groupby('id_autor', observed=True).size().rename('muestras_total')

    # Días hábiles: contar fechas (por promotor) con >= 2 eventos
    df['fecha_dia'] = df['fecha_evento'].dt.date
    cnt_por_dia = df.groupby(['id_autor', 'fecha_dia'], observed=True).size().rename('n_dia')
    dias_habiles = (cnt_por_dia >= 2).groupby(level=0, observed=True).sum().rename('dias_habiles')

    # No fieles: id_contacto_categoria NOT IN CATEGORIAS_FIELES
    if 'id_contacto_categoria' in df.columns:
        cats = pd.to_numeric(df['id_contacto_categoria'], errors='coerce')
        mask_no_fiel = ~cats.isna() & ~cats.astype('Int64').isin(list(CATEGORIAS_FIELES))
        muestras_no_fieles = mask_no_fiel.groupby(df['id_autor'], observed=True).sum().rename('muestras_no_fieles')
    else:
        muestras_no_fieles = pd.Series(0, index=totales.index, name='muestras_no_fieles')

    # Armar DataFrame final
    out = (
        totales.to_frame()
        .join(dias_habiles, how='left')
        .join(muestras_no_fieles, how='left')
        .fillna({'dias_habiles': 0, 'muestras_no_fieles': 0})
    )

    # Porcentaje no fieles
    out['pct_no_fieles'] = 0.0
    mask_den = out['muestras_total'] > 0
    out.loc[mask_den, 'pct_no_fieles'] = (out.loc[mask_den, 'muestras_no_fieles'] / out.loc[mask_den, 'muestras_total']) * 100.0

    # Tipos
    out['muestras_total'] = out['muestras_total'].astype('int64')
    out['dias_habiles'] = out['dias_habiles'].astype('int64')
    out['muestras_no_fieles'] = out['muestras_no_fieles'].astype('int64')
    out['pct_no_fieles'] = out['pct_no_fieles'].astype('float64')

    out = out.reset_index()
    return out

def fetch_contactabilidad_base(ciudad: str, fecha_inicio: str, fecha_fin: str, ids_autor=None) -> pd.DataFrame:
    """
    Trae id_autor, id_contacto, fecha_evento, ultima_llamada para eventos de muestras (id_evento_tipo=15)
    en el rango. No compara ultima_llamada > fecha_evento en SQL; eso se hace en pandas.
    """
    try:
        ciudad_norm = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        co = get_co(ciudad_norm)

        query = """
        SELECT 
            e.id_autor,
            e.id_contacto,
            e.fecha_evento,
            c.ultima_llamada
        FROM fullclean_contactos.vwEventos e
        INNER JOIN fullclean_contactos.vwContactos c ON c.id = e.id_contacto
        INNER JOIN fullclean_contactos.ciudades ciu ON ciu.id = c.id_ciudad
        INNER JOIN fullclean_personal.personal per ON per.id = e.id_autor AND per.id_cargo = 39
        WHERE 
            e.id_evento_tipo = 15
            AND e.fecha_evento BETWEEN :fecha_inicio AND :fecha_fin
            AND ciu.id_centroope = :co
        """

        params = {
            'fecha_inicio': f"{fecha_inicio} 00:00:00",
            'fecha_fin': f"{fecha_fin} 23:59:59",
            'co': co,
        }

        if ids_autor:
            ids_list = [int(x) for x in ids_autor if str(x).strip()]
            if ids_list:
                placeholders = ",".join([f":id_{i}" for i in range(len(ids_list))])
                query += f" AND e.id_autor IN ({placeholders})"
                for i, v in enumerate(ids_list):
                    params[f"id_{i}"] = v

        df = sql_read(query + ";", params=params, schema="fullclean_contactos")

        # Normalizar tipos
        if not df.empty:
            if not pd.api.types.is_datetime64_any_dtype(df['fecha_evento']):
                df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
            if 'ultima_llamada' in df.columns and not pd.api.types.is_datetime64_any_dtype(df['ultima_llamada']):
                df['ultima_llamada'] = pd.to_datetime(df['ultima_llamada'], errors='coerce')
        return df
    except Exception as e:
        logging.warning(f"fetch_contactabilidad_base error: {e}")
        return pd.DataFrame(columns=['id_autor', 'id_contacto', 'fecha_evento', 'ultima_llamada'])

def prepo_metricas_promotores_muestras(ciudad: str, fecha_inicio: str, fecha_fin: str, ids_autor=None) -> pd.DataFrame:
    """
    Pipeline de preprocesamiento para métricas por promotor en Muestras.

    - Usa crear_df(...) para traer muestras del CO de la ciudad.
    - Calcula métricas base con metricas_muestras_por_promotor(...).
    - Calcula contactabilidad a partir de ultima_llamada > fecha_evento en pandas.
    - Añade columnas M1, M2, M3, muestras_m2 vacías.
    """
    # Resolver centroope y ruta de coordenadas de barrios de la ciudad
    ciudad_norm = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
    co = get_co(ciudad_norm)
    # Ruta a CSV de barrios para la ciudad
    root = Path(__file__).resolve().parents[1]
    ruta_coordenadas = root / 'ciudades' / ciudad_norm / 'barrios.csv'

    # Traer muestras del rango
    try:
        df_muestras = crear_df(co, fecha_inicio, fecha_fin, str(ruta_coordenadas), promotores=ids_autor)
    except Exception:
        # Fallback: si no existe CSV, traer sólo desde BD sin merge
        df_muestras = consultar_muestras_db(co, fecha_inicio, fecha_fin, promotores=ids_autor)

    # Métricas base
    base = metricas_muestras_por_promotor(df_muestras, fecha_inicio, fecha_fin, co=co, ids_autor=ids_autor)

    # Contactabilidad
    df_contact = fetch_contactabilidad_base(ciudad, fecha_inicio, fecha_fin, ids_autor=ids_autor)
    if not df_contact.empty:
        df_contact['contactable'] = df_contact['ultima_llamada'].notna() & (df_contact['ultima_llamada'] > df_contact['fecha_evento'])
        contactables = df_contact.groupby('id_autor', observed=True)['contactable'].sum().rename('muestras_contactables')
    else:
        contactables = pd.Series(0, index=base.set_index('id_autor').index if not base.empty else [], name='muestras_contactables')

    out = base.set_index('id_autor').join(contactables, how='left').fillna({'muestras_contactables': 0})
    out['muestras_contactables'] = out['muestras_contactables'].astype('int64')
    out['pct_contactables'] = 0.0
    den = out['muestras_total'] > 0
    out.loc[den, 'pct_contactables'] = (out.loc[den, 'muestras_contactables'] / out.loc[den, 'muestras_total']) * 100.0

    # Columnas vacías solicitadas
    out['M1'] = None
    out['M2'] = None
    out['M3'] = None
    out['muestras_m2'] = None

    # Orden de columnas de salida
    cols = [
        'muestras_total', 'dias_habiles', 'muestras_no_fieles', 'pct_no_fieles',
        'muestras_contactables', 'pct_contactables', 'M1', 'M2', 'M3', 'muestras_m2'
    ]
    # Asegurar id_autor como primera columna
    out = out.reset_index()
    out = out[['id_autor'] + cols]
    return out

def obtener_promotores_por_ids(ids):
    """
    Retorna dict {str(id_autor): nombre_completo} usando:
    SELECT p.id AS id_autor, p.apellido AS nombre_completo
    FROM fullclean_personal.personal p
    WHERE p.id IN (%s, %s, ...) AND p.id_cargo = 39;
    Solo incluye personal con cargo = 39 (promotores).
    """
    if not ids:
        return {}
    
    try:
        # Crear parámetros nombrados para la consulta IN
        param_dict = {}
        placeholders_named = []
        for i, vid in enumerate(ids):
            param_name = f'id_{i}'
            param_dict[param_name] = vid
            placeholders_named.append(f':{param_name}')
        
        placeholders_str = ','.join(placeholders_named)
        query = f"""
        SELECT 
            p.id AS id_autor, 
            p.apellido AS nombre_completo
        FROM 
            fullclean_personal.personal p
        WHERE 
            p.id IN ({placeholders_str})
            AND p.id_cargo = 39
        """
        
        df = sql_read(query, params=param_dict, schema="fullclean_personal")
        
        # Convertir a dict {str(id): nombre_completo}
        result = {}
        for _, row in df.iterrows():
            result[str(row['id_autor'])] = row['nombre_completo']
        
        return result
        
    except Exception as e:
        print(f"Error en obtener_promotores_por_ids: {e}")
        return {}

def obtener_metricas_pedidos_por_promotores(centroope, fecha_inicio, fecha_fin, ids_promotores):
    """
    Devuelve un DataFrame con columnas:
      - id_vendedor (INT)
      - cant_pedidos (INT)
      - valor_conIVA (FLOAT)  # SUM(p.total_conIVA)
      - venta_adq_recu (INT)  # Pedidos a categorías {10,22,38}
      - venta_fieles (INT)    # cant_pedidos - venta_adq_recu
      - pct_nrecu (FLOAT)     # % N/Recu = 100 × venta_adq_recu / cant_pedidos
      - pct_fieles (FLOAT)    # % Fieles = 100 - pct_nrecu
    
    Filtra por:
      - p.estado_pedido = 1
      - p.anulada = 0
      - p.autorizar IN (1,2)
      - p.autorizacion_descuento = 0
      - p.tipo_documento < 2
      - p.id_centroope = centroope
      - p.fecha_hora_pedido BETWEEN fecha_inicio 00:00:00 y fecha_fin 23:59:59
      - p.id_vendedor IN (lista de ids_promotores)
      
    Definiciones:
      - N/Recu: Nuevos + Recuperación + Perdidos reactivados (categorías 10, 22, 38)
      - Fieles: Resto de categorías (100% - % N/Recu)
    """
    if not ids_promotores:
        # Retorna DF vacío con las columnas esperadas
        return pd.DataFrame(columns=["id_vendedor", "cant_pedidos", "valor_conIVA"])

    # Normalizar parámetros
    ids = [int(x) for x in ids_promotores if str(x).strip()]
    
    try:
        # Convertir parámetros a formato dict para SQLAlchemy 2.x
        param_dict = {
            'centroope': centroope,
            'fecha_inicio': f"{fecha_inicio} 00:00:00",
            'fecha_fin': f"{fecha_fin} 23:59:59"
        }
        
        # Agregar parámetros de categorías ADQ/RECU
        for i, cat_id in enumerate(CATEGORIAS_ADQ_RECU):
            param_dict[f'cat_{i}'] = cat_id
        cat_placeholders = ",".join([f":cat_{i}" for i in range(len(CATEGORIAS_ADQ_RECU))])
        
        # Agregar parámetros de IDs de vendedores
        for i, vid in enumerate(ids):
            param_dict[f'vendedor_{i}'] = vid
        
        # Reescribir query con nombres de parámetros incluyendo JOIN y nuevas métricas
        placeholders_named = ",".join([f":vendedor_{i}" for i in range(len(ids))])
        query = f"""
            SELECT
                pe.id_vendedor AS id_vendedor,
                COUNT(*) AS cant_pedidos,
                SUM(pe.total_conIVA) AS valor_conIVA,
                SUM(CASE WHEN c.id_categoria IN ({cat_placeholders}) THEN 1 ELSE 0 END) AS venta_adq_recu
            FROM fullclean_telemercadeo.pedidos pe
            JOIN fullclean_contactos.vwContactos c ON c.id = pe.id_contacto
            WHERE
                pe.estado_pedido = 1
                AND pe.anulada = 0
                AND pe.autorizar IN (1,2)
                AND pe.autorizacion_descuento = 0
                AND pe.tipo_documento < 2
                AND pe.id_centroope = :centroope
                AND pe.fecha_hora_pedido BETWEEN :fecha_inicio AND :fecha_fin
                AND pe.id_vendedor IN ({placeholders_named})
            GROUP BY pe.id_vendedor
        """
        
        df = sql_read(query, params=param_dict, schema="fullclean_telemercadeo")
        
        # Post-proceso para calcular métricas derivadas
        if not df.empty:
            # Asegurar tipos base
            df["id_vendedor"] = df["id_vendedor"].astype("int64")
            df["cant_pedidos"] = df["cant_pedidos"].astype("int64") 
            df["valor_conIVA"] = df["valor_conIVA"].astype("float64")
            df["venta_adq_recu"] = df["venta_adq_recu"].fillna(0).astype("int64")
            
            # Calcular métricas derivadas
            df["venta_fieles"] = (df["cant_pedidos"] - df["venta_adq_recu"]).clip(lower=0).astype("int64")
            
            # Calcular porcentajes
            mask = df["cant_pedidos"] > 0
            df["pct_nrecu"] = 0.0
            df.loc[mask, "pct_nrecu"] = (df.loc[mask, "venta_adq_recu"] / df.loc[mask, "cant_pedidos"]) * 100.0
            df["pct_fieles"] = 100.0 - df["pct_nrecu"]
            
            # Asegurar tipos finales
            df["pct_nrecu"] = df["pct_nrecu"].astype("float64")
            df["pct_fieles"] = df["pct_fieles"].astype("float64")

        return df
    except Exception as e:
        print(f"Error en obtener_metricas_pedidos_por_promotores: {e}")
        return pd.DataFrame(columns=["id_vendedor", "cant_pedidos", "valor_conIVA", "venta_adq_recu", "venta_fieles", "pct_nrecu", "pct_fieles"])


def compute_ism_metrics_por_cuadrante(
    df_eventos,               # pd.DataFrame con columnas mínimas: lat, lon, fecha_evento, id_autor, id_contacto
    features_cuadrantes,      # list[feature GeoJSON] con geometry y properties[codigo_key]
    ciudad,                   # str (ej. 'CALI')
    codigo_key: str = 'codigo',
    tz: str = 'America/Bogota',
    hogares_por_m2_override: float = None,  # Override directo para hogares/m²
    pph_override: float = None              # Override para personas por hogar
) -> 'pd.DataFrame':
    """
    Calcula métricas ISM (Índice de Saturación del Mercado) por cuadrante.
    
    Agrega eventos por cuadrante y calcula:
    - C (Cobertura): muestras / hogares_estimados
    - E (Esfuerzo): muestras / (promotores * dias * lambda_promedio)  
    - ISM: media armónica de C y E escalada a 0-100
    
    Args:
        df_eventos: DataFrame con columnas lat, lon, fecha_evento, id_autor, id_contacto
        features_cuadrantes: Lista de features GeoJSON con geometry y properties[codigo_key]
        ciudad: Nombre de ciudad (ej. 'CALI') para obtener densidad demográfica
        codigo_key: Clave en properties para identificar cuadrantes (default: 'codigo')
        tz: Zona horaria para normalización de fechas (default: 'America/Bogota')
        hogares_por_m2_override: Override directo para hogares/m² (para calibración)
        pph_override: Override para personas por hogar (para calibración)
        
    Returns:
        pd.DataFrame con métricas ISM por cuadrante:
        - ciudad, codigo_cuadrante, area_m2, area_km2, hogares_por_m2, hogares_estimados
        - muestras_local, dias_operacion, n_promotores, lambda_q
        - C_raw, C, E_raw, E, ISM, over_flag
        
    Raises:
        ValueError: Si ciudad no tiene densidad_hab_km2 configurada y no se proveen overrides
        
    Notes:
        - Retorna DataFrame vacío con esquema completo si no hay eventos o cuadrantes
        - C y E se capan en 1.0, ISM usa media armónica: 2*C*E/(C+E) * 100
        - over_flag=True cuando cobertura raw > 100%
        - Overrides permiten calibración sin modificar configuración base
        - Maneja casos edge: divisiones por cero, cuadrantes sin eventos, etc.
    """
    
    # Esquema final de columnas esperado
    schema_final = [
        'ciudad', 'codigo_cuadrante',
        'area_m2', 'area_km2', 'hogares_por_m2', 'hogares_estimados',
        'muestras_local', 'dias_operacion', 'n_promotores',
        'lambda_q', 'C_raw', 'C', 'E_raw', 'E', 'ISM', 'over_flag'
    ]
    
    # Paso A — Normalización y guardas
    df = _normalize_eventos_columns(df_eventos, tz)
    
    if df.empty:
        return pd.DataFrame(columns=schema_final)
    
    if not features_cuadrantes:
        return pd.DataFrame(columns=schema_final)
    
    # Paso B — Asignar punto→cuadrante
    df['codigo_cuadrante'] = assign_quadrant_to_points(df[['lat','lon']], features_cuadrantes, codigo_key)
    
    df = df[df['codigo_cuadrante'].notna()]
    
    if df.empty:
        return pd.DataFrame(columns=schema_final)
    
    # Paso C — Constantes ciudad y áreas por código
    city_key = get_city_key(str(ciudad))
    
    # Obtener hogares_por_m2 con nueva función de override
    hogares_por_m2 = resolve_hogares_por_m2(
        city_key=city_key,
        hogares_por_m2_override=hogares_por_m2_override,
        pph_override=pph_override
    )
    
    # Construir cache de áreas una sola vez
    area_por_codigo = {}
    codigos_vistos = set()
    
    for feature in features_cuadrantes:
        codigo = feature['properties'].get(codigo_key)
        if codigo is None:
            # Saltar polígonos sin codigo_key
            continue
            
        if codigo in codigos_vistos:
            # Log warning para códigos duplicados y usar primera geometría
            print(f"WARNING: Código cuadrante duplicado '{codigo}', usando primera geometría encontrada")
            continue
            
        codigos_vistos.add(codigo)
        
        try:
            area_m2 = area_m2_geodesic(feature['geometry'])
            # Protección contra áreas 0 o NaN
            if pd.isna(area_m2) or area_m2 <= 0:
                area_m2 = 0.0
            area_por_codigo[codigo] = float(area_m2)
        except Exception:
            # Si falla cálculo de área, setear a 0.0
            area_por_codigo[codigo] = 0.0
    
    # Paso D — Agregados base por cuadrante
    g = df.groupby('codigo_cuadrante', observed=True)
    
    M = g.size().rename('muestras_local')
    N = g['id_autor'].nunique().rename('n_promotores') 
    D = g['fecha_dia'].nunique().rename('dias_operacion')
    
    # Paso E — Tasas por promotor y λ_q (dentro del cuadrante)
    gp = df.groupby(['codigo_cuadrante','id_autor'], observed=True)
    
    M_p = gp.size().rename('M_p')
    D_p = gp['fecha_dia'].nunique().rename('D_p')
    
    # Construir λ_p sólo donde D_p > 0
    tmp = pd.concat([M_p, D_p], axis=1)
    tmp = tmp[tmp['D_p'] > 0]
    tmp['lambda_p'] = tmp['M_p'] / tmp['D_p']
    
    lambda_q = tmp['lambda_p'].groupby(level=0, observed=True).mean().rename('lambda_q')
    
    # Paso F — DataFrame por cuadrante (join + constantes)
    df_q = M.to_frame().join([N, D, lambda_q], how='left')
    
    # Si un cuadrante no aparece en lambda_q ⇒ rellenar con 0.0
    df_q['lambda_q'] = df_q['lambda_q'].fillna(0.0)
    
    # Mapear áreas desde el cache
    df_q['area_m2'] = df_q.index.map(area_por_codigo).astype(float)
    df_q['area_km2'] = df_q['area_m2'] / 1_000_000.0
    df_q['hogares_por_m2'] = float(hogares_por_m2)  # constante por ciudad
    df_q['hogares_estimados'] = df_q['area_m2'] * df_q['hogares_por_m2']
    
    # Paso G — C, E e ISM (raw + capped) con protección de ceros/NaN
    
    # Cobertura
    df_q['C_raw'] = 0.0
    mask_H = df_q['hogares_estimados'] > 0
    df_q.loc[mask_H, 'C_raw'] = df_q.loc[mask_H, 'muestras_local'] / df_q.loc[mask_H, 'hogares_estimados']
    
    df_q['C'] = df_q['C_raw'].clip(upper=1.0)
    df_q['over_flag'] = df_q['C_raw'] > 1.0
    
    # Esfuerzo
    den_E = (df_q['n_promotores'] * df_q['dias_operacion'] * df_q['lambda_q']).astype(float)
    
    df_q['E_raw'] = 0.0
    mask_E = den_E > 0
    df_q.loc[mask_E, 'E_raw'] = df_q.loc[mask_E, 'muestras_local'] / den_E[mask_E]
    
    df_q['E'] = df_q['E_raw'].clip(upper=1.0)
    
    # ISM
    df_q['ISM'] = 0.0
    mask_ISM = (df_q['C'] + df_q['E']) > 0
    df_q.loc[mask_ISM, 'ISM'] = 100.0 * (2.0 * df_q.loc[mask_ISM, 'C'] * df_q.loc[mask_ISM, 'E']) / (df_q.loc[mask_ISM, 'C'] + df_q.loc[mask_ISM, 'E'])
    
    # Paso H — Columnas, orden, tipos y retorno
    
    # Añadir columna constante ciudad
    df_q['ciudad'] = city_key
    
    # Convertir índice a columna
    df_q.index.name = 'codigo_cuadrante'
    df_q = df_q.reset_index()
    
    # Asegurar tipos enteros en columnas específicas
    df_q['muestras_local'] = df_q['muestras_local'].astype(int)
    df_q['dias_operacion'] = df_q['dias_operacion'].astype(int)  
    df_q['n_promotores'] = df_q['n_promotores'].astype(int)
    
    # Orden exacto de salida (esquema final)
    df_q = df_q[schema_final]
    
    return df_q

# === Helpers de nombres de rutas (para tooltips/popup) ===

_RUTAS_CACHE = {}

def _cache_nombres_rutas(ciudad: str):
    """
    Devuelve {id_ruta:int -> nombre:str} cacheado por ciudad (clave en mayúsculas sin acentos).
    """
    key = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
    if key not in _RUTAS_CACHE:
        try:
            df = listar_rutas_simple(key)  # columnas: id_ruta, ruta
            _RUTAS_CACHE[key] = {int(r.id_ruta): str(r.ruta) for _, r in df.iterrows()} if df is not None and not df.empty else {}
        except Exception as e:
            logging.warning(f"[RUTAS] No fue posible cargar nombres de rutas para {key}: {e}")
            _RUTAS_CACHE[key] = {}
    return _RUTAS_CACHE[key]

def _parse_id_ruta_desde_codigo(codigo: str):
    """
    Extrae id_ruta desde patrones estilo 'CL_ruta_37_01'. Devuelve int o None.
    """
    if not isinstance(codigo, str):
        return None
    m = re.search(r"_ruta_(\d+)_", codigo)
    return int(m.group(1)) if m else None

def resolver_nombre_ruta(ciudad: str, codigo: str, props: dict | None = None) -> str:
    """
    1) Si el GeoJSON trae nombre en properties, úsalo.
    2) Si no, parsea id_ruta del código y consulta cache BD.
    3) Fallback: devuelve 'codigo'.
    """
    if props:
        for k in ("nom_ruta", "nombre_ruta", "ruta", "nombre", "name"):
            if k in props and str(props[k]).strip():
                return str(props[k]).strip()

    rid = _parse_id_ruta_desde_codigo(codigo)
    if rid is not None:
        nombres = _cache_nombres_rutas(ciudad)
        if rid in nombres and str(nombres[rid]).strip():
            return str(nombres[rid]).strip()
    return str(codigo or "")
