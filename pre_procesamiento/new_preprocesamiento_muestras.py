"""Nuevo módulo de preprocesamiento para muestras (Fase 1).

Responsabilidad limitada a:
1. Consultar la BD (consultar_db)
2. Limpiar / normalizar DataFrame crudo (crear_df)

No calcula métricas, no agrupa, no deduplica. Preparación básica de datos.
"""

from __future__ import annotations

import pandas as pd
from typing import List, Optional
import unicodedata
from .db_utils import sql_read  # Reutilizamos helper existente de lectura SQL
from datetime import datetime, timedelta
import numpy as np

# Columnas estándar esperadas en la salida normalizada
COLUMNAS_ESTANDAR = [
    "id_muestra",
    "id_contacto",
    "fecha_evento",
    "id_evento_tipo",
    "id_promotor",
    "coordenada_longitud",
    "coordenada_latitud",
    "medio_contacto",
    "tipo_evento",
    "id_contacto_categoria",
    "ultima_llamada",
    "id_barrio",
    "barrio",
    "apellido_promotor",
    "mes",
]

def listar_promotores(id_centroope: int, fecha_inicio: str, fecha_fin: str) -> pd.DataFrame:
    """Lista promotores (cargo=39) con actividad en el rango y centro dados.

    Retorna columnas estándar para UI:
      - id_promotor (int)
      - apellido_promotor (str)
    """
    query = (
        """
        SELECT DISTINCT
            per.id AS id_promotor,
            per.apellido AS apellido_promotor
        FROM fullclean_contactos.vwEventos e
        INNER JOIN fullclean_personal.personal per
            ON per.id = e.id_autor AND per.id_cargo = 39
        INNER JOIN fullclean_contactos.vwContactos con
            ON con.id = e.id_contacto
        INNER JOIN fullclean_contactos.ciudades ciu
            ON ciu.id = con.id_ciudad
        WHERE
            e.fecha_evento BETWEEN :fecha_inicio AND :fecha_fin
            AND ciu.id_centroope = :id_centroope
            AND e.id_evento_tipo = 15
        ORDER BY per.apellido
        """
    )
    params = {
        "fecha_inicio": f"{fecha_inicio} 00:00:00",
        "fecha_fin": f"{fecha_fin} 23:59:59",
        "id_centroope": int(id_centroope),
    }
    df = sql_read(query, params=params, schema="fullclean_contactos")
    if df is None or df.empty:
        return pd.DataFrame(columns=["id_promotor", "apellido_promotor"])
    # Normalización de tipos
    if "id_promotor" in df.columns:
        df["id_promotor"] = pd.to_numeric(df["id_promotor"], errors="coerce").astype("Int64")
    if "apellido_promotor" in df.columns:
        df["apellido_promotor"] = df["apellido_promotor"].fillna("").astype(str)
    return df[[c for c in ["id_promotor", "apellido_promotor"] if c in df.columns]].dropna(subset=["id_promotor"]).drop_duplicates("id_promotor").reset_index(drop=True)
    
def consultar_db(
    id_centroope: int,
    fecha_inicio: str,
    fecha_fin: str,
    ids_promotor: Optional[List[int]] = None,
) -> pd.DataFrame:
    """Ejecuta una consulta única para eventos de muestras.

    Retorna DataFrame crudo con las columnas solicitadas. Si no hay filas,
    devuelve DataFrame vacío con las columnas esperadas.
    """
    query = (
        """
        SELECT
            e.idEvento        AS id_muestra,
            e.id_contacto     AS id_contacto,
            e.fecha_evento    AS fecha_evento,
            e.id_evento_tipo  AS id_evento_tipo,
            e.id_autor        AS id_promotor,
            e.coordenada_longitud,
            e.coordenada_latitud,
            e.medio_contacto,
            e.tipo_evento,
            con.id_categoria  AS id_contacto_categoria,
            con.ultima_llamada AS ultima_llamada,
            con.id_barrio     AS id_barrio,
            bar.barrio        AS barrio,
            per.apellido      AS apellido_promotor,
            MONTH(e.fecha_evento) AS mes
        FROM fullclean_contactos.vwEventos e
        INNER JOIN fullclean_contactos.vwContactos con ON con.id = e.id_contacto
        LEFT JOIN fullclean_contactos.barrios bar ON bar.id = con.id_barrio
        INNER JOIN fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
        INNER JOIN fullclean_personal.personal per ON per.id = e.id_autor AND per.id_cargo = 39
        WHERE
            e.fecha_evento BETWEEN :fecha_inicio AND :fecha_fin
            AND ciu.id_centroope = 2
            AND e.id_evento_tipo = 15
            AND e.coordenada_longitud <> 0
            AND e.coordenada_latitud <> 0
        """
    )

    params = {
        "fecha_inicio": f"{fecha_inicio} 00:00:00",
        "fecha_fin": f"{fecha_fin} 23:59:59",
        "id_centroope": id_centroope,
    }

    # Filtro opcional por lista de promotores
    if ids_promotor:
        ids_promotor_limpios = [int(x) for x in ids_promotor if str(x).strip()]
        if ids_promotor_limpios:
            placeholders = ",".join([f":pid_{i}" for i in range(len(ids_promotor_limpios))])
            query += f" AND e.id_autor IN ({placeholders})"
            for i, v in enumerate(ids_promotor_limpios):
                params[f"pid_{i}"] = v

    query += ";"

    df_raw = sql_read(query, params=params, schema="fullclean_contactos")
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=COLUMNAS_ESTANDAR)
    return df_raw


def crear_df(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Normaliza columnas, tipos y limpia filas inválidas.

    No aplica deduplicación ni cálculos de métricas.
    """
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=COLUMNAS_ESTANDAR)

    df = df_raw.copy()

    # Posibles variantes de nombres -> estándar
    mapping_variantes = {
        "ID_MUESTRA": "id_muestra",
        "ID_EVENTO": "id_muestra",
        "ID_CONTACTO": "id_contacto",
        "FECHA_EVENTO": "fecha_evento",
        "ID_EVENTO_TIPO": "id_evento_tipo",
        "ID_AUTOR": "id_promotor",
        "ID_PROMOTOR": "id_promotor",
        "COORDENADA_LONGITUD": "coordenada_longitud",
        "COORDENADA_LATITUD": "coordenada_latitud",
        "MEDIO_CONTACTO": "medio_contacto",
        "TIPO_EVENTO": "tipo_evento",
        "ID_CATEGORIA": "id_contacto_categoria",
        "ID_CONTACTO_CATEGORIA": "id_contacto_categoria",
        "ULTIMA_LLAMADA": "ultima_llamada",
        "ID_BARRIO": "id_barrio",
        "BARRIO": "barrio",
        "APELLIDO_PROMOTOR": "apellido_promotor",
    }

    # Renombrar columnas por coincidencia exacta en mayúsculas
    cols_actuales = df.columns.tolist()
    rename_map = {}
    for c in cols_actuales:
        cu = c.upper()
        if cu in mapping_variantes:
            rename_map[c] = mapping_variantes[cu]
    if rename_map:
        df.rename(columns=rename_map, inplace=True)

    # Asegurar presencia de todas las columnas estándar (crear vacías si faltan)
    for col in COLUMNAS_ESTANDAR:
        if col not in df.columns:
            df[col] = pd.NA

    # Tipos básicos
    for col in ["fecha_evento", "ultima_llamada"]:
        if col in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in ["coordenada_latitud", "coordenada_longitud"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["id_muestra", "id_contacto", "id_evento_tipo", "id_promotor", "id_contacto_categoria", "id_barrio"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Filtrado básico
    if "fecha_evento" in df.columns:
        df = df[df["fecha_evento"].notna()]
    if {"coordenada_latitud", "coordenada_longitud"}.issubset(df.columns):
        df = df[df["coordenada_latitud"].notna() & df["coordenada_longitud"].notna()]

    # Columna mes
    if "mes" not in df.columns or df["mes"].isna().all():
        if "fecha_evento" in df.columns:
            df["mes"] = df["fecha_evento"].dt.month.astype("Int64")
        else:
            df["mes"] = pd.NA

    return df.reset_index(drop=True)[COLUMNAS_ESTANDAR]


__all__ = ["consultar_db", "crear_df", "COLUMNAS_ESTANDAR", "listar_promotores"]

# === Nuevas funciones Fase 2: Anclas, Candidatos y Asignación ===

def obtener_anclas_visita_programada(
    ids_contacto: list[int],
    id_centroope: int = 2
) -> pd.DataFrame:
    """
    Devuelve un DataFrame con 1 evento (con coordenadas válidas) por cada id_contacto en ids_contacto.
    Cada fila representa una 'visita programada' (ancla).

    Columnas mínimas esperadas:
        - id_muestra         (e.idEvento)
        - id_contacto
        - nombre             (con.nombre)
        - direccion          (con.direccion)
        - ciudad             (ciu.ciudad)
        - fecha_evento
        - id_evento_tipo
        - id_autor
        - coordenada_longitud
        - coordenada_latitud
        - tipo_evento
        - id_contacto_categoria
        - ultima_llamada
        - id_barrio
        - barrio
        - apellido_autor
        - mes                (MONTH(fecha_evento))
        - es_visita_programada (1)
    """
    ids_contacto = [int(x) for x in (ids_contacto or []) if str(x).strip()]

    # 1) Caso sin IDs → DF vacío y salimos
    if not ids_contacto:
        return pd.DataFrame(columns=[
            "id_muestra","id_contacto","nombre","direccion","ciudad","fecha_evento",
            "id_evento_tipo","id_autor","coordenada_longitud","coordenada_latitud","tipo_evento",
            "id_contacto_categoria","ultima_llamada","id_barrio","barrio","apellido_autor","mes",
            "es_visita_programada"
        ])

    # 2) Caso normal → construir placeholders y query FUERA del if
    placeholders = ",".join([f":cid_{i}" for i in range(len(ids_contacto))])
    query = f"""
    SELECT
        e.idEvento               AS id_muestra,
        e.id_contacto            AS id_contacto,
        con.nombre               AS nombre,
        CAST(NULL AS CHAR)       AS direccion,
        ciu.ciudad               AS ciudad,
        e.fecha_evento           AS fecha_evento,
        e.id_evento_tipo         AS id_evento_tipo,
        e.id_autor               AS id_autor,
        e.coordenada_longitud    AS coordenada_longitud,
        e.coordenada_latitud     AS coordenada_latitud,
        e.tipo_evento            AS tipo_evento,
        con.id_categoria         AS id_contacto_categoria,
        con.ultima_llamada       AS ultima_llamada,
        con.id_barrio            AS id_barrio,
        bar.barrio               AS barrio,
        per.apellido             AS apellido_autor,
        MONTH(e.fecha_evento)    AS mes
    FROM fullclean_contactos.vwEventos e
    JOIN fullclean_contactos.vwContactos con ON con.id = e.id_contacto
    JOIN fullclean_contactos.ciudades ciu    ON ciu.id = con.id_ciudad
    LEFT JOIN fullclean_contactos.barrios bar ON bar.id = con.id_barrio
    JOIN fullclean_personal.personal per     ON per.id = e.id_autor AND per.id_cargo = 39
    JOIN (
        SELECT 
            e2.id_contacto,
            MAX(e2.idEvento) AS idEvento
        FROM fullclean_contactos.vwEventos e2
        JOIN fullclean_contactos.vwContactos con2 ON con2.id = e2.id_contacto
        JOIN fullclean_contactos.ciudades ciu2    ON ciu2.id = con2.id_ciudad
        WHERE ciu2.id_centroope = :id_centroope
          AND e2.id_contacto IN ({placeholders})
          AND e2.coordenada_latitud  IS NOT NULL
          AND e2.coordenada_longitud IS NOT NULL
          AND e2.coordenada_latitud  <> 0
          AND e2.coordenada_longitud <> 0
        GROUP BY e2.id_contacto
    ) AS ult
        ON ult.id_contacto = e.id_contacto
       AND ult.idEvento    = e.idEvento
    WHERE ciu.id_centroope      = :id_centroope
      AND e.coordenada_latitud  IS NOT NULL
      AND e.coordenada_longitud IS NOT NULL
      AND e.coordenada_latitud  <> 0
      AND e.coordenada_longitud <> 0
    ;
    """

    params = {"id_centroope": int(id_centroope)}
    for i, cid in enumerate(ids_contacto):
        params[f"cid_{i}"] = int(cid)

    df = sql_read(query, params=params, schema="fullclean_contactos")
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "id_muestra","id_contacto","nombre","direccion","ciudad","fecha_evento",
            "id_evento_tipo","id_autor","coordenada_longitud","coordenada_latitud","tipo_evento",
            "id_contacto_categoria","ultima_llamada","id_barrio","barrio","apellido_autor","mes",
            "es_visita_programada"
        ])

    df["es_visita_programada"] = 1
    return df


def obtener_candidatos_no_fieles_cali_2m(
    ids_contacto_excluir: list[int],
    fecha_referencia: datetime | None = None
) -> pd.DataFrame:
    """
    Devuelve un DF de clientes candidatos (no fieles) en Cali, últimos 2 meses,
    con coordenadas válidas, excluyendo los contactos de ids_contacto_excluir (anclas).
    """
    # Ventana fija 60 días hacia atrás
    if fecha_referencia is None:
        fecha_referencia = datetime.now()
    f_fin = fecha_referencia.strftime("%Y-%m-%d") + " 23:59:59"
    f_ini = (fecha_referencia - timedelta(days=60)).strftime("%Y-%m-%d") + " 00:00:00"

    ids_excluir = [int(x) for x in (ids_contacto_excluir or []) if str(x).strip()]
    placeholders_ex = ",".join([f":ex_{i}" for i in range(len(ids_excluir))]) if ids_excluir else None

    # Nota: Reusar lógica de 'cliente no fiel' y filtro de muestras (id_evento_tipo) del proyecto.
    # Aquí asumimos id_evento_tipo = 15 para muestras, y condición de no fiel basada en id_categoria.
    query = f"""
        SELECT
                e.idEvento               AS id_evento_candidato,
                e.id_contacto            AS id_contacto,
                con.nombre               AS nombre,
                CAST(NULL AS CHAR)       AS direccion,
                ciu.ciudad               AS ciudad,
                e.fecha_evento           AS fecha_evento,
                e.id_evento_tipo         AS id_evento_tipo,
                e.id_autor               AS id_autor,
                e.coordenada_latitud     AS lat,
                e.coordenada_longitud    AS lon,
                e.tipo_evento            AS tipo_evento,
                con.id_categoria         AS id_contacto_categoria,
                con.id_barrio            AS id_barrio,
                bar.barrio               AS barrio,
                per.apellido             AS apellido_autor
        FROM fullclean_contactos.vwEventos e
        JOIN fullclean_contactos.vwContactos con ON con.id = e.id_contacto
        JOIN fullclean_contactos.ciudades ciu ON ciu.id = con.id_ciudad
        LEFT JOIN fullclean_contactos.barrios bar ON bar.id = con.id_barrio
        JOIN fullclean_personal.personal per ON per.id = e.id_autor
        JOIN (
                SELECT e2.id_contacto, MAX(e2.idEvento) AS idEvento
                FROM fullclean_contactos.vwEventos e2
                JOIN fullclean_contactos.vwContactos con2 ON con2.id = e2.id_contacto
                JOIN fullclean_contactos.ciudades ciu2 ON ciu2.id = con2.id_ciudad
                WHERE ciu2.id_centroope = 2
                    AND e2.fecha_evento BETWEEN :f_ini AND :f_fin
                    AND e2.id_evento_tipo = 15
                    AND e2.coordenada_latitud IS NOT NULL AND e2.coordenada_longitud IS NOT NULL
                    AND e2.coordenada_latitud <> 0 AND e2.coordenada_longitud <> 0
                    AND e2.coordenada_latitud BETWEEN -5 AND 13
                    AND e2.coordenada_longitud BETWEEN -81 AND -66
                GROUP BY e2.id_contacto
        ) AS ult ON ult.id_contacto = e.id_contacto AND ult.idEvento = e.idEvento
        WHERE ciu.id_centroope = 2
            AND e.id_evento_tipo = 15
            AND e.fecha_evento BETWEEN :f_ini AND :f_fin
            AND e.coordenada_latitud IS NOT NULL AND e.coordenada_longitud IS NOT NULL
            AND e.coordenada_latitud <> 0 AND e.coordenada_longitud <> 0
            AND e.coordenada_latitud BETWEEN -5 AND 13
            AND e.coordenada_longitud BETWEEN -81 AND -66
            AND (con.id_categoria IS NULL OR con.id_categoria NOT IN (/* categorias fieles */ 1))
            {"AND e.id_contacto NOT IN (" + placeholders_ex + ")" if placeholders_ex else ""}
        ;
        """

    params = {"f_ini": f_ini, "f_fin": f_fin}
    for i, cid in enumerate(ids_excluir):
        params[f"ex_{i}"] = int(cid)

    df = sql_read(query, params=params, schema="fullclean_contactos")
    if df is None:
        return pd.DataFrame(columns=[
            "id_evento_candidato","id_contacto","nombre","direccion","ciudad","fecha_evento",
            "id_evento_tipo","id_autor","lat","lon","tipo_evento","id_contacto_categoria",
            "id_barrio","barrio","apellido_autor"
        ])
    return df


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    Calcula la distancia Haversine entre dos puntos (en grados) en METROS.
    Devuelve np.nan si alguna coordenada no es numérica.
    """
    try:
        lat1 = float(lat1)
        lon1 = float(lon1)
        lat2 = float(lat2)
        lon2 = float(lon2)
    except (TypeError, ValueError):
        return np.nan

    # Si alguna coordenada es NaN, devolvemos NaN también
    if any(np.isnan([lat1, lon1, lat2, lon2])):
        return np.nan

    R = 6371000.0  # Radio de la tierra en metros
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)

    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return R * c


def asignar_prospectos_a_anclas(
    df_anclas: pd.DataFrame,
    df_candidatos: pd.DataFrame,
    radio_m: float = 300.0,
    max_prospectos_por_ancla: int = 4
) -> pd.DataFrame:
    """
    Asigna candidatos (prospectos) a cada ancla según proximidad geográfica (Haversine).
    """
    cols_result = [
        "id_contacto","tipo_punto","id_contacto_ancla","id_evento","lat","lon",
        "distancia_m","orden_en_radio","ciudad","barrio","nombre","direccion","apellido_autor",
        "es_visita_programada"
    ]

    if df_anclas is None or df_anclas.empty:
        return pd.DataFrame(columns=cols_result)

    # Copias defensivas
    df_anclas = df_anclas.copy()
    df_candidatos = df_candidatos.copy()

    # Normalizar nombres de columnas de coordenadas (si vienen con nombres base)
    if "coordenada_latitud" in df_anclas.columns and "coordenada_longitud" in df_anclas.columns:
        df_anclas["lat_ancla"] = df_anclas["coordenada_latitud"]
        df_anclas["lon_ancla"] = df_anclas["coordenada_longitud"]

    if "coordenada_latitud" in df_candidatos.columns and "coordenada_longitud" in df_candidatos.columns:
        df_candidatos["lat"] = df_candidatos["coordenada_latitud"]
        df_candidatos["lon"] = df_candidatos["coordenada_longitud"]

    # Forzar coordenadas a float
    for col in ["lat_ancla", "lon_ancla"]:
        if col in df_anclas.columns:
            df_anclas[col] = pd.to_numeric(df_anclas[col], errors="coerce")

    for col in ["lat", "lon"]:
        if col in df_candidatos.columns:
            df_candidatos[col] = pd.to_numeric(df_candidatos[col], errors="coerce")

    # Eliminar filas sin coordenadas válidas
    if {"lat_ancla", "lon_ancla"}.issubset(df_anclas.columns):
        df_anclas = df_anclas.dropna(subset=["lat_ancla", "lon_ancla"])
    if {"lat", "lon"}.issubset(df_candidatos.columns):
        df_candidatos = df_candidatos.dropna(subset=["lat", "lon"])

    # Base: anclas
    anclas = df_anclas.copy()
    anclas = anclas.rename(columns={
        "coordenada_latitud": "lat",
        "coordenada_longitud": "lon",
        "apellido_autor": "apellido_autor"
    })

    # DF resultado inicia con las anclas
    df_res_anclas = pd.DataFrame({
        "id_contacto": anclas["id_contacto"].values,
        "tipo_punto": ["ANCLA"] * len(anclas),
        "id_contacto_ancla": anclas["id_contacto"].values,
        "id_evento": anclas["id_muestra"].values,
        "lat": anclas["lat"].values,
        "lon": anclas["lon"].values,
        "distancia_m": [0.0] * len(anclas),
        "orden_en_radio": [0] * len(anclas),
        "ciudad": anclas.get("ciudad", pd.Series([None]*len(anclas))).values,
        "barrio": anclas.get("barrio", pd.Series([None]*len(anclas))).values,
        "nombre": anclas.get("nombre", pd.Series([None]*len(anclas))).values,
        "direccion": anclas.get("direccion", pd.Series([None]*len(anclas))).values,
        "apellido_autor": anclas.get("apellido_autor", pd.Series([None]*len(anclas))).values,
        "es_visita_programada": [1] * len(anclas)
    })

    if df_candidatos is None or df_candidatos.empty:
        return df_res_anclas[cols_result]

    # Construir pares ancla-candidato (producto cartesiano)
    A = anclas[["id_contacto","lat","lon"]].rename(columns={"id_contacto":"id_contacto_ancla","lat":"lat_ancla","lon":"lon_ancla"})
    C = df_candidatos[["id_contacto","lat","lon","id_evento_candidato","ciudad","barrio","nombre","direccion","apellido_autor"]].rename(columns={"id_contacto":"id_contacto_candidato"})

    A["key"] = 1
    C["key"] = 1
    pairs = A.merge(C, on="key").drop(columns=["key"])

    # Calcular distancia y filtrar por radio
    pairs["distancia_m"] = pairs.apply(lambda r: haversine_m(r["lat_ancla"], r["lon_ancla"], r["lat"], r["lon"]), axis=1)
    pairs = pairs[pairs["distancia_m"] <= float(radio_m)]

    if pairs.empty:
        return df_res_anclas[cols_result]

    # Cada candidato con su ancla más cercana
    idx_min = pairs.groupby("id_contacto_candidato")["distancia_m"].idxmin()
    pairs_min = pairs.loc[idx_min].copy()

    # Para cada ancla, ordenar candidatos y recortar al máximo
    pairs_min.sort_values(["id_contacto_ancla","distancia_m"], inplace=True)
    pairs_min["orden_en_radio"] = pairs_min.groupby("id_contacto_ancla").cumcount() + 1
    pairs_min = pairs_min[pairs_min["orden_en_radio"] <= int(max_prospectos_por_ancla)]

    # Construir filas de prospectos
    df_res_pros = pd.DataFrame({
        "id_contacto": pairs_min["id_contacto_candidato"].values,
        "tipo_punto": ["PROSPECTO"] * len(pairs_min),
        "id_contacto_ancla": pairs_min["id_contacto_ancla"].values,
        "id_evento": pairs_min["id_evento_candidato"].values,
        "lat": pairs_min["lat"].values,
        "lon": pairs_min["lon"].values,
        "distancia_m": pairs_min["distancia_m"].values,
        "orden_en_radio": pairs_min["orden_en_radio"].values,
        "ciudad": pairs_min["ciudad"].values,
        "barrio": pairs_min["barrio"].values,
        "nombre": pairs_min["nombre"].values,
        "direccion": pairs_min["direccion"].values,
        "apellido_autor": pairs_min["apellido_autor"].values,
        "es_visita_programada": [0] * len(pairs_min)
    })

    df_resultado = pd.concat([df_res_anclas, df_res_pros], ignore_index=True)
    # Forzar tipos numéricos finales en lat/lon para evitar strings concatenados
    for col in ["lat", "lon"]:
        if col in df_resultado.columns:
            df_resultado[col] = pd.to_numeric(df_resultado[col], errors="coerce")
    return df_resultado[cols_result]
