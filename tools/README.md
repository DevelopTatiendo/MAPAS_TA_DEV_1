# GeoJSON Standardizer Tool

This tool standardizes GeoJSON files for the MAPAS_TA_DEV_1 project by normalizing quadrant codes with proper city prefixes and calculating geodesic metrics.

## Features

- **Code Normalization**: Converts all quadrant codes to use proper city prefixes (CL, MZ, BG, MD, PR, BC, BR)
- **PADRE Level Setting**: Forces all features to PADRE level (no hierarchy)
- **Geodesic Calculations**: Accurate area and perimeter calculations using WGS84 ellipsoid
- **Comprehensive Metrics**: Calculates centroid, compactness, elongation ratio, and hole counts
- **CSV Export**: Exports detailed metrics for analysis

## Installation

Install required dependencies:

```bash
pip install geopandas shapely pyproj pandas
```

Optional (for progress bars):
```bash
pip install tqdm
```

## Usage

### Basic Usage

```bash
python tools/geojson_standardizer.py \
  --input data/manizales_base.geojson \
  --output data_out/manizales_base_fixed.geojson \
  --city "MANIZALES" \
  --csv-out data_out/manizales_metricas.csv
```

### All Options

```bash
python tools/geojson_standardizer.py \
  --input /path/to/input.geojson \
  --output /path/to/output.geojson \
  --city "PEREIRA" \
  --csv-out /path/to/metrics.csv \
  --force-reindex \
  --verbose
```

## City Prefixes

The tool supports these official city prefixes:

| City | Prefix |
|------|--------|
| CALI | CL |
| MANIZALES | MZ |
| BOGOTA | BG |
| MEDELLIN | MD |
| PEREIRA | PR |
| BUCARAMANGA | BC |
| BARRANQUILLA | BR |

## Output Files

### Standardized GeoJSON
- All codes normalized to `PREFIX_001`, `PREFIX_002`, etc.
- All features set to PADRE level
- Properties include: `codigo`, `ciudad`, `nivel`, `es_hijo`, `codigo_padre`

### Metrics CSV
Contains these columns:
- `cod_cuadrante`: Standardized quadrant code
- `ciudad`: City name
- `area_m2`: Geodesic area in square meters
- `perimetro_m`: Geodesic perimeter in meters
- `centroid_lon`: Centroid longitude (WGS84)
- `centroid_lat`: Centroid latitude (WGS84)
- `compactness_polsby`: Polsby-Popper compactness ratio (0-1)
- `elongation_ratio`: Length/width ratio of bounding box
- `holes_count`: Number of interior holes

## Examples

### Process Manizales Data
```bash
python tools/geojson_standardizer.py \
  --input geojson/manizales_base.geojson \
  --output data_out/manizales_base_fixed.geojson \
  --city "MANIZALES" \
  --csv-out data_out/manizales_metricas.csv
```

This will:
- Convert codes like `CL_XX` to `MZ_001`, `MZ_002`, etc.
- Set all features as PADRE level
- Calculate geodesic metrics
- Export standardized GeoJSON and metrics CSV

### Process Pereira Data
```bash
python tools/geojson_standardizer.py \
  --input geojson/pap/pereira_base.geojson \
  --output data_out/pereira_base_fixed.geojson \
  --city "PEREIRA" \
  --csv-out data_out/pereira_metricas.csv
```

## Validation

After processing, you can validate the results by:

1. **Check code format**: All codes should follow `PREFIX_###` pattern
2. **Verify PADRE level**: All features should have `nivel: "PADRE"`
3. **Review metrics**: Areas and perimeters should be reasonable for your region
4. **Compare counts**: Input and output feature counts should match

## Error Handling

The tool includes comprehensive error handling for:
- Invalid GeoJSON format
- Missing geometry data
- Coordinate system issues
- File I/O problems

Check the console output for detailed error messages and warnings.