import os
import pandas as pd
import mysql.connector
import unicodedata
from datetime import date

# --- Resolver CO por ciudad (reusar mapping de otros módulos) ---
CENTROOPES = {'CALI':2,'MEDELLIN':3,'MANIZALES':6,'PEREIRA':5,'BOGOTA':4,'BARRANQUILLA':8,'BUCARAMANGA':7}
def get_co(ciudadN:str)->int:
    return CENTROOPES[ciudadN]

def _norm_city(ciudad: str) -> str:
    """Normalizar ciudad removiendo acentos y convirtiendo a mayúsculas."""
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

def _conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD")
    )

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

def eventos_por_ruta_en_rango(centroope:int, id_ruta:int, f_ini:str, f_fin:str)->pd.DataFrame:
    """
    Retorna todos los eventos de la ruta en el rango de fechas con coordenadas válidas.
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
