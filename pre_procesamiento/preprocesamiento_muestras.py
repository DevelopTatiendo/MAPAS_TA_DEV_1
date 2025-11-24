import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os
import mysql.connector
import warnings
from typing import List, Dict
import logging
import re
import unicodedata
from .db_utils import sql_read
# Wrappers de métricas de área para Muestras
try:
    from .metricas_areas import (
        areas_muestras_resumen,
        areas_muestras_auditoria,
        calcular_areas_por_promotor,  # opcional si se usa en otros contextos
    )
except Exception:
    try:
        from metricas_areas import (
            areas_muestras_resumen,
            areas_muestras_auditoria,
            calcular_areas_por_promotor,
        )
    except Exception:
        areas_muestras_resumen = None
        areas_muestras_auditoria = None
        calcular_areas_por_promotor = None
from utils.spatial_ops import assign_quadrant_to_points, area_m2_geodesic
# (Eliminado) imports exclusivos de ISM
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


def _dbg_db(msg: str) -> None:
    # print(f"[DB-TRACE][MUESTRAS] {msg}")  # DEBUG deshabilitado
    pass


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
    
    _dbg_db("listar_promotores() → SELECT promotores (cargo=39) en fullclean_personal")
    df = sql_read(query, schema="fullclean_personal")
    
    # Asegurar tipos de datos apropiados
    if not df.empty:
        df['id_autor'] = df['id_autor'].astype('int64')
        df['apellido'] = df['apellido'].fillna('').astype(str)
    
    return df

def obtener_nombre_promotor(id_autor: int) -> str | None:
    """
    Retorna el nombre del promotor basado en su ID.
    Consulta la tabla fullclean_personal.personal.
    Si no encuentra el ID, retorna None.
    """
    try:
        query = """
            SELECT id, apellido AS nombre
            FROM fullclean_personal.personal
            WHERE id = :id_autor
            LIMIT 1
        """
        _dbg_db(f"obtener_nombre_promotor(id_autor={id_autor}) → consulta 1 fila en fullclean_personal")
        df = sql_read(query, params={"id_autor": id_autor}, schema="fullclean_personal")
        if df is None or df.empty:
            return None
        nombre = df.loc[0, "nombre"]
        if nombre is None:
            return None
        return str(nombre).strip()
    except Exception as e:
        print(f"[WARN] obtener_nombre_promotor({id_autor}) falló: {e}")
        return None

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
    _dbg_db(f"filtrar_ids_por_cargo(cargo={cargo}, n_ids={len(ids)}) → filtro en fullclean_personal")
    df = sql_read(query, params=param_dict, schema="fullclean_personal")
    return df['id'].astype(int).tolist() if not df.empty else []

def consultar_muestras_db(centroope, fecha_inicio, fecha_fin, promotores=None):
    """
    Consulta la base de datos para obtener los eventos de muestras filtrados por centroope y fechas.
    Solo incluye autores que sean promotores (cargo = 39).
    Retorna un DataFrame.
    """
    # (Refactor Fase 1) Eliminado pre-filtrado adicional por cargo; el JOIN ya restringe a promotores (id_cargo=39).
    
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
        con.ultima_llamada AS ultima_llamada,
        bar.id        AS id_barrio,
        bar.barrio    AS barrio,
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
    
    n_prom = len(promotores) if promotores is not None else 0
    _dbg_db(f"consultar_muestras_db(centroope={centroope}, rango={fecha_inicio}→{fecha_fin}, n_promotores={n_prom}) → vwEventos/fullclean_contactos")
    df = sql_read(query, params=param_dict, schema="fullclean_contactos")
    return df


def crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, promotores=None, agentes=None):
    """
    Crea un DataFrame final al combinar los datos de la base de datos con las coordenadas de los barrios.
    Retorna un DataFrame listo para usar.
    """
    # Obtener datos de muestras directamente desde BD (sin CSV barrios)
    df_muestras = consultar_muestras_db(centroope, fecha_inicio, fecha_fin, promotores)
    df_muestras_completo = df_muestras.copy()

    # Asegurar tipos básicos requeridos por nuevas métricas
    if 'fecha_evento' in df_muestras_completo.columns and not pd.api.types.is_datetime64_any_dtype(df_muestras_completo['fecha_evento']):
        df_muestras_completo['fecha_evento'] = pd.to_datetime(df_muestras_completo['fecha_evento'], errors='coerce')
    if 'ultima_llamada' in df_muestras_completo.columns and not pd.api.types.is_datetime64_any_dtype(df_muestras_completo['ultima_llamada']):
        df_muestras_completo['ultima_llamada'] = pd.to_datetime(df_muestras_completo['ultima_llamada'], errors='coerce')

    # Lista de columnas deseadas mínimas garantizadas para métricas nuevas
    columnas_minimas = [
        'id_autor', 'fecha_evento', 'id_evento_tipo', 'id_contacto',
        'id_contacto_categoria', 'ultima_llamada', 'coordenada_latitud', 'coordenada_longitud'
    ]

    # Lista ampliada de columnas útiles para otros flujos existentes
    columnas_deseadas = columnas_minimas + [
        'id_muestra', 'tipo_evento', 'tipo_categoria', 'id_barrio', 'barrio'
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

def metricas_areas_muestras(
    df_muestras: pd.DataFrame,
    centroope: int | None,
    origen: str = "mapa_muestras",
) -> pd.DataFrame:
    """
    Wrapper de alto nivel para obtener métricas de área de muestreo
    asociadas al módulo de Muestras.

    - origen="mapa_muestras":
        Uso actual en modo normal. Devuelve df con columnas:
            * id_autor
            * area_m2
        Delegando en `metricas_areas.areas_muestras_resumen`.

    - origen="mapa_muestras_auditoria":
        Uso futuro en modo auditoría. En esta fase se deja solo el esqueleto;
        el cálculo real y el GeoJSON se implementarán cuando exista
        `mapa_muestras_auditoria`.

    En esta fase:
    - NO se modifican ni los mapas ni las tablas visibles.
    - `mapa_muestras` seguirá llamando a esta función sin cambiar su firma
      (se apoya en el valor por defecto origen="mapa_muestras").
    """
    if df_muestras is None or df_muestras.empty:
        return pd.DataFrame(columns=["id_autor", "area_m2"])

    if origen == "mapa_muestras":
        # Modo normal: resumen por promotor
        if areas_muestras_resumen is None:
            return pd.DataFrame(columns=["id_autor", "area_m2"])
        return areas_muestras_resumen(df_muestras, centroope)

    elif origen == "mapa_muestras_auditoria":
        # Placeholder para modo auditoría (aún no utilizado aquí)
        return pd.DataFrame(columns=["id_autor", "area_m2"])

    else:
        raise ValueError(f"Origen desconocido para metricas_areas_muestras: {origen}")

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
    # % Muestras contactables (NO fieles) = contactables_no_fieles / no_fieles * 100
    out['pct_contactables_nofieles'] = 0.0
    mask_den = out['muestras_no_fieles'] > 0
    out.loc[mask_den, 'pct_contactables_nofieles'] = (
        out.loc[mask_den, 'muestras_contactables_nofieles'] / out.loc[mask_den, 'muestras_no_fieles'] ) * 100.0
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

        n_autores = len(ids_autor) if ids_autor else 0
        _dbg_db(f"fetch_contactabilidad_base(ciudad={ciudad}, rango={fecha_inicio}→{fecha_fin}, n_autores={n_autores}) → vwEventos/fullclean_contactos")
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

def prepo_metricas_promotores_muestras(
    ciudad: str,
    fecha_inicio: str,
    fecha_fin: str,
    ids_autor=None,
    df_muestras: pd.DataFrame | None = None,
    df_areas_precalculadas: pd.DataFrame | None = None,
) -> pd.DataFrame:
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
    # Si no se pasa un DataFrame, consultar BD (modo legacy). Si se pasa, reutilizarlo.
    if df_muestras is None:
        df_muestras = consultar_muestras_db(co, fecha_inicio, fecha_fin, promotores=ids_autor)
    else:
        df_muestras = df_muestras.copy()
        if ids_autor is not None:
            try:
                df_muestras = df_muestras[df_muestras['id_autor'].isin(ids_autor)]
            except Exception:
                pass

    # Normalizar tipos base necesarios
    if not df_muestras.empty:
        if not pd.api.types.is_datetime64_any_dtype(df_muestras['fecha_evento']):
            df_muestras['fecha_evento'] = pd.to_datetime(df_muestras['fecha_evento'], errors='coerce')
        if 'ultima_llamada' in df_muestras.columns and not pd.api.types.is_datetime64_any_dtype(df_muestras['ultima_llamada']):
            df_muestras['ultima_llamada'] = pd.to_datetime(df_muestras['ultima_llamada'], errors='coerce')

    # Filtro rango fecha por seguridad
    if not df_muestras.empty:
        f_ini = pd.to_datetime(f"{fecha_inicio} 00:00:00", errors='coerce')
        f_fin = pd.to_datetime(f"{fecha_fin} 23:59:59", errors='coerce')
        df_muestras = df_muestras[(df_muestras['fecha_evento'] >= f_ini) & (df_muestras['fecha_evento'] <= f_fin)]

    if df_muestras.empty:
        return pd.DataFrame(columns=[
            'id_autor','muestras_total','dias_habiles','muestras_no_fieles','pct_no_fieles',
            'muestras_contactables','pct_contactables','muestras_contactables_nofieles','pct_contactables_nofieles',
            'area_m2','muestras_area'
        ])

    df_work = df_muestras.copy()
    # dias_habiles
    df_work['fecha_dia'] = df_work['fecha_evento'].dt.date
    conteo_dia = df_work.groupby(['id_autor','fecha_dia'], observed=True).size().rename('n_dia')
    dias_hab = (conteo_dia >= 2).groupby(level=0, observed=True).sum().rename('dias_habiles')

    # muestras_total
    totales = df_work.groupby('id_autor', observed=True).size().rename('muestras_total')

    # no fieles
    if 'id_contacto_categoria' in df_work.columns:
        cats = pd.to_numeric(df_work['id_contacto_categoria'], errors='coerce')
        mask_nf = ~cats.isna() & ~cats.astype('Int64').isin(list(CATEGORIAS_FIELES))
        muestras_nf = mask_nf.groupby(df_work['id_autor'], observed=True).sum().rename('muestras_no_fieles')
    else:
        muestras_nf = pd.Series(0, index=totales.index, name='muestras_no_fieles')

    # contactables
    if 'ultima_llamada' in df_work.columns:
        df_work['contactable'] = df_work['ultima_llamada'].notna() & (df_work['ultima_llamada'] > df_work['fecha_evento'])
        contactables = df_work.groupby('id_autor', observed=True)['contactable'].sum().rename('muestras_contactables')
    else:
        contactables = pd.Series(0, index=totales.index, name='muestras_contactables')

    # contactables no fieles
    if 'id_contacto_categoria' in df_work.columns and 'contactable' in df_work.columns:
        df_work['contactable_nf'] = mask_nf & df_work['contactable']
        contactables_nf = df_work.groupby('id_autor', observed=True)['contactable_nf'].sum().rename('muestras_contactables_nofieles')
    else:
        contactables_nf = pd.Series(0, index=totales.index, name='muestras_contactables_nofieles')

    out = (
        totales.to_frame()
        .join(dias_hab, how='left')
        .join(muestras_nf, how='left')
        .join(contactables, how='left')
        .join(contactables_nf, how='left')
        .fillna({'dias_habiles':0,'muestras_no_fieles':0,'muestras_contactables':0,'muestras_contactables_nofieles':0})
    )

    # porcentajes
    out['pct_no_fieles'] = 0.0
    mask_tot = out['muestras_total'] > 0
    out.loc[mask_tot, 'pct_no_fieles'] = (out.loc[mask_tot,'muestras_no_fieles'] / out.loc[mask_tot,'muestras_total'])*100.0

    out['pct_contactables'] = 0.0
    out.loc[mask_tot, 'pct_contactables'] = (out.loc[mask_tot,'muestras_contactables'] / out.loc[mask_tot,'muestras_total'])*100.0

    # % Muestras contactables dentro de los NO fieles
    out['pct_contactables_nofieles'] = np.nan
    mask_nf_den = out['muestras_no_fieles'] > 0
    out.loc[mask_nf_den, 'pct_contactables_nofieles'] = (
        out.loc[mask_nf_den, 'muestras_contactables_nofieles'] / out.loc[mask_nf_den, 'muestras_no_fieles']
    ) * 100.0
    # Opcional: evitar mostrar 0.0 cuando no hay datos
    out['pct_contactables_nofieles'] = out['pct_contactables_nofieles'].replace(0.0, np.nan)

    # tipos
    for c in ['muestras_total','dias_habiles','muestras_no_fieles','muestras_contactables','muestras_contactables_nofieles']:
        out[c] = out[c].astype('int64')
    for c in ['pct_no_fieles','pct_contactables','pct_contactables_nofieles']:
        out[c] = out[c].astype('float64')

    # --- Integrar métricas de área por promotor (M2) ---
    # Reutilizar áreas pre-calculadas si se proveen para evitar recomputar (optimización rendimiento)
    if df_areas_precalculadas is not None:
        try:
            df_areas = df_areas_precalculadas.copy()
        except Exception:
            df_areas = pd.DataFrame(columns=["id_autor", "area_m2"])
    else:
        try:
            df_areas = metricas_areas_muestras(df_muestras, co, origen="mapa_muestras")
        except Exception as e:
            logging.error(f"Error en metricas_areas_muestras: {e}")
            df_areas = pd.DataFrame(columns=["id_autor", "area_m2"])

    if not df_areas.empty:
        df_areas = df_areas.set_index("id_autor")
        out = out.join(df_areas, how="left")
    else:
        out['area_m2'] = np.nan

    # Muestras por unidad de área
    out['muestras_area'] = np.nan
    mask_area = out['area_m2'].notna() & (out['area_m2'] > 0)
    out.loc[mask_area, 'muestras_area'] = (
        out.loc[mask_area, 'muestras_total'].astype(float) /
        out.loc[mask_area, 'area_m2'].astype(float)
    )

    out = out.reset_index()
    out = out[[
        'id_autor','muestras_total','dias_habiles','muestras_no_fieles','pct_no_fieles',
        'muestras_contactables','pct_contactables','muestras_contactables_nofieles','pct_contactables_nofieles',
        'area_m2','muestras_area'
    ]]
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
        
        _dbg_db(f"obtener_promotores_por_ids(n_ids={len(ids)}) → fullclean_personal")
        df = sql_read(query, params=param_dict, schema="fullclean_personal")
        
        # Convertir a dict {str(id): nombre_completo}
        result = {}
        for _, row in df.iterrows():
            result[str(row['id_autor'])] = row['nombre_completo']
        
        return result
        
    except Exception as e:
        print(f"Error en obtener_promotores_por_ids: {e}")
        return {}

# (Deprecado) obtener_metricas_pedidos_por_promotores eliminado: ya no se usa en módulo de Directores


# (Eliminado) compute_ism_metrics_por_cuadrante y toda lógica ISM

# === Helpers de nombres de rutas (para tooltips/popup) ===

_RUTAS_CACHE = {}

def _cache_nombres_rutas(ciudad: str):
    """
    Devuelve {id_ruta:int -> nombre:str} cacheado por ciudad (clave en mayúsculas sin acentos).
    """
    key = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
    if key not in _RUTAS_CACHE:
        try:
            _dbg_db(f"_cache_nombres_rutas(ciudad={ciudad}) → listar_rutas_simple(key={key}) [INDIRECTO BD]")
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
