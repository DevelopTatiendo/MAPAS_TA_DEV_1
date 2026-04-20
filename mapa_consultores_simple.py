"""
Módulo "Consultores (Simple)" - Genera mapas básicos con puntos sobre comunas.
Sin cuadrantes, sin métricas globales, solo puntos filtrados por ruta + fechas.
"""

import folium
import hashlib
import json
import unicodedata
import pandas as pd
import os
import logging
from datetime import date
from utils.gestor_mapas import guardar_mapa_controlado
from pre_procesamiento.preprocesamiento_consultores import (
    eventos_con_coordenadas_por_ruta_y_rango,
    get_co
)

# Configurar logging
logger = logging.getLogger(__name__)

# =============================================================================
# PALETA DE CONSULTORES — 20 colores de alto contraste, totalmente fija.
# El color es determinístico: mismo id_autor o apellido → mismo color siempre.
# =============================================================================
PALETTE_CONSULTORES = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#469990", "#9A6324",
    "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075",
    "#e6beff", "#fabebe", "#008080", "#ffe119", "#a9a9a9",
]


def _normalize_name(value: str) -> str:
    """Sin tildes, uppercase, espacios colapsados. Ej: 'Gómez  López' → 'GOMEZ LOPEZ'."""
    s = unicodedata.normalize('NFD', str(value or ""))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.upper().split())


def _consultor_key(id_autor, apellido_norm: str) -> str:
    """Clave canónica de agrupación: 'ID_{n}' si hay id_autor, 'AP_{apellido}' si no."""
    if id_autor is not None:
        try:
            if pd.notna(id_autor):
                return f"ID_{int(id_autor)}"
        except (TypeError, ValueError):
            pass
    return f"AP_{apellido_norm}" if apellido_norm else "AP_DESCONOCIDO"


def color_for_consultor(seed_str: str) -> str:
    """
    Color determinístico basado en MD5 del seed.
    seed_str debe ser:
      - "{ciudadN}-{id_autor}"  cuando id_autor está disponible
      - apellido_norm            cuando no hay id_autor
    Mismo seed → mismo color estable entre corridas.
    """
    h = int(hashlib.md5(seed_str.encode('utf-8')).hexdigest(), 16)
    return PALETTE_CONSULTORES[h % len(PALETTE_CONSULTORES)]


def _build_stats_consultores(df: pd.DataFrame) -> list[dict]:
    """
    Calcula estadísticas por consultor desde df_eventos pre-anotado.
    Requiere columnas: consultor_key, apellido_norm, id_autor_norm, color_consultor.
    Retorna lista ordenada por n_eventos descendente.
    El color de cada entrada es exactamente el mismo que se pintó en el mapa.
    """
    if df is None or df.empty:
        return []
    if "consultor_key" not in df.columns:
        return []
    total = len(df)
    rows = []
    for key, grp in df.groupby("consultor_key", sort=False):
        apellido_n = str(grp["apellido_norm"].iloc[0]) if "apellido_norm" in grp.columns else str(key)
        id_a       = grp["id_autor_norm"].iloc[0]  if "id_autor_norm"  in grp.columns else None
        color      = str(grp["color_consultor"].iloc[0]) if "color_consultor" in grp.columns else PALETTE_CONSULTORES[0]
        tipos = grp["id_evento_tipo"].dropna().astype(int)
        rows.append({
            "consultor_key": key,
            "apellido":      apellido_n,   # alias para compatibilidad con _render_legend_html_consultores
            "id_consultor":  id_a,
            "color":         color,        # alias para compatibilidad con _render_legend_html_consultores
            "n_eventos":     len(grp),
            "n_contactos":   int(grp["id_contacto"].nunique()),
            "n_aperturas":   int(tipos.isin([10, 11, 13, 16, 17, 21, 22, 62, 64, 71, 73, 74, 76]).sum()),
            "n_sac":         int(tipos.isin([74, 76]).sum()),
            "n_muestras":    int((tipos == 15).sum()),
            "n_venta_ruta":  int(tipos.isin([57, 58]).sum()),
            "n_venta_fuera": int((tipos == 20).sum()),
            "pct":           (len(grp) / total * 100) if total > 0 else 0.0,
        })
    rows.sort(key=lambda x: x["n_eventos"], reverse=True)
    return rows


def _render_legend_html_consultores(stats: list[dict], titulo: str) -> str:
    """
    Genera HTML de tabla resumen por consultor + JS de ordenamiento por columna.
    Se inyecta directamente como elemento HTML en el mapa Folium.
    """
    if not stats:
        return ""

    T = {k: sum(s[k] for s in stats) for k in
         ("n_eventos", "n_contactos", "n_aperturas", "n_sac",
          "n_muestras", "n_venta_ruta", "n_venta_fuera")}

    def _d(v):
        return "—" if v == 0 else str(v)

    rows_html = "".join(f"""
          <tr>
            <td style="padding:4px 7px;">
              <span style="display:inline-flex;align-items:center;gap:6px;">
                <span style="display:inline-block;width:10px;height:10px;border-radius:2px;
                      background:{s['color']};flex-shrink:0;"></span>
                <span style="white-space:nowrap;">{s['apellido']}</span>
              </span>
            </td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_eventos']}">{s['n_eventos']}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_contactos']}">{s['n_contactos']}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_aperturas']}">{s['n_aperturas']}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_sac']}">{_d(s['n_sac'])}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_muestras']}">{_d(s['n_muestras'])}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_venta_ruta']}">{s['n_venta_ruta']}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['n_venta_fuera']}">{_d(s['n_venta_fuera'])}</td>
            <td style="padding:4px 7px;text-align:right;" data-val="{s['pct']:.2f}">{s['pct']:.1f}%</td>
          </tr>""" for s in stats)

    total_row = f"""
          <tr class="total-row" style="font-weight:600;border-top:2px solid #d1d5db;">
            <td style="padding:4px 7px;">TOTAL</td>
            <td style="padding:4px 7px;text-align:right;">{T['n_eventos']}</td>
            <td style="padding:4px 7px;text-align:right;">{T['n_contactos']}</td>
            <td style="padding:4px 7px;text-align:right;">{T['n_aperturas']}</td>
            <td style="padding:4px 7px;text-align:right;">{_d(T['n_sac'])}</td>
            <td style="padding:4px 7px;text-align:right;">{_d(T['n_muestras'])}</td>
            <td style="padding:4px 7px;text-align:right;">{T['n_venta_ruta']}</td>
            <td style="padding:4px 7px;text-align:right;">{_d(T['n_venta_fuera'])}</td>
            <td style="padding:4px 7px;text-align:right;">100%</td>
          </tr>"""

    def _th(label, col, typ="num"):
        align = "left" if typ == "str" else "right"
        return (f'<th data-col="{col}" data-type="{typ}" style="padding:5px 7px;'
                f'text-align:{align};border-bottom:1px solid #e5e7eb;'
                f'white-space:nowrap;cursor:pointer;user-select:none;">{label}</th>')

    headers = "".join([
        _th("Consultor",   0, "str"),
        _th("Eventos ▼",   1),
        _th("Contactos",   2),
        _th("Aperturas",   3),
        _th("SAC",         4),
        _th("Muestras",    5),
        _th("Vta.Ruta",    6),
        _th("Vta.Fuera",   7),
        _th("% Part.",     8),
    ])

    sort_js = """<script>
(function(){
  var tbl=document.getElementById('tbl-cons');
  if(!tbl)return;
  var tbody=tbl.querySelector('tbody');
  var dir={};
  tbl.querySelectorAll('thead th[data-col]').forEach(function(th){
    th.addEventListener('click',function(){
      var col=parseInt(th.getAttribute('data-col'));
      var isNum=th.getAttribute('data-type')==='num';
      var asc=!dir[col]; dir[col]=asc;
      tbl.querySelectorAll('thead th').forEach(function(h){
        h.textContent=h.textContent.replace(/ [▲▼]$/,'');
      });
      th.textContent=th.textContent+(asc?' ▲':' ▼');
      var rows=Array.from(tbody.querySelectorAll('tr:not(.total-row)'));
      rows.sort(function(a,b){
        var av=a.cells[col],bv=b.cells[col];
        av=av?(av.getAttribute('data-val')||av.textContent.trim()):'';
        bv=bv?(bv.getAttribute('data-val')||bv.textContent.trim()):'';
        if(isNum){av=parseFloat(av)||0;bv=parseFloat(bv)||0;return asc?av-bv:bv-av;}
        return asc?av.localeCompare(bv):bv.localeCompare(av);
      });
      rows.forEach(function(r){tbody.appendChild(r);});
      var tot=tbody.querySelector('.total-row');
      if(tot)tbody.appendChild(tot);
    });
  });
})();
</script>"""

    return f"""
<div id="legend-consultores" style="
    position:fixed;bottom:20px;left:20px;z-index:1000;
    background:white;border:1px solid #e5e7eb;border-radius:8px;
    box-shadow:0 4px 12px rgba(0,0,0,.12);padding:10px 12px;
    max-height:45vh;overflow-y:auto;max-width:95vw;overflow-x:auto;">
  <details open>
    <summary style="cursor:pointer;font-weight:600;font-size:13px;color:#111;margin-bottom:6px;">
      Resumen por consultor — {titulo}
    </summary>
    <table id="tbl-cons" style="border-collapse:collapse;font-size:11px;min-width:520px;">
      <thead><tr>{headers}</tr></thead>
      <tbody>{rows_html}{total_row}</tbody>
    </table>
  </details>
</div>
{sort_js}
"""

def _render_mini_legend_html_consultores(stats: list[dict], titulo: str) -> str:
    """
    Mini leyenda flotante arriba-derecha con máximo 10 consultores.
    Muestra chip de color, nombre y cantidad de eventos.
    Objetivo: validar visualmente que se asignan varios colores sin abrir popups.
    """
    if not stats:
        return ""
    top = stats[:10]
    extra = len(stats) - 10
    items_html = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;padding:2px 0;">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:3px;'
        f'background:{s["color"]};flex-shrink:0;border:1px solid rgba(0,0,0,.15);"></span>'
        f'<span style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
        f'max-width:140px;">{s["apellido"]}</span>'
        f'<span style="font-size:10px;color:#6b7280;margin-left:auto;padding-left:6px;">'
        f'{s["n_eventos"]}</span>'
        f'</div>'
        for s in top
    )
    footer = (
        f'<div style="font-size:10px;color:#6b7280;margin-top:4px;padding-top:4px;'
        f'border-top:1px solid #e5e7eb;">+ {extra} consultores más</div>'
        if extra > 0 else ""
    )
    return f"""
<div id="mini-legend-consultores" style="
    position:fixed;top:80px;right:12px;z-index:1000;
    background:white;border:1px solid #e5e7eb;border-radius:8px;
    box-shadow:0 4px 12px rgba(0,0,0,.12);padding:10px 12px;
    min-width:190px;max-width:220px;">
  <div style="font-weight:600;font-size:12px;color:#111;margin-bottom:6px;
       white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{titulo}</div>
  {items_html}
  {footer}
</div>
"""


def _norm_city(ciudad: str) -> str:
    """Normalizar ciudad removiendo acentos y convirtiendo a mayúsculas."""
    return ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()

def _slug_ciudad(ciudadN: str) -> str:
    """Convierte clave de ciudad normalizada a slug minúsculas (sin tildes ya removidas)."""
    return ciudadN.lower()

def _coords_and_geojson():
    """Coordenadas centrales por ciudad. El GeoJSON base se resuelve dinámicamente en _load_geojson_base()."""
    return {
        'CALI':         [3.4516,  -76.5320],
        'MEDELLIN':     [6.2442,  -75.5812],
        'MANIZALES':    [5.0672,  -75.5174],
        'PEREIRA':      [4.8087,  -75.6906],
        'BOGOTA':       [4.7110,  -74.0721],
        'BARRANQUILLA': [10.9720, -74.7962],
        'BUCARAMANGA':  [7.1193,  -73.1227],
    }

# Fallback de comunas genéricas por ciudad (cuando no existe el cuadrantes_rutas_* file)
_FALLBACK_GEOJSON = {
    'CALI':         'geojson/comunas_cali.geojson',
    'MEDELLIN':     'geojson/comunas_medellin.geojson',
    'MANIZALES':    'geojson/comunas_manizales.geojson',
    'PEREIRA':      'geojson/comunas_pereira.geojson',
    'BOGOTA':       'geojson/comunas_bogota.geojson',
    'BARRANQUILLA': 'geojson/comunas_barranquilla.geojson',
    'BUCARAMANGA':  'geojson/comunas_bucaramanga.geojson',
}

def _load_geojson_base(ciudadN: str):
    """
    Carga el GeoJSON completo de la ciudad para usar como lienzo base.
    Prioridad:
      1. geojson/rutas/{slug}/cuadrantes_rutas_{slug}.geojson  (prediseñado)
      2. _FALLBACK_GEOJSON[ciudadN]                            (comunas genéricas)
    Retorna el objeto GeoJSON parseado o None si ninguno existe / puede leerse.
    """
    slug = _slug_ciudad(ciudadN)
    primary = f"geojson/rutas/{slug}/cuadrantes_rutas_{slug}.geojson"

    for path in (primary, _FALLBACK_GEOJSON.get(ciudadN, "")):
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            logger.info(f"✓ GeoJSON base cargado desde: {path}")
            return data
        except Exception as exc:
            logger.warning(f"No se pudo leer GeoJSON desde {path}: {exc}")

    logger.warning(f"⚠️ No se encontró GeoJSON base para {ciudadN} — el mapa continuará sin capa base")
    return None

def generar_mapa_consultores_simple(ciudad: str, id_ruta, fecha_inicio: date, fecha_fin: date, nombre_ruta_ui: str = "") -> tuple[str, int]:
    """
    Genera un mapa Folium simple con eventos de consultores sobre capa de comunas.
    
    Proceso:
    1) Resuelve centro de operaciones (CO) a partir de 'ciudad'
    2) Convierte fechas date → strings 'YYYY-MM-DD 00:00:00' / '23:59:59'  
    3) Llama a eventos_con_coordenadas_por_ruta_y_rango(CO, id_ruta, f_ini, f_fin)
       id_ruta puede ser None para traer todas las rutas.
    4) Crea folium.Map centrado en la ciudad y sobrepone GeoJSON de comunas
    5) Itera df_eventos y dibuja CircleMarker por fila con popup mínimo
    6) Guarda el html en static/maps y retorna (filename, n_puntos)
    
    Args:
        ciudad (str): Nombre de la ciudad
        id_ruta (int | None): ID de la ruta de cobro; None para todas las rutas.
        fecha_inicio (date): Fecha de inicio
        fecha_fin (date): Fecha de fin
        nombre_ruta_ui (str): Nombre de la ruta tal como se muestra en la UI (e.g. "TODOS").
    
    Returns:
        tuple[str, int]: (filename, n_puntos)
        - filename: Nombre del archivo HTML generado
        - n_puntos: Total de eventos renderizados
    
    Raises:
        ValueError: Si la ciudad no es reconocida
        Exception: Si hay errores en la generación del mapa
    """
    try:
        # 1. Normalizar ciudad y validar
        ciudadN = _norm_city(ciudad)
        centers = _coords_and_geojson()
        
        if ciudadN not in centers:
            raise ValueError(f"Ciudad no reconocida: {ciudad}")
        
        location = centers[ciudadN]
        
        # 2. Obtener centroope
        co = get_co(ciudadN)
        
        # 3. Convertir fechas date → strings con horarios completos
        fecha_inicio_str = f"{fecha_inicio.strftime('%Y-%m-%d')} 00:00:00"
        fecha_fin_str = f"{fecha_fin.strftime('%Y-%m-%d')} 23:59:59"
        
        # 4. Consultar eventos con coordenadas
        logger.info(f"Consultando eventos - CO:{co}, Ruta:{id_ruta}, Fechas:{fecha_inicio_str} a {fecha_fin_str}")
        df_eventos = eventos_con_coordenadas_por_ruta_y_rango(co, id_ruta, fecha_inicio_str, fecha_fin_str)
        
        if df_eventos is None or df_eventos.empty:
            logger.warning("No se encontraron eventos para los parámetros especificados")
            df_eventos = pd.DataFrame()

        # 4b. Materializar columnas de consultor en el DataFrame (una sola vez, antes del render)
        if not df_eventos.empty:
            df_eventos = df_eventos.copy()

            # apellido_norm: sin tildes, uppercase, sin espacios dobles
            apellido_col = (
                df_eventos["apellido"] if "apellido" in df_eventos.columns
                else pd.Series([""] * len(df_eventos), dtype=str)
            )
            df_eventos["apellido_norm"] = apellido_col.apply(
                lambda v: _normalize_name(str(v or ""))
            )

            # id_autor_norm: int o None
            if "id_autor" in df_eventos.columns:
                def _to_int_or_none(v):
                    try:
                        if pd.isna(v):
                            return None
                    except TypeError:
                        pass
                    try:
                        return int(v)
                    except (ValueError, TypeError):
                        return None
                df_eventos["id_autor_norm"] = df_eventos["id_autor"].apply(_to_int_or_none)
            else:
                df_eventos["id_autor_norm"] = None

            # consultor_key: "ID_{n}" si hay id_autor, "AP_{apellido_norm}" si no
            df_eventos["consultor_key"] = df_eventos.apply(
                lambda r: (
                    f"ID_{r['id_autor_norm']}"
                    if r["id_autor_norm"] is not None
                    else (f"AP_{r['apellido_norm']}" if r["apellido_norm"] else "AP_DESCONOCIDO")
                ),
                axis=1,
            )

            # color_consultor: MD5 sobre seed que incluye ciudadN para mayor unicidad
            def _compute_color(r):
                ckey = r["consultor_key"]
                if ckey.startswith("ID_"):
                    seed = f"{ciudadN}-{ckey[3:]}"
                elif ckey.startswith("AP_"):
                    seed = ckey[3:] or "DESCONOCIDO"
                else:
                    seed = ckey or "DESCONOCIDO"
                return color_for_consultor(seed)

            df_eventos["color_consultor"] = df_eventos.apply(_compute_color, axis=1)

            # [CONSULTORES_COLOR] Logging obligatorio de verificación antes de pintar
            resumen_color = (
                df_eventos[["consultor_key", "id_autor_norm", "apellido_norm", "color_consultor"]]
                .drop_duplicates("consultor_key")
                .sort_values("consultor_key")
                .reset_index(drop=True)
            )
            logger.info(f"[CONSULTORES_COLOR] consultores_unicos={len(resumen_color)}")
            logger.info(f"[CONSULTORES_COLOR] top_consultores=\n{resumen_color.to_string(index=False)}")

        # 5. Crear mapa base centrado en la ciudad
        mapa = folium.Map(location=location, zoom_start=12)
        
        # 6. Cargar y añadir GeoJSON completo de la ciudad como lienzo base (sin filtrar por ruta)
        geojson_base = _load_geojson_base(ciudadN)
        if geojson_base is not None:
            folium.GeoJson(
                data=geojson_base,
                name="Base ciudad",
                style_function=lambda feature: {
                    'fillColor': feature.get('properties', {}).get('fillColor', '#e5e7eb'),
                    'color':     feature.get('properties', {}).get('color',     '#6b7280'),
                    'weight':    feature.get('properties', {}).get('weight',    1),
                    'fillOpacity': 0.18,
                }
            ).add_to(mapa)
        
        # 7. Calcular estadísticas por consultor (usa columnas pre-materializadas del DataFrame)
        stats = _build_stats_consultores(df_eventos)

        # 8. Renderizar eventos — color tomado directamente de row["color_consultor"]
        n_puntos = 0
        if not df_eventos.empty:
            for _, row in df_eventos.iterrows():
                lat = row.get("lat")
                lon = row.get("lon")

                if pd.notna(lat) and pd.notna(lon):
                    apellido_n     = str(row.get("apellido_norm", row.get("apellido", "")) or "")
                    id_contacto    = row.get("id_contacto", "N/A")
                    fecha_evento   = row.get("fecha_evento", "Sin fecha")
                    tipo_evento    = row.get("tipo_evento", "")
                    id_evento_tipo = row.get("id_evento_tipo", "")

                    # Color materializado en el DataFrame — no se recalcula aquí
                    color = str(row.get("color_consultor") or PALETTE_CONSULTORES[0])

                    # Formatear fecha
                    if pd.notna(fecha_evento) and hasattr(fecha_evento, "strftime"):
                        fecha_str = fecha_evento.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        fecha_str = str(fecha_evento)

                    # Tipo evento display
                    if pd.isna(tipo_evento) or not tipo_evento or tipo_evento == "":
                        tipo_evt_display = f"Desconocido ({id_evento_tipo})"
                    else:
                        tipo_evt_display = f"{tipo_evento} ({id_evento_tipo})"

                    popup_text = f"""
                    <div style="font-family:Arial,sans-serif;font-size:12px;">
                        <span style="display:inline-block;width:10px;height:10px;border-radius:2px;
                              background:{color};margin-right:5px;vertical-align:middle;"></span>
                        <b>Consultor:</b> {apellido_n}<br>
                        <b>ID Contacto:</b> {id_contacto}<br>
                        <b>Fecha:</b> {fecha_str}<br>
                        <b>Tipo de evento:</b> {tipo_evt_display}
                    </div>
                    """

                    folium.CircleMarker(
                        location=[lat, lon],
                        radius=6,
                        color=color,
                        fill=True,
                        fillColor=color,
                        fillOpacity=0.95,
                        opacity=1.0,
                        weight=2,
                        popup=folium.Popup(popup_text, max_width=280)
                    ).add_to(mapa)

                    n_puntos += 1
        
        # 9. Inyectar leyendas en el mapa
        if stats:
            titulo_leyenda = nombre_ruta_ui if nombre_ruta_ui else ciudad
            # Tabla resumen detallada (abajo-izquierda, ordenable)
            legend_html = _render_legend_html_consultores(stats, titulo_leyenda)
            mapa.get_root().html.add_child(folium.Element(legend_html))
            # Mini leyenda de validación visual (arriba-derecha, top 10)
            mini_html = _render_mini_legend_html_consultores(stats, titulo_leyenda)
            mapa.get_root().html.add_child(folium.Element(mini_html))

        # 10. Guardar mapa usando el helper central
        filename = guardar_mapa_controlado(mapa, tipo_mapa="mapa_consultores_simple", permitir_multiples=False)
        filepath = f"static/maps/{filename}"
        mapa.save(filepath)
        
        logger.info(f"Mapa consultores simple generado: {filename} con {n_puntos} puntos")
        
        return filename, n_puntos
        
    except ValueError as e:
        logger.error(f"Error de parámetros en mapa consultores simple: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"Error generando mapa consultores simple: {str(e)}")
        raise e
