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

def listar_promotores():
    """
    Devuelve DataFrame con columnas id_autor, apellido a partir de:
    SELECT p.id AS id_autor, p.apellido
    FROM fullclean_personal.personal p
    WHERE p.id_cargo = 39;
    """
    conexion = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
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
    
    df = pd.read_sql(query, conexion)
    conexion.close()
    
    # Asegurar tipos de datos apropiados
    if not df.empty:
        df['id_autor'] = df['id_autor'].astype('int64')
        df['apellido'] = df['apellido'].fillna('').astype(str)
    
    return df

def consultar_muestras_db(centroope, fecha_inicio, fecha_fin, promotores=None):
    """
    Consulta la base de datos para obtener los eventos de muestras filtrados por centroope y fechas.
    Retorna un DataFrame.
    """
    conexion = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    # Construir consulta base
    query = """
    SELECT 
        e.idEvento AS id_muestra,
        e.id_contacto,
        e.fecha_evento, 
        e.id_autor,
        e.coordenada_longitud, 
        e.coordenada_latitud,
        e.medio_contacto,
        e.tipo_evento,
        e.tipo_categoria,
        con.id_barrio AS id_barrio
        
    FROM 
        fullclean_contactos.vwEventos e
    LEFT JOIN 
        fullclean_contactos.vwContactos con ON e.id_contacto = con.id
    LEFT JOIN 
        fullclean_contactos.barrios bar ON bar.id = con.id_barrio
    LEFT JOIN 
        fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
    WHERE 
        e.fecha_evento BETWEEN %s AND %s
        AND e.id_evento_tipo = 15
        AND ciu.id_centroope = %s
        AND coordenada_longitud <> 0 
        AND coordenada_latitud <> 0"""
    
    # Parámetros base
    params = [f'{fecha_inicio} 00:00:00', f'{fecha_fin} 23:59:59', centroope]
    
    # Agregar filtro dinámico por promotores si se especifica
    if promotores is not None and len(promotores) > 0:
        placeholders = ",".join(["%s"] * len(promotores))
        query += f" AND e.id_autor IN ({placeholders})"
        params.extend(promotores)
    
    query += ";"
    
    df = pd.read_sql(query, conexion, params=params)
    conexion.close()
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

    # Lista de columnas deseadas (ajusta según tus archivos)
    columnas_deseadas = [
        'id_muestra', 'id_contacto',  'fecha_evento', 
        'id_autor', 'coordenada_longitud', 'coordenada_latitud',
        'tipo_evento', 'tipo_categoria','id_barrio', 'barrio', 'id_estrato',
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

def obtener_promotores_por_ids(ids):
    """
    Retorna dict {str(id_autor): nombre_completo} usando:
    SELECT p.id AS id_autor, p.apellido AS nombre_completo
    FROM fullclean_personal.personal p
    WHERE p.id IN (%s, %s, ...);
    """
    if not ids:
        return {}
    
    try:
        conexion = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        # Crear placeholders para la consulta IN
        placeholders = ','.join(['%s'] * len(ids))
        query = f"""
        SELECT 
            p.id AS id_autor, 
            p.apellido AS nombre_completo
        FROM 
            fullclean_personal.personal p
        WHERE 
            p.id IN ({placeholders})
        """
        
        df = pd.read_sql(query, conexion, params=ids)
        conexion.close()
        
        # Convertir a dict {str(id): nombre_completo}
        result = {}
        for _, row in df.iterrows():
            result[str(row['id_autor'])] = row['nombre_completo']
        
        return result
        
    except Exception as e:
        print(f"Error en obtener_promotores_por_ids: {e}")
        return {}
