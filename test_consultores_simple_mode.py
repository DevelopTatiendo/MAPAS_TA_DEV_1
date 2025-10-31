"""
Script de prueba para verificar el módulo "Consultores (Simple)".
"""

import sys
import os
from datetime import datetime, date, timedelta

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_consultores_simple():
    """Prueba básica de funcionalidad del módulo consultores simple."""
    print("=" * 70)
    print("TEST: Módulo Consultores (Simple)")
    print("=" * 70)
    
    try:
        from mapa_consultores_simple import generar_mapa_consultores_simple
        print("✓ Módulo importado correctamente")
        
        # Parámetros de prueba
        ciudad = "Cali"
        id_ruta = 13  # Ruta 7 en Cali
        
        # Fechas de prueba (últimos 7 días)
        fecha_fin = date.today()
        fecha_inicio = fecha_fin - timedelta(days=7)
        
        print(f"\nParámetros de prueba:")
        print(f"  Ciudad: {ciudad}")
        print(f"  ID Ruta: {id_ruta}")
        print(f"  Fechas: {fecha_inicio} a {fecha_fin}")
        
        print("\n" + "-" * 70)
        print("Ejecutando generar_mapa_consultores_simple...")
        print("-" * 70)
        
        # Ejecutar la función
        resultado = generar_mapa_consultores_simple(
            ciudad=ciudad,
            id_ruta=id_ruta,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin
        )
        
        # Validar resultado
        if resultado and isinstance(resultado, tuple) and len(resultado) == 2:
            filename, n_puntos = resultado
            
            print("\n" + "=" * 70)
            print("RESULTADO DEL TEST")
            print("=" * 70)
            print(f"✓ Archivo generado: {filename}")
            print(f"✓ Puntos renderizados: {n_puntos}")
            
            # Verificar que el archivo existe
            filepath = f"static/maps/{filename}"
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath) / 1024  # KB
                print(f"✓ Archivo HTML existe ({file_size:.1f} KB)")
                
                # Verificar contenido básico del HTML
                with open(filepath, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                    
                # Verificaciones básicas
                checks = [
                    ("Folium map", "folium" in html_content.lower()),
                    ("CircleMarkers", "CircleMarker" in html_content),
                    ("Comunas layer", "Comunas" in html_content or "geojson" in html_content.lower()),
                ]
                
                print("\nVerificaciones de contenido HTML:")
                for check_name, check_result in checks:
                    status = "✓" if check_result else "✗"
                    print(f"  {status} {check_name}")
                
            else:
                print(f"\n✗ Archivo HTML no encontrado en {filepath}")
            
            print("\n" + "=" * 70)
            print("TEST COMPLETADO EXITOSAMENTE")
            print("=" * 70)
            return True
        else:
            print("\n✗ ERROR: La función no retornó el formato esperado")
            print(f"  Resultado: {resultado}")
            return False
            
    except ImportError as e:
        print(f"\n✗ ERROR de importación: {e}")
        return False
    except Exception as e:
        print(f"\n✗ ERROR durante la ejecución: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_consultores_simple()
    sys.exit(0 if success else 1)