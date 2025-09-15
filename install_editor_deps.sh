#!/bin/bash

# Script de instalación de dependencias para el editor de cuadrantes
# Ejecutar desde la raíz del proyecto: bash install_editor_deps.sh

echo "🚀 Instalando dependencias del Editor de Cuadrantes..."

# Crear directorios necesarios
mkdir -p static/vendor/turf
mkdir -p static/vendor/proj4

# Descargar Turf.js (operaciones geoespaciales)
echo "📦 Descargando Turf.js..."
curl -L "https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js" -o "static/vendor/turf/turf.min.js"

# Descargar Proj4js (transformaciones de coordenadas)
echo "📦 Descargando Proj4js..."
curl -L "https://cdn.jsdelivr.net/npm/proj4@2/dist/proj4.min.js" -o "static/vendor/proj4/proj4.min.js"

# Verificar descargas
if [ -f "static/vendor/turf/turf.min.js" ] && [ -f "static/vendor/proj4/proj4.min.js" ]; then
    echo "✅ Dependencias instaladas exitosamente"
    echo "📊 Tamaños de archivo:"
    ls -lh static/vendor/turf/turf.min.js
    ls -lh static/vendor/proj4/proj4.min.js
    echo ""
    echo "🎯 Sistema de jerarquía listo para uso completo"
    echo "🌐 Accede a: http://localhost:5000/editor/cuadrantes?city=CALI"
else
    echo "❌ Error descargando dependencias"
    echo "⚠️ El sistema funcionará con aproximaciones básicas"
fi

echo "✨ Instalación completada"
