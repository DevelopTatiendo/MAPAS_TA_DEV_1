"""
FASE 2 - Definiciones métricas formales por cuadrante
=====================================================

Este módulo documenta las reglas exactas para el cálculo de métricas ISM 
(Índice de Saturación del Mercado) por cuadrante que se implementarán en Fase 3.

REGLAS IMPLEMENTADAS:
- Duplicados se conservan (no deduplicar)
- Días/λ se computan por cuadrante, no global
- Fórmulas exactas especificadas a continuación

DEPENDENCIAS:
- ism_config.py: compute_hogares_por_m2(ciudad)
- utils.spatial_ops: assign_quadrant_to_points, area_m2_geodesic
"""

# === MÉTRICAS BÁSICAS POR CUADRANTE ===

def calcular_metricas_cuadrante_formal(df_eventos, cuadrante_codigo, area_m2, ciudad):
    """
    Fórmulas formales para métricas por cuadrante.
    
    ENTRADA:
        df_eventos: DataFrame normalizado con eventos del cuadrante
        cuadrante_codigo: str, código del cuadrante  
        area_m2: float, área geodésica del polígono en m²
        ciudad: str, para obtener densidad demográfica
        
    MÉTRICAS CALCULADAS:
    
    1. EVENTOS:
       M(q) = número de eventos dentro del polígono del cuadrante q
       
    2. PROMOTORES:
       P(q) = conjunto de promotores únicos en q
       N_promotores(q) = |P(q)|
       
    3. DÍAS OPERACIÓN:
       D_operacion(q) = días distintos con ≥1 evento en q
       
    4. POR PROMOTOR p ∈ P(q):
       M_p(q) = eventos de p en q
       D_p(q) = días distintos de p en q  
       λ_p(q) = M_p(q) / D_p(q) si D_p(q) > 0
       
    5. TASA DEL CUADRANTE:
       λ_q = mean(λ_p(q)) para todos los p con D_p(q) > 0
       Si ningún promotor tiene D_p(q) > 0 → λ_q = 0
       
    6. HOGARES ESTIMADOS:
       hogares_por_m2 = compute_hogares_por_m2(ciudad)  # de ism_config.py
       H_est(q) = Área_m2(q) × hogares_por_m2
       
    7. COBERTURA (C):
       C_raw = 0 si H_est == 0, sino C_raw = M / H_est  
       C = min(1, C_raw)  # limitada a 1.0
       over_flag = (C_raw > 1)  # indicador de sobre-cobertura
       
    8. ESFUERZO (E):
       den_E = N_promotores × D_operacion × λ_q
       E_raw = 0 si den_E == 0, sino E_raw = M / den_E
       E = min(1, E_raw)  # limitada a 1.0
       
    9. ISM (Índice de Saturación del Mercado):
       Si C + E == 0 → ISM = 0
       Sino: ISM = 100 × (2 × C × E) / (C + E)  # media armónica ponderada
       
    REDONDEOS PARA UI/CSV:
       - ISM: 1 decimal
       - C, E: 2 decimales  
       - C_raw, E_raw, λ_q: 2 decimales
       - Conteos (M, N_promotores, D_operacion): enteros
    """
    pass  # Implementación en Fase 3


# === NOTAS TÉCNICAS ===

"""
CONFIGURACIÓN DEMOGRÁFICA:
- Ciudad: CALI (activa en Fase 1)
- personas_por_hogar: 2.5 (configurado en ism_config.py)  
- densidad_hab_km2: None (DEBE definirse antes de calcular ISM)

MANEJO DE ERRORES:
- Si densidad_hab_km2 es None → excepción clara, no traceback
- Mensaje: "Defina densidad_hab_km2 para CALI en ism_config.CITY_PARAMS antes de calcular C/ISM"

EXTENSIBILIDAD:
- Nuevas ciudades: agregar entrada en ism_config.CITY_PARAMS
- Mismo flujo para todas las ciudades

VALIDACIÓN:
- Área > 0: obligatorio
- Eventos válidos: lat/lon no nulos, dentro de bounds razonables
- Fechas: timezone normalizado a America/Bogota

RENDIMIENTO:
- usar utils.spatial_ops.assign_quadrant_to_points con prepared geometries
- Pre-filtro bbox antes de contains
- Evitar recálculos de área por cuadrante
"""