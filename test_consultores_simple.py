"""
Script de prueba para verificar el módulo simplificado de consultores.
"""

import sys
import os
from datetime import datetime, timedelta

# Asegurar que el directorio raíz está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_basic_functionality():
    """Prueba básica de funcionalidad del módulo consultores."""
    print("=" * 60)
    print("TEST: Módulo Consultores Simplificado")
    print("=" * 60)
    
    try:
        from mapa_consultores_simple import generar_mapa_consultores
        print("✓ Módulo importado correctamente")
        
        # Parámetros de prueba
        ciudad = "Cali"
        id_ruta = 13  # Ruta 7 en Cali
        nombre_ruta_ui = "ruta 7"
        
        # Fechas de prueba (últimos 7 días)
        fecha_fin = datetime.now()
        fecha_inicio = fecha_fin - timedelta(days=7)
        
        fecha_inicio_str = fecha_inicio.strftime("%Y-%m-%d 00:00:00")
        fecha_fin_str = fecha_fin.strftime("%Y-%m-%d 23:59:59")
        
        print(f"\nParámetros de prueba:")
        print(f"  Ciudad: {ciudad}")
        print(f"  Ruta: {nombre_ruta_ui} (ID: {id_ruta})")
        print(f"  Fechas: {fecha_inicio_str[:10]} a {fecha_fin_str[:10]}")
        
        print("\n" + "-" * 60)
        print("Ejecutando generar_mapa_consultores...")
        print("-" * 60)
        
        # Ejecutar la función
        resultado = generar_mapa_consultores(
            fecha_inicio=fecha_inicio_str,
            fecha_fin=fecha_fin_str,
            ciudad=ciudad,
            id_ruta=id_ruta,
            nombre_ruta_ui=nombre_ruta_ui,
            mostrar_fuera=False
        )
        
        # Validar resultado
        if resultado and isinstance(resultado, tuple) and len(resultado) == 3:
            filename, n_puntos, df_export = resultado
            
            print("\n" + "=" * 60)
            print("RESULTADO DEL TEST")
            print("=" * 60)
            print(f"✓ Archivo generado: {filename}")
            print(f"✓ Puntos renderizados: {n_puntos}")
            print(f"✓ Filas en CSV: {len(df_export) if df_export is not None else 0}")
            
            if df_export is not None and not df_export.empty:
                print(f"\nColumnas del DataFrame de exportación:")
                for col in df_export.columns:
                    print(f"  - {col}")
                
                print(f"\nPrimeras 3 filas del DataFrame:")
                print(df_export.head(3).to_string())
            
            # Verificar que el archivo existe
            filepath = f"static/maps/{filename}"
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath) / 1024  # KB
                print(f"\n✓ Archivo HTML existe ({file_size:.1f} KB)")
            else:
                print(f"\n✗ Archivo HTML no encontrado en {filepath}")
            
            print("\n" + "=" * 60)
            print("TEST COMPLETADO EXITOSAMENTE")
            print("=" * 60)
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
    success = test_basic_functionality()
    sys.exit(0 if success else 1)
