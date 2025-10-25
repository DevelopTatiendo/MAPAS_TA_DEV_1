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
        'personas_por_hogar': 2.5,      # vigente
        'densidad_hab_km2': 4382.05,     # Densidad aproximada Cali (DANE 2018: ~2.4M hab, ~570 km²)
        # 'hogares_por_m2': None        # opcional: si lo pones, tiene prioridad
        # Fuente: Proyecciones DANE - ajustar con datos oficiales más recientes según sea necesario
    },
    'MEDELLIN': {
        'personas_por_hogar': 2.5,      # valor inicial (lo calibraremos)
        'densidad_hab_km2': None,       # si no hay, usamos solo pph o override
        # 'hogares_por_m2': None
    },
    'MANIZALES': {
        'personas_por_hogar': 2.0,      # solicitado por negocio
        'densidad_hab_km2': 958.0,      # dato 2024
        # 'hogares_por_m2': None
        # Fuente: Insumo de negocio 2024
    },
    'PEREIRA': {
        'personas_por_hogar': 2.5,      # valor inicial (pendiente calibración)
        'densidad_hab_km2': None,       
        # 'hogares_por_m2': None
    },
    'BOGOTA': {
        'personas_por_hogar': 2.5,      # valor inicial (pendiente calibración)
        'densidad_hab_km2': None,       
        # 'hogares_por_m2': None
    },
    'BARRANQUILLA': {
        'personas_por_hogar': 2.5,      # valor inicial (pendiente calibración)
        'densidad_hab_km2': None,       
        # 'hogares_por_m2': None
    },
    'BUCARAMANGA': {
        'personas_por_hogar': 2.5,      # valor inicial (pendiente calibración)
        'densidad_hab_km2': None,       
        # 'hogares_por_m2': None
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


def resolve_hogares_por_m2(city_key, pph_override=None, hogares_por_m2_override=None):
    """
    Resuelve la densidad de hogares por m² con jerarquía de prioridad.
    
    Prioridad:
    1) hogares_por_m2_override (runtime)
    2) CITY_PARAMS[city]['hogares_por_m2'] (config)
    3) (densidad_hab_km2 / personas_por_hogar) / 1_000_000  (si ambos existen)
    4) (densidad_hab_km2 / pph_override) / 1_000_000        (si densidad y override pph)
    -> Si nada aplica: raise ValueError con mensaje claro de ciudad faltante.
    
    Args:
        city_key (str): Clave de ciudad normalizada (usar get_city_key())
        pph_override (float, optional): Override de personas por hogar
        hogares_por_m2_override (float, optional): Override directo de hogares por m²
        
    Returns:
        float: Densidad de hogares por metro cuadrado
        
    Raises:
        ValueError: Si no se puede resolver hogares_por_m2 con parámetros disponibles
    """
    # 1) Override directo tiene máxima prioridad
    if hogares_por_m2_override is not None:
        if hogares_por_m2_override <= 0:
            raise ValueError(f"hogares_por_m2_override debe ser mayor a 0, recibido: {hogares_por_m2_override}")
        return float(hogares_por_m2_override)
    
    # Obtener parámetros de la ciudad
    params = get_params(city_key)
    
    # 2) Valor directo en configuración
    config_hogares_por_m2 = params.get('hogares_por_m2')
    if config_hogares_por_m2 is not None:
        if config_hogares_por_m2 <= 0:
            raise ValueError(f"hogares_por_m2 en config debe ser mayor a 0 para {city_key}")
        return float(config_hogares_por_m2)
    
    # 3 y 4) Calcular desde densidad y pph (config o override)
    densidad_hab_km2 = params.get('densidad_hab_km2')
    personas_por_hogar = pph_override if pph_override is not None else params.get('personas_por_hogar')
    
    if densidad_hab_km2 is not None and personas_por_hogar is not None:
        if densidad_hab_km2 <= 0:
            raise ValueError(f"densidad_hab_km2 debe ser mayor a 0 para {city_key}")
        if personas_por_hogar <= 0:
            raise ValueError(f"personas_por_hogar debe ser mayor a 0 para {city_key}")
        
        # Calcular densidad de hogares por m²
        hogares_por_km2 = densidad_hab_km2 / personas_por_hogar
        hogares_por_m2 = hogares_por_km2 / 1_000_000
        return float(hogares_por_m2)
    
    # Si llegamos aquí, no hay suficientes datos
    available_cities = ", ".join(CITY_PARAMS.keys())
    missing_params = []
    if densidad_hab_km2 is None:
        missing_params.append("densidad_hab_km2")
    if personas_por_hogar is None:
        missing_params.append("personas_por_hogar")
    
    raise ValueError(f"No se puede calcular hogares_por_m2 para {city_key}. "
                    f"Faltantes: {', '.join(missing_params)}. "
                    f"Defina parámetros en config o use overrides. "
                    f"Ciudades disponibles: {available_cities}")


def compute_hogares_por_m2(city_key):
    """
    Calcula la densidad de hogares por m² para una ciudad (compatibilidad).
    
    Esta función mantiene compatibilidad con código existente.
    Internamente delega a resolve_hogares_por_m2 sin overrides.
    
    Args:
        city_key (str): Clave de ciudad normalizada (usar get_city_key())
        
    Returns:
        float: Densidad de hogares por metro cuadrado
        
    Raises:
        ValueError: Si no se puede resolver hogares_por_m2 para la ciudad
    """
    return resolve_hogares_por_m2(city_key)