import os
import time
import logging
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from mapa_pruebas import generar_mapa_pruebas
from mapa_pedidos import generar_mapa_pedidos
from mapa_facturas_vencidas import generar_mapa_facturas_vencidas
from mapa_visitas import generar_mapa_visitas
from mapa_muestras import generar_mapa_muestras
from generar_estadisticas import generar_estadisticas
import validators

#serbot software de verificacion y certificacion de https
# Configuración de entorno
# FAVOR NO BORRAR ESTOS COMANDOS .venv\Scripts\activate  python flask_server.py


ENVIRONMENT = os.getenv("ENVIRONMENT", "development")  # Por defecto, "development"
FLASK_SERVER = os.getenv("FLASK_SERVER_URL", "http://localhost:5000") if ENVIRONMENT == "production" else "http://localhost:5000"

# Permitir localhost en desarrollo
if not validators.url(FLASK_SERVER) and not FLASK_SERVER.startswith("http://localhost"):
    raise ValueError(f"❌ Error: `FLASK_SERVER_URL` no es una URL válida: {FLASK_SERVER}")

print(f"🌍 Servidor activo en: {FLASK_SERVER} | Entorno: {ENVIRONMENT}")

# Configuración de logs
logging.basicConfig(level=logging.ERROR, format="%(asctime)s - %(levelname)s - %(message)s", filename="errors.log")

def manejar_error(funcion, *args, **kwargs):
    """ Ejecuta una función y captura cualquier error. """
    try:
        return funcion(*args, **kwargs)
    except Exception as e:  # ⬅️ Asegura que esta línea esté presente
        logging.error(f"Error en {funcion.__name__}: {str(e)}")
        st.error(f"❌ Ocurrió un error en {funcion.__name__}. Revisa los logs.")
        return None


# Función para cargar los datos de cada ciudad
def cargar_datos_ciudad(ciudad):
    ciudad_folder = ciudad.upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    base_path = f"ciudades/{ciudad_folder}/"
    
    archivos = ["rutas_logistica.csv", "rutas_cobro.csv", "barrios.csv"]
    datos = {}

    for archivo in archivos:
        file_path = os.path.join(base_path, archivo)
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
            df = pd.read_csv(file_path)
            if df.empty:
                raise ValueError(f"El archivo {archivo} está vacío.")
            datos[archivo.split('.')[0]] = df
        except Exception as e:
            st.error(f"Error cargando {archivo}: {e}")
            datos[archivo.split('.')[0]] = pd.DataFrame()

    return datos

# UI de Streamlit
st.title("Visualización de Mapas Interactivos")

st.sidebar.header("Seleccione una ciudad")
ciudades = ["Barranquilla", "Bogotá", "Bucaramanga", "Cali", "Manizales", "Medellín", "Pereira"]
ciudad = st.sidebar.radio("Ciudad:", ciudades, index=3)

tipos_mapa = ["Pedidos", "Facturas Vencidas", "Muestras", "Visitas", "Pruebas"]
st.header("Seleccione el tipo de mapa")
tipo_mapa = st.selectbox("Tipo de Mapa:", tipos_mapa)

# Cargar datos según la ciudad seleccionada
datos_ciudad = cargar_datos_ciudad(ciudad)

# Formulario dinámico de filtros
st.subheader("Aplicar Filtros")
with st.form(key="filtros_form"):
    if tipo_mapa == "Pedidos":
        rutas_disponibles = datos_ciudad["rutas_logistica"]["nombre_ruta"].sort_values().unique()
        ruta = st.selectbox("Seleccione una ruta logística (opcional):", options=[""] + list(rutas_disponibles))
        fecha_inicio = st.date_input("Fecha de Inicio")
        fecha_fin = st.date_input("Fecha de Fin")
    elif tipo_mapa == "Facturas Vencidas":
        edad_min = st.number_input("Edad mínima (días):", min_value=0, value=91)
        edad_max = st.number_input("Edad máxima (días):", min_value=0, value=120)
        rutas_cobro_disponibles = datos_ciudad["rutas_cobro"]["ruta"].sort_values().unique()
        ruta_cobro = st.selectbox("Seleccione una ruta de cobro (opcional):", options=[""] + list(rutas_cobro_disponibles))
    elif tipo_mapa == "Muestras":
        barrios_disponibles = datos_ciudad["barrios"]["barrio"].sort_values().unique()
        barrios = st.multiselect("Seleccione los barrios:", options=barrios_disponibles, default=[])
        fecha_inicio = st.date_input("Fecha de Inicio")
        fecha_fin = st.date_input("Fecha de Fin")
    elif tipo_mapa == "Visitas":
        rutas_cobro_disponibles = datos_ciudad["rutas_cobro"]["ruta"].sort_values().unique()
        ruta_cobro = st.selectbox("Seleccione una ruta de cobro (opcional):", options=[""] + list(rutas_cobro_disponibles))
        agrupacion = st.radio("Tipo de agrupación:", ["Agrupado", "No agrupado"], index=0)
        fecha_inicio = st.date_input("Fecha de Inicio")
        fecha_fin = st.date_input("Fecha de Fin")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        submit_button = st.form_submit_button("Generar Mapa", use_container_width=True, type="primary")
        mostrar_estadisticas = st.form_submit_button("Generar Estadísticas", use_container_width=True, type="secondary")

# Procesamiento
if submit_button or mostrar_estadisticas:
    try:
        if submit_button:
            if tipo_mapa == "Pedidos":
                filename = manejar_error(generar_mapa_pedidos, fecha_inicio, fecha_fin, ciudad, ruta)
                map_type = "pedidos"
            elif tipo_mapa == "Visitas":
                filename = manejar_error(generar_mapa_visitas, fecha_inicio, fecha_fin, agrupacion, ciudad, ruta_cobro)
                map_type = "visitas"
            elif tipo_mapa == "Facturas Vencidas":
                filename = manejar_error(generar_mapa_facturas_vencidas, ciudad, edad_min, edad_max, ruta_cobro)
                map_type = "facturas"
            elif tipo_mapa == "Muestras":
                filename = manejar_error(generar_mapa_muestras, fecha_inicio, fecha_fin, ciudad, barrios)
                map_type = "muestras"
            elif tipo_mapa == "Pruebas":
                filename = manejar_error(generar_mapa_pruebas, fecha_inicio, fecha_fin, ciudad, ruta)

            map_url = f"{FLASK_SERVER}/maps/mapa_{map_type}.html"
            timestamp = int(time.time())
            st.markdown(f"[Ver Mapa en Nueva Pestaña]({map_url}?v={timestamp})")


        if mostrar_estadisticas:
            st.markdown("---")  # Separador visual
            st.subheader("📊 Estadísticas Generadas")
            
            graficos = manejar_error(generar_estadisticas, tipo_mapa, ciudad,
                             fecha_inicio=locals().get("fecha_inicio"),
                             fecha_fin=locals().get("fecha_fin"),
                             ruta=locals().get("ruta"),
                             ruta_cobro=locals().get("ruta_cobro"),
                             barrios=locals().get("barrios"),
                             edad_min=locals().get("edad_min"),
                             edad_max=locals().get("edad_max"),
                             agrupacion=locals().get("agrupacion"))

            if graficos:
                for i, (titulo, grafico) in enumerate(graficos.items()):
                    col = st.columns(2)[i % 2]  # Alternar columnas
                    with col:
                        st.write(f"### {titulo}")
                        st.plotly_chart(grafico, use_container_width=True)
            else:
                st.warning("⚠️ No hay datos disponibles para generar estadísticas.")
    except Exception as e:
        logging.error(f"❌ Error inesperado: {str(e)}")
        st.error("⚠️ Se produjo un error inesperado. Revisa los logs.")

