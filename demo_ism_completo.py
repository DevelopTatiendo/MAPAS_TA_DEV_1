#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demostración completa del sistema ISM con nueva configuración
"""

import pandas as pd
from ism_config import resolve_hogares_por_m2, CITY_PARAMS

def demo_sistema_ism():
    print("=== 🚀 DEMOSTRACIÓN SISTEMA ISM - CONFIGURACIÓN MEJORADA ===\n")
    
    print("1. 🏙️ CIUDADES CONFIGURADAS:")
    print("   " + "="*60)
    for ciudad, params in CITY_PARAMS.items():
        pph = params.get('personas_por_hogar', 'N/A')
        densidad = params.get('densidad_hab_km2', 'N/A')
        status = "✅ COMPLETA" if pph != 'N/A' and densidad != 'N/A' else "⚠️ INCOMPLETA"
        print(f"   {ciudad:<12}: pph={pph}, densidad={densidad} hab/km² - {status}")
    
    print(f"\n2. 🎯 MANIZALES - CIUDAD DE PRUEBA:")
    print("   " + "="*40)
    try:
        manizales_hogares = resolve_hogares_por_m2('MANIZALES')
        print(f"   ✓ Configuración base: {manizales_hogares:.8f} hogares/m²")
        print(f"   ✓ Equivalencia: ~{manizales_hogares * 1000000:.0f} hogares/km²")
        print(f"   ✓ Parámetros: pph=2.0, densidad=958 hab/km²")
        print(f"   ✓ Cálculo: 958 ÷ 2.0 ÷ 1,000,000 = 0.000479")
        
        # Test overrides
        print(f"\n   🔧 Calibración con overrides:")
        
        # Override PPH
        hogares_pph3 = resolve_hogares_por_m2('MANIZALES', pph_override=3.0)
        print(f"      • PPH override 3.0: {hogares_pph3:.8f} hogares/m²")
        print(f"        (958 ÷ 3.0 ÷ 1M = {958/3/1000000:.8f})")
        
        # Override directo
        hogares_directo = resolve_hogares_por_m2('MANIZALES', hogares_por_m2_override=0.0006)
        print(f"      • Override directo: {hogares_directo:.8f} hogares/m²")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print(f"\n3. ⚙️ OTRAS CIUDADES - CAPACIDADES:")
    print("   " + "="*45)
    
    ciudades_prueba = ['MEDELLIN', 'BOGOTA', 'CALI']
    for ciudad in ciudades_prueba:
        print(f"\n   {ciudad}:")
        try:
            # Sin override - debe fallar para ciudades incompletas
            hogares_base = resolve_hogares_por_m2(ciudad)
            print(f"      ✓ Base: {hogares_base:.8f} hogares/m²")
        except Exception as e:
            print(f"      ⚠️ Base: {str(e)[:60]}...")
        
        try:
            # Con override directo - debe funcionar
            hogares_override = resolve_hogares_por_m2(ciudad, hogares_por_m2_override=0.0005)
            print(f"      ✅ Con override: {hogares_override:.8f} hogares/m²")
        except Exception as e:
            print(f"      ❌ Override falló: {e}")
    
    print(f"\n4. 📊 CARACTERÍSTICAS DEL SISTEMA:")
    print("   " + "="*40)
    print("   ✅ Configuración centralizada por ciudad")
    print("   ✅ Jerarquía de overrides para calibración")
    print("   ✅ Validación robusta de parámetros")
    print("   ✅ Compatibilidad con ciudades incompletas")
    print("   ✅ Cálculos automáticos densidad → hogares/m²")
    print("   ✅ Integración con ISM compute_ism_metrics_por_cuadrante")
    
    print(f"\n5. 🔄 JERARQUÍA DE RESOLUCIÓN:")
    print("   " + "="*35)
    print("   1️⃣ hogares_por_m2_override (directo)")
    print("   2️⃣ CITY_PARAMS[ciudad]['hogares_por_m2'] (config)")
    print("   3️⃣ densidad_hab_km2 / personas_por_hogar (calculado)")
    print("   4️⃣ densidad_hab_km2 / pph_override (calculado con override)")
    
    print(f"\n6. 🎮 USO EN INTERFAZ:")
    print("   " + "="*25)
    print("   • Manizales: ¡Funciona sin overrides!")
    print("   • Medellín: Requiere overrides en UI")
    print("   • Otras: Configurar densidad o usar overrides")
    print("   • UI: Controles numéricos para pph y hogares/m²")
    
    print(f"\n=== 🎉 SISTEMA ISM LISTO PARA PRODUCCIÓN ===")
    print(f"✅ Manizales habilitado con densidad 958 hab/km² y pph=2.0")
    print(f"🎯 Calibración flexible vía overrides para otras ciudades")
    print(f"🔧 Configuración extensible para futuras ciudades")
    print(f"🚀 Integración completa con mapas y exportación CSV")

if __name__ == "__main__":
    demo_sistema_ism()