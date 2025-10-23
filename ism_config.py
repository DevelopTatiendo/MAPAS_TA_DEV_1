"""
ISM (Índice de Saturación del Mercado) - Configuración global por ciudad

Este módulo centraliza los parámetros demográficos necesarios para calcular
métricas de saturación de mercado por ciudad.

Uso:
    from ism_config import get_city_key, compute_hogares_por_m2
    
    city_key = get_city_key("Cali")
    hogares_por_m2 = compute_hogares_por_m2(city_key)
"""

# === PARÁMETROS DEMOGRÁFICOS POR CIUDAD ===
CITY_PARAMS = {
    'CALI': {
        'personas_por_hogar': 2.5,  # valor vigente
        'densidad_hab_km2': 4200.0  # Densidad aproximada Cali (DANE 2018: ~2.4M hab, ~570 km²)
        # Fuente: Proyecciones DANE - ajustar con datos oficiales más recientes según sea necesario
    }
}


def get_city_key(ciudad_str):
    """
    Normaliza el nombre de ciudad a clave válida y valida su presencia.
    
    Args:
        ciudad_str (str): Nombre de la ciudad (ej: "Cali", "cali", "CALI")
        
    Returns:
        str: Clave normalizada en mayúsculas (ej: "CALI")
        
    Raises:
        ValueError: Si la ciudad no está configurada en CITY_PARAMS
    """
    if not ciudad_str:
        raise ValueError("El nombre de ciudad no puede estar vacío")
    
    # Normalizar a mayúsculas
    city_key = str(ciudad_str).strip().upper()
    
    # Validar presencia en configuración
    if city_key not in CITY_PARAMS:
        available_cities = ", ".join(CITY_PARAMS.keys())
        raise ValueError(f"Ciudad '{ciudad_str}' no configurada. Ciudades disponibles: {available_cities}")
    
    return city_key


def get_params(city_key):
    """
    Obtiene los parámetros demográficos de una ciudad.
    
    Args:
        city_key (str): Clave de ciudad normalizada (usar get_city_key())
        
    Returns:
        dict: Diccionario con llaves 'personas_por_hogar' y 'densidad_hab_km2'
        
    Raises:
        ValueError: Si la clave de ciudad no existe
    """
    if city_key not in CITY_PARAMS:
        available_cities = ", ".join(CITY_PARAMS.keys())
        raise ValueError(f"Clave de ciudad '{city_key}' no válida. Ciudades disponibles: {available_cities}")
    
    return CITY_PARAMS[city_key].copy()


def compute_hogares_por_m2(city_key):
    """
    Calcula la densidad de hogares por m² para una ciudad.
    
    Fórmula: hogares_por_m2 = (densidad_hab_km2 / personas_por_hogar) / 1_000_000
    
    Args:
        city_key (str): Clave de ciudad normalizada (usar get_city_key())
        
    Returns:
        float: Densidad de hogares por metro cuadrado
        
    Raises:
        ValueError: Si densidad_hab_km2 no está definida para la ciudad
        ValueError: Si la clave de ciudad no existe
    """
    params = get_params(city_key)
    
    densidad_hab_km2 = params['densidad_hab_km2']
    personas_por_hogar = params['personas_por_hogar']
    
    # Validar que la densidad esté definida
    if densidad_hab_km2 is None:
        raise ValueError(f"Defina densidad_hab_km2 para {city_key} en ism_config.CITY_PARAMS antes de calcular C/ISM.")
    
    # Validar valores positivos
    if densidad_hab_km2 <= 0:
        raise ValueError(f"densidad_hab_km2 debe ser mayor a 0 para {city_key}")
    
    if personas_por_hogar <= 0:
        raise ValueError(f"personas_por_hogar debe ser mayor a 0 para {city_key}")
    
    # Calcular densidad de hogares por m²
    hogares_por_km2 = densidad_hab_km2 / personas_por_hogar
    hogares_por_m2 = hogares_por_km2 / 1_000_000
    
    return hogares_por_m2