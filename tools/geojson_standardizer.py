#!/usr/bin/env python3
"""
GeoJSON Standardizer and Metrics Calculator

This script normalizes GeoJSON files by:
1. Standardizing quadrant codes with proper city prefixes
2. Setting all features as PADRE level (no hierarchy)
3. Calculating geodesic geometry metrics
4. Exporting a CSV summary with metrics

Usage:
    python tools/geojson_standardizer.py \
        --input /path/to/input.geojson \
        --output /path/to/output.geojson \
        --city "PEREIRA" \
        --csv-out /path/to/metrics.csv \
        [--force-reindex]

City prefixes:
    CALI → CL
    MANIZALES → MZ
    BOGOTA → BG
    MEDELLIN → MD
    PEREIRA → PR
    BUCARAMANGA → BC
    BARRANQUILLA → BR
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

# Third-party imports (will be checked for availability)
try:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import shape, Point, Polygon
    from shapely.ops import transform
    import pyproj
    from pyproj import Geod
    HAS_GEOSPATIAL_LIBS = True
except ImportError as e:
    HAS_GEOSPATIAL_LIBS = False
    MISSING_LIBS = str(e)

# Optional progress bar
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Official city prefix dictionary
CITY_PREFIX = {
    'CALI': 'CL',
    'MANIZALES': 'MZ',
    'BOGOTA': 'BG',
    'MEDELLIN': 'MD',
    'PEREIRA': 'PR',
    'BUCARAMANGA': 'BC',
    'BARRANQUILLA': 'BR'
}

# WGS84 ellipsoid for geodesic calculations
WGS84_GEOD = Geod(ellps='WGS84')


def check_dependencies():
    """Check if required dependencies are available."""
    if not HAS_GEOSPATIAL_LIBS:
        logger.error(f"Missing required geospatial libraries: {MISSING_LIBS}")
        logger.error("Please install: pip install geopandas shapely pyproj pandas")
        return False
    return True


def get_city_prefix(city: str) -> str:
    """Get the official prefix for a city."""
    city_upper = city.upper().strip()
    if city_upper not in CITY_PREFIX:
        logger.warning(f"Unknown city '{city}', using first 2 letters as prefix")
        return city_upper[:2]
    return CITY_PREFIX[city_upper]


def load_geojson(file_path: Path) -> dict:
    """Load GeoJSON file and validate format."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
            raise ValueError("Invalid GeoJSON: must be a FeatureCollection")
        
        features = data.get('features', [])
        if not features:
            logger.warning("GeoJSON contains no features")
        
        logger.info(f"Loaded GeoJSON with {len(features)} features")
        return data
    
    except Exception as e:
        logger.error(f"Error loading GeoJSON from {file_path}: {e}")
        raise


def normalize_code(
    feature: dict, 
    city_prefix: str, 
    index: int, 
    force_reindex: bool = True
) -> Tuple[str, str]:
    """
    Normalize feature code to proper city prefix format.
    
    Returns:
        tuple: (old_code, new_code)
    """
    props = feature.get('properties', {})
    
    # Try to get existing code from various properties
    old_code = props.get('codigo') or props.get('id') or props.get('name') or f'UNKNOWN_{index}'
    
    # Generate new code with 3-digit padding
    new_code = f"{city_prefix}_{str(index + 1).zfill(3)}"
    
    return str(old_code), new_code


def calculate_geodesic_metrics(geometry: dict) -> dict:
    """
    Calculate geodesic metrics for a geometry.
    
    Returns:
        dict: geometry metrics
    """
    try:
        # Convert to Shapely geometry
        geom = shape(geometry)
        
        if geom.geom_type not in ['Polygon', 'MultiPolygon']:
            logger.warning(f"Unsupported geometry type: {geom.geom_type}")
            return create_empty_metrics()
        
        # Calculate geodesic area and perimeter
        area_m2 = abs(WGS84_GEOD.geometry_area_perimeter(geom)[0])
        perimeter_m = WGS84_GEOD.geometry_area_perimeter(geom)[1]
        
        # Calculate centroid
        centroid = geom.centroid
        centroid_lon, centroid_lat = centroid.x, centroid.y
        
        # Calculate compactness (Polsby-Popper)
        # Compactness = 4π * Area / Perimeter²
        compactness_polsby = (4 * 3.14159 * area_m2) / (perimeter_m ** 2) if perimeter_m > 0 else 0
        compactness_polsby = min(1.0, compactness_polsby)  # Cap at 1.0
        
        # Calculate elongation ratio (simplified as length/width of bounding box)
        bounds = geom.bounds  # (minx, miny, maxx, maxy)
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        elongation_ratio = max(width, height) / min(width, height) if min(width, height) > 0 else 1.0
        
        # Count holes (interior rings)
        holes_count = 0
        if geom.geom_type == 'Polygon':
            holes_count = len(geom.interiors)
        elif geom.geom_type == 'MultiPolygon':
            holes_count = sum(len(poly.interiors) for poly in geom.geoms)
        
        return {
            'area_m2': round(area_m2, 2),
            'perimetro_m': round(perimeter_m, 2),
            'centroid_lon': round(centroid_lon, 6),
            'centroid_lat': round(centroid_lat, 6),
            'compactness_polsby': round(compactness_polsby, 4),
            'elongation_ratio': round(elongation_ratio, 2),
            'holes_count': holes_count
        }
    
    except Exception as e:
        logger.warning(f"Error calculating metrics for geometry: {e}")
        return create_empty_metrics()


def create_empty_metrics() -> dict:
    """Create empty metrics dict for error cases."""
    return {
        'area_m2': 0.0,
        'perimetro_m': 0.0,
        'centroid_lon': 0.0,
        'centroid_lat': 0.0,
        'compactness_polsby': 0.0,
        'elongation_ratio': 1.0,
        'holes_count': 0
    }


def standardize_geojson(
    geojson_data: dict,
    city: str,
    force_reindex: bool = True
) -> Tuple[dict, List[dict], Dict[str, str]]:
    """
    Standardize GeoJSON features with proper city codes and PADRE level.
    
    Returns:
        tuple: (standardized_geojson, metrics_list, code_mapping)
    """
    city_prefix = get_city_prefix(city)
    city_upper = city.upper().strip()
    
    features = geojson_data.get('features', [])
    standardized_features = []
    metrics_list = []
    code_mapping = {}
    
    logger.info(f"Standardizing {len(features)} features for city {city_upper} with prefix {city_prefix}")
    
    # Use tqdm if available
    iterator = tqdm(enumerate(features), total=len(features), desc="Processing features") if HAS_TQDM else enumerate(features)
    
    for index, feature in iterator:
        # Normalize the code
        old_code, new_code = normalize_code(feature, city_prefix, index, force_reindex)
        code_mapping[old_code] = new_code
        
        # Calculate geometric metrics
        geometry = feature.get('geometry', {})
        metrics = calculate_geodesic_metrics(geometry)
        
        # Update feature properties
        properties = feature.get('properties', {})
        properties.update({
            'codigo': new_code,
            'ciudad': city_upper,
            'nivel': 'PADRE',
            'es_hijo': False,
            'codigo_padre': None
        })
        
        # Create standardized feature
        standardized_feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': properties
        }
        
        standardized_features.append(standardized_feature)
        
        # Add to metrics list
        metrics_row = {
            'cod_cuadrante': new_code,
            'ciudad': city_upper,
            **metrics
        }
        metrics_list.append(metrics_row)
    
    # Create standardized GeoJSON
    standardized_geojson = {
        'type': 'FeatureCollection',
        'features': standardized_features
    }
    
    return standardized_geojson, metrics_list, code_mapping


def save_geojson(geojson_data: dict, output_path: Path):
    """Save GeoJSON data to file."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(geojson_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved standardized GeoJSON to {output_path}")
    except Exception as e:
        logger.error(f"Error saving GeoJSON to {output_path}: {e}")
        raise


def save_csv(metrics_list: List[dict], csv_path: Path):
    """Save metrics to CSV file."""
    try:
        df = pd.DataFrame(metrics_list)
        
        # Sort by cod_cuadrante
        df = df.sort_values('cod_cuadrante')
        
        # Define column order
        columns = [
            'cod_cuadrante', 'ciudad', 'area_m2', 'perimetro_m',
            'centroid_lon', 'centroid_lat', 'compactness_polsby',
            'elongation_ratio', 'holes_count'
        ]
        
        # Reorder columns (keep any extra columns at the end)
        available_columns = [col for col in columns if col in df.columns]
        extra_columns = [col for col in df.columns if col not in columns]
        final_columns = available_columns + extra_columns
        
        df = df[final_columns]
        
        df.to_csv(csv_path, index=False, encoding='utf-8')
        logger.info(f"Saved metrics CSV to {csv_path}")
        logger.info(f"CSV contains {len(df)} rows and {len(df.columns)} columns")
        
    except Exception as e:
        logger.error(f"Error saving CSV to {csv_path}: {e}")
        raise


def print_summary(
    city: str,
    city_prefix: str,
    code_mapping: Dict[str, str],
    metrics_list: List[dict]
):
    """Print processing summary with statistics."""
    logger.info("=" * 60)
    logger.info("PROCESSING SUMMARY")
    logger.info("=" * 60)
    logger.info(f"City: {city}")
    logger.info(f"Prefix used: {city_prefix}")
    logger.info(f"Total features processed: {len(code_mapping)}")
    
    # Show sample mappings (first 5)
    logger.info("\nCode mappings (first 5):")
    for i, (old_code, new_code) in enumerate(list(code_mapping.items())[:5]):
        logger.info(f"  {old_code} → {new_code}")
    
    if len(code_mapping) > 5:
        logger.info(f"  ... and {len(code_mapping) - 5} more")
    
    # Calculate statistics
    if metrics_list:
        areas = [m['area_m2'] for m in metrics_list]
        perimeters = [m['perimetro_m'] for m in metrics_list]
        
        # Calculate percentiles
        areas_sorted = sorted(areas)
        perimeters_sorted = sorted(perimeters)
        
        n = len(areas_sorted)
        median_idx = n // 2
        p95_idx = int(n * 0.95)
        
        area_stats = {
            'min': min(areas),
            'median': areas_sorted[median_idx],
            'p95': areas_sorted[p95_idx] if p95_idx < n else areas_sorted[-1]
        }
        
        perimeter_stats = {
            'min': min(perimeters),
            'median': perimeters_sorted[median_idx],
            'p95': perimeters_sorted[p95_idx] if p95_idx < n else perimeters_sorted[-1]
        }
        
        logger.info(f"\nArea statistics (m²):")
        logger.info(f"  Min: {area_stats['min']:,.2f}")
        logger.info(f"  Median: {area_stats['median']:,.2f}")
        logger.info(f"  95th percentile: {area_stats['p95']:,.2f}")
        
        logger.info(f"\nPerimeter statistics (m):")
        logger.info(f"  Min: {perimeter_stats['min']:,.2f}")
        logger.info(f"  Median: {perimeter_stats['median']:,.2f}")
        logger.info(f"  95th percentile: {perimeter_stats['p95']:,.2f}")
    
    logger.info("=" * 60)


def main():
    """Main function to handle CLI arguments and execute processing."""
    parser = argparse.ArgumentParser(
        description='Standardize GeoJSON codes and calculate geodesic metrics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--input', 
        type=Path, 
        required=True,
        help='Path to input GeoJSON file'
    )
    
    parser.add_argument(
        '--output', 
        type=Path, 
        required=True,
        help='Path to output standardized GeoJSON file'
    )
    
    parser.add_argument(
        '--city', 
        type=str, 
        required=True,
        choices=list(CITY_PREFIX.keys()),
        help='City name (must match exactly)'
    )
    
    parser.add_argument(
        '--csv-out', 
        type=Path, 
        required=True,
        help='Path to output CSV metrics file'
    )
    
    parser.add_argument(
        '--force-reindex',
        action='store_true',
        default=True,
        help='Force sequential reindexing of all codes (default: True)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Check dependencies
        if not check_dependencies():
            sys.exit(1)
        
        # Validate input file
        if not args.input.exists():
            logger.error(f"Input file does not exist: {args.input}")
            sys.exit(1)
        
        # Create output directories if needed
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        
        # Load input GeoJSON
        logger.info(f"Loading GeoJSON from {args.input}")
        geojson_data = load_geojson(args.input)
        
        # Standardize the GeoJSON
        logger.info("Starting standardization process...")
        standardized_geojson, metrics_list, code_mapping = standardize_geojson(
            geojson_data, 
            args.city, 
            args.force_reindex
        )
        
        # Save outputs
        logger.info("Saving outputs...")
        save_geojson(standardized_geojson, args.output)
        save_csv(metrics_list, args.csv_out)
        
        # Print summary
        city_prefix = get_city_prefix(args.city)
        print_summary(args.city, city_prefix, code_mapping, metrics_list)
        
        logger.info("✅ Processing completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Processing failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()