from pathlib import Path
import os
import sys
from datetime import datetime
import pandas as pd

# Asegurar importación de paquetes del proyecto cuando se ejecuta desde Pruebas/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pre_procesamiento.new_preprocesamiento_muestras import (
    obtener_anclas_visita_programada,
    obtener_candidatos_no_fieles_cali_2m,
    asignar_prospectos_a_anclas,
)
from mapa_pruebas import generar_mapa_anclas_prospectos

# Lista fija de anclas
IDS_ANCLAS = [
    50153,
    223992,
    337347,
    157862,
    283184,
    59168,
    59820,
    159658,
    335902,
    336052,
    340529,
    1490041,
    51404,
    55320,
    222968,
    354255,
    1495295,
]

# Fecha de referencia reproducible
fecha_ref = datetime.strptime(os.getenv("FECHA_REF", "2025-11-25"), "%Y-%m-%d")

# Ejecutar flujo
print("[TEST] Obteniendo anclas...")
df_anclas = obtener_anclas_visita_programada(IDS_ANCLAS, id_centroope=2)
print(f"[TEST] Anclas: {len(df_anclas)} filas")

print("[TEST] Obteniendo candidatos...")
df_candidatos = obtener_candidatos_no_fieles_cali_2m(IDS_ANCLAS, fecha_referencia=fecha_ref)
print(f"[TEST] Candidatos: {len(df_candidatos)} filas")

print("[TEST] Asignando prospectos a anclas...")
df_resultado = asignar_prospectos_a_anclas(df_anclas, df_candidatos, radio_m=100.0, max_prospectos_por_ancla=4)
print(f"[TEST] Resultado total: {len(df_resultado)} filas")

# Debug ligero para detectar valores corruptos
try:
    print("[DEBUG] dtypes df_resultado:")
    print(df_resultado[["lat", "lon"]].dtypes)
    mask_rara = df_resultado["lat"].astype(str).str.len() > 20
    df_raras = df_resultado[mask_rara][["tipo_punto", "id_contacto", "lat", "lon"]].head(10)
    print("[DEBUG] Filas con lat rara (>20 chars):")
    if not df_raras.empty:
        print(df_raras.to_string(index=False))
    else:
        print("(ninguna)")
except Exception as e:
    print(f"[DEBUG] Error inspeccionando df_resultado: {e}")

# Guardar CSVs en Resultados/
ROOT = Path(__file__).resolve().parents[1]
RESULTADOS_DIR = ROOT / "Resultados_pruebas_anclas"
os.makedirs(RESULTADOS_DIR, exist_ok=True)

# Anclas
anclas_csv = RESULTADOS_DIR / "anclas.csv"
pros_csv = RESULTADOS_DIR / "prospectos.csv"
full_csv = RESULTADOS_DIR / "anclas_prospectos_full.csv"

try:
    df_anclas_out = df_resultado[df_resultado["tipo_punto"] == "ANCLA"].copy()
    df_pros_out = df_resultado[df_resultado["tipo_punto"] == "PROSPECTO"].copy()

    df_anclas_out.to_csv(anclas_csv, index=False, sep=";")
    df_pros_out.to_csv(pros_csv, index=False, sep=";")
    df_resultado.to_csv(full_csv, index=False, sep=";")
    print(f"[TEST] Guardados:\n - {anclas_csv}\n - {pros_csv}\n - {full_csv}")
    # Generar mapa HTML
    filename = generar_mapa_anclas_prospectos(df_resultado, ciudad="CALI")
    print(f"[TEST] Mapa generado: static/maps/{filename}")
except Exception as e:
    print(f"[TEST] Error guardando CSVs: {e}")
