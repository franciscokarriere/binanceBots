import ccxt
import pandas as pd
import sys
import time
from datetime import datetime, timedelta

# Comisión estándar de Binance (0.1%)
COMISION_PCT = 0.001 

def backtest_semana(monto_inicial=100.0, fecha_inicio='2026-05-04', media_lenta=1000, media_rapida=300):
    exchange = ccxt.binance({'enableRateLimit': True})
    
    # 1. Ajuste Dinámico de Fecha (Warmup según MA Lenta)
    dt = datetime.strptime(fecha_inicio, '%Y-%m-%d')
    dt_warmup = dt - timedelta(minutes=media_lenta)
    since_ms = int(dt_warmup.timestamp() * 1000)
    
    print(f"Descargando historial (incluyendo warmup de {media_lenta} velas) desde {dt_warmup.strftime('%Y-%m-%d %H:%M')}...")
    
    # 2. Paginación de API para los 7 días exactos (10080 minutos) + warmup
    velas_totales = []
    minutos_en_siete_dias = 10080
    limite_velas = media_lenta + minutos_en_siete_dias
    
    while len(velas_totales) < limite_velas:
        try:
            velas = exchange.fetch_ohlcv('BTC/USDT', '1m', since=since_ms, limit=1000)
            if not velas:
                break
            since_ms = velas[-1][0] + 1
            velas_totales.extend(velas)
            time.sleep(0.1) 
        except Exception as e:
            print(f"Error descargando bloque de datos: {e}")
            break
            
    df = pd.DataFrame(velas_totales, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    if len(df) < media_lenta:
        print(f"Error: No hay suficientes datos para calcular la SMA de {media_lenta} periodos.")
        return
    
    # Lógica de indicadores con parámetros dinámicos
    df['SMA_rapida'] = df['close'].rolling(window=media_rapida).mean()
    df['SMA_lenta'] = df['close'].rolling(window=media_lenta).mean()
    df['ATR_pct'] = ((df['high'] - df['low']).rolling(window=14).mean() / df['close']) * 100
    
    capital = float(monto_inicial)
    capital_pico = float(monto_inicial)
    max_drawdown = 0.0
    
    comisiones_totales = 0
    ops_compra = 0
    ops_venta = 0
    en_posicion = False
    precio_entrada = 0
    
    print(f"Iniciando evaluación de 7 días desde: {fecha_inicio}...")
    
    # Bucle inicia exactamente en la fecha solicitada
    for i in range(media_lenta, len(df)):
        # Detener la simulación exactamente a los 7 días (10080 velas evaluadas)
        if i >= media_lenta + minutos_en_siete_dias:
            break
            
        fila = df.iloc[i]
        
        # Filtros de entrada V4.1
        if not en_posicion and fila['ATR_pct'] >= 0.25 and fila['SMA_rapida'] > fila['SMA_lenta'] and \
           ((fila['SMA_rapida'] - fila['SMA_lenta']) / fila['SMA_lenta']) * 100 >= 0.05:
            
            comision = capital * COMISION_PCT
            capital -= comision
            comisiones_totales += comision
            precio_entrada = fila['close']
            en_posicion = True
            ops_compra += 1
            
        # Filtros de salida V4.1
        elif en_posicion:
            tp = precio_entrada * 1.0175
            sl = precio_entrada * 0.9930
            
            if fila['high'] >= tp or fila['low'] <= sl:
                precio_salida = tp if fila['high'] >= tp else sl
                capital *= (precio_salida / precio_entrada)
                
                comision = capital * COMISION_PCT
                capital -= comision
                comisiones_totales += comision
                en_posicion = False
                ops_venta += 1
        
        # Cálculo de Drawdown Máximo
        if capital > capital_pico:
            capital_pico = capital
        drawdown = (capital_pico - capital) / capital_pico
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Cálculo del beneficio neto en porcentaje
    beneficio_pct = ((capital - monto_inicial) / monto_inicial) * 100

    # Formato de salida estricto
    print(f"\nmonto inicial: {monto_inicial:.2f} USD | MA Larga: {media_lenta} |  MA Corta: {media_rapida} | "
          f"operaciones compra: {ops_compra} | operaciones venta: {ops_venta} | "
          f"balance final: {capital:.2f} USD | beneficio neto: {beneficio_pct:.2f}% | "
          f"comisiones pagadas: {comisiones_totales:.4f} USD | drawdown máximo: {max_drawdown*100:.2f}%")

if __name__ == "__main__":
    monto = float(sys.argv[1]) if len(sys.argv) > 1 else 100.0
    fecha = sys.argv[2] if len(sys.argv) > 2 else '2026-05-04'
    m_lenta = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    m_rapida = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    
    backtest_semana(monto, fecha, m_lenta, m_rapida)