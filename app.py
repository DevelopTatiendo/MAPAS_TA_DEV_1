import os
import time
import logging
import json
import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
from mapa_pruebas import generar_mapa_pruebas
from mapa_pedidos import generar_mapa_pedidos
from mapa_facturas_vencidas import generar_mapa_facturas_vencidas
from mapa_visitas import generar_mapa_visitas_individuales
from mapa_muestras import generar_mapa_muestras
from pre_procesamiento.preprocesamiento_muestras import listar_promotores
import validators

#serbot software de verificacion y certificacion de https
# Configuración de entorno
# FAVOR NO BORRAR ESTOS COMANDOS :
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# .venv\Scripts\activate  python flask_server.py


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
st.title("Gestión Visual de Operaciones")

st.sidebar.header("Seleccione una ciudad")
ciudades = ["Barranquilla", "Bogotá", "Bucaramanga", "Cali", "Manizales", "Medellín", "Pereira"]
ciudad = st.sidebar.radio("Ciudad:", ciudades, index=3)

tipos_mapa = ["Pedidos", "Facturas Vencidas", "Muestras", "Visitas", "Pruebas", "Consultores"]
st.header("Seleccione el tipo de mapa")
tipo_mapa = st.selectbox("Tipo de Mapa:", tipos_mapa)

# Limpiar URL del mapa si cambian ciudad o tipo de mapa
current_selection = f"{ciudad}_{tipo_mapa}"
if "last_selection" not in st.session_state:
    st.session_state["last_selection"] = current_selection
elif st.session_state["last_selection"] != current_selection:
    st.session_state["map_url"] = None
    st.session_state["last_selection"] = current_selection

# Cargar datos según la ciudad seleccionada
datos_ciudad = cargar_datos_ciudad(ciudad)

# Formulario dinámico de filtros
st.subheader("Aplicar Filtros")

# --- CONTENEDOR REACTIVO FUERA DEL FORM ---
promotor_container = st.container()

# Estado por defecto
if "promotores_sel" not in st.session_state:
    st.session_state["promotores_sel"] = None
if "filtrar_por_promotor" not in st.session_state:
    st.session_state["filtrar_por_promotor"] = False

with promotor_container:
    if tipo_mapa == "Muestras":
        st.session_state["filtrar_por_promotor"] = st.toggle("Filtrar por promotor", value=st.session_state["filtrar_por_promotor"])
        if st.session_state["filtrar_por_promotor"]:
            with st.spinner("Cargando promotores..."):
                try:
                    df_prom = listar_promotores()
                    # Depuración en terminal
                    print("[DEBUG] listar_promotores rows:", 0 if df_prom is None else len(df_prom))
                    if df_prom is not None and not df_prom.empty:
                        print("[DEBUG] listar_promotores head:\n", df_prom.head(10).to_string())
                        logging.info("promotores.head():\n%s", df_prom.head(10).to_string())
                except Exception as e:
                    st.error(f"Error al cargar promotores: {e}")
                    df_prom = None

            if df_prom is None or df_prom.empty:
                st.info("No se encontraron promotores en la BD.")
                st.session_state["promotores_sel"] = None
            else:
                ids = df_prom["id_autor"].astype(str).tolist()
                etiquetas = (df_prom["apellido"].fillna("").astype(str) + " · " + df_prom["id_autor"].astype(str)).tolist()
                label_map = dict(zip(ids, etiquetas))

                seleccion = st.multiselect(
                    "Promotores",
                    options=ids,
                    format_func=lambda x: label_map.get(x, x),
                    placeholder="Escribe para buscar…"
                )
                if seleccion:
                    try:
                        st.session_state["promotores_sel"] = [int(x) for x in seleccion]
                    except Exception:
                        st.session_state["promotores_sel"] = seleccion
                else:
                    st.session_state["promotores_sel"] = None
        else:
            st.session_state["promotores_sel"] = None

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
        
        # Expander para cuadrantes personalizados
        with st.expander("🗺️ Cuadrantes (opcional)"):
            st.write("Suba un archivo GeoJSON personalizado para usar como base en lugar de las comunas por defecto.")
            uploaded_file = st.file_uploader(
                "Archivo GeoJSON:",
                type=['geojson'],
                key="muestras_geojson_uploader"
            )
            
            if uploaded_file is not None:
                try:
                    # Leer y parsear el archivo GeoJSON
                    geojson_content = uploaded_file.read().decode('utf-8')
                    override_fc = json.loads(geojson_content)
                    
                    # Validar que sea un FeatureCollection
                    if override_fc.get('type') == 'FeatureCollection':
                        st.session_state["muestras_override_fc"] = override_fc
                        st.success(f"✅ Archivo cargado: {uploaded_file.name}")
                        st.caption(f"Se usará como base geográfica en lugar de las comunas de {ciudad}.")
                    else:
                        st.error("❌ El archivo debe ser un FeatureCollection válido.")
                        st.session_state["muestras_override_fc"] = None
                except Exception as e:
                    st.error(f"❌ Error al procesar el archivo: {str(e)}")
                    st.session_state["muestras_override_fc"] = None
            else:
                # Limpiar session state si no hay archivo
                if "muestras_override_fc" in st.session_state:
                    del st.session_state["muestras_override_fc"]
    elif tipo_mapa == "Visitas":
        # Lista de rutas desde BD (id_ruta, ruta) - usando mismo flujo que Consultores
        from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple
        df_rutas = listar_rutas_simple(ciudad)  # columnas: id_ruta, ruta
        if df_rutas is None or df_rutas.empty:
            st.warning("No hay rutas disponibles para la ciudad seleccionada.")
            id_ruta_visitas = None
            nombre_ruta_ui_visitas = None
        else:
            import re
            # Crear lista con ordenamiento robusto descendente (mismo flujo que Consultores)
            rutas_list = []
            for _, r in df_rutas.iterrows():
                ruta_nombre = str(r.ruta)
                # Extraer número inicial si existe
                match = re.match(r'^(\d+)', ruta_nombre)
                num = int(match.group()) if match else None
                rutas_list.append((int(r.id_ruta), ruta_nombre, num))
            
            # Ordenar: primero rutas numéricas (desc), luego alfanuméricas (desc)
            rutas_list.sort(key=lambda x: (0 if x[2] is not None else 1, -x[2] if x[2] is not None else 0, x[1].upper()), reverse=True)
            
            # Crear diccionario para mapear texto → id_ruta
            options_dict = {ruta_nombre: id_ruta for id_ruta, ruta_nombre, _ in rutas_list}
            options_list = [ruta_nombre for _, ruta_nombre, _ in rutas_list]
            
            # Selector que muestra solo el nombre de la ruta
            ruta_seleccionada = st.selectbox("Seleccione una ruta de cobro:", options=[""] + options_list)
            id_ruta_visitas = options_dict.get(ruta_seleccionada) if ruta_seleccionada else None
            nombre_ruta_ui_visitas = ruta_seleccionada if ruta_seleccionada else None
        
        fecha_inicio = st.date_input("Fecha de Inicio")
        fecha_fin = st.date_input("Fecha de Fin")
    elif tipo_mapa == "Consultores":
        # Lista de rutas desde BD (id_ruta, ruta)
        from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple
        df_rutas = listar_rutas_simple(ciudad)  # columnas: id_ruta, ruta
        if df_rutas is None or df_rutas.empty:
            st.warning("No hay rutas disponibles para la ciudad seleccionada.")
            id_ruta = None
            nombre_ruta_ui = None
        else:
            import re
            # Crear lista con ordenamiento robusto descendente
            rutas_list = []
            for _, r in df_rutas.iterrows():
                ruta_nombre = str(r.ruta)
                # Extraer número inicial si existe
                match = re.match(r'^(\d+)', ruta_nombre)
                num = int(match.group()) if match else None
                rutas_list.append((int(r.id_ruta), ruta_nombre, num))
            
            # Ordenar: primero rutas numéricas (desc), luego alfanuméricas (desc)
            rutas_list.sort(key=lambda x: (0 if x[2] is not None else 1, -x[2] if x[2] is not None else 0, x[1].upper()), reverse=True)
            
            # Crear diccionario para mapear texto → id_ruta
            options_dict = {ruta_nombre: id_ruta for id_ruta, ruta_nombre, _ in rutas_list}
            options_list = [ruta_nombre for _, ruta_nombre, _ in rutas_list]
            
            # Selector que muestra solo el nombre de la ruta
            ruta_seleccionada = st.selectbox("Seleccione la ruta (obligatorio):", options=options_list)
            id_ruta = options_dict.get(ruta_seleccionada) if ruta_seleccionada else None
            nombre_ruta_ui = ruta_seleccionada if ruta_seleccionada else None
        
        # Fechas obligatorias
        fecha_inicio = st.date_input("Fecha de Inicio")
        fecha_fin = st.date_input("Fecha de Fin")
        

        
        # Checkbox para mostrar puntos fuera de cuadrantes
        mostrar_fuera = st.checkbox("Mostrar puntos fuera de cuadrantes (rojo)", value=False)
    elif tipo_mapa == "Pruebas":
        # Lista de rutas desde BD (id_ruta, ruta) - usando mismo flujo que Consultores
        from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple
        df_rutas = listar_rutas_simple(ciudad)  # columnas: id_ruta, ruta
        if df_rutas is None or df_rutas.empty:
            st.warning("No hay rutas disponibles para la ciudad seleccionada.")
            id_ruta_pruebas = None
            nombre_ruta_ui_pruebas = None
        else:
            import re
            # Crear lista con ordenamiento robusto descendente (mismo flujo que Consultores)
            rutas_list = []
            for _, r in df_rutas.iterrows():
                ruta_nombre = str(r.ruta)
                # Extraer número inicial si existe
                match = re.match(r'^(\d+)', ruta_nombre)
                num = int(match.group()) if match else None
                rutas_list.append((int(r.id_ruta), ruta_nombre, num))
            
            # Ordenar: primero rutas numéricas (desc), luego alfanuméricas (desc)
            rutas_list.sort(key=lambda x: (0 if x[2] is not None else 1, -x[2] if x[2] is not None else 0, x[1].upper()), reverse=True)
            
            # Crear diccionario para mapear texto → id_ruta
            options_dict = {ruta_nombre: id_ruta for id_ruta, ruta_nombre, _ in rutas_list}
            options_list = [ruta_nombre for _, ruta_nombre, _ in rutas_list]
            
            # Selector que muestra solo el nombre de la ruta
            ruta_seleccionada = st.selectbox("Seleccione una ruta de cobro:", options=[""] + options_list)
            id_ruta_pruebas = options_dict.get(ruta_seleccionada) if ruta_seleccionada else None
            nombre_ruta_ui_pruebas = ruta_seleccionada if ruta_seleccionada else None
        
        # Campo fecha objetivo con default = mañana (America/Bogota)
        from datetime import datetime, timedelta
        import pytz
        
        # Obtener fecha de mañana en zona horaria Colombia
        try:
            tz_colombia = pytz.timezone('America/Bogota')
            hoy_colombia = datetime.now(tz_colombia).date()
            manana_colombia = hoy_colombia + timedelta(days=1)
        except:
            # Fallback si hay problemas con timezone
            from datetime import date
            manana_colombia = date.today() + timedelta(days=1)
        
        fecha_objetivo = st.date_input(
            "Fecha objetivo (proyección visitas):", 
            value=manana_colombia,
            help="Fecha para la cual se proyectan las visitas (por defecto: mañana)"
        )
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        submit_button = st.form_submit_button("Generar Mapa", use_container_width=True, type="primary")
    
    # Placeholder fijo para el enlace del mapa generado
    link_placeholder = st.empty()

# Separador sutil entre secciones
st.markdown("<div style='margin: 2rem 0 1.5rem 0;'></div>", unsafe_allow_html=True)

# Card secundario para Cuadrantes (opcional)
ciudad_normalizada = ciudad.upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
editor_url = f"{FLASK_SERVER}/editor/cuadrantes?city={ciudad_normalizada}"

st.markdown(
    f"""
    <style>
    .card-cuadrantes {{
        background: #fafafa;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 2rem;
    }}
    .card-cuadrantes h3 {{
        color: #262730;
        font-size: 1.2rem;
        font-weight: 600;
        margin: 0 0 0.5rem 0;
    }}
    .card-cuadrantes p {{
        color: #6c757d;
        font-size: 14px;
        line-height: 1.4;
        margin: 0 0 1.5rem 0;
    }}
    .cta-editor {{
        display: inline-block;
        padding: 12px 20px;
        background: linear-gradient(135deg, #0EA5E9 0%, #2563EB 100%);
        color: #FFFFFF;
        text-decoration: none;
        border-radius: 12px;
        font-weight: 700;
        font-size: 16px;
        border: none;
        cursor: pointer;
        box-shadow: 0 4px 12px rgba(37, 99, 235, .25);
        transition: all 0.3s ease;
        text-align: center;
        width: 100%;
        max-width: 280px;
    }}
    .cta-editor:hover {{
        color: #FFFFFF;
        text-decoration: none;
    }}
    .cta-editor:focus {{
        outline: 2px solid #2563EB;
        outline-offset: 2px;
        color: #FFFFFF;
        text-decoration: none;
    }}
    @media (prefers-color-scheme: dark) {{
        .card-cuadrantes {{
            background: #2d3748;
            border-color: #4a5568;
        }}
        .card-cuadrantes h3 {{
            color: #f7fafc;
        }}
        .card-cuadrantes p {{
            color: #a0aec0;
        }}
    }}
    </style>
    <div class="card-cuadrantes">
        <h3>Segmentación de ciudades</h3>
        <p>Dibuje cuadrantes a base de polígonos para dividir areas de interés en la ciudad seleccionada.</p>
        <div style="text-align: center;">
            <a href="{editor_url}" 
               target="_blank" 
               class="cta-editor"
               aria-label="Abrir editor de cuadrantes para la ciudad seleccionada"
               tabindex="0">
                🗺️ Abrir editor de cuadrantes
            </a>
        </div>
    </div>
    """, 
    unsafe_allow_html=True
)

# Procesamiento
if submit_button:
    try:
        if tipo_mapa == "Pedidos":
            filename = manejar_error(generar_mapa_pedidos, fecha_inicio, fecha_fin, ciudad, ruta)
            map_type = "pedidos"
        elif tipo_mapa == "Visitas":
            if not id_ruta_visitas:
                st.error("Seleccione una ruta válida.")
                filename = None
            else:
                filename = manejar_error(
                    generar_mapa_visitas_individuales,
                    ciudad,
                    id_ruta_visitas,  # Pasar ID entero directamente
                    nombre_ruta_ui_visitas,  # Pasar nombre para mostrar en el mapa
                    str(fecha_inicio),
                    str(fecha_fin)
                )
            map_type = "visitas"
        elif tipo_mapa == "Facturas Vencidas":
            filename = manejar_error(generar_mapa_facturas_vencidas, ciudad, edad_min, edad_max, ruta_cobro)
            map_type = "facturas"
        elif tipo_mapa == "Muestras":
            override_fc = st.session_state.get("muestras_override_fc")
            promotores_sel = st.session_state.get("promotores_sel")  # <-- de session_state
            resultado = manejar_error(
                generar_mapa_muestras, fecha_inicio, fecha_fin, ciudad, barrios, promotores_sel, override_fc
            )
            if resultado:
                filename, n_puntos = resultado
            else:
                filename, n_puntos = None, 0
            map_type = "muestras"
        elif tipo_mapa == "Consultores":
            if not id_ruta:
                st.error("Seleccione una ruta válida.")
                filename = None
            elif fecha_inicio > fecha_fin:
                st.error("La fecha de inicio debe ser anterior o igual a la fecha de fin.")
                filename = None
            else:
                # Transformar fechas a strings día-completo
                f_ini_dt = f"{fecha_inicio} 00:00:00"
                f_fin_dt = f"{fecha_fin} 23:59:59"
                # Llamar función simplificada
                from mapa_consultores import generar_mapa_consultores
                filename = manejar_error(generar_mapa_consultores, f_ini_dt, f_fin_dt, ciudad, id_ruta, nombre_ruta_ui, mostrar_fuera)
                map_type = "consultores"
        elif tipo_mapa == "Pruebas":
            if not id_ruta_pruebas:
                st.error("Seleccione una ruta válida.")
                filename = None
            else:
                from mapa_pruebas import generar_mapa_pruebas_proyeccion
                filename = manejar_error(
                    generar_mapa_pruebas_proyeccion,
                    ciudad,
                    id_ruta_pruebas,          # ruta_id_ui: ID entero resuelto desde el selector
                    nombre_ruta_ui_pruebas,   # ruta_nombre_ui: nombre para mostrar en leyenda
                    str(fecha_objetivo)       # fecha_objetivo: YYYY-MM-DD del día objetivo
                )
            map_type = "pruebas"

        if filename:
            # Agregar cache-busting al URL del mapa
            timestamp = int(time.time())
            map_url = f"{FLASK_SERVER}/maps/{filename}?t={timestamp}"
            st.session_state["map_url"] = map_url
            # Actualizar el placeholder con el enlace
            link_placeholder.markdown(
                f'<a href="{map_url}" target="_blank" rel="noopener" style="text-decoration:underline; color:#1d4ed8; font-weight:500;">Ver Mapa en Nueva Pestaña</a>', 
                unsafe_allow_html=True
            )
            
            # Warning si hay filtro y no hubo puntos
            if tipo_mapa == "Muestras" and st.session_state.get("filtrar_por_promotor") and st.session_state.get("promotores_sel") and n_puntos == 0:
                st.warning("No hay datos para los promotores seleccionados en el rango de fechas.")

    except Exception as e:
        logging.error(f"❌ Error inesperado: {str(e)}")
        st.error("⚠️ Se produjo un error inesperado. Revisa los logs.")

# Manejar el enlace en el placeholder basado en session state
if "map_url" in st.session_state and st.session_state["map_url"] is not None:
    if not submit_button:  # Solo mostrar si no acabamos de procesar (evita duplicación)
        link_placeholder.markdown(
            f'<a href="{st.session_state["map_url"]}" target="_blank" rel="noopener" style="text-decoration:underline; color:#1d4ed8; font-weight:500;">Ver Mapa en Nueva Pestaña</a>', 
            unsafe_allow_html=True
        )
elif not submit_button:
    link_placeholder.empty()
