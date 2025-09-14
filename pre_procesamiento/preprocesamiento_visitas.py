import os
import pandas as pd
import mysql.connector
import unicodedata
import logging
import time
from datetime import date
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

def ping_db():
    """Prueba básica de conectividad a la base de datos."""
    try:
        conn = _conn()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        logging.info("Ping BD exitoso")
        return result is not None
    except Exception as e:
        logging.error(f"Ping BD falló: {e}")
        return False

def listar_rutas_simple(ciudad:str)->pd.DataFrame:
    """Devuelve id_ruta, ruta para la ciudad (sin depender de eventos)."""
    # Normalizar ciudad removiendo acentos
    ciudad_norm = _norm_city(ciudad)
    co = get_co(ciudad_norm)
    
    q = """
    SELECT r.id AS id_ruta, r.ruta
    FROM fullclean_contactos.rutas_cobro r
    WHERE r.id_centroope = %s
    ORDER BY r.ruta;
    """
    cn = _conn()
    df = pd.read_sql(q, cn, params=[co])
    cn.close()
    return df

def eventos_visitas_por_ruta_en_rango(centroope:int, id_ruta:int, f_ini:str, f_fin:str)->pd.DataFrame:
    """
    Retorna todos los eventos de visitas de la ruta en el rango de fechas con coordenadas válidas.
    Columnas: id_evento, id_contacto, lat, lon, fecha_evento, id_cargo, cargo
    """
    q = """
    SELECT  e.idEvento            AS id_evento,
            e.id_contacto         AS id_contacto,
            e.coordenada_latitud  AS lat,
            e.coordenada_longitud AS lon,
            e.fecha_evento,
            p.id_cargo            AS id_cargo,
            ca.cargo              AS cargo
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_contactos.vwContactos c           ON c.id = e.id_contacto
    JOIN fullclean_contactos.barrios b               ON b.id = c.id_barrio
    JOIN fullclean_contactos.rutas_cobro_zonas rc    ON rc.id_barrio = b.id
    JOIN fullclean_contactos.rutas_cobro r           ON r.id = rc.id_ruta_cobro
    JOIN fullclean_personal.personal p               ON p.id = e.id_autor
    JOIN fullclean_personal.cargos ca                ON ca.Id_cargo = p.id_cargo
    WHERE c.estado = 1
      AND c.estado_cxc IN (0,1)
      AND r.id_centroope = %s
      AND r.id = %s
      AND e.fecha_evento BETWEEN %s AND %s
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
      AND e.coordenada_latitud  BETWEEN -5 AND 13
      AND e.coordenada_longitud BETWEEN -81 AND -66
       AND ca.Id_cargo = 181
      -- AND ca.Id_cargo in (181, 5)
    ORDER BY e.fecha_evento ASC;
    """
    cn = _conn()
    df = pd.read_sql(q, cn, params=[centroope, id_ruta, f_ini, f_fin])
    cn.close()
    
    # Normalizar tipos por seguridad
    if not df.empty:
        df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
        df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
        df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
        df = df.dropna(subset=['lat','lon'])
    return df

def nombre_ruta(centroope: int, id_ruta: int) -> str:
    """
    Retorna el nombre de la ruta (r.ruta) para el CO e id_ruta dados.
    Si no encuentra, retorna None.
    """
    q = """
    SELECT r.ruta
    FROM fullclean_contactos.rutas_cobro r
    WHERE r.id_centroope = %s AND r.id = %s
    LIMIT 1;
    """
    cn = _conn()
    df = pd.read_sql(q, cn, params=[centroope, id_ruta])
    cn.close()
    return None if df.empty else str(df.iloc[0]['ruta'])

def eventos_visitas_con_coordenadas_por_ruta_y_rango(id_centroope: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Trae todos los eventos de visitas con coordenadas válidas para la ruta y rango especificados.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro
        f_ini (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        f_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_evento', 'id_contacto', 'id_consultor', 'apellido', 
                     'lat', 'lon', 'fecha_evento', 'id_evento_tipo', 'es_visita', 'cargo']
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando eventos_visitas_con_coordenadas_por_ruta_y_rango - CO:{id_centroope}, Ruta:{id_ruta}, Rango:{f_ini} a {f_fin}")
    
    q = """
    SELECT 
        e.idEvento                AS id_evento,
        e.id_contacto             AS id_contacto,
        p.id                      AS id_consultor,
        p.apellido                AS apellido,
        e.coordenada_latitud      AS lat,
        e.coordenada_longitud     AS lon,
        e.fecha_evento            AS fecha_evento,
        e.id_evento_tipo          AS id_evento_tipo,
        1                         AS es_visita,
        ca.cargo                  AS cargo
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_contactos.vwContactos c           ON c.id = e.id_contacto
    JOIN fullclean_contactos.barrios b               ON b.id = c.id_barrio
    JOIN fullclean_contactos.rutas_cobro_zonas rc    ON rc.id_barrio = b.id
    JOIN fullclean_contactos.rutas_cobro r           ON r.id = rc.id_ruta_cobro
    JOIN fullclean_personal.personal p               ON p.id = e.id_autor
    JOIN fullclean_personal.cargos ca                ON ca.Id_cargo = p.id_cargo
    WHERE 
          c.estado = 1
      AND c.estado_cxc IN (0,1)
      AND r.id_centroope = 2
      AND r.id = 780
      AND e.fecha_evento BETWEEN %s AND %s
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
      AND e.coordenada_latitud  BETWEEN -5  AND 13
      AND e.coordenada_longitud BETWEEN -81 AND -66
       -- AND ca.Id_cargo = 181
     AND ca.Id_cargo in (181, 5)
    ORDER BY 
        e.fecha_evento ASC,
        p.id ASC,
        e.id_contacto ASC;
    """
    
    try:
        cn = _conn()
        df = pd.read_sql(q, cn, params=[id_centroope, id_ruta, f_ini, f_fin])
        cn.close()
        
        # Normalizar tipos de datos
        if not df.empty:
            df['id_evento'] = pd.to_numeric(df['id_evento'], errors='coerce')
            df['id_contacto'] = pd.to_numeric(df['id_contacto'], errors='coerce')
            df['id_consultor'] = pd.to_numeric(df['id_consultor'], errors='coerce')
            df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
            df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
            df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
            df['id_evento_tipo'] = pd.to_numeric(df['id_evento_tipo'], errors='coerce')
            df['es_visita'] = pd.to_numeric(df['es_visita'], errors='coerce').fillna(1).astype(int)
            df['apellido'] = df['apellido'].fillna('').astype(str)
            df['cargo'] = df['cargo'].fillna('').astype(str)
            
            # Eliminar filas con coordenadas inválidas después de conversión
            df = df.dropna(subset=['lat', 'lon', 'fecha_evento'])
            
            # Validar coordenadas realistas
            df = df[
                (df['lat'].between(-5, 13)) & 
                (df['lon'].between(-81, -66))
            ]
        
        # Logging de tiempo de ejecución y tamaño
        tiempo_ejecucion = time.time() - inicio_tiempo
        filas_resultado = len(df)
        logging.info(f"eventos_visitas_con_coordenadas_por_ruta_y_rango completada en {tiempo_ejecucion:.2f}s - {filas_resultado} eventos retornados")
        
        return df
        
    except Exception as e:
        logging.error(f"Error en eventos_visitas_con_coordenadas_por_ruta_y_rango: {str(e)}")
        raise e

def consultores_metricas_visitas_por_ruta_y_rango(id_centroope: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Ejecuta consulta SQL agregada por consultor para obtener métricas de visitas realizadas.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro
        f_ini (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        f_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_consultor', 'apellido', 'cant_visitas']
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando consultores_metricas_visitas_por_ruta_y_rango - CO:{id_centroope}, Ruta:{id_ruta}, Rango:{f_ini} a {f_fin}")
    
    # Consulta SQL parametrizada siguiendo exactamente el patrón del Gestor
    q = """
    SELECT
        p.id  AS id_consultor,
        p.apellido,
        COUNT(e.idEvento) AS cant_visitas
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_contactos.vwContactos c           ON c.id = e.id_contacto
    JOIN fullclean_contactos.barrios b               ON b.id = c.id_barrio
    JOIN fullclean_contactos.rutas_cobro_zonas rc    ON rc.id_barrio = b.id
    JOIN fullclean_contactos.rutas_cobro r           ON r.id = rc.id_ruta_cobro
    JOIN fullclean_personal.personal p               ON p.id = e.id_autor
    JOIN fullclean_personal.cargos ca                ON ca.Id_cargo = p.id_cargo
    WHERE
          c.estado = 1
      AND c.estado_cxc IN (0,1)
      AND r.id_centroope = %s
      AND r.id = %s
      AND e.fecha_evento BETWEEN %s AND %s
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
      AND e.coordenada_latitud  BETWEEN -5  AND 13
      AND e.coordenada_longitud BETWEEN -81 AND -66
      AND ca.Id_cargo = 181
    GROUP BY
        p.id, p.apellido
    ORDER BY
        cant_visitas DESC;
    """
    
    try:
        cn = _conn()
        df = pd.read_sql(q, cn, params=[id_centroope, id_ruta, f_ini, f_fin])
        cn.close()
        
        # Asegurar tipos de datos correctos
        if not df.empty:
            df['id_consultor'] = pd.to_numeric(df['id_consultor'], errors='coerce')
            df['cant_visitas'] = pd.to_numeric(df['cant_visitas'], errors='coerce').fillna(0).astype(int)
            df['apellido'] = df['apellido'].fillna('').astype(str)
        
        # Logging de tiempo de ejecución y tamaño
        tiempo_ejecucion = time.time() - inicio_tiempo
        filas_resultado = len(df)
        logging.info(f"consultores_metricas_visitas_por_ruta_y_rango completada en {tiempo_ejecucion:.2f}s - {filas_resultado} filas retornadas")
        
        return df
        
    except Exception as e:
        logging.error(f"Error en consultores_metricas_visitas_por_ruta_y_rango: {str(e)}")
        raise e

def eventos_visitas_no_agrupado_fijo() -> pd.DataFrame:
    """
    Ejecuta consulta SQL fija para modo "No agrupado" sin parámetros variables.
    Valores hardcodeados según especificación del Gerente:
    - id_centroope = 2 (CALI)
    - id_ruta = 780 (16 PALMIRA)
    - Rango de fechas: "2024-01-01" a "2025-09-01"
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_evento', 'id_contacto', 'id_consultor', 'apellido', 
                     'lat', 'lon', 'fecha_evento', 'id_evento_tipo', 'es_visita', 'cargo']
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info("Iniciando eventos_visitas_no_agrupado_fijo - Consulta SQL fija sin parámetros")
    
    # Consulta SQL completamente fija según especificación del Gerente
    q = """
    SELECT 
        e.idEvento                AS id_evento,
        e.id_contacto             AS id_contacto,
        p.id                      AS id_consultor,
        p.apellido                AS apellido,
        e.coordenada_latitud      AS lat,
        e.coordenada_longitud     AS lon,
        e.fecha_evento            AS fecha_evento,
        e.id_evento_tipo          AS id_evento_tipo,
        1                         AS es_visita,
        ca.cargo                  AS cargo
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_contactos.vwContactos c           ON c.id = e.id_contacto
    JOIN fullclean_contactos.barrios b               ON b.id = c.id_barrio
    JOIN fullclean_contactos.rutas_cobro_zonas rc    ON rc.id_barrio = b.id
    JOIN fullclean_contactos.rutas_cobro r           ON r.id = rc.id_ruta_cobro
    JOIN fullclean_personal.personal p               ON p.id = e.id_autor
    JOIN fullclean_personal.cargos ca                ON ca.Id_cargo = p.id_cargo
    WHERE 
          c.estado = 1
      AND c.estado_cxc IN (0,1)
      AND r.id_centroope = 2
      AND r.id = 780
      AND e.fecha_evento BETWEEN "2024-01-01" AND "2025-09-01"
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
      AND e.coordenada_latitud  BETWEEN -5  AND 13
      AND e.coordenada_longitud BETWEEN -81 AND -66
       -- AND ca.Id_cargo = 181
      AND ca.Id_cargo in (181, 5)
    ORDER BY 
        e.fecha_evento ASC,
        p.id ASC,
        e.id_contacto ASC;
    """
    
    try:
        cn = _conn()
        # Ejecutar consulta sin parámetros (todo hardcodeado)
        df = pd.read_sql(q, cn)
        cn.close()
        
        # Normalizar tipos de datos
        if not df.empty:
            df['id_evento'] = pd.to_numeric(df['id_evento'], errors='coerce')
            df['id_contacto'] = pd.to_numeric(df['id_contacto'], errors='coerce')
            df['id_consultor'] = pd.to_numeric(df['id_consultor'], errors='coerce')
            df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
            df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
            df['fecha_evento'] = pd.to_datetime(df['fecha_evento'], errors='coerce')
            df['id_evento_tipo'] = pd.to_numeric(df['id_evento_tipo'], errors='coerce')
            df['es_visita'] = pd.to_numeric(df['es_visita'], errors='coerce').fillna(1).astype(int)
            df['apellido'] = df['apellido'].fillna('').astype(str)
            df['cargo'] = df['cargo'].fillna('').astype(str)
            
            # Eliminar filas con coordenadas inválidas después de conversión
            df = df.dropna(subset=['lat', 'lon', 'fecha_evento'])
            
            # Validar coordenadas realistas
            df = df[
                (df['lat'].between(-5, 13)) & 
                (df['lon'].between(-81, -66))
            ]
        
        # Logging de tiempo de ejecución y tamaño
        tiempo_ejecucion = time.time() - inicio_tiempo
        filas_resultado = len(df)
        logging.info(f"eventos_visitas_no_agrupado_fijo completada en {tiempo_ejecucion:.2f}s - {filas_resultado} eventos retornados (SQL fijo: CO=2, ruta=780, 2024-01-01 a 2025-09-01)")
        
        return df
        
    except Exception as e:
        logging.error(f"Error en eventos_visitas_no_agrupado_fijo: {str(e)}")
        raise e

# === FUNCIONES DE COMPATIBILIDAD HACIA ATRÁS ===

def consultar_visitas_db(centroope, id_ruta, fecha_inicio, fecha_fin):
    """
    Función de compatibilidad hacia atrás. Usa la nueva función mejorada.
    DEPRECADA: Usar eventos_visitas_por_ruta_en_rango() en su lugar.
    """
    logging.warning("consultar_visitas_db está deprecada. Usar eventos_visitas_por_ruta_en_rango() en su lugar.")
    return eventos_visitas_por_ruta_en_rango(centroope, id_ruta, fecha_inicio, fecha_fin)

def crear_df(centroope, id_ruta, fecha_inicio, fecha_fin, ruta_coordenadas):
    """
    Función de compatibilidad hacia atrás.
    DEPRECADA: Usar las nuevas funciones específicas en su lugar.
    """
    logging.warning("crear_df está deprecada. Usar eventos_visitas_con_coordenadas_por_ruta_y_rango() en su lugar.")
    
    try:
        # Obtener datos de visitas desde la base de datos usando la nueva función
        df_visitas = eventos_visitas_con_coordenadas_por_ruta_y_rango(centroope, id_ruta, fecha_inicio, fecha_fin)
        
        if df_visitas.empty:
            logging.info("No se encontraron visitas para los parámetros dados")
            return pd.DataFrame()
            
        # Si se proporciona ruta de coordenadas, intentar merge (para compatibilidad)
        if ruta_coordenadas and os.path.exists(ruta_coordenadas):
            try:
                df_coord = pd.read_csv(ruta_coordenadas)
                if 'id_barrio' in df_coord.columns and 'id_barrio' in df_visitas.columns:
                    df_visitas_completo = pd.merge(df_visitas, df_coord, how='left', on='id_barrio')
                else:
                    df_visitas_completo = df_visitas
            except Exception as e:
                logging.error(f"Error leyendo coordenadas de {ruta_coordenadas}: {e}")
                df_visitas_completo = df_visitas
        else:
            df_visitas_completo = df_visitas
            
        # Lista de columnas deseadas (ajustar según archivos existentes)
        columnas_deseadas = [
            'id_evento', 'id_contacto', 'fecha_evento', 'id_consultor', 'lon', 'lat',
            'id_evento_tipo', 'es_visita', 'apellido', 'cargo'
        ]
        
        # Filtrar solo las columnas que existen
        columnas_existentes = [col for col in columnas_deseadas if col in df_visitas_completo.columns]
        df_visitas_completo = df_visitas_completo[columnas_existentes]
        
        # Renombrar por compatibilidad
        if 'barrio_x' in df_visitas_completo.columns:
            df_visitas_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)
            
        return df_visitas_completo
        
    except Exception as e:
        logging.error(f"Error en crear_df (función de compatibilidad): {str(e)}")
        return pd.DataFrame()
