import os
import pandas as pd
import mysql.connector
import unicodedata
import logging
import time
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

def eventos_con_coordenadas_por_ruta_y_rango(id_centroope: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Trae todos los eventos con coordenadas válidas para la ruta y rango especificados.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro
        f_ini (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        f_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_evento', 'id_contacto', 'id_consultor', 'apellido', 
                     'lat', 'lon', 'fecha_evento', 'id_evento_tipo', 'es_visita', 'es_apertura', 'es_venta_evento']
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando eventos_con_coordenadas_por_ruta_y_rango - CO:{id_centroope}, Ruta:{id_ruta}, Rango:{f_ini} a {f_fin}")
    
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
        CASE 
            WHEN e.id_evento_tipo IN (73,62,71,64,74) THEN 1 
            ELSE 0 
        END                       AS es_apertura,
        CASE 
            WHEN e.id_evento_tipo = 58 THEN 1 
            ELSE 0 
        END                       AS es_venta_evento
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
            df['es_visita'] = pd.to_numeric(df['es_visita'], errors='coerce').fillna(0).astype(int)
            df['es_apertura'] = pd.to_numeric(df['es_apertura'], errors='coerce').fillna(0).astype(int)
            df['es_venta_evento'] = pd.to_numeric(df['es_venta_evento'], errors='coerce').fillna(0).astype(int)
            df['apellido'] = df['apellido'].fillna('').astype(str)
            
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
        logging.info(f"eventos_con_coordenadas_por_ruta_y_rango completada en {tiempo_ejecucion:.2f}s - {filas_resultado} eventos retornados")
        
        return df
        
    except Exception as e:
        logging.error(f"Error en eventos_con_coordenadas_por_ruta_y_rango: {str(e)}")
        raise e

def ventas_con_coordenadas_por_ruta_y_rango(id_centroope: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Construye un DataFrame de ventas con coordenadas usando la lógica de herencia de coordenadas.
    
    Para cada venta (pedido):
    1. Si existe evento de venta (tipo 58) con coordenadas, usa esas coordenadas
    2. Si no, hereda coordenadas del evento más cercano (±24h, mismo consultor y contacto)
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro
        f_ini (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        f_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_pedido', 'id_contacto', 'id_consultor', 'apellido',
                     'lat', 'lon', 'fecha_factura', 'valor_conIVA', 'origen_coords']
                     
    Notes:
        - origen_coords indica: 'evento_venta' o 'evento_heredado'
        - Solo incluye ventas con coordenadas válidas (realistas para Colombia)
        - Aplica ventana de ±24h para herencia de coordenadas
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando ventas_con_coordenadas_por_ruta_y_rango - CO:{id_centroope}, Ruta:{id_ruta}, Rango:{f_ini} a {f_fin}")
    
    try:
        # Paso 1: Obtener todas las ventas (pedidos) en el rango
        q_ventas = """
        SELECT 
            pe.id                     AS id_pedido,
            pe.id_contacto            AS id_contacto,
            pe.id_vendedor            AS id_consultor,
            p.apellido                AS apellido,
            pe.fecha_factura          AS fecha_factura,
            pe.total_conIVA           AS valor_conIVA
        FROM fullclean_telemercadeo.pedidos pe
        JOIN fullclean_personal.personal p               ON p.id = pe.id_vendedor
        JOIN fullclean_personal.cargos ca                ON ca.Id_cargo = p.id_cargo
        JOIN fullclean_contactos.vwContactos c           ON c.id = pe.id_contacto
        JOIN fullclean_contactos.barrios b               ON b.id = c.id_barrio
        JOIN fullclean_contactos.rutas_cobro_zonas rc    ON rc.id_barrio = b.id
        JOIN fullclean_contactos.rutas_cobro r           ON r.id = rc.id_ruta_cobro
        WHERE 
              c.estado = 1
          AND c.estado_cxc IN (0,1)
          AND r.id_centroope = %s
          AND r.id = %s
          AND pe.fecha_factura BETWEEN %s AND %s
          AND ca.Id_cargo = 181
        ORDER BY 
            pe.fecha_factura ASC,
            pe.id_vendedor ASC;
        """
        
        cn = _conn()
        df_ventas = pd.read_sql(q_ventas, cn, params=[id_centroope, id_ruta, f_ini, f_fin])
        
        if df_ventas.empty:
            cn.close()
            logging.info("No se encontraron ventas en el rango especificado")
            return pd.DataFrame(columns=['id_pedido', 'id_contacto', 'id_consultor', 'apellido', 
                                       'lat', 'lon', 'fecha_factura', 'valor_conIVA', 'origen_coords'])
        
        # Normalizar tipos de datos de ventas
        df_ventas['id_pedido'] = pd.to_numeric(df_ventas['id_pedido'], errors='coerce')
        df_ventas['id_contacto'] = pd.to_numeric(df_ventas['id_contacto'], errors='coerce')
        df_ventas['id_consultor'] = pd.to_numeric(df_ventas['id_consultor'], errors='coerce')
        df_ventas['fecha_factura'] = pd.to_datetime(df_ventas['fecha_factura'], errors='coerce')
        df_ventas['valor_conIVA'] = pd.to_numeric(df_ventas['valor_conIVA'], errors='coerce')
        df_ventas['apellido'] = df_ventas['apellido'].fillna('').astype(str)
        
        # Paso 2: Obtener todos los eventos con coordenadas para hacer matching
        # Expandir ventana temporal ±24h para permitir herencia
        from datetime import datetime, timedelta
        f_ini_dt = datetime.strptime(f_ini[:19], '%Y-%m-%d %H:%M:%S')
        f_fin_dt = datetime.strptime(f_fin[:19], '%Y-%m-%d %H:%M:%S')
        f_ini_expandido = (f_ini_dt - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        f_fin_expandido = (f_fin_dt + timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        
        q_eventos = """
        SELECT 
            e.idEvento                AS id_evento,
            e.id_contacto             AS id_contacto,
            p.id                      AS id_consultor,
            e.coordenada_latitud      AS lat,
            e.coordenada_longitud     AS lon,
            e.fecha_evento            AS fecha_evento,
            e.id_evento_tipo          AS id_evento_tipo
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
        ORDER BY 
            e.fecha_evento ASC;
        """
        
        df_eventos = pd.read_sql(q_eventos, cn, params=[id_centroope, id_ruta, f_ini_expandido, f_fin_expandido])
        cn.close()
        
        if df_eventos.empty:
            logging.info("No se encontraron eventos con coordenadas para hacer matching")
            return pd.DataFrame(columns=['id_pedido', 'id_contacto', 'id_consultor', 'apellido', 
                                       'lat', 'lon', 'fecha_factura', 'valor_conIVA', 'origen_coords'])
        
        # Normalizar tipos de datos de eventos
        df_eventos['id_evento'] = pd.to_numeric(df_eventos['id_evento'], errors='coerce')
        df_eventos['id_contacto'] = pd.to_numeric(df_eventos['id_contacto'], errors='coerce')
        df_eventos['id_consultor'] = pd.to_numeric(df_eventos['id_consultor'], errors='coerce')
        df_eventos['lat'] = pd.to_numeric(df_eventos['lat'], errors='coerce')
        df_eventos['lon'] = pd.to_numeric(df_eventos['lon'], errors='coerce')
        df_eventos['fecha_evento'] = pd.to_datetime(df_eventos['fecha_evento'], errors='coerce')
        df_eventos['id_evento_tipo'] = pd.to_numeric(df_eventos['id_evento_tipo'], errors='coerce')
        
        # Filtrar eventos con coordenadas válidas
        df_eventos = df_eventos.dropna(subset=['lat', 'lon', 'fecha_evento'])
        df_eventos = df_eventos[
            (df_eventos['lat'].between(-5, 13)) & 
            (df_eventos['lon'].between(-81, -66))
        ]
        
        # Paso 3: Para cada venta, buscar coordenadas
        ventas_con_coords = []
        
        for _, venta in df_ventas.iterrows():
            id_contacto = venta['id_contacto']
            id_consultor = venta['id_consultor']
            fecha_factura = venta['fecha_factura']
            
            # Buscar primero evento de venta (tipo 58) exacto
            eventos_venta = df_eventos[
                (df_eventos['id_contacto'] == id_contacto) &
                (df_eventos['id_consultor'] == id_consultor) &
                (df_eventos['id_evento_tipo'] == 58)
            ]
            
            lat, lon, origen = None, None, None
            
            if not eventos_venta.empty:
                # Si hay eventos de venta, tomar el más cercano en tiempo
                eventos_venta['diff_tiempo'] = abs((eventos_venta['fecha_evento'] - fecha_factura).dt.total_seconds())
                evento_mejor = eventos_venta.loc[eventos_venta['diff_tiempo'].idxmin()]
                lat, lon, origen = evento_mejor['lat'], evento_mejor['lon'], 'evento_venta'
            else:
                # Buscar evento más cercano (±24h, mismo consultor y contacto)
                ventana_24h = 24 * 3600  # 24 horas en segundos
                eventos_candidatos = df_eventos[
                    (df_eventos['id_contacto'] == id_contacto) &
                    (df_eventos['id_consultor'] == id_consultor)
                ]
                
                if not eventos_candidatos.empty:
                    eventos_candidatos['diff_tiempo'] = abs((eventos_candidatos['fecha_evento'] - fecha_factura).dt.total_seconds())
                    eventos_en_ventana = eventos_candidatos[eventos_candidatos['diff_tiempo'] <= ventana_24h]
                    
                    if not eventos_en_ventana.empty:
                        evento_mejor = eventos_en_ventana.loc[eventos_en_ventana['diff_tiempo'].idxmin()]
                        lat, lon, origen = evento_mejor['lat'], evento_mejor['lon'], 'evento_heredado'
            
            # Si encontramos coordenadas, agregar a resultado
            if lat is not None and lon is not None:
                ventas_con_coords.append({
                    'id_pedido': venta['id_pedido'],
                    'id_contacto': venta['id_contacto'],
                    'id_consultor': venta['id_consultor'],
                    'apellido': venta['apellido'],
                    'lat': lat,
                    'lon': lon,
                    'fecha_factura': venta['fecha_factura'],
                    'valor_conIVA': venta['valor_conIVA'],
                    'origen_coords': origen
                })
        
        # Crear DataFrame resultado
        df_resultado = pd.DataFrame(ventas_con_coords)
        
        # Logging de tiempo de ejecución y estadísticas
        tiempo_ejecucion = time.time() - inicio_tiempo
        total_ventas = len(df_ventas)
        ventas_con_coords_count = len(df_resultado)
        eventos_venta_count = len(df_resultado[df_resultado['origen_coords'] == 'evento_venta']) if not df_resultado.empty else 0
        eventos_heredados_count = len(df_resultado[df_resultado['origen_coords'] == 'evento_heredado']) if not df_resultado.empty else 0
        
        logging.info(f"ventas_con_coordenadas_por_ruta_y_rango completada en {tiempo_ejecucion:.2f}s")
        logging.info(f"Estadísticas: {total_ventas} ventas totales, {ventas_con_coords_count} con coordenadas")
        logging.info(f"Origen coordenadas: {eventos_venta_count} eventos_venta, {eventos_heredados_count} eventos_heredados")
        
        return df_resultado
        
    except Exception as e:
        logging.error(f"Error en ventas_con_coordenadas_por_ruta_y_rango: {str(e)}")
        raise e

def consultores_metricas_por_ruta_y_rango(id_centroope: int, id_ruta: int, f_ini: str, f_fin: str) -> pd.DataFrame:
    """
    Ejecuta consulta SQL agregada por consultor para obtener métricas de visitas, aperturas, ventas y total de ventas.
    
    Args:
        id_centroope (int): ID del centro de operaciones
        id_ruta (int): ID de la ruta de cobro
        f_ini (str): Fecha inicio en formato 'YYYY-MM-DD HH:MM:SS'
        f_fin (str): Fecha fin en formato 'YYYY-MM-DD HH:MM:SS'
    
    Returns:
        pd.DataFrame: DataFrame con columnas ['id_consultor', 'apellido', 'cant_visitas', 'cant_aperturas', 'cant_ventas', 'total_venta_conIVA']
    
    Raises:
        Exception: Si hay error en la conexión o ejecución de la consulta SQL
    """
    inicio_tiempo = time.time()
    logging.info(f"Iniciando consultores_metricas_por_ruta_y_rango - CO:{id_centroope}, Ruta:{id_ruta}, Rango:{f_ini} a {f_fin}")
    
    # Consulta SQL parametrizada siguiendo exactamente el patrón del Gestor
    q = """
    SELECT
        eagg.id_consultor,
        eagg.apellido,
        eagg.cant_visitas,
        eagg.cant_aperturas,
        eagg.cant_ventas,
        COALESCE(v.total_venta_conIVA, 0) AS total_venta_conIVA
    FROM (
        /* Agregado por consultor desde eventos */
        SELECT
            p.id  AS id_consultor,
            p.apellido,
            COUNT(e.idEvento)                                                     AS cant_visitas,
            SUM(CASE WHEN e.id_evento_tipo IN (73,62,71,64,74) THEN 1 ELSE 0 END) AS cant_aperturas,
            SUM(CASE WHEN e.id_evento_tipo = 58             THEN 1 ELSE 0 END)    AS cant_ventas
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
    ) AS eagg
    LEFT JOIN (
        /* Sumar ventas solo para consultores que tuvieron ventas registradas en eventos */
        SELECT
            pe.id_vendedor           AS id_consultor,
            SUM(pe.total_conIVA)     AS total_venta_conIVA
        FROM fullclean_telemercadeo.pedidos pe
        /* Lista de consultores con ventas (id_evento_tipo = 58) bajo los mismos filtros de eventos */
        JOIN (
            SELECT
                p2.id AS id_consultor
            FROM fullclean_contactos.vwEventos e2
            JOIN fullclean_contactos.vwContactos c2        ON c2.id = e2.id_contacto
            JOIN fullclean_contactos.barrios b2            ON b2.id = c2.id_barrio
            JOIN fullclean_contactos.rutas_cobro_zonas rc2 ON rc2.id_barrio = b2.id
            JOIN fullclean_contactos.rutas_cobro r2        ON r2.id = rc2.id_ruta_cobro
            JOIN fullclean_personal.personal p2            ON p2.id = e2.id_autor
            JOIN fullclean_personal.cargos ca2             ON ca2.Id_cargo = p2.id_cargo
            WHERE
                  c2.estado = 1
              AND c2.estado_cxc IN (0,1)
              AND r2.id_centroope = %s
              AND r2.id = %s
              AND e2.fecha_evento BETWEEN %s AND %s
              AND e2.coordenada_latitud  IS NOT NULL
              AND e2.coordenada_longitud IS NOT NULL
              AND e2.coordenada_latitud  <> 0
              AND e2.coordenada_longitud <> 0
              AND e2.coordenada_latitud  BETWEEN -5  AND 13
              AND e2.coordenada_longitud BETWEEN -81 AND -66
              AND ca2.Id_cargo = 181
              AND e2.id_evento_tipo = 58   /* solo ventas */
            GROUP BY p2.id
        ) AS vv
          ON vv.id_consultor = pe.id_vendedor
        WHERE
            /* mismo rango temporal para ventas por pedidos */
            pe.fecha_factura BETWEEN %s AND %s
        GROUP BY pe.id_vendedor
    ) AS v
      ON v.id_consultor = eagg.id_consultor
    ORDER BY
        eagg.cant_visitas DESC;
    """
    
    try:
        cn = _conn()
        # Parámetros seguros: id_centroope, id_ruta, f_ini, f_fin se repiten para ambas subconsultas
        params = [
            id_centroope, id_ruta, f_ini, f_fin,  # Primera subconsulta (eagg)
            id_centroope, id_ruta, f_ini, f_fin,  # Segunda subconsulta (vv dentro de v)
            f_ini, f_fin                          # Filtro de fecha_factura en pedidos
        ]
        
        df = pd.read_sql(q, cn, params=params)
        cn.close()
        
        # Asegurar tipos de datos correctos con COALESCE para valores nulos
        if not df.empty:
            df['id_consultor'] = pd.to_numeric(df['id_consultor'], errors='coerce')
            df['cant_visitas'] = pd.to_numeric(df['cant_visitas'], errors='coerce').fillna(0).astype(int)
            df['cant_aperturas'] = pd.to_numeric(df['cant_aperturas'], errors='coerce').fillna(0).astype(int)
            df['cant_ventas'] = pd.to_numeric(df['cant_ventas'], errors='coerce').fillna(0).astype(int)
            df['total_venta_conIVA'] = pd.to_numeric(df['total_venta_conIVA'], errors='coerce').fillna(0.0)
            df['apellido'] = df['apellido'].fillna('').astype(str)
        
        # Logging de tiempo de ejecución y tamaño
        tiempo_ejecucion = time.time() - inicio_tiempo
        filas_resultado = len(df)
        logging.info(f"consultores_metricas_por_ruta_y_rango completada en {tiempo_ejecucion:.2f}s - {filas_resultado} filas retornadas")
        
        return df
        
    except Exception as e:
        logging.error(f"Error en consultores_metricas_por_ruta_y_rango: {str(e)}")
        raise e
