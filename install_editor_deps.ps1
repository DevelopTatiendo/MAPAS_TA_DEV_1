# Script de instalación de dependencias para el editor de cuadrantes (Windows)
# Ejecutar desde PowerShell: .\install_editor_deps.ps1

Write-Host "🚀 Instalando dependencias del Editor de Cuadrantes..." -ForegroundColor Green

# Crear directorios necesarios
New-Item -ItemType Directory -Force -Path "static\vendor\turf" | Out-Null
New-Item -ItemType Directory -Force -Path "static\vendor\proj4" | Out-Null

try {
    # Descargar Turf.js (operaciones geoespaciales)
    Write-Host "📦 Descargando Turf.js..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/@turf/turf@6/turf.min.js" -OutFile "static\vendor\turf\turf.min.js"

    # Descargar Proj4js (transformaciones de coordenadas)
    Write-Host "📦 Descargando Proj4js..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://cdn.jsdelivr.net/npm/proj4@2/dist/proj4.min.js" -OutFile "static\vendor\proj4\proj4.min.js"

    # Verificar descargas
    if ((Test-Path "static\vendor\turf\turf.min.js") -and (Test-Path "static\vendor\proj4\proj4.min.js")) {
        Write-Host "✅ Dependencias instaladas exitosamente" -ForegroundColor Green
        Write-Host "📊 Tamaños de archivo:" -ForegroundColor Cyan
        Get-ChildItem "static\vendor\turf\turf.min.js" | Format-List Name, Length
        Get-ChildItem "static\vendor\proj4\proj4.min.js" | Format-List Name, Length
        Write-Host ""
        Write-Host "🎯 Sistema de jerarquía listo para uso completo" -ForegroundColor Green
        Write-Host "🌐 Accede a: http://localhost:5000/editor/cuadrantes?city=CALI" -ForegroundColor Cyan
    } else {
        Write-Host "❌ Error verificando archivos descargados" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Error descargando dependencias: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "⚠️ El sistema funcionará con aproximaciones básicas" -ForegroundColor Yellow
}

Write-Host "✨ Instalación completada" -ForegroundColor Green
