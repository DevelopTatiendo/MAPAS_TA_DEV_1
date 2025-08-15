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
    # Validar que no haya path traversal y que la extensión sea .geojson o .json
    if '..' in filename or not (filename.endswith('.geojson') or filename.endswith('.json')):
        abort(400, description="Archivo no permitido")
    return send_from_directory('geojson', filename)

if __name__ == '__main__':
    # Asegurar que las carpetas necesarias existen
    os.makedirs('static/maps', exist_ok=True)
    os.makedirs('static/quadrants_editor', exist_ok=True)
    # Ejecutar el servidor en el puerto 5000
    app.run(port=5000)