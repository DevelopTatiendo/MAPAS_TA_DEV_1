#!/usr/bin/env python3
"""
Test del pipeline voronoi_v2.py con datos sintéticos
Demuestra la funcionalidad completa sin conexión a BD
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon
from datetime import datetime, timedelta
from pathlib import Path
import json

# Importar el módulo principal
from voronoi_v2 import (
    log_info, crear_directorio_pruebas, detectar_y_normalizar_codigo,
    filtrar_cuadrantes_ruta, recortar_eventos_por_cuadrantes,
    asignar_cuadrantes_a_eventos, clusterizar_por_cuadrante_dbscan,
    calcular_metricas_clusters, score_clusters, seleccionar_seeds_greedy,
    mapa_clusters_y_seeds, generar_reporte_auditoria,
    CUADRANTES_PATH, RUTA_NOMBRE, PROJ_CRS, D_MIN_M, R_M,
    KNN_K, EPS_FACTORS, MIN_SAMPLES_RULE, MIN_CLUSTER_SIZE_ABS, 
    MAX_SAMPLES_SILHOUETTE, SCORE_WEIGHTS
)

def generar_datos_sinteticos():
    """Genera datos sintéticos para prueba del pipeline."""
    log_info("🧪", "Generando datos sintéticos para prueba")
    
    # Coordenadas base para Cali (zona ruta 3)
    base_lat, base_lon = 3.45, -76.52
    
    # Generar eventos sintéticos distribuidos en clusters
    np.random.seed(42)
    eventos = []
    
    # Simular 3 cuadrantes: CL_3_01, CL_3_02, CL_3_03
    cuadrantes_config = [
        {'codigo': 'CL_3_01', 'center': (3.45, -76.52), 'n_clusters': 3, 'pts_per_cluster': 25},
        {'codigo': 'CL_3_02', 'center': (3.46, -76.51), 'n_clusters': 2, 'pts_per_cluster': 30},
        {'codigo': 'CL_3_03', 'center': (3.44, -76.53), 'n_clusters': 4, 'pts_per_cluster': 20}
    ]
    
    evento_id = 1
    consultor_id = 100
    
    for config in cuadrantes_config:
        center_lat, center_lon = config['center']
        
        for cluster_i in range(config['n_clusters']):
            # Centro del cluster (desplazado del centro del cuadrante)
            cluster_lat = center_lat + np.random.normal(0, 0.005)
            cluster_lon = center_lon + np.random.normal(0, 0.005)
            
            # Generar puntos alrededor del centro del cluster
            for pt_i in range(config['pts_per_cluster']):
                lat = cluster_lat + np.random.normal(0, 0.002)
                lon = cluster_lon + np.random.normal(0, 0.002)
                
                # Fecha aleatoria en el rango
                fecha_base = datetime(2024, 8, 1)
                dias_random = np.random.randint(0, 365)
                fecha_evento = fecha_base + timedelta(days=dias_random)
                
                eventos.append({
                    'id_evento': evento_id,
                    'id_contacto': evento_id,
                    'id_consultor': consultor_id + (cluster_i % 3),
                    'apellido': f'Consultor_{consultor_id + (cluster_i % 3)}',
                    'lat': lat,
                    'lon': lon,
                    'fecha_evento': fecha_evento,
                    'id_evento_tipo': 181,
                    'es_visita': 1,
                    'es_apertura': np.random.choice([0, 1], p=[0.7, 0.3]),
                    'es_venta_evento': np.random.choice([0, 1], p=[0.8, 0.2])
                })
                
                evento_id += 1
    
    df_eventos = pd.DataFrame(eventos)
    log_info("📊", f"Datos sintéticos generados: {len(df_eventos)} eventos")
    
    return df_eventos

def crear_cuadrantes_sinteticos():
    """Crea archivo GeoJSON sintético de cuadrantes para prueba."""
    log_info("🧪", "Creando cuadrantes sintéticos")
    
    # Definir cuadrantes como polígonos
    cuadrantes = []
    
    configs = [
        {'codigo': 'CL_3_01', 'bounds': (3.44, -76.53, 3.46, -76.51)},
        {'codigo': 'CL_3_02', 'bounds': (3.45, -76.52, 3.47, -76.50)},
        {'codigo': 'CL_3_03', 'bounds': (3.43, -76.54, 3.45, -76.52)}
    ]
    
    for config in configs:
        min_lat, min_lon, max_lat, max_lon = config['bounds']
        
        # Crear polígono rectangular
        polygon = Polygon([
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat)
        ])
        
        cuadrantes.append({
            'codigo': config['codigo'],
            'geometry': polygon
        })
    
    gdf = gpd.GeoDataFrame(cuadrantes, crs='EPSG:4326')
    
    # Guardar como GeoJSON temporal
    temp_path = "../pruebas/cuadrantes_test.geojson"
    gdf.to_file(temp_path, driver='GeoJSON')
    
    log_info("📊", f"Cuadrantes sintéticos creados: {temp_path}")
    return temp_path

def test_pipeline_completo():
    """Prueba el pipeline completo con datos sintéticos."""
    log_info("🚀", "=== TEST PIPELINE VORONOI V2 ===")
    
    try:
        # Crear directorio de pruebas
        crear_directorio_pruebas()
        
        # 1. Generar datos sintéticos
        log_info("1️⃣", "GENERACIÓN DE DATOS SINTÉTICOS")
        df_eventos = generar_datos_sinteticos()
        cuadrantes_path = crear_cuadrantes_sinteticos()
        
        # 2. Cargar y filtrar cuadrantes
        log_info("2️⃣", "PROCESAMIENTO GEOESPACIAL")
        gdf_cuad = detectar_y_normalizar_codigo(cuadrantes_path)
        gdf_cuad_ruta = filtrar_cuadrantes_ruta(gdf_cuad, RUTA_NOMBRE)
        
        # 3. Recortar eventos
        df_filtrado, gdf_cuad_ruta = recortar_eventos_por_cuadrantes(df_eventos, gdf_cuad_ruta)
        
        # 4. Asignar códigos
        df_etq = asignar_cuadrantes_a_eventos(df_filtrado, gdf_cuad_ruta)
        
        # 5. Clustering
        log_info("3️⃣", "CLUSTERING DBSCAN")
        df_lab, resumen_clusters = clusterizar_por_cuadrante_dbscan(
            df_etq, PROJ_CRS, KNN_K, EPS_FACTORS, MIN_SAMPLES_RULE, 
            MIN_CLUSTER_SIZE_ABS, MAX_SAMPLES_SILHOUETTE
        )
        
        # 6. Métricas
        log_info("4️⃣", "CÁLCULO DE MÉTRICAS")
        df_metricas = calcular_metricas_clusters(df_lab, gdf_cuad_ruta, PROJ_CRS)
        
        # 7. Scores
        log_info("5️⃣", "CÁLCULO DE SCORES")
        df_scores = score_clusters(df_metricas, SCORE_WEIGHTS, 0.0, por_cuadrante=True)
        
        # 8. Selección de seeds
        log_info("6️⃣", "SELECCIÓN DE SEEDS")
        df_seeds, log_seleccion = seleccionar_seeds_greedy(df_scores, 0.0, D_MIN_M)
        
        # 9. Mapa
        log_info("7️⃣", "GENERACIÓN DE MAPA")
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_filename = f"test_voronoi_seeds_{timestamp}.html"
        html_path = Path("../pruebas") / html_filename
        
        filename = mapa_clusters_y_seeds(df_etq, gdf_cuad, gdf_cuad_ruta, df_seeds, str(html_path))
        
        # 9. Auditoría
        log_info("7️⃣", "AUDITORÍA")
        reporte = generar_reporte_auditoria(df_seeds, df_etq, R_M)
        
        # Resultados
        log_info("✅", "=== TEST COMPLETADO ===")
        log_info("📊", f"Eventos procesados: {len(df_etq)}")
        log_info("📊", f"Clusters: {len(df_metricas)}")
        log_info("📊", f"Seeds: {len(df_seeds)}")
        
        if filename:
            log_info("📊", f"Mapa: {filename}")
        
        if reporte:
            log_info("📊", f"Cobertura: {reporte.get('coverage_pct', 0):.1f}%")
        
        # Mostrar muestra de resultados
        if not df_seeds.empty:
            log_info("📋", "Muestra de seeds seleccionados:")
            columns_to_show = ['codigo', 'cluster_id', 'n', 'seed_lat', 'seed_lon']
            if 'score_total' in df_seeds.columns:
                columns_to_show.append('score_total')
            if 'margen' in df_seeds.columns:
                columns_to_show.append('margen')
            print(df_seeds[columns_to_show].head())
        
        return True
        
    except Exception as e:
        log_info("❌", f"Error en test: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_pipeline_completo()
    print(f"\n{'✅ TEST EXITOSO' if success else '❌ TEST FALLIDO'}")
