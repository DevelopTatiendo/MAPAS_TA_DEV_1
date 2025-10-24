#!/usr/bin/env python3
"""
GeoJSON Sweep Line Reordering Tool

Reordena códigos de cuadrantes por sweep line (arriba hacia abajo, izquierda a derecha)
manteniendo el prefijo auto-inferido (CL, PR, MD, etc.).

Configuración:
    Editar INPUT_PATH con la ruta del archivo GeoJSON de entrada
    
Salida:
    Genera {nombre_base}_order.geojson en la misma carpeta
"""

import json
import re
from pathlib import Path
import logging

# Required imports
try:
    from shapely.geometry import shape
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False
    print("WARNING: Shapely no disponible - usando cálculo de bounds aproximado")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================================================================================================
# CONFIGURACIÓN - CAMBIAR ESTA RUTA
# ================================================================================================

INPUT_PATH = r"C:\Users\ESP_NEGOCIO\Documents\GitHub\MAPAS_TA_DEV_1\geojson\pap\manizales_base.geojson"

# ================================================================================================
# CONSTANTES
# ================================================================================================

DIGITS = 3  # Siempre 3 dígitos para códigos

# Diccionario ciudad → prefijo (opcional)
CITY_PREFIX_MAP = {
    'CALI': 'CL',
    'MANIZALES': 'MZ', 
    'BOGOTA': 'BG',
    'BOGOTÁ': 'BG',
    'MEDELLIN': 'MD',
    'MEDELLÍN': 'MD',
    'PEREIRA': 'PR',
    'BUCARAMANGA': 'BC',
    'BARRANQUILLA': 'BR'
}


def auto_infer_prefix(features, input_path):
    """
    Auto-iniere el prefijo XX desde los códigos existentes o el contexto.
    
    Args:
        features: Lista de features del GeoJSON
        input_path: Path del archivo de entrada
        
    Returns:
        str: Prefijo de 2 caracteres (ej: 'CL', 'MZ', etc.)
    """
    # 1. Buscar patrón ^[A-Z]{2}_\d+$ en properties["codigo"]
    prefix_counts = {}
    pattern = re.compile(r'^([A-Z]{2})_\d+$')
    
    for feature in features:
        props = feature.get('properties', {})
        codigo = props.get('codigo')
        
        if codigo:
            match = pattern.match(str(codigo).upper())
            if match:
                prefix = match.group(1)
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
    
    # Prefijo mayoritario
    if prefix_counts:
        most_common = max(prefix_counts.items(), key=lambda x: x[1])
        logger.info(f"Prefijo auto-detectado: '{most_common[0]}' ({most_common[1]} ocurrencias)")
        return most_common[0]
    
    # 2. Intentar desde properties["ciudad"]
    for feature in features:
        props = feature.get('properties', {})
        ciudad = props.get('ciudad', '').upper().strip()
        
        if ciudad in CITY_PREFIX_MAP:
            prefix = CITY_PREFIX_MAP[ciudad]
            logger.info(f"Prefijo inferido desde ciudad '{ciudad}': '{prefix}'")
            return prefix
    
    # 3. Usar primeras dos letras del nombre de archivo
    filename = Path(input_path).stem.upper()
    if len(filename) >= 2:
        prefix = filename[:2]
        logger.info(f"Prefijo desde nombre de archivo '{filename}': '{prefix}'")
        return prefix
    
    # 4. Fallback
    logger.warning("No se pudo inferir prefijo - usando 'XX'")
    return "XX"


def get_geometry_bounds(geometry):
    """
    Obtiene bounds (minx, miny, maxx, maxy) de una geometría.
    
    Args:
        geometry: Geometría GeoJSON
        
    Returns:
        tuple: (minx, miny, maxx, maxy)
    """
    if HAS_SHAPELY:
        try:
            geom = shape(geometry)
            return geom.bounds
        except Exception as e:
            logger.warning(f"Error calculando bounds con Shapely: {e}")
    
    # Fallback sin Shapely
    coords = geometry.get('coordinates', [])
    if not coords:
        return (0.0, 0.0, 0.0, 0.0)
    
    def flatten_coordinates(coord_list):
        """Aplana recursivamente las coordenadas."""
        flat = []
        for item in coord_list:
            if isinstance(item, (list, tuple)):
                if len(item) == 2 and all(isinstance(x, (int, float)) for x in item):
                    # Es un par de coordenadas [lon, lat]
                    flat.append(item)
                else:
                    # Es anidado, continuar recursión
                    flat.extend(flatten_coordinates(item))
        return flat
    
    all_coords = flatten_coordinates(coords)
    if not all_coords:
        return (0.0, 0.0, 0.0, 0.0)
    
    lons = [coord[0] for coord in all_coords]
    lats = [coord[1] for coord in all_coords]
    
    return (min(lons), min(lats), max(lons), max(lats))


def calculate_sweep_position(bounds):
    """
    Calcula la posición para el ordenamiento sweep line.
    
    Criterio: arriba hacia abajo (top descendente), izquierda a derecha (left ascendente)
    
    Args:
        bounds: (minx, miny, maxx, maxy)
        
    Returns:
        tuple: (-top, left) para ordenamiento
    """
    minx, miny, maxx, maxy = bounds
    top = maxy  # Coordenada norte máxima
    left = minx  # Coordenada oeste mínima
    
    # Negativo en top para orden descendente (arriba primero)
    return (-top, left)


def reorder_by_sweep_line(features, prefix):
    """
    Reordena features por sweep line y asigna nuevos códigos.
    
    Args:
        features: Lista de features GeoJSON
        prefix: Prefijo para los códigos (ej: 'CL')
        
    Returns:
        list: Features reordenadas con nuevos códigos
    """
    n = len(features)
    logger.info(f"Reordenando {n} features con prefijo '{prefix}'")
    
    # Calcular posiciones de sweep line
    feature_positions = []
    
    for i, feature in enumerate(features):
        geometry = feature.get('geometry', {})
        geom_type = geometry.get('type', '')
        
        if geom_type in ['Polygon', 'MultiPolygon']:
            bounds = get_geometry_bounds(geometry)
            position = calculate_sweep_position(bounds)
            feature_positions.append((position, i, feature))
        else:
            # Geometrías no soportadas van al final
            logger.warning(f"Geometría tipo '{geom_type}' no soportada - enviando al final")
            feature_positions.append(((999999, 999999), i, feature))
    
    # Ordenar por posición de sweep line
    feature_positions.sort(key=lambda x: x[0])
    
    # Generar códigos ordenados
    new_codes = [f"{prefix}_{str(i+1).zfill(DIGITS)}" for i in range(n)]
    
    # Reasignar códigos
    reordered_features = []
    mappings = []  # Para logging
    
    for idx, (position, original_idx, feature) in enumerate(feature_positions):
        # Preservar código original
        props = feature.get('properties', {})
        old_code = props.get('codigo', f'ORIGINAL_{original_idx}')
        new_code = new_codes[idx]
        
        # Actualizar properties
        new_props = props.copy()
        new_props['old_codigo'] = str(old_code)
        new_props['codigo'] = new_code
        
        # Crear nuevo feature
        new_feature = {
            'type': 'Feature',
            'geometry': feature['geometry'],
            'properties': new_props
        }
        
        reordered_features.append(new_feature)
        mappings.append((old_code, new_code))
    
    # Log de los primeros 3 mapeos
    logger.info("Mapeos de códigos (primeros 3):")
    for i, (old, new) in enumerate(mappings[:3]):
        logger.info(f"  {old} → {new}")
    
    if len(mappings) > 3:
        logger.info(f"  ... y {len(mappings) - 3} más")
    
    logger.info(f"Códigos asignados: {new_codes[0]} a {new_codes[-1]}")
    
    return reordered_features


def main():
    """Función principal."""
    input_path = Path(INPUT_PATH)
    
    logger.info(f"GeoJSON Sweep Line Reordering Tool")
    logger.info(f"Archivo de entrada: {input_path}")
    
    # Validar archivo de entrada
    if not input_path.exists():
        logger.error(f"Archivo no encontrado: {input_path}")
        return 1
    
    # Cargar GeoJSON
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
    except Exception as e:
        logger.error(f"Error cargando GeoJSON: {e}")
        return 1
    
    # Validar estructura
    if geojson_data.get('type') != 'FeatureCollection':
        logger.error("El archivo debe ser un FeatureCollection")
        return 1
    
    features = geojson_data.get('features', [])
    if not features:
        logger.error("No se encontraron features en el GeoJSON")
        return 1
    
    logger.info(f"Cargadas {len(features)} features")
    
    # Auto-inferir prefijo
    prefix = auto_infer_prefix(features, input_path)
    
    # Reordenar por sweep line
    reordered_features = reorder_by_sweep_line(features, prefix)
    
    # Crear GeoJSON de salida
    output_geojson = {
        'type': 'FeatureCollection',
        'features': reordered_features
    }
    
    # Generar ruta de salida
    output_path = input_path.parent / f"{input_path.stem}_order.geojson"
    
    # Guardar archivo
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_geojson, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Archivo guardado: {output_path}")
        logger.info(f"✅ Procesamiento completado exitosamente!")
        
        return 0
        
    except Exception as e:
        logger.error(f"Error guardando archivo: {e}")
        return 1


if __name__ == '__main__':
    exit(main())