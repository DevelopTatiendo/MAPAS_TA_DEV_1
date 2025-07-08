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

def consultar_muestras_db(centroope, fecha_inicio, fecha_fin):
    """
    Consulta la base de datos para obtener los eventos de muestras filtrados por centroope y fechas.
    Retorna un DataFrame.
    """
    conexion = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    query = f"""
    SELECT 
        e.idEvento, 
        e.fecha_evento, 
        e.id_evento_tipo, 
        e.coordenada_longitud, 
        e.coordenada_latitud, 
        e.medio_contacto, 
        e.tipo_evento, 
        e.id_categoria_evento, 
        bar.id AS id_barrio, 
        bar.barrio, 
        bar.id_estrato
    FROM 
        fullclean_contactos.vwEventos e
    LEFT JOIN 
        fullclean_contactos.vwContactos con ON e.id_contacto = con.id
    LEFT JOIN 
        fullclean_contactos.barrios bar ON bar.id = con.id_barrio
    LEFT JOIN 
        fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
    WHERE 
        e.fecha_evento BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
        AND e.id_evento_tipo = 15
        AND ciu.id_centroope = {centroope}
        AND coordenada_longitud <> 0 
        AND coordenada_latitud <> 0;
    """
    df = pd.read_sql(query, conexion)
    conexion.close()
    return df


def crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas):
    """
    Crea un DataFrame final al combinar los datos de la base de datos con las coordenadas de los barrios.
    Retorna un DataFrame listo para usar.
    """
    # Obtener datos de muestras desde la base de datos
    df_muestras = consultar_muestras_db(centroope, fecha_inicio, fecha_fin)
    

    # Leer el archivo de coordenadas
    df_coord = pd.read_csv(ruta_coordenadas)

    # Realizar el merge por 'id_barrio'
    df_muestras_completo = pd.merge(df_muestras, df_coord, how='left', on='id_barrio')

    # Mantener solo las columnas necesarias
    df_muestras_completo = df_muestras_completo[['fecha_evento', 'coordenada_longitud', 
                                                 'coordenada_latitud',
                                                 'id_barrio', 'barrio_x', 'id_estrato', 
                                                 'latitud', 'longitud', 'ruta_cobro', 'nom_ruta']]
    
    # Renombrar columnas si es necesario
    df_muestras_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)
    # print(df_muestras_completo.head())
    return df_muestras_completo
