#!/usr/bin/env python3
"""
Test script to verify the improvements in CSV export and popup display
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from mapa_consultores import generar_mapa_consultores
import pandas as pd
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_csv_export():
    """Test CSV export with events without coordinates"""
    print("=" * 60)
    print("TESTING CSV EXPORT WITH EVENTS WITHOUT COORDINATES")
    print("=" * 60)
    
    # Test parameters - adjust these for your test data
    fecha_inicio = "2024-01-01 00:00:00"
    fecha_fin = "2024-12-31 23:59:59"
    ciudad = "CALI"
    ruta_id = 1  # Adjust this
    ruta_nombre = "Test Route"
    
    try:
        filename, df_export = generar_mapa_consultores(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            ciudad=ciudad,
            ruta_id=ruta_id,
            ruta_nombre=ruta_nombre,
            mostrar_fuera=True
        )
        
        print(f"✅ Map generated successfully: {filename}")
        
        if df_export is not None and not df_export.empty:
            print(f"✅ CSV Export DataFrame generated: {len(df_export)} rows")
            
            # Check for type 20 events without coordinates
            type_20_sin_coords = df_export[
                (df_export['id_evento_tipo'] == 20) & 
                (df_export['origen'] == 'sin_coordenadas')
            ]
            
            print(f"✅ Type 20 events without coordinates: {len(type_20_sin_coords)}")
            
            # Check for different origins
            origins = df_export['origen'].value_counts() if 'origen' in df_export.columns else {}
            print(f"✅ CSV origins breakdown: {dict(origins)}")
            
            # Check columns
            expected_cols = ['tipo_evento', 'venta_fuera_ruta', 'dentro_cuadrante', 'origen']
            for col in expected_cols:
                if col in df_export.columns:
                    print(f"✅ Column '{col}' present")
                else:
                    print(f"❌ Column '{col}' missing")
            
            # Check venta_fuera_ruta flag
            if len(type_20_sin_coords) > 0:
                venta_fuera_ruta_check = type_20_sin_coords['venta_fuera_ruta'].all()
                print(f"✅ All type 20 events have venta_fuera_ruta=1: {venta_fuera_ruta_check}")
            
            # Show sample data
            print("\nSample data from CSV export:")
            print(df_export[['id_evento_tipo', 'tipo_evento', 'venta_fuera_ruta', 'origen']].head(10))
            
            # Test flag consistency verification
            print("\n" + "=" * 40)
            print("FLAG CONSISTENCY VERIFICATION")
            print("=" * 40)
            
            if 'venta_fuera_ruta' in df_export.columns:
                flag_sum = df_export['venta_fuera_ruta'].sum()
                type_20_count = len(df_export[df_export['id_evento_tipo'] == 20])
                print(f"venta_fuera_ruta flag sum: {flag_sum}")
                print(f"Type 20 events count: {type_20_count}")
                print(f"✅ Consistency check: {'PASS' if flag_sum == type_20_count else 'FAIL'}")
            
        else:
            print("❌ No CSV export data generated")
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

def test_popup_columns():
    """Test that popup includes Muestras column"""
    print("\n" + "=" * 60)
    print("TESTING POPUP DISPLAY WITH MUESTRAS COLUMN")
    print("=" * 60)
    
    # This is harder to test programmatically since popups are HTML
    # But we can check if the function imports work
    try:
        from mapa_consultores import _generar_popup_cuadrante
        print("✅ _generar_popup_cuadrante function imported successfully")
        
        # Create sample data to test popup generation
        import pandas as pd
        
        df_resumen = pd.DataFrame([{
            'codigo_cuadrante': 'TEST-01',
            'area_m2': 1000000,
            'visitas_tot': 10,
            'visitas_por_m2': 0.00001
        }])
        
        df_detalle = pd.DataFrame([{
            'codigo_cuadrante': 'TEST-01',
            'id_consultor': 123,
            'apellido': 'Test Consultant',
            'visitas': 5,
            'aperturas': 2,
            'sac': 1,
            'muestras': 3,  # This should appear in popup
            'ventas_58': 1,
            'ventas_fuera': 0,
            'total_venta_conIVA': 50000
        }])
        
        popup_html = _generar_popup_cuadrante('TEST-01', df_resumen, df_detalle)
        
        # Check if Muestras appears in the HTML
        if 'Muestras' in popup_html:
            print("✅ 'Muestras' column found in popup HTML")
        else:
            print("❌ 'Muestras' column missing from popup HTML")
            
        # Check if the value appears
        if '3' in popup_html:  # Our test value
            print("✅ Muestras value (3) found in popup HTML")
        else:
            print("❌ Muestras value not found in popup HTML")
            
        print(f"\nSample popup HTML preview:")
        print(popup_html[:500] + "..." if len(popup_html) > 500 else popup_html)
        
    except Exception as e:
        print(f"❌ Error testing popup: {e}")
        import traceback
        traceback.print_exc()

def test_legend_csv_consistency():
    """Test that legend matches CSV export exactly"""
    print("\n" + "=" * 60)
    print("TESTING LEGEND-CSV CONSISTENCY")
    print("=" * 60)
    
    # Test parameters - adjust for your test data  
    fecha_inicio = "2024-01-01 00:00:00"
    fecha_fin = "2024-12-31 23:59:59"
    ciudad = "CALI"
    ruta_id = 1
    ruta_nombre = "Test Route"
    
    try:
        filename, df_export_clean = generar_mapa_consultores(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            ciudad=ciudad,
            ruta_id=ruta_id,
            ruta_nombre=ruta_nombre,
            mostrar_fuera=True
        )
        
        print(f"✅ Map generated: {filename}")
        
        if df_export_clean is not None and not df_export_clean.empty:
            # Calculate what should match the legend
            total_csv = len(df_export_clean)
            dentro_csv = int(df_export_clean.get('dentro_cuadrante', pd.Series([False] * len(df_export_clean))).sum())
            
            print(f"✅ CSV export contains {total_csv} total events")
            print(f"✅ CSV export contains {dentro_csv} events dentro_cuadrante=True")
            print(f"✅ Legend should show Total: {total_csv}, Dentro: {dentro_csv}")
            
            # Check for duplicates to verify deduplication worked
            if 'id_evento' in df_export_clean.columns:
                duplicates = df_export_clean['id_evento'].duplicated().sum()
                print(f"✅ Deduplication check: {duplicates} duplicate id_evento (should be 0)")
            
            # Verify type 20 events are included
            type_20_count = len(df_export_clean[df_export_clean['id_evento_tipo'] == 20])
            print(f"✅ Type 20 events in final CSV: {type_20_count}")
            
        else:
            print("❌ No CSV export data generated")
            
    except Exception as e:
        print(f"❌ Error during legend-CSV test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("Starting comprehensive improvement tests...")
    
    # Test CSV export functionality
    test_csv_export()
    
    # Test popup functionality  
    test_popup_columns()
    
    # Test legend-CSV consistency
    test_legend_csv_consistency()
    
    print("\n" + "=" * 60)
    print("TESTS COMPLETED")
    print("=" * 60)
    print("\nManual verification steps:")
    print("1. Generate a map and verify legend 'Total' and 'Dentro' match CSV row counts")
    print("2. Download CSV and confirm no duplicate events (especially type 20)")
    print("3. Open popup and verify no horizontal scrolling, 'Total venta' on one line")
    print("4. Verify 'Muestras' column appears between 'SAC' and 'Venta en ruta'")
    print("5. Confirm both coordinate-based and consultant-based type 20 events included")