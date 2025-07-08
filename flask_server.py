from flask import Flask, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)  # Esto permite las solicitudes cross-origin

# Ruta para servir archivos estáticos desde la carpeta static/maps
@app.route('/maps/<path:filename>')
def serve_map(filename):
    return send_from_directory('static/maps', filename)

if __name__ == '__main__':
    # Asegurarse de que la carpeta static/maps existe
    os.makedirs('static/maps', exist_ok=True)
    # Ejecutar el servidor en el puerto 5000
    app.run(port=5000)