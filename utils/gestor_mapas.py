#gestor_mapas.py

import os
from pathlib import Path
import time
import logging

logger = logging.getLogger(__name__)

def guardar_mapa_controlado(mapa, tipo_mapa, permitir_multiples=False, carpeta='static/maps', max_archivos=10):
    """
    Guarda el mapa HTML con control de duplicación y limpieza.
    - Si permitir_multiples=False, no guarda si ya existe.
    - Siempre limpia para dejar máximo `max_archivos`.
    """
    os.makedirs(carpeta, exist_ok=True)

    if permitir_multiples:
        timestamp = int(time.time())
        filename = f"{tipo_mapa}_{timestamp}.html"
    else:
        filename = f"{tipo_mapa}.html"

    filepath = os.path.join(carpeta, filename)

    if not permitir_multiples and os.path.exists(filepath):
        #logger.info(f"Ya existe el mapa: {filepath}. No se sobrescribe.")
        return filename

    mapa.save(filepath)
    logger.info(f"Mapa guardado en {filepath}")
    limpiar_mapas_antiguos(carpeta, tipo_mapa, max_archivos)
    return filename

def limpiar_mapas_antiguos(directorio, prefijo, max_archivos):
    archivos = sorted(
        [f for f in Path(directorio).glob(f"{prefijo}*.html")],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    for archivo in archivos[max_archivos:]:
        try:
            archivo.unlink()
            logger.info(f"Archivo eliminado: {archivo.name}")
        except Exception as e:
            logger.warning(f"Error al eliminar {archivo.name}: {e}")
