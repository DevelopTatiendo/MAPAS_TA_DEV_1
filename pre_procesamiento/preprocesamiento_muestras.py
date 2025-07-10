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
        
        e.id_contacto,
        e.fecha_creacion,
        e.fecha_evento, 
        hour(e.fecha_evento) AS hora_evento,
        e.id_autor,
        e.coordenada_longitud, 
        e.coordenada_latitud,
        e.nombre_evento,
        e.categoria_evento,
        con.id_barrio AS id_barrio
        
    FROM 
        fullclean_contactos.vwEventosAgente e
    LEFT JOIN 
        fullclean_contactos.vwContactos con ON e.id_contacto = con.id
    LEFT JOIN 
        fullclean_contactos.barrios bar ON bar.id = con.id_barrio
    LEFT JOIN 
        fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
    WHERE 
        e.fecha_evento BETWEEN '{fecha_inicio}' AND '{fecha_fin}'
        AND e.id_evento_tipo = 15
        AND ciu.id_centroope = '{centroope}'
        AND coordenada_longitud <> 0 
        AND coordenada_latitud <> 0;
    """
    df = pd.read_sql(query, conexion)
    #print(df.columns)
    conexion.close()
    return df


def crear_df(centroope, fecha_inicio, fecha_fin, ruta_coordenadas, agentes=None):
    """
    Crea un DataFrame final al combinar los datos de la base de datos con las coordenadas de los barrios.
    Retorna un DataFrame listo para usar.
    """
    # Obtener datos de muestras desde la base de datos
    df_muestras = consultar_muestras_db(centroope, fecha_inicio, fecha_fin)

    # Agregar columna id_muestra al inicio
    df_muestras.insert(0, 'id_muestra', range(len(df_muestras)))

    # Leer el archivo de coordenadas
    df_coord = pd.read_csv(ruta_coordenadas)

    # Realizar el merge por 'id_barrio'
    df_muestras_completo = pd.merge(df_muestras, df_coord, how='left', on='id_barrio')

    # Verifica las columnas disponibles
    #print("Columnas después del merge:", df_muestras_completo.columns.tolist())

    # Lista de columnas deseadas (ajusta según tus archivos)
    columnas_deseadas = [
        'id_muestra', 'id_contacto', 'fecha_creacion', 'fecha_evento', 'hora_evento',
        'id_autor', 'coordenada_longitud', 'coordenada_latitud',
        'nombre_evento', 'categoria_evento',
        'id_barrio', 'barrio', 'id_estrato',
        'latitud', 'longitud', 'ruta_cobro', 'nom_ruta'
    ]
    # Filtra solo las columnas que existen
    columnas_existentes = [col for col in columnas_deseadas if col in df_muestras_completo.columns]
    df_muestras_completo = df_muestras_completo[columnas_existentes]

    # Si el CSV tiene 'barrio' y no 'barrio_x', no necesitas renombrar
    # Si tienes 'barrio_x', renómbralo a 'barrio'
    if 'barrio_x' in df_muestras_completo.columns:
        df_muestras_completo.rename(columns={'barrio_x': 'barrio'}, inplace=True)

    return df_muestras_completo
