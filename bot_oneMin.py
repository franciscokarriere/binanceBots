import ccxt
import pandas as pd
import time
import os
import gc

from dotenv import load_dotenv

# ==========================================
# 1. CONFIGURACIÓN Y CREDENCIALES
# ==========================================
load_dotenv(dotenv_path=".env")

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
    }
})

# Parámetros de Gestión de Riesgo (Escenario Híbrido)
TAKE_PROFIT_PCT = 1.0175  # +1.75%
STOP_LOSS_PCT = 0.9940    # -0.60%
UMBRAL_ATR_PCT = 0.03     # Filtro mínimo de volatilidad (0.03%)

# ==========================================
# 2. OBTENCIÓN DE DATOS (CACHÉ LOCAL)
# ==========================================
def obtener_datos(simbolo='BTC/USDT', timeframe='1m', limit=5000):
    archivo_csv = 'historico_velas.csv'
    
    if os.path.exists(archivo_csv):
        df = pd.read_csv(archivo_csv)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        ultimo_ms = int(df['timestamp'].iloc[-1].timestamp() * 1000)
        
        velas_nuevas = exchange.fetch_ohlcv(simbolo, timeframe, since=ultimo_ms, limit=1000)
        
        if velas_nuevas:
            df_nuevo = pd.DataFrame(velas_nuevas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_nuevo['timestamp'] = pd.to_datetime(df_nuevo['timestamp'], unit='ms')
            df = pd.concat([df, df_nuevo]).drop_duplicates(subset=['timestamp'])
            df = df.tail(limit)
    else:
        print(f"Caché no encontrado. Descargando bloque pesado de {limit} velas...")
        velas_totales = []
        desde_ms = exchange.milliseconds() - (limit * 60 * 1000) 
        
        while len(velas_totales) < limit:
            velas = exchange.fetch_ohlcv(simbolo, timeframe, since=desde_ms, limit=1000)
            if not velas: break
            desde_ms = velas[-1][0] + 1 
            velas_totales.extend(velas)
            time.sleep(0.1) 
            
        velas_totales = velas_totales[-limit:]
        df = pd.DataFrame(velas_totales, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

    df.to_csv(archivo_csv, index=False)
    return df

# ==========================================
# 3. MOTOR ALGORÍTMICO Y GESTIÓN DE RIESGO
# ==========================================
def calcular_indicadores(df, sma_rapida=50, sma_lenta=5000):
    """ Calcula Medias Móviles y Volatilidad (ATR). """
    # Medias Móviles
    df['SMA_rapida'] = df['close'].rolling(window=sma_rapida).mean()
    df['SMA_lenta'] = df['close'].rolling(window=sma_lenta).mean()
    
    # Average True Range (ATR 14) para filtro de volatilidad
    df['high_low'] = df['high'] - df['low']
    df['high_close'] = abs(df['high'] - df['close'].shift())
    df['low_close'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    df['ATR_pct'] = (df['ATR'] / df['close']) * 100
    
    return df

def recuperar_precio_entrada(simbolo):
    """ Busca en el historial de Binance a qué precio se compró la posición actual. """
    try:
        trades = exchange.fetch_my_trades(simbolo, limit=20)
        compras = [t for t in trades if t['side'] == 'buy']
        if compras:
            return compras[-1]['price']
    except Exception as e:
        print(f"Error recuperando historial: {e}")
    return 0.0

def procesar_mercado(simbolo, df, en_posicion, precio_entrada_memoria, balances):
    precio_actual = df['close'].iloc[-1]
    ultima_rapida = df['SMA_rapida'].iloc[-1]
    ultima_lenta = df['SMA_lenta'].iloc[-1]
    ultimo_atr = df['ATR_pct'].iloc[-1]
    
    # A. LÓGICA DE SALIDA (Desacoplada de las gráficas)
    if en_posicion:
        # Failsafe: Si el bot se reinició, recuperar el precio de entrada de la API
        if precio_entrada_memoria == 0.0:
            print("Recuperando precio de entrada desde el historial de Binance...")
            precio_entrada_memoria = recuperar_precio_entrada(simbolo)
            # Si aún falla, usamos el precio actual para no quedar desprotegidos
            if precio_entrada_memoria == 0.0: precio_entrada_memoria = precio_actual
            
        precio_tp = precio_entrada_memoria * TAKE_PROFIT_PCT
        precio_sl = precio_entrada_memoria * STOP_LOSS_PCT
        
        print(f"Posición Abierta | Entrada: ${precio_entrada_memoria:.2f} | Actual: ${precio_actual:.2f} | TP: ${precio_tp:.2f} | SL: ${precio_sl:.2f}")
        
        if precio_actual >= precio_tp:
            print(f"[!] TAKE PROFIT ALCANZADO (+1.75%). Cerrando posición en ${precio_actual:.2f}")
            exchange.create_market_sell_order(simbolo, balances['base'])
            return False, 0.0
            
        elif precio_actual <= precio_sl:
            print(f"[!] STOP LOSS ALCANZADO (-0.60%). Cortando pérdidas en ${precio_actual:.2f}")
            exchange.create_market_sell_order(simbolo, balances['base'])
            return False, 0.0
            
        return True, precio_entrada_memoria

    # B. LÓGICA DE ENTRADA (Golden Cross + ATR)
    else:
        print(f"Buscando Entrada | Precio: ${precio_actual:.2f} | SMA50: ${ultima_rapida:.2f} | SMA5000: ${ultima_lenta:.2f} | Volatilidad: {ultimo_atr:.3f}%")
        
        if pd.isna(ultima_lenta): return False, 0.0
        
        if ultimo_atr < UMBRAL_ATR_PCT:
            print("-> Mercado lateral/sin volumen. Operación bloqueada por filtro ATR.")
            return False, 0.0
            
        if ultima_rapida > ultima_lenta:
            try:
                tamano_compra = (balances['usdt'] * 0.98) / precio_actual
                print(f"[!] GOLDEN CROSS CONFIRMADO. Ejecutando COMPRA de {tamano_compra:.6f} BTC a ${precio_actual:.2f}")
                orden = exchange.create_market_buy_order(simbolo, tamano_compra)
                # Guardar el precio de entrada real para el Take Profit
                precio_ejecutado = orden['price'] if 'price' in orden and orden['price'] else precio_actual
                return True, precio_ejecutado
            except Exception as e:
                print(f"Error al comprar: {e}")
                
        return False, 0.0

# ==========================================
# 4. CICLO PRINCIPAL (DAEMON)
# ==========================================
def bot_daemon():
    simbolo = 'BTC/USDT'
    moneda_base = simbolo.split('/')[0]
    moneda_cotiz = simbolo.split('/')[1]
    
    print("=== INICIANDO BOT ALGORÍTMICO V2 (RISK MANAGEMENT) ===")
    
    # Variables de estado en memoria
    precio_entrada = 0.0
    
    while True:
        try:
            print(f"\n[{pd.Timestamp.now().strftime('%H:%M:%S')}] Evaluando...")
            
            # 1. Obtener saldos en vivo
            balance_raw = exchange.fetch_balance()
            balances = {
                'base': balance_raw[moneda_base]['free'],
                'usdt': balance_raw[moneda_cotiz]['free']
            }
            en_posicion = balances['base'] > 0.0001
            
            # 2. Procesar datos del mercado
            df = obtener_datos(simbolo, '1m', 5000)
            df = calcular_indicadores(df)
            
            # 3. Ejecutar estrategia
            en_posicion, precio_entrada = procesar_mercado(simbolo, df, en_posicion, precio_entrada, balances)
            
            # 4. Limpieza agresiva de memoria
            del df
            gc.collect()
            
            time.sleep(60)
            
        except KeyboardInterrupt:
            print("\nEjecución detenida manualmente.")
            break
        except ccxt.NetworkError:
            print("Error de red con Binance. Se reintentará en el próximo minuto.")
            time.sleep(60)
        except Exception as e:
            print(f"\nFallo general en el ciclo: {e}")
            time.sleep(60)

if __name__ == "__main__":
    bot_daemon()