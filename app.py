from config.secrets_manager import load_env_secure
load_env_secure(
    prefer_plain=True,
    enc_path="config/.env.enc",
    pass_env_var="MAPAS_SECRET_PASSPHRASE",
    cache=False
)

import os
import time
import logging
import json
import streamlit as st
import pandas as pd
from pathlib import Path
from PIL import Image
import base64
# from mapa_pruebas import generar_mapa_pruebas
# from mapa_pedidos import generar_mapa_pedidos
# from mapa_facturas_vencidas import generar_mapa_facturas_vencidas
# from mapa_visitas import generar_mapa_visitas_individuales
from mapa_muestras import generar_mapa_muestras
from mapa_consultores import generar_mapa_consultores
from mapa_consultores_simple import generar_mapa_consultores_simple
from mapa_pruebas import generar_mapa_pruebas
from pre_procesamiento.preprocesamiento_muestras import listar_promotores
import validators

#serbot software de verificacion y certificacion de https
# Configuración de entorno
# FAVOR NO BORRAR ESTOS COMANDOS :
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
# .venv\Scripts\activate  python flask_server.py 
# $env:MAPAS_SECRET_PASSPHRASE=


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

# Variables de marca - rutas sólidas
APP_TITLE = "Atlas TA"

BASE_DIR = Path(__file__).resolve().parent        # carpeta donde está app.py
LOGO_FILE = BASE_DIR / "static" / "img" / "Atlas_TA.png"

def img_to_b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("utf-8")

# Configuración de la página - DEBE ser el PRIMER st.* del archivo
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=Image.open(LOGO_FILE) if LOGO_FILE.exists() else "🗺️",
    layout="wide"
)

# CSS con paleta de marca (morado + amarillo) y hero centrado
st.markdown("""
<style>
:root{
  --primary:#5B21B6; --primary-600:#6D28D9; --accent:#FACC15;
  --bg:#F8F7FF; --card:#FFFFFF; --text:#1F1A2F; --muted:#6B7280; --border:#E5E7EB;
  --bg-dark:#0F1116; --card-dark:#161923; --text-dark:#EAEAF0; --muted-dark:#A3A8B3; --border-dark:#2A2F3A;
}
/* Contenedor más estrecho para foco visual */
.block-container { max-width: 1100px; }

/* ===== HERO de marca ===== */
.hero-wrap{
  display:flex; justify-content:center; margin: 6px 0 18px 0;
}
.hero{
  display:flex; align-items:center; gap:28px;
}
.hero .logo{
  width: 112px; height:auto; display:block;
}
.hero .title{
  font-weight: 900;
  font-size: clamp(40px, 6vw, 64px);
  line-height: 1.0;
  letter-spacing: -0.02em;
  margin: 0;
}
.hero .subtitle{
  font-weight: 700;
  font-size: clamp(18px, 2.6vw, 26px);
  margin-top: 6px;
}
.hero .tagline{
  color: var(--muted, #6B7280);
  font-size: clamp(14px, 1.8vw, 18px);
  margin-top: 4px;
}

/* Apilado en móviles */
@media (max-width: 820px){
  .hero{ flex-direction: column; text-align: center; gap: 14px; }
  .hero .logo{ width: 88px; }
}

/* tipografía */
h1, h2, h3 { letter-spacing: -0.015em; }
.subtle { color: var(--muted); font-size: .95rem; }
/* cards */
.card{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:18px; }
.card + .card{ margin-top:16px; }
.card-header{ font-weight:700; font-size:1.05rem; margin-bottom:8px; }
.muted{ color:var(--muted); }
/* chips y enlaces de acción */
.pill{
  display:inline-block; padding:6px 12px; border:1px solid var(--border);
  border-radius:999px; font-size:.9rem; color:var(--text); background:#F9FAFB;
}
a.pill, .btn-link{
  display:block; text-align:center; text-decoration:none; color:#fff;
  background:var(--primary); border:1px solid var(--primary);
  padding:10px 14px; border-radius:10px; font-weight:600;
}
a.pill:hover, .btn-link:hover{ background:var(--primary-600); border-color:var(--primary-600); }
a.pill .icon{ margin-right:.35rem; }
.btn-row{ display:flex; justify-content:center; }
.btn-row > div{ width:320px; }
/* acento */
.emphasis{ color:var(--accent); }
/* espaciados */
.sp-2{ margin: 1rem 0; } .sp-3{ margin: 1.5rem 0; }

/* Dark mode alto contraste */
@media (prefers-color-scheme: dark){
  .block-container{ background:var(--bg-dark); }
  .card{ background:var(--card-dark); border-color:var(--border-dark); }
  .pill{ background:#0F1220; color:var(--text-dark); border-color:var(--border-dark); }
  .subtle, .muted{ color:var(--muted-dark); }
  body, .stMarkdown, .stText, .stRadio, .stSelectbox, .stMultiSelect{ color:var(--text-dark) !important; }
  a.pill, .btn-link{ background:var(--primary-600); border-color:var(--primary-600); }
  a.pill:hover{ filter:brightness(1.05); }
  .hero .title, .hero .subtitle{ color: var(--text-dark, #EAEAF0); }
  .hero .tagline{ color: var(--muted-dark, #A3A8B3); }
}
</style>
""", unsafe_allow_html=True)

# UI de Streamlit - Hero centrado
logo_b64 = img_to_b64(LOGO_FILE) if LOGO_FILE.exists() else None

st.markdown(
    f"""
    <div class="hero-wrap">
      <div class="hero">
        {'<img class="logo" src="data:image/png;base64,' + logo_b64 + '" alt="Atlas TA">' if logo_b64 else ''}
        <div class="hero-text">
          <h1 class="title">Atlas TA</h1>
          <div class="subtitle">El mapa de tu operación</div>
          <div class="tagline"></div>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

# Debug checks (opcional - descomentarlas si necesitas verificar rutas)
# st.write("CWD:", os.getcwd())
# st.write("Logo existe:", LOGO_FILE.exists())
# st.write("Logo (abspath):", str(LOGO_FILE))

# Toolbar compacta (resumen de selección)
st.markdown('<div class="toolbar"><div></div><div id="toolbar-pill"></div></div>', unsafe_allow_html=True)

st.sidebar.header("Seleccione una ciudad")
ciudades = ["Barranquilla", "Bogotá", "Bucaramanga", "Cali", "Manizales", "Medellín", "Pereira"]
ciudad = st.sidebar.radio("Ciudad:", ciudades, index=3)

# Card "Configuración y Filtros"
st.markdown('<div class="card"><div class="card-header">Configuración y Filtros</div>', unsafe_allow_html=True)

tipos_mapa = ["Muestras", "Consultores", "Pruebas"]  # Solo módulos activos
# tipos_mapa = ["Pedidos", "Facturas Vencidas", "Muestras", "Visitas", "Pruebas", "Consultores"]
tipo_mapa = st.selectbox("Tipo de Mapa:", tipos_mapa)

# Compatibilidad temporal para sesiones con "Gestores"
if tipo_mapa == "Gestores":
    tipo_mapa = "Consultores"

# Limpiar URL del mapa si cambian ciudad o tipo de mapa
current_selection = f"{ciudad}_{tipo_mapa}"
if "last_selection" not in st.session_state:
    st.session_state["last_selection"] = current_selection
elif st.session_state["last_selection"] != current_selection:
    st.session_state["map_url"] = None
    st.session_state["muestras_last_filename"] = None
    st.session_state["last_selection"] = current_selection

# Cargar datos según la ciudad seleccionada
datos_ciudad = cargar_datos_ciudad(ciudad)

st.divider()

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
    # if tipo_mapa == "Pedidos":
    #     rutas_disponibles = datos_ciudad["rutas_logistica"]["nombre_ruta"].sort_values().unique()
    #     ruta = st.selectbox("Seleccione una ruta logística (opcional):", options=[""] + list(rutas_disponibles))
    #     fecha_inicio = st.date_input("Fecha de Inicio")
    #     fecha_fin = st.date_input("Fecha de Fin")
    # if tipo_mapa == "Facturas Vencidas":
    #     edad_min = st.number_input("Edad mínima (días):", min_value=0, value=91)
    #     edad_max = st.number_input("Edad máxima (días):", min_value=0, value=120)
    #     rutas_cobro_disponibles = datos_ciudad["rutas_cobro"]["ruta"].sort_values().unique()
    #     ruta_cobro = st.selectbox("Seleccione una ruta de cobro (opcional):", options=[""] + list(rutas_cobro_disponibles))
    if tipo_mapa == "Muestras":
        # Barrios
        barrios_disponibles = datos_ciudad["barrios"]["barrio"].sort_values().unique()
        barrios = st.multiselect("Seleccione los barrios:", options=barrios_disponibles, default=[])
        
        # Fechas en dos columnas
        c1, c2 = st.columns(2)
        with c1: 
            fecha_inicio = st.date_input("Fecha de Inicio")
        with c2: 
            fecha_fin = st.date_input("Fecha de Fin")
        
        # Opciones de visualización
        with st.expander("Opciones de visualización"):
            # default = Temporalidad
            color_options = ["Promotores", "Temporalidad (mes)"]
            default_idx = 1
            color_mode = st.radio("Colores por:", color_options, index=default_idx, key="color_mode_muestras")
            verificar_areas = st.checkbox("🔍 Verificar áreas (modo debug)", value=False, help="Muestra información detallada sobre el cálculo de áreas en los popups de cuadrantes")
            
            # ISM Calibración
            st.markdown("**🎯 Calibración ISM**")
            st.caption("Overrides opcionales para ajustar el cálculo de ISM sin modificar la configuración base")
            
            col1, col2 = st.columns(2)
            with col1:
                pph_override = st.number_input(
                    "Personas por hogar", 
                    min_value=1.0, 
                    max_value=10.0, 
                    value=None,
                    step=0.1,
                    placeholder="Por defecto según ciudad",
                    help="Override para personas por hogar (afecta densidad de hogares)"
                )
            with col2:
                hogares_por_m2_override = st.number_input(
                    "Hogares por m²", 
                    min_value=0.0, 
                    max_value=0.01, 
                    value=None,
                    step=0.0001,
                    format="%.6f",
                    placeholder="Por defecto según ciudad",
                    help="Override directo para hogares por metro cuadrado"
                )
        
        # Cuadrantes (opcional)
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
        # Ruta (obligatorio)
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
        
        # Fechas en dos columnas
        c1, c2 = st.columns(2)
        with c1: 
            fecha_inicio = st.date_input("Fecha de Inicio")
        with c2: 
            fecha_fin = st.date_input("Fecha de Fin")
        
        # Toggle para modo simple (sin cuadrantes)
        modo_simple = st.checkbox("Modo simple (sin cuadrantes)", value=True, help="Muestra todos los puntos sobre la capa base de la ciudad, sin cálculo de métricas por cuadrante")
        
        # Opción para mostrar puntos fuera de cuadrante (solo visible en modo completo)
        if not modo_simple:
            mostrar_fuera = st.checkbox("Mostrar puntos fuera de cuadrante", value=False, help="Incluye eventos que no están dentro de ningún cuadrante")
        else:
            mostrar_fuera = False  # No aplica en modo simple
    elif tipo_mapa == "Pruebas":
        # Ruta (obligatorio)
        from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple
        df_rutas = listar_rutas_simple(ciudad)  # columnas: id_ruta, ruta
        if df_rutas is None or df_rutas.empty:
            st.warning("No hay rutas disponibles para la ciudad seleccionada.")
            id_ruta_pruebas = None
            nombre_ruta_ui_pruebas = None
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
            
            # Agregar opción "TODOS" al inicio
            options_list_plus = ["TODOS"] + options_list
            
            # Selector mostrando el nombre de ruta (incluye "TODOS")
            ruta_seleccionada = st.selectbox("Seleccione la ruta:", options=options_list_plus, index=0)
            
            if ruta_seleccionada == "TODOS":
                id_ruta_pruebas = None           # ← clave: None significa NO filtrar por ruta
                nombre_ruta_ui_pruebas = "TODOS"
            else:
                id_ruta_pruebas = options_dict.get(ruta_seleccionada)
                nombre_ruta_ui_pruebas = ruta_seleccionada
        
        # Fechas en dos columnas
        c1, c2 = st.columns(2)
        with c1: 
            fecha_inicio = st.date_input("Fecha de Inicio")
        with c2: 
            fecha_fin = st.date_input("Fecha de Fin")
    # elif tipo_mapa == "Pruebas":
    #     # Lista de rutas desde BD (id_ruta, ruta) - usando mismo flujo que Consultores
    #     from pre_procesamiento.preprocesamiento_consultores import listar_rutas_simple
    #     df_rutas = listar_rutas_simple(ciudad)  # columnas: id_ruta, ruta
    #     if df_rutas is None or df_rutas.empty:
    #         st.warning("No hay rutas disponibles para la ciudad seleccionada.")
    #         id_ruta_pruebas = None
    #         nombre_ruta_ui_pruebas = None
    #     else:
    #         import re
    #         # Crear lista con ordenamiento robusto descendente (mismo flujo que Consultores)
    #         rutas_list = []
    #         for _, r in df_rutas.iterrows():
    #             ruta_nombre = str(r.ruta)
    #             # Extraer número inicial si existe
    #             match = re.match(r'^(\d+)', ruta_nombre)
    #             num = int(match.group()) if match else None
    #             rutas_list.append((int(r.id_ruta), ruta_nombre, num))
    #         
    #         # Ordenar: primero rutas numéricas (desc), luego alfanuméricas (desc)
    #         rutas_list.sort(key=lambda x: (0 if x[2] is not None else 1, -x[2] if x[2] is not None else 0, x[1].upper()), reverse=True)
    #         
    #         # Crear diccionario para mapear texto → id_ruta
    #         options_dict = {ruta_nombre: id_ruta for id_ruta, ruta_nombre, _ in rutas_list}
    #         options_list = [ruta_nombre for _, ruta_nombre, _ in rutas_list]
    #         
    #         # Selector que muestra solo el nombre de la ruta
    #         ruta_seleccionada = st.selectbox("Seleccione una ruta de cobro:", options=[""] + options_list)
    #         id_ruta_pruebas = options_dict.get(ruta_seleccionada) if ruta_seleccionada else None
    #         nombre_ruta_ui_pruebas = ruta_seleccionada if ruta_seleccionada else None
    #     
    #     # Campo fecha objetivo con default = mañana (America/Bogota)
    #     from datetime import datetime, timedelta
    #     import pytz
    #     
    #     # Obtener fecha de mañana en zona horaria Colombia
    #     try:
    #         tz_colombia = pytz.timezone('America/Bogota')
    #         hoy_colombia = datetime.now(tz_colombia).date()
    #         manana_colombia = hoy_colombia + timedelta(days=1)
    #     except:
    #         # Fallback si hay problemas con timezone
    #         from datetime import date
    #         manana_colombia = date.today() + timedelta(days=1)
    #     
    #     fecha_objetivo = st.date_input(
    #         "Fecha objetivo (proyección visitas):", 
    #         value=manana_colombia,
    #         help="Fecha para la cual se proyectan las visitas (por defecto: mañana)"
    #     )
    
    # Guardar overrides ISM en session state
    if 'pph_override' in locals():
        st.session_state["pph_override"] = pph_override if pph_override else None
    if 'hogares_por_m2_override' in locals():
        st.session_state["hogares_por_m2_override"] = hogares_por_m2_override if hogares_por_m2_override else None
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        submit_button = st.form_submit_button("Generar Mapa", use_container_width=True, type="primary")

# Cerrar card "Configuración y Filtros"
st.markdown('</div>', unsafe_allow_html=True)

# Actualizar pill dinámico (solo si hay fechas disponibles)
if submit_button and 'fecha_inicio' in locals() and 'fecha_fin' in locals():
    st.markdown(
        f'<div class="pill" style="text-align: center; margin: 1rem 0;">{ciudad} · {str(fecha_inicio)} → {str(fecha_fin)}</div>',
        unsafe_allow_html=True
    )

# Card "Resultados y Descargas"
st.markdown('<div class="card sp-2"><div class="card-header">Resultados y Descargas</div>', unsafe_allow_html=True)

# Enlace del mapa (anti-embed)
link_placeholder = st.empty()
if "map_url" in st.session_state and st.session_state["map_url"]:
    link_placeholder.markdown(
      f'<div class="btn-row"><div><a href="{st.session_state["map_url"]}" target="_blank" rel="noopener" class="pill">'
      '🗺️ Ver Mapa en Nueva Pestaña</a></div></div>',
      unsafe_allow_html=True
    )
else:
    link_placeholder.markdown('<div class="muted" style="text-align:center;">Genere un mapa para habilitar el enlace.</div>', unsafe_allow_html=True)

# Descargas (tres botones centrados)

# 1. Descarga HTML del mapa
if tipo_mapa == "Muestras":
    map_filename = st.session_state.get("muestras_last_filename")
    
    if map_filename and os.path.exists(os.path.join("static", "maps", map_filename)):
        from datetime import datetime
        import re
        
        ciudad_html = re.sub(r'[^A-Za-z0-9]', '', ciudad.upper())
        ciudad_html = ciudad_html.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        fecha_actual = datetime.now().strftime("%Y%m%d")
        filename_html = f"Mapa_Muestras_{ciudad_html}_{fecha_actual}.html"
        
        with open(os.path.join("static", "maps", map_filename), "rb") as f:
            html_bytes = f.read()
        
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.download_button(
            label="📥 Descargar HTML del mapa",
            data=html_bytes,
            file_name=filename_html,
            mime="text/html",
            type="secondary",
            use_container_width=True,
            help="Descarga el archivo HTML del mapa generado"
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.button(
            "📥 Descargar HTML del mapa",
            disabled=True,
            type="secondary",
            use_container_width=True,
            help="Genere un mapa para habilitar esta descarga."
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
elif tipo_mapa == "Consultores":
    st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
    st.button(
        "📥 Descargar HTML del mapa",
        disabled=True,
        type="secondary", 
        use_container_width=True,
        help="Descarga HTML no disponible para Consultores"
    )
    st.markdown('</div></div>', unsafe_allow_html=True)

# 2. Descarga CSV (resumen de operación)
if tipo_mapa == "Consultores":
    df_export = st.session_state.get("consultores_export_df")
    export_meta = st.session_state.get("consultores_export_meta")
    
    if df_export is not None and not df_export.empty and export_meta is not None:
        from datetime import datetime
        import re
        
        ciudad_csv = re.sub(r'[^A-Za-z0-9]', '', export_meta["ciudad"].upper())
        ciudad_csv = ciudad_csv.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        
        fecha_ini_str = export_meta["fecha_inicio"].strftime("%Y%m%d")
        fecha_fin_str = export_meta["fecha_fin"].strftime("%Y%m%d")
        timestamp = datetime.now().strftime("%H%M%S")
        
        filename_csv = f"consultores_{ciudad_csv}_{export_meta['id_ruta']}_{fecha_ini_str}-{fecha_fin_str}_{timestamp}.csv"
        
        df_csv = df_export.copy()
        if 'fecha_evento' in df_csv.columns:
            df_csv['fecha_evento'] = pd.to_datetime(df_csv['fecha_evento']).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        if 'id_evento_tipo' in df_csv.columns and 'tipo_evento' in df_csv.columns:
            cols = list(df_csv.columns)
            cols.remove('tipo_evento')
            insert_at = cols.index('id_evento_tipo') + 1
            cols.insert(insert_at, 'tipo_evento')
            df_csv = df_csv[cols]
        
        csv_data = df_csv.to_csv(index=False, sep=';').encode('utf-8-sig')
        
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.download_button(
            label="📥 Descargar CSV (resumen de operación)",
            data=csv_data,
            file_name=filename_csv,
            mime="text/csv",
            type="secondary",
            use_container_width=True,
            help="Descarga los datos mostrados en el mapa"
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.button(
            "📥 Descargar CSV (resumen de operación)",
            disabled=True,
            type="secondary",
            use_container_width=True,
            help="Genere un mapa para habilitar esta descarga."
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
elif tipo_mapa == "Muestras":
    df_export = st.session_state.get("muestras_export_df")
    export_meta = st.session_state.get("muestras_export_meta")
    
    if df_export is not None and not df_export.empty and export_meta is not None:
        from datetime import datetime
        import re
        
        def _fmt_yyyymmdd(x):
            try:
                if hasattr(x, 'strftime'):
                    return x.strftime("%Y%m%d")
                if isinstance(x, str) and x:
                    cleaned = x.replace("-", "")
                    if len(cleaned) >= 8 and cleaned[:8].isdigit():
                        return cleaned[:8]
            except Exception:
                pass
            return datetime.now().strftime("%Y%m%d")
        
        ciudad_csv = re.sub(r'[^A-Za-z0-9]', '', export_meta.get("ciudad", ciudad).upper())
        ciudad_csv = ciudad_csv.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        
        fecha_inicio_fmt = _fmt_yyyymmdd(export_meta.get("fecha_inicio"))
        fecha_fin_fmt = _fmt_yyyymmdd(export_meta.get("fecha_fin"))
        
        filename_csv = f"Muestras_{ciudad_csv}_{fecha_inicio_fmt}_{fecha_fin_fmt}.csv"
        
        csv_data = df_export.to_csv(index=False, sep=';').encode('utf-8-sig')
        
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.download_button(
            label="📥 Descargar CSV (resumen de operación)",
            data=csv_data,
            file_name=filename_csv,
            mime="text/csv",
            type="secondary",
            use_container_width=True,
            help="Descarga los datos mostrados en el mapa"
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.button(
            "📥 Descargar CSV (resumen de operación)",
            disabled=True,
            type="secondary",
            use_container_width=True,
            help="Genere un mapa para habilitar esta descarga."
        )
        st.markdown('</div></div>', unsafe_allow_html=True)

# 3. Descarga CSV ISM (métricas por cuadrante)
if tipo_mapa == "Muestras":
    df_ism_export = st.session_state.get("muestras_ism_df")
    
    if df_ism_export is not None and not df_ism_export.empty:
        from datetime import datetime
        import re
        
        def _fmt_yyyymmdd(x):
            try:
                if hasattr(x, 'strftime'):
                    return x.strftime("%Y%m%d")
                if isinstance(x, str) and x:
                    cleaned = x.replace("-", "")
                    if len(cleaned) >= 8 and cleaned[:8].isdigit():
                        return cleaned[:8]
            except Exception:
                pass
            return datetime.now().strftime("%Y%m%d")
        
        meta_ism = st.session_state.get("muestras_export_meta", {})
        ciudad_ism = re.sub(r'[^A-Za-z0-9]', '', meta_ism.get("ciudad", ciudad).upper())
        ciudad_ism = ciudad_ism.replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U')
        
        fecha_inicio_ism = _fmt_yyyymmdd(meta_ism.get("fecha_inicio"))
        fecha_fin_ism = _fmt_yyyymmdd(meta_ism.get("fecha_fin"))
        
        filename_ism = f"ISM_Muestras_{ciudad_ism}_{fecha_inicio_ism}_{fecha_fin_ism}.csv"
        
        csv_data_ism = df_ism_export.to_csv(index=False, decimal=',').encode('utf-8-sig')
        
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.download_button(
            label="📥 Descargar CSV ISM (métricas por cuadrante)",
            data=csv_data_ism,
            file_name=filename_ism,
            mime="text/csv",
            type="secondary",
            use_container_width=True,
            help="Descarga métricas ISM por cuadrante"
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
        st.button(
            "📥 Descargar CSV ISM (métricas por cuadrante)",
            disabled=True,
            type="secondary",
            use_container_width=True,
            help="Genere un mapa para habilitar esta descarga."
        )
        st.markdown('</div></div>', unsafe_allow_html=True)
elif tipo_mapa == "Consultores":
    st.markdown('<div class="btn-row"><div>', unsafe_allow_html=True)
    st.button(
        "📥 Descargar CSV ISM (métricas por cuadrante)",
        disabled=True,
        type="secondary",
        use_container_width=True,
        help="ISM no disponible para Consultores"
    )
    st.markdown('</div></div>', unsafe_allow_html=True)

# Cerrar card "Resultados y Descargas"
st.markdown('</div>', unsafe_allow_html=True)

# Separador entre cards y procesamiento
st.markdown('<div class="sp-3"></div>', unsafe_allow_html=True)

# Separador sutil entre secciones
st.markdown("<div style='margin: 2rem 0 1.5rem 0;'></div>", unsafe_allow_html=True)

# Card secundario para Cuadrantes (opcional)
ciudad_normalizada = ciudad.upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
editor_url = f"{FLASK_SERVER}/editor/cuadrantes?city={ciudad_normalizada}"

st.markdown(
    f"""
    <style>
    .card-cuadrantes {{
        background: linear-gradient(135deg, #5B21B6 0%, #6D28D9 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1.5rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        border: 1px solid rgba(255,255,255,.15);
    }}
    .card-cuadrantes h3 {{
        margin: 0 0 0.5rem 0;
        font-size: 1.25rem;
        font-weight: bold;
    }}
    .cta-editor {{
        display: inline-block;
        background: rgba(255, 255, 255, 0.2);
        color: white;
        text-decoration: none;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.3s ease;
        border: 1px solid rgba(255, 255, 255, 0.3);
    }}
    .cta-editor:hover {{
        background: rgba(255, 255, 255, 0.3);
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
        text-decoration: none;
        color: white;
    }}
    @media (prefers-color-scheme: dark) {{
        .card-cuadrantes {{
            border-color: rgba(255,255,255,.25);
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
        # if tipo_mapa == "Pedidos":
        #     filename = manejar_error(generar_mapa_pedidos, fecha_inicio, fecha_fin, ciudad, ruta)
        #     map_type = "pedidos"
        # elif tipo_mapa == "Visitas":
        #     if not id_ruta_visitas:
        #         st.error("Seleccione una ruta válida.")
        #         filename = None
        #     else:
        #         filename = manejar_error(
        #             generar_mapa_visitas_individuales,
        #             ciudad,
        #             id_ruta_visitas,  # Pasar ID entero directamente
        #             nombre_ruta_ui_visitas,  # Pasar nombre para mostrar en el mapa
        #             str(fecha_inicio),
        #             str(fecha_fin)
        #         )
        #     map_type = "visitas"
        # elif tipo_mapa == "Facturas Vencidas":
        #     filename = manejar_error(generar_mapa_facturas_vencidas, ciudad, edad_min, edad_max, ruta_cobro)
        #     map_type = "facturas"
        if tipo_mapa == "Muestras":
            override_fc = st.session_state.get("muestras_override_fc")
            promotores_sel = st.session_state.get("promotores_sel")  # <-- de session_state
            # Obtener overrides ISM de los controles
            pph_override = st.session_state.get("pph_override")
            hogares_por_m2_override = st.session_state.get("hogares_por_m2_override")
            
            resultado = manejar_error(
                generar_mapa_muestras, fecha_inicio, fecha_fin, ciudad, barrios, promotores_sel, override_fc, color_mode, verificar_areas, hogares_por_m2_override, pph_override
            )
            if resultado:
                # Manejar el nuevo formato (filename, n_puntos, df_csv, df_ism)
                if isinstance(resultado, tuple) and len(resultado) == 4:
                    filename, n_puntos, df_csv, df_ism = resultado
                    st.session_state["muestras_export_df"] = df_csv
                    st.session_state["muestras_ism_df"] = df_ism  # Nuevo: ISM DataFrame
                    st.session_state["muestras_export_meta"] = {
                        "ciudad": ciudad, 
                        "fecha_inicio": str(fecha_inicio),  # YYYY-MM-DD
                        "fecha_fin": str(fecha_fin)         # YYYY-MM-DD
                    }
                elif isinstance(resultado, tuple) and len(resultado) == 3:
                    # Compatibilidad con formato anterior (sin ISM)
                    filename, n_puntos, df_csv = resultado
                    st.session_state["muestras_export_df"] = df_csv
                    st.session_state["muestras_ism_df"] = None
                    st.session_state["muestras_export_meta"] = {
                        "ciudad": ciudad, 
                        "fecha_inicio": str(fecha_inicio),  # YYYY-MM-DD
                        "fecha_fin": str(fecha_fin)         # YYYY-MM-DD
                    }
                else:
                    filename, n_puntos = resultado
                    st.session_state["muestras_export_df"] = None
                    st.session_state["muestras_ism_df"] = None
                    st.session_state["muestras_export_meta"] = None
                # Guardar filename para el botón de descarga HTML
                st.session_state["muestras_last_filename"] = filename
            else:
                filename, n_puntos = None, 0
                st.session_state["muestras_last_filename"] = None
                st.session_state["muestras_export_df"] = None
                st.session_state["muestras_ism_df"] = None  # Nuevo: limpiar ISM
                st.session_state["muestras_export_meta"] = None
            map_type = "muestras"
        elif tipo_mapa == "Consultores":
            # Validar que se haya seleccionado una ruta válida
            if not id_ruta:
                st.error("Seleccione una ruta válida.")
                filename = None
                n_puntos = 0
            else:
                # Desvío según modo simple o completo
                if modo_simple:
                    # Modo simple: sin cuadrantes, solo capa base + puntos
                    resultado = manejar_error(
                        generar_mapa_consultores_simple,
                        ciudad,
                        int(id_ruta),
                        fecha_inicio,  # Pasar date directamente
                        fecha_fin      # Pasar date directamente
                    )
                    if resultado:
                        filename, n_puntos = resultado
                    else:
                        filename, n_puntos = None, 0
                    # Limpiar session state (simple no exporta CSV)
                    st.session_state["consultores_export_df"] = None
                    st.session_state["consultores_export_meta"] = None
                else:
                    # Modo completo: con cuadrantes y métricas
                    resultado = manejar_error(
                        generar_mapa_consultores,
                        str(fecha_inicio),
                        str(fecha_fin),
                        ciudad,
                        int(id_ruta),
                        nombre_ruta_ui if nombre_ruta_ui else "",
                        mostrar_fuera
                    )
                    if resultado:
                        filename, n_puntos, df_export = resultado
                        # Guardar DataFrame para descarga CSV
                        st.session_state["consultores_export_df"] = df_export
                        st.session_state["consultores_export_meta"] = {
                            "ciudad": ciudad,
                            "id_ruta": id_ruta,
                            "fecha_inicio": fecha_inicio,
                            "fecha_fin": fecha_fin
                        }
                    else:
                        filename, n_puntos = None, 0
                        st.session_state["consultores_export_df"] = None
                        st.session_state["consultores_export_meta"] = None
            map_type = "consultores"
        elif tipo_mapa == "Pruebas":
            # id_ruta_pruebas puede ser None (para "TODOS") o un int
            resultado = manejar_error(
                generar_mapa_pruebas,
                ciudad,               # str (con acentos tal como viene del radio)
                id_ruta_pruebas,      # int | None (None para "TODOS")
                fecha_inicio,         # date
                fecha_fin             # date
            )
            if resultado:
                filename, n_puntos = resultado
            else:
                filename, n_puntos = None, 0
            map_type = "pruebas"

        if filename:
            # Agregar cache-busting al URL del mapa
            timestamp = int(time.time())
            map_url = f"{FLASK_SERVER}/maps/{filename}?t={timestamp}"
            st.session_state["map_url"] = map_url
            # Actualizar el placeholder con el enlace
            link_placeholder.markdown(
                f'<div class="btn-row"><div><a href="{map_url}" target="_blank" rel="noopener" class="pill">'
                '🗺️ Ver Mapa en Nueva Pestaña</a></div></div>', 
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
            f'<div class="btn-row"><div><a href="{st.session_state["map_url"]}" target="_blank" rel="noopener" class="pill">'
            '🗺️ Ver Mapa en Nueva Pestaña</a></div></div>', 
            unsafe_allow_html=True
        )
elif not submit_button:
    link_placeholder.empty()
