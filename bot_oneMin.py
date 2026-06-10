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

exchange.load_markets()

# Parámetros de Gestión de Riesgo (Protocolo Estricto)
TAKE_PROFIT_PCT = 1.0175        # +1.75%
STOP_LOSS_TRIGGER_PCT = 0.9940  # -0.60% 
STOP_LOSS_LIMIT_PCT = 0.9930    # -0.70% 

# Nuevos Filtros Cuantitativos de Entrada
UMBRAL_ATR_PCT = 0.25           # Volatilidad mínima exigida (Aumentado)
DISTANCIA_CRUCE_PCT = 0.05      # Brecha mínima entre MAs para confirmar fuerza

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
    df['SMA_rapida'] = df['close'].rolling(window=sma_rapida).mean()
    df['SMA_lenta'] = df['close'].rolling(window=sma_lenta).mean()
    
    df['high_low'] = df['high'] - df['low']
    df['high_close'] = abs(df['high'] - df['close'].shift())
    df['low_close'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['high_low', 'high_close', 'low_close']].max(axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    df['ATR_pct'] = (df['ATR'] / df['close']) * 100
    
    return df

def recuperar_precio_entrada(simbolo):
    try:
        trades = exchange.fetch_my_trades(simbolo, limit=20)
        compras = [t for t in trades if t['side'] == 'buy']
        if compras:
            return compras[-1]['price']
    except Exception as e:
        print(f"Error recuperando historial: {e}")
    return 0.0

def colocar_orden_oco(simbolo, cantidad, precio_entrada):
    tp_price = precio_entrada * TAKE_PROFIT_PCT
    sl_trigger = precio_entrada * STOP_LOSS_TRIGGER_PCT
    sl_limit = precio_entrada * STOP_LOSS_LIMIT_PCT
    
    try:
        tp_formateado = float(exchange.price_to_precision(simbolo, tp_price))
        sl_trig_formateado = float(exchange.price_to_precision(simbolo, sl_trigger))
        sl_lim_formateado = float(exchange.price_to_precision(simbolo, sl_limit))
        cantidad_formateada = float(exchange.amount_to_precision(simbolo, cantidad))
        
        print(f"[!] ENVIANDO PROTOCOLO OCO -> TP: ${tp_formateado} | SL: ${sl_trig_formateado}")
        
        exchange.create_oco_order(
            symbol=simbolo,
            side='sell',
            amount=cantidad_formateada,
            price=tp_formateado,
            stopPrice=sl_trig_formateado,
            stopLimitPrice=sl_lim_formateado
        )
        print("Protocolo OCO establecido con éxito en Binance.")
        
    except Exception as e:
        print(f"Fallo crítico al colocar OCO: {e}")

def procesar_mercado(simbolo, df, btc_total, btc_free, usdt_free):
    precio_actual = df['close'].iloc[-1]
    ultima_rapida = df['SMA_rapida'].iloc[-1]
    ultima_lenta = df['SMA_lenta'].iloc[-1]
    ultimo_atr = df['ATR_pct'].iloc[-1]
    
    if pd.isna(ultima_lenta): return
    
    # A. ESCENARIO CON ACTIVOS (Gestión de OCO)
    if btc_total > 0.0001:
        if btc_free < 0.0001:
            print(f"Posición Segura | {btc_total:.6f} BTC delegados a red OCO de Binance.")
            return
        else:
            print("Detectado BTC libre sin protección OCO. Estructurando barreras...")
            precio_entrada = recuperar_precio_entrada(simbolo)
            if precio_entrada == 0.0: precio_entrada = precio_actual
            colocar_orden_oco(simbolo, btc_free, precio_entrada)
            return

    # B. ESCENARIO LIQUIDEZ (Filtros de Entrada Estrictos)
    else:
        print(f"Evaluando | Precio: ${precio_actual:.2f} | Gap: {(((ultima_rapida/ultima_lenta)-1)*100):.3f}% | Vol: {ultimo_atr:.3f}%")
        
        # Filtro 1: Volatilidad
        if ultimo_atr < UMBRAL_ATR_PCT:
            return
            
        # Filtro 2: Cruce de Medias
        if ultima_rapida > ultima_lenta:
            
            # Filtro 3: Distancia de Confirmación (Brecha)
            gap_actual_pct = ((ultima_rapida - ultima_lenta) / ultima_lenta) * 100
            
            if gap_actual_pct < DISTANCIA_CRUCE_PCT:
                print(f"-> Cruce sin fuerza suficiente. Brecha de {gap_actual_pct:.3f}% no supera el umbral de {DISTANCIA_CRUCE_PCT}%.")
                return
            
            try:
                tamano_compra = (usdt_free * 0.98) / precio_actual
                print(f"\n[!] CONDICIONES ÓPTIMAS ALCANZADAS. Ejecutando COMPRA de {tamano_compra:.6f} BTC a ${precio_actual:.2f}")
                orden_compra = exchange.create_market_buy_order(simbolo, tamano_compra)
                
                precio_ejecutado = orden_compra.get('average', orden_compra.get('price', precio_actual))
                time.sleep(2)
                balance_post = exchange.fetch_balance()
                btc_adquirido = balance_post[simbolo.split('/')[0]]['free']
                
                colocar_orden_oco(simbolo, btc_adquirido, precio_ejecutado)
                
            except Exception as e:
                print(f"Error en ejecución de compra: {e}")

# ==========================================
# 4. CICLO PRINCIPAL (DAEMON)
# ==========================================
def bot_daemon():
    simbolo = 'BTC/USDT'
    moneda_base = simbolo.split('/')[0]
    moneda_cotiz = simbolo.split('/')[1]
    
    print("=== INICIANDO BOT ALGORÍTMICO V4 (FILTROS CUANTITATIVOS) ===")
    
    while True:
        try:
            print(f"\n[{pd.Timestamp.now().strftime('%H:%M:%S')}] Escaneando mercado...")
            
            balance_raw = exchange.fetch_balance()
            btc_total = balance_raw[moneda_base]['total']
            btc_free = balance_raw[moneda_base]['free']
            usdt_free = balance_raw[moneda_cotiz]['free']
            
            df = obtener_datos(simbolo, '1m', 5000)
            df = calcular_indicadores(df)
            
            procesar_mercado(simbolo, df, btc_total, btc_free, usdt_free)
            
            del df
            gc.collect()
            
            time.sleep(60)
            
        except KeyboardInterrupt:
            print("\nEjecución detenida manualmente.")
            break
        except ccxt.NetworkError:
            print("Error de red. Se reintentará en el próximo ciclo.")
            time.sleep(60)
        except Exception as e:
            print(f"\nFallo general: {e}")
            time.sleep(60)

if __name__ == "__main__":
    bot_daemon()