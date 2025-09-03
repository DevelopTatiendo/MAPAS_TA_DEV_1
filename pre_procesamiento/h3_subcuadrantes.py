import h3
import networkx as nx
import numpy as np
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union
import math
from typing import List, Tuple, Dict, Any

def build_h3_subquadrants(quadrant_polygons: List[Tuple[str, Polygon]], 
                         df_events, 
                         r: int = 10, 
                         visitas_semana: int = 150, 
                         tol_pct: float = 12) -> Tuple[Dict, Dict]:
    """
    Divide cada cuadrante en subcuadrantes H3 contiguos y balanceados.
    
    Args:
        quadrant_polygons: Lista de (codigo_cuadrante, shapely_polygon)
        df_events: DataFrame con columnas lat, lon (peso=1 por visita)
        r: Resolución H3 (default=10)
        visitas_semana: Capacidad objetivo por consultor (default=150)
        tol_pct: Tolerancia de balance en % (default=12)
    
    Returns:
        (geojson_subs, metrics_dict): FeatureCollection y métricas agregadas
    """
    features = []
    all_metrics = {}
    
    for codigo_cuadrante, polygon in quadrant_polygons:
        try:
            # 1) Polyfill cuadrante en H3
            geojson_poly = {
                "type": "Polygon",
                "coordinates": [list(polygon.exterior.coords)]
            }
            h3_cells = h3.polygon_to_cells(geojson_poly, r, geo_json_conformant=True)
            
            if not h3_cells:
                continue
                
            # 2) Asignar visitas a celdas
            cell_counts = {}
            total_visitas = 0
            
            for _, event in df_events.iterrows():
                point = Point(event['lon'], event['lat'])
                if polygon.contains(point):
                    h3_cell = h3.latlng_to_cell(event['lat'], event['lon'], r)
                    if h3_cell in h3_cells:
                        cell_counts[h3_cell] = cell_counts.get(h3_cell, 0) + 1
                        total_visitas += 1
            
            if total_visitas == 0:
                continue
                
            # 3) Calcular K (número de subcuadrantes)
            K = max(1, min(10, round(total_visitas / visitas_semana)))
            
            # 4) Construir grafo de celdas (vecindad H3)
            G = nx.Graph()
            for cell in h3_cells:
                G.add_node(cell, weight=cell_counts.get(cell, 0))
                
            # Agregar aristas entre vecinos
            for cell in h3_cells:
                neighbors = h3.grid_disk(cell, 1)
                for neighbor in neighbors:
                    if neighbor in h3_cells and neighbor != cell:
                        G.add_edge(cell, neighbor)
            
            # 5) Particionar en K grupos balanceados
            if K == 1:
                partitions = [list(h3_cells)]
            else:
                partitions = _balanced_partition(G, K, visitas_semana)
            
            # 6) Crear subcuadrantes
            ruta = codigo_cuadrante.split('_')[1] if '_' in codigo_cuadrante else 'N/A'
            
            for i, partition in enumerate(partitions):
                if not partition:
                    continue
                    
                # Disolver celdas del grupo
                cell_polygons = []
                n_visitas = 0
                
                for cell in partition:
                    try:
                        cell_boundary = h3.cell_to_boundary(cell, geo_json=True)
                        cell_poly = Polygon(cell_boundary)
                        cell_polygons.append(cell_poly)
                        n_visitas += cell_counts.get(cell, 0)
                    except:
                        continue
                
                if not cell_polygons:
                    continue
                    
                # Unir polígonos
                sub_polygon = unary_union(cell_polygons)
                if hasattr(sub_polygon, 'geoms'):
                    # Si es MultiPolygon, tomar el mayor
                    sub_polygon = max(sub_polygon.geoms, key=lambda p: p.area)
                
                # Calcular métricas
                area_m2 = _calculate_area_m2(sub_polygon)
                perimetro_m = _calculate_perimeter_m(sub_polygon)
                compacidad_Q = (4 * math.pi * area_m2) / (perimetro_m ** 2) if perimetro_m > 0 else 0
                carga_objetivo = visitas_semana
                desvio_pct = ((n_visitas - carga_objetivo) / carga_objetivo * 100) if carga_objetivo > 0 else 0
                densidad = (n_visitas / (area_m2 / 1e6)) if area_m2 > 0 else 0  # visitas/km²
                
                # Crear feature
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [list(sub_polygon.exterior.coords)]
                    },
                    "properties": {
                        "ruta": ruta,
                        "codigo_cuadrante": codigo_cuadrante,
                        "id_sub": i + 1,
                        "n_visitas": n_visitas,
                        "area_m2": round(area_m2, 2),
                        "perimetro_m": round(perimetro_m, 2),
                        "compacidad_Q": round(compacidad_Q, 4),
                        "carga_objetivo": carga_objetivo,
                        "desvio_pct": round(desvio_pct, 2),
                        "densidad": round(densidad, 2)
                    }
                }
                features.append(feature)
            
            # Calcular métricas agregadas del cuadrante
            all_metrics[codigo_cuadrante] = compute_kpis(partitions, cell_counts, visitas_semana, total_visitas)
            
        except Exception as e:
            print(f"Error procesando cuadrante {codigo_cuadrante}: {e}")
            continue
    
    geojson_subs = {
        "type": "FeatureCollection",
        "features": features
    }
    
    return geojson_subs, all_metrics

def _balanced_partition(G, K, target_weight):
    """Particiona el grafo en K grupos balanceados usando algoritmo greedy mejorado."""
    if K <= 1:
        return [list(G.nodes())]
    
    # Inicializar particiones
    partitions = [[] for _ in range(K)]
    partition_weights = [0] * K
    unassigned = set(G.nodes())
    
    # Asignar nodos de mayor peso primero
    nodes_by_weight = sorted(G.nodes(), key=lambda n: G.nodes[n]['weight'], reverse=True)
    
    for node in nodes_by_weight:
        if node not in unassigned:
            continue
            
        # Encontrar la partición con menor peso
        min_partition = min(range(K), key=lambda i: partition_weights[i])
        
        # Verificar si el nodo puede conectarse a esa partición
        can_connect = False
        if not partitions[min_partition]:  # Partición vacía
            can_connect = True
        else:
            # Verificar conectividad con algún nodo de la partición
            for existing_node in partitions[min_partition]:
                if G.has_edge(node, existing_node):
                    can_connect = True
                    break
        
        if can_connect:
            partitions[min_partition].append(node)
            partition_weights[min_partition] += G.nodes[node]['weight']
            unassigned.remove(node)
        else:
            # Buscar la partición más ligera donde pueda conectarse
            best_partition = None
            min_weight = float('inf')
            
            for i in range(K):
                if partition_weights[i] < min_weight:
                    for existing_node in partitions[i]:
                        if G.has_edge(node, existing_node):
                            best_partition = i
                            min_weight = partition_weights[i]
                            break
            
            if best_partition is not None:
                partitions[best_partition].append(node)
                partition_weights[best_partition] += G.nodes[node]['weight']
                unassigned.remove(node)
    
    # Asignar nodos restantes a la partición más ligera
    for node in list(unassigned):
        min_partition = min(range(K), key=lambda i: partition_weights[i])
        partitions[min_partition].append(node)
        partition_weights[min_partition] += G.nodes[node]['weight']
    
    return [p for p in partitions if p]  # Filtrar particiones vacías

def compute_kpis(partitions, cell_counts, cap_obj, total_visitas):
    """Calcula KPIs agregados del cuadrante."""
    if not partitions or total_visitas == 0:
        return {}
    
    weights = []
    for partition in partitions:
        weight = sum(cell_counts.get(cell, 0) for cell in partition)
        weights.append(weight)
    
    # Cobertura
    cobertura = (sum(weights) / total_visitas * 100) if total_visitas > 0 else 0
    
    # Balance
    desvios = [abs(w - cap_obj) / cap_obj * 100 if cap_obj > 0 else 0 for w in weights]
    desvio_promedio = np.mean(desvios) if desvios else 0
    desvio_maximo = max(desvios) if desvios else 0
    
    # Gini de carga
    gini = _calculate_gini(weights) if len(weights) > 1 else 0
    
    return {
        "total_visitas": total_visitas,
        "subcuadrantes": len(partitions),
        "cobertura": round(cobertura, 2),
        "desvio_promedio": round(desvio_promedio, 2),
        "desvio_maximo": round(desvio_maximo, 2),
        "gini": round(gini, 4),
        "borde_total": len(partitions) * 4  # Estimación simplificada
    }

def _calculate_area_m2(polygon):
    """Calcula área aproximada en metros cuadrados usando proyección UTM."""
    try:
        # Obtener centroide para determinar zona UTM
        centroid = polygon.centroid
        # Estimación simple: 1 grado ≈ 111 km
        lat_factor = 111000  # metros por grado de latitud
        lon_factor = 111000 * math.cos(math.radians(centroid.y))  # metros por grado de longitud
        
        # Convertir coordenadas a metros aproximados
        coords = list(polygon.exterior.coords)
        area_deg2 = polygon.area
        area_m2 = area_deg2 * lat_factor * lon_factor
        
        return area_m2
    except:
        return 0

def _calculate_perimeter_m(polygon):
    """Calcula perímetro aproximado en metros."""
    try:
        centroid = polygon.centroid
        lat_factor = 111000
        lon_factor = 111000 * math.cos(math.radians(centroid.y))
        
        perimeter_deg = polygon.length
        # Promedio de factores para aproximación
        avg_factor = (lat_factor + lon_factor) / 2
        perimeter_m = perimeter_deg * avg_factor
        
        return perimeter_m
    except:
        return 0

def _calculate_gini(weights):
    """Calcula coeficiente de Gini para medir desigualdad de carga."""
    if len(weights) <= 1:
        return 0
    
    weights = np.array(sorted(weights))
    n = len(weights)
    cumsum = np.cumsum(weights)
    
    return (n + 1 - 2 * np.sum(cumsum) / cumsum[-1]) / n if cumsum[-1] > 0 else 0
