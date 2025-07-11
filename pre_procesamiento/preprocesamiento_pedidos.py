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

def consultar_pedidos_db(centroope, fecha_inicio, fecha_fin):
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
    p.id_contacto, 
    p.fecha_pedido, 
    p.id AS id_pedido, 
    p.id_barrio, 
    ba.barrio, 
    ba.id_estrato, 
    p.id_centroope,
    (CASE 
        WHEN p.fecha_hora_entrega <= p.promesa_entrega THEN 1
        ELSE 0
    END) AS pedido_a_tiempo
FROM 
    fullclean_telemercadeo.pedidos p
LEFT JOIN 
    fullclean_contactos.barrios ba ON ba.id = p.id_barrio
LEFT JOIN 
    fullclean_contactos.ciudades ciu ON ciu.id = ba.id_ciudad
WHERE 
    p.estado_pedido = 1 
    AND p.anulada = 0
    AND p.autorizar IN (1, 2) 
    AND p.autorizacion_descuento = 0
    AND p.tipo_documento < 2 
    AND p.id_centroope = {centroope}
    AND p.fecha_hora_pedido BETWEEN '{fecha_inicio} 00:00:00' AND '{fecha_fin} 23:59:59'
;
    """
    df = pd.read_sql(query, conexion)
    print("CONSULTA REALIZADA")
    conexion.close()
    return df

def crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas):
    """
    Crea un DataFrame final al combinar los datos de la base de datos con las coordenadas de los barrios.
    Retorna un DataFrame listo para usar.
    """
    # Obtener pedidos desde la base de datos
    df_ped = consultar_pedidos_db(centroope, fecha_inicio, fecha_fin)
    
    # Leer el archivo de coordenadas
    df_coord = pd.read_csv(ruta_coordenadas)

    # Realizar el merge por 'id_barrio'
    df_ped_completo = pd.merge(df_ped, df_coord, how='left', on='id_barrio')

    # Mantener solo las columnas necesarias, incluyendo 'pedido_a_tiempo'
    df_ped_completo = df_ped_completo[['id_pedido', 'id_barrio', 'barrio_x', 'fecha_pedido', 'id_estrato', 
                                       'id_centroope', 'latitud', 'longitud', 'ruta_cobro', 'nom_ruta', 'pedido_a_tiempo']]
    
    # Renombrar columnas para mayor claridad
    df_ped_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)
    
    df_ped_completo.drop_duplicates(subset=['id_pedido'], keep='first', inplace=True)
    
    return df_ped_completo

