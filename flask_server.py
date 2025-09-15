from flask import Flask, send_from_directory, abort, request
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)  # Esto permite las solicitudes cross-origin

# Ruta para servir archivos estáticos desde la carpeta static/maps
@app.route('/maps/<path:filename>')
def serve_map(filename):
    return send_from_directory('static/maps', filename)

# Ruta para servir el editor de cuadrantes - devuelve la página principal
@app.route('/editor/cuadrantes')
def serve_quadrants_editor():
    print("[EDITOR] Serving quadrants editor", flush=True)
    return send_from_directory('static/quadrants_editor', 'index.html')

# Ruta para servir la página de validación del sistema
@app.route('/test/jerarquia')
def serve_validation_test():
    print("[TEST] Serving hierarchy validation test", flush=True)
    return send_from_directory('static/quadrants_editor', 'validation_test.html')

# Ruta para servir assets del editor de cuadrantes (JS, CSS, etc.)
@app.route('/static/quadrants_editor/<path:filename>')
def serve_quadrants_assets(filename):
    return send_from_directory('static/quadrants_editor', filename)

# Ruta para servir librerías vendor locales
@app.route('/static/vendor/<path:filename>')
def serve_vendor_assets(filename):
    return send_from_directory('static/vendor', filename)

# Ruta para servir archivos geojson con validación de seguridad
@app.route('/geojson/<path:filename>')
def serve_geojson(filename):
    # Bloquear traversal y rutas absolutas
    if '..' in filename or filename.startswith('/'):
        abort(400, description="Archivo no permitido")
    # Aceptar solo .geojson o .json
    if not (filename.endswith('.geojson') or filename.endswith('.json')):
        abort(400, description="Extensión no permitida")
    return send_from_directory('geojson', filename, mimetype='application/geo+json')

# Ruta para servir GeoJSON por defecto según ciudad
@app.route('/geojson/default')
def geojson_default():
    from unicodedata import normalize
    
    # 1) Leer ciudad de query y normalizar (espacios, acentos, mayúsculas)
    raw = (request.args.get('city') or 'CALI').strip()
    # "BOGOTÁ" -> "bogota", "Medellín" -> "medellin"
    city_slug = normalize('NFKD', raw).encode('ascii', 'ignore').decode('ascii')
    city_slug = city_slug.lower().replace(' ', '_')

    # 2) Construir nombre estándar de comunas
    filename = f'comunas_{city_slug}.geojson'

    # 3) Verificar existencia (y fallback opcional por compatibilidad)
    path = os.path.join('geojson', filename)
    if not os.path.exists(path):
        # Fallback legacy solo para CALI (por si aún no está el comunas_cali.geojson)
        if city_slug == 'cali' and os.path.exists(os.path.join('geojson', 'cuadrantes_cali_rutas_consultores.geojson')):
            filename = 'cuadrantes_cali_rutas_consultores.geojson'
        else:
            abort(404, description=f"No hay GeoJSON de comunas para '{raw}' (esperado: {filename})")

    print(f"[GEOJSON] default city={raw} -> {filename}", flush=True)
    return send_from_directory('geojson', filename, mimetype='application/geo+json')

if __name__ == '__main__':
    # Asegurar que las carpetas necesarias existen
    os.makedirs('static/maps', exist_ok=True)
    os.makedirs('static/quadrants_editor', exist_ok=True)
    # Ejecutar el servidor en el puerto 5000
    app.run(port=5000)