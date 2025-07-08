import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pre_procesamiento.preprocesamiento_pedidos import crear_df as crear_df_pedidos
from pre_procesamiento.preprocesamiento_muestras import crear_df as crear_df_muestras
from pre_procesamiento.preprocesamiento_visitas import crear_df as crear_df_visitas
import unicodedata

def generar_estadisticas_visitas(fecha_inicio, fecha_fin, ruta_coordenadas, ruta_cobro=None, centroope=None):
    """
    Genera los gráficos estadísticos para pedidos.
    Retorna un diccionario con los títulos y figuras de Plotly.
    """
    df = crear_df_visitas(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)


    if ruta_cobro:
        df = df[df['ruta_cobro'] == ruta_cobro]
    graficos = {}

    # 1. Top 10 barrios con más pedidos
    top_barrios = df['barrio'].value_counts().head(10)
    fig_barrios = go.Figure(data=[
        go.Bar(
            x=top_barrios.index,
            y=top_barrios.values,
            text=top_barrios.values,
            textposition='auto',
        )
    ])
    fig_barrios.update_layout(
        title='Top 10 Barrios con Más Visitas',
        xaxis_title='Barrios',
        yaxis_title='Cantidad de Visitas',
        xaxis_tickangle=45
    )
    graficos["Top 10 Barrios"] = fig_barrios

    # 2. Tendencia temporal de pedidos
    df['fecha'] = pd.to_datetime(df['fecha_evento']).dt.date
    pedidos_por_dia = df.groupby('fecha').size()
    pedidos_por_dia = pedidos_por_dia[pedidos_por_dia > 15]
    
    # Calcular intervalo basado en el rango de fechas
    dias_totales = (pedidos_por_dia.index.max() - pedidos_por_dia.index.min()).days
    if dias_totales <= 30:
        intervalo = 2
    elif dias_totales <= 180:
        intervalo = 7
    elif dias_totales <= 365:
        intervalo = 15
    else:
        intervalo = 30

    # Agrupar por intervalo
    df_temp = pedidos_por_dia.reset_index()
    df_temp.columns = ['fecha', 'cantidad']
    df_temp['grupo'] = df_temp.index // intervalo
    pedidos_acumulados = df_temp.groupby('grupo').agg({
        'fecha': 'min',
        'cantidad': 'sum'
    })

    fig_tendencia = go.Figure(data=[
        go.Scatter(
            x=pedidos_acumulados['fecha'],
            y=pedidos_acumulados['cantidad'],
            mode='lines+markers+text',
            text=pedidos_acumulados['cantidad'],
            textposition="top center"
        )
    ])
    fig_tendencia.update_layout(
        title=f'Tendencia de Visitas (Acumulado cada {intervalo} días)',
        xaxis_title='Fecha',
        yaxis_title='Cantidad Acumulada de Visitas',
        showlegend=False
    )
    graficos["Tendencia Temporal"] = fig_tendencia
    
    # 3. Distribución por estrato
    muestras_por_estrato = df['id_estrato'].value_counts()
    muestras_por_estrato = muestras_por_estrato[muestras_por_estrato.index != 0]
    
    fig_estrato = go.Figure(data=[
        go.Pie(
            labels=muestras_por_estrato.index,
            values=muestras_por_estrato.values,
            textinfo='percent+label'
        )
    ])
    fig_estrato.update_layout(
        title='Distribución de Visitas por Estrato'
    )
    graficos["Distribución por Estrato"] = fig_estrato

    # 4. Visitas por tipo evento
    # 1. Distribución de tipos de evento
    eventos_count = df['tipo_evento'].value_counts()
    fig_eventos = go.Figure(data=[
        go.Bar(
            x=eventos_count.index,
            y=eventos_count.values,
            text=eventos_count.values,
            textposition='auto',
        )
    ])
    fig_eventos.update_layout(
        title='Distribución de Visitas por Tipo de Evento',
        xaxis_title='Tipo de Evento',
        yaxis_title='Cantidad de Visitas',
        xaxis_tickangle=45
    )
    graficos["Tipos de Evento"] = fig_eventos

    # 4. Pedidos por ruta (solo si no se ha filtrado por ruta)
    if not ruta_cobro:
        
        pedidos_por_ruta = df['ruta_cobro'].value_counts()
        
        
        fig_rutas = go.Figure(data=[
            go.Bar(
                x=pedidos_por_ruta.index,
                y=pedidos_por_ruta.values,
                text=pedidos_por_ruta.values,
                textposition='auto',
            )
        ])
        fig_rutas.update_layout(
            title='Visitas por Ruta',
            xaxis_title='Ruta',
            yaxis_title='Cantidad de Visitas',
            xaxis_tickangle=45
        )
        graficos["Visitas por Ruta"] = fig_rutas
    return graficos

def generar_estadisticas_muestras(fecha_inicio, fecha_fin, ruta_coordenadas,ruta_cobro=None, centroope=None):
    """
    Genera los gráficos estadísticos para pedidos.
    Retorna un diccionario con los títulos y figuras de Plotly.
    """
    df = crear_df_muestras(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)


    if ruta_cobro:
        df = df[df['nom_ruta'] == ruta_cobro]
    graficos = {}

    # 1. Top 10 barrios con más pedidos
    top_barrios = df['barrio'].value_counts().head(10)
    fig_barrios = go.Figure(data=[
        go.Bar(
            x=top_barrios.index,
            y=top_barrios.values,
            text=top_barrios.values,
            textposition='auto',
        )
    ])
    fig_barrios.update_layout(
        title='Top 10 Barrios con Más Muestras',
        xaxis_title='Barrios',
        yaxis_title='Cantidad de Muestras',
        xaxis_tickangle=45
    )
    graficos["Top 10 Barrios"] = fig_barrios

    # 2. Tendencia temporal de pedidos
    df['fecha'] = pd.to_datetime(df['fecha_evento']).dt.date
    pedidos_por_dia = df.groupby('fecha').size()
    pedidos_por_dia = pedidos_por_dia[pedidos_por_dia > 15]
    
    # Calcular intervalo basado en el rango de fechas
    dias_totales = (pedidos_por_dia.index.max() - pedidos_por_dia.index.min()).days
    if dias_totales <= 30:
        intervalo = 2
    elif dias_totales <= 180:
        intervalo = 7
    elif dias_totales <= 365:
        intervalo = 15
    else:
        intervalo = 30

    # Agrupar por intervalo
    df_temp = pedidos_por_dia.reset_index()
    df_temp.columns = ['fecha', 'cantidad']
    df_temp['grupo'] = df_temp.index // intervalo
    pedidos_acumulados = df_temp.groupby('grupo').agg({
        'fecha': 'min',
        'cantidad': 'sum'
    })

    fig_tendencia = go.Figure(data=[
        go.Scatter(
            x=pedidos_acumulados['fecha'],
            y=pedidos_acumulados['cantidad'],
            mode='lines+markers+text',
            text=pedidos_acumulados['cantidad'],
            textposition="top center"
        )
    ])
    fig_tendencia.update_layout(
        title=f'Tendencia de Muestreo (Acumulado cada {intervalo} días)',
        xaxis_title='Fecha',
        yaxis_title='Cantidad Acumulada de Muestreas',
        showlegend=False
    )
    graficos["Tendencia Temporal"] = fig_tendencia
    
    # 3. Distribución por estrato
    muestras_por_estrato = df['id_estrato'].value_counts()
    muestras_por_estrato = muestras_por_estrato[muestras_por_estrato.index != 0]
    
    fig_estrato = go.Figure(data=[
        go.Pie(
            labels=muestras_por_estrato.index,
            values=muestras_por_estrato.values,
            textinfo='percent+label'
        )
    ])
    fig_estrato.update_layout(
        title='Distribución de Muestras por Estrato'
    )
    graficos["Distribución por Estrato"] = fig_estrato
    return graficos
    
def generar_estadisticas_pedidos( fecha_inicio, fecha_fin,ruta_coordenadas, ruta=None, centroope=None):
    """
    Genera los gráficos estadísticos para pedidos.
    Retorna un diccionario con los títulos y figuras de Plotly.
    """
    # Obtener los datos usando la función crear_df
    df = crear_df_pedidos(centroope, fecha_inicio, fecha_fin, ruta_coordenadas)
    # print(df.head())
    
    # Filtrar por ruta si se especifica
    if ruta:
        df = df[df['nom_ruta'] == ruta]
    
    graficos = {}
    
    # 1. Top 10 barrios con más pedidos
    top_barrios = df['barrio'].value_counts().head(10)
    fig_barrios = go.Figure(data=[
        go.Bar(
            x=top_barrios.index,
            y=top_barrios.values,
            text=top_barrios.values,
            textposition='auto',
        )
    ])
    fig_barrios.update_layout(
        title='Top 10 Barrios con Más Pedidos',
        xaxis_title='Barrios',
        yaxis_title='Cantidad de Pedidos',
        xaxis_tickangle=45
    )
    graficos["Top 10 Barrios"] = fig_barrios

    # 2. Tendencia temporal de pedidos
    df['fecha'] = pd.to_datetime(df['fecha_pedido']).dt.date
    pedidos_por_dia = df.groupby('fecha').size()
    pedidos_por_dia = pedidos_por_dia[pedidos_por_dia > 15]
    
    # Calcular intervalo basado en el rango de fechas
    dias_totales = (pedidos_por_dia.index.max() - pedidos_por_dia.index.min()).days
    if dias_totales <= 30:
        intervalo = 2
    elif dias_totales <= 180:
        intervalo = 7
    elif dias_totales <= 365:
        intervalo = 15
    else:
        intervalo = 30

    # Agrupar por intervalo
    df_temp = pedidos_por_dia.reset_index()
    df_temp.columns = ['fecha', 'cantidad']
    df_temp['grupo'] = df_temp.index // intervalo
    pedidos_acumulados = df_temp.groupby('grupo').agg({
        'fecha': 'min',
        'cantidad': 'sum'
    })

    fig_tendencia = go.Figure(data=[
        go.Scatter(
            x=pedidos_acumulados['fecha'],
            y=pedidos_acumulados['cantidad'],
            mode='lines+markers+text',
            text=pedidos_acumulados['cantidad'],
            textposition="top center"
        )
    ])
    fig_tendencia.update_layout(
        title=f'Tendencia de Pedidos (Acumulado cada {intervalo} días)',
        xaxis_title='Fecha',
        yaxis_title='Cantidad Acumulada de Pedidos',
        showlegend=False
    )
    graficos["Tendencia Temporal"] = fig_tendencia

    # 3. Distribución por estrato
    pedidos_por_estrato = df['id_estrato'].value_counts()
    pedidos_por_estrato = pedidos_por_estrato[pedidos_por_estrato.index != 0]
    
    fig_estrato = go.Figure(data=[
        go.Pie(
            labels=pedidos_por_estrato.index,
            values=pedidos_por_estrato.values,
            textinfo='percent+label'
        )
    ])
    fig_estrato.update_layout(
        title='Distribución de Pedidos por Estrato'
    )
    graficos["Distribución por Estrato"] = fig_estrato

    # 4. Pedidos por ruta (solo si no se ha filtrado por ruta)
    if not ruta:
        rutas_excluir = ['EMPLEADOS', 'TRANSPORTADORA']
        pedidos_por_ruta = df['nom_ruta'].value_counts()
        pedidos_por_ruta = pedidos_por_ruta[~pedidos_por_ruta.index.isin(rutas_excluir)]
        
        fig_rutas = go.Figure(data=[
            go.Bar(
                x=pedidos_por_ruta.index,
                y=pedidos_por_ruta.values,
                text=pedidos_por_ruta.values,
                textposition='auto',
            )
        ])
        fig_rutas.update_layout(
            title='Pedidos por Ruta',
            xaxis_title='Ruta',
            yaxis_title='Cantidad de Pedidos',
            xaxis_tickangle=45
        )
        graficos["Pedidos por Ruta"] = fig_rutas

    return graficos

def generar_estadisticas(tipo_mapa, ciudad, **kwargs):
    """
    Función principal que dirige la generación de estadísticas según el tipo de mapa.
    """
    ciudad = ''.join(c for c in unicodedata.normalize('NFD', ciudad) if unicodedata.category(c) != 'Mn').upper()
        # Ruta de coordenadas para cada ciudad
    rutas_coordenadas = {
        'CALI': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_CALI.csv",
        'MEDELLIN': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MEDELLIN.csv",
        'MANIZALES': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_MANIZALES.csv",
        'PEREIRA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_PEREIRA.csv",
        'BOGOTA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BOGOTA.csv",
        'BARRANQUILLA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BARRANQUILLA.csv",
        'BUCARAMANGA': "pre_procesamiento/data/BARRIOS_COORDENADAS_RUTAS_COMPLETO_BUCARAMANGA.csv"
    }
    centroopes = {
        'CALI': 2,
        'MEDELLIN': 3,
        'MANIZALES': 6,
        'PEREIRA': 5,
        'BOGOTA': 4,
        'BARRANQUILLA': 8,
        'BUCARAMANGA': 7
    }
    if tipo_mapa == "Pedidos":
        return generar_estadisticas_pedidos(
            centroope=centroopes[ciudad],
            fecha_inicio=kwargs.get('fecha_inicio'),
            fecha_fin=kwargs.get('fecha_fin'),
            ruta_coordenadas = rutas_coordenadas[ciudad],
            ruta=kwargs.get('ruta')
        )
    elif tipo_mapa == "Muestras":
        return generar_estadisticas_muestras(
            centroope=centroopes[ciudad],
            fecha_inicio=kwargs.get('fecha_inicio'),
            fecha_fin=kwargs.get('fecha_fin'),
            ruta_coordenadas = rutas_coordenadas[ciudad],
            ruta_cobro=kwargs.get('ruta_cobro')
        )
    elif tipo_mapa == "Visitas":
        return generar_estadisticas_visitas(
            centroope=centroopes[ciudad],
            fecha_inicio=kwargs.get('fecha_inicio'),
            fecha_fin=kwargs.get('fecha_fin'),
            ruta_coordenadas = rutas_coordenadas[ciudad],
            ruta_cobro=kwargs.get('ruta_cobro')
        )
    # Aquí se añadirían los otros tipos de mapas
    return None