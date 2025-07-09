import pandas as pd
from dotenv import load_dotenv
import os
import mysql.connector

# Cargar variables de entorno
load_dotenv()

# Credenciales desde el archivo .env
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

def consultar_facturas_vencidas_db(centroope, edad_min, edad_max):
    """
    Consulta la base de datos para obtener los pedidos filtrados por centroope y fechas.
    Retorna un DataFrame.
    """
    conexion = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    query = query = f"""
    SELECT 
    cz.id_ruta_cobro,
    rc.ruta AS ruta_cobro,
    cz.id_barrio,
    ba.barrio,
    ba.id_estrato,
    ci.ciudad,
    ci.id_centroope,
    sa.num_factura,
    SUM(sa.saldo) AS valor_mora,  -- Corregido con alias
    MAX(sa.edad_factura) AS edad, -- Usamos MAX para evitar errores
    sa.id_contacto,
    MAX(sa.fecha_factura) AS fecha_venta
    FROM fullclean_telemercadeo.saldos sa
    LEFT JOIN fullclean_contactos.barrios ba ON ba.id = sa.id_barrio
    LEFT JOIN fullclean_contactos.rutas_cobro_zonas cz ON cz.id_barrio = ba.id
    LEFT JOIN fullclean_contactos.rutas_cobro rc ON cz.id_ruta_cobro = rc.id
    LEFT JOIN fullclean_contactos.ciudades ci ON ci.id = ba.id_ciudad
    WHERE sa.saldo > 0 
    AND sa.anulada = 0 
    AND ci.id_centroope = {centroope}
    AND sa.edad_factura BETWEEN {edad_min} AND {edad_max}
    GROUP BY sa.id_contacto, cz.id_ruta_cobro, rc.ruta, cz.id_barrio, ba.barrio, 
            ba.id_estrato, ci.ciudad, ci.id_centroope, sa.num_factura;
"""
    df = pd.read_sql(query, conexion)
    print("CONSULTA REALIZADA")
    
    conexion.close()
    return df

def crear_df(centroope, edad_min, edad_max, ruta_coordenadas, rutas=None):
    # Obtener pedidos desde la base de datos
    df_fac = consultar_facturas_vencidas_db(centroope, edad_min, edad_max)
    print(df_fac.shape)

    # Leer el archivo de coordenadas
    df_coord = pd.read_csv(ruta_coordenadas)

    # Realizar el merge por 'id_barrio'
    df_fac_completo = pd.merge(df_fac, df_coord, how='left', on='id_barrio')
    print(df_fac_completo.shape, "shape")

    # Renombrar si hay colisiones después del merge
    columnas = df_fac_completo.columns
    if 'barrio_x' in columnas:
        df_fac_completo['barrio'] = df_fac_completo['barrio_x']
    if 'ruta_cobro_x' in columnas:
        df_fac_completo['ruta_cobro'] = df_fac_completo['ruta_cobro_x']
    if 'ruta_cobro_y' in columnas:
        df_fac_completo['ruta_cobro'] = df_fac_completo['ruta_cobro_y']

    # Mantener solo las columnas necesarias
    df_fac_completo = df_fac_completo[[
        "id_ruta_cobro",
        "ruta_cobro",
        "id_barrio",
        "barrio",
        "id_estrato",
        "ciudad",
        "id_centroope",
        "num_factura",
        "valor_mora",
        "edad",
        "id_contacto",
        "fecha_venta",
        'latitud',
        'longitud'
    ]]

    # Renombrar columnas para mayor claridad
    df_fac_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)

    #print("TAMAÑO DEL DF ANTES DE ELIMINAR DUPLICADOS")
    print(df_fac_completo.shape)

    df_fac_completo.drop_duplicates(subset=['id_contacto'], keep='first', inplace=True)

    return df_fac_completo
