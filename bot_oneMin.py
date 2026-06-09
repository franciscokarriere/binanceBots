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

# Cargar mercados una vez para garantizar precisión decimal
exchange.load_markets()

# Parámetros de Gestión de Riesgo (Escenario Híbrido)
TAKE_PROFIT_PCT = 1.0175        # +1.75%
STOP_LOSS_TRIGGER_PCT = 0.9940  # -0.60% (Precio que dispara la emergencia)
STOP_LOSS_LIMIT_PCT = 0.9930    # -0.70% (Precio de venta asegurado tras el disparo)
UMBRAL_ATR_PCT = 0.03           # Filtro mínimo de volatilidad

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
    """ Failsafe: Busca el precio de la última compra. """
    try:
        trades = exchange.fetch_my_trades(simbolo, limit=20)
        compras = [t for t in trades if t['side'] == 'buy']
        if compras:
            return compras[-1]['price']
    except Exception as e:
        print(f"Error recuperando historial: {e}")
    return 0.0

def colocar_orden_oco(simbolo, cantidad, precio_entrada):
    """ Estructura y envía el protocolo OCO a Binance. """
    tp_price = precio_entrada * TAKE_PROFIT_PCT
    sl_trigger = precio_entrada * STOP_LOSS_TRIGGER_PCT
    sl_limit = precio_entrada * STOP_LOSS_LIMIT_PCT
    
    try:
        # Formatear a la precisión estricta exigida por la API de Binance
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
    
    # A. ESCENARIO CON ACTIVOS (Gestión de OCO)
    if btc_total > 0.0001:
        # Si el BTC está bloqueado (no libre), Binance tiene el OCO activo. Todo en orden.
        if btc_free < 0.0001:
            print(f"Posición Segura | {btc_total:.6f} BTC delegados a red OCO de Binance. Esperando ruptura de límites...")
            return
            
        # Si tenemos BTC libre, falta el escudo OCO (Failsafe)
        else:
            print("Detectado BTC libre sin protección OCO. Estructurando barreras...")
            precio_entrada = recuperar_precio_entrada(simbolo)
            if precio_entrada == 0.0: 
                precio_entrada = precio_actual
            colocar_orden_oco(simbolo, btc_free, precio_entrada)
            return

    # B. ESCENARIO LIQUIDEZ (Buscando Entrada)
    else:
        print(f"Buscando Entrada | Precio: ${precio_actual:.2f} | SMA50: ${ultima_rapida:.2f} | SMA5000: ${ultima_lenta:.2f} | Volatilidad: {ultimo_atr:.3f}%")
        
        if pd.isna(ultima_lenta): return
        if ultimo_atr < UMBRAL_ATR_PCT:
            print("-> Mercado sin fuerza (ATR bajo). Operación bloqueada.")
            return
            
        if ultima_rapida > ultima_lenta:
            try:
                tamano_compra = (usdt_free * 0.98) / precio_actual
                print(f"\\n[!] GOLDEN CROSS DETECTADO. Ejecutando COMPRA de {tamano_compra:.6f} BTC a ${precio_actual:.2f}")
                orden_compra = exchange.create_market_buy_order(simbolo, tamano_compra)
                
                # Extraer precio real de ejecución para cálculos precisos
                precio_ejecutado = orden_compra.get('average', orden_compra.get('price', precio_actual))
                
                # Pausa estructural de 2 segundos para permitir a los nodos de Binance actualizar saldos
                time.sleep(2)
                balance_post = exchange.fetch_balance()
                btc_adquirido = balance_post[simbolo.split('/')[0]]['free']
                
                # Desplegar escudo OCO inmediatamente
                colocar_orden_oco(simbolo, btc_adquirido, precio_ejecutado)
                
            except Exception as e:
                print(f"Error en bloque de entrada: {e}")

# ==========================================
# 4. CICLO PRINCIPAL (DAEMON)
# ==========================================
def bot_daemon():
    simbolo = 'BTC/USDT'
    moneda_base = simbolo.split('/')[0]
    moneda_cotiz = simbolo.split('/')[1]
    
    print("=== INICIANDO BOT ALGORÍTMICO V3 (INFRAESTRUCTURA OCO) ===")
    
    while True:
        try:
            print(f"\\n[{pd.Timestamp.now().strftime('%H:%M:%S')}] Evaluando...")
            
            # Obtener saldos crudos de la API
            balance_raw = exchange.fetch_balance()
            btc_total = balance_raw[moneda_base]['total']
            btc_free = balance_raw[moneda_base]['free']
            usdt_free = balance_raw[moneda_cotiz]['free']
            
            # Procesamiento de Mercado
            df = obtener_datos(simbolo, '1m', 5000)
            df = calcular_indicadores(df)
            
            procesar_mercado(simbolo, df, btc_total, btc_free, usdt_free)
            
            # Limpieza exhaustiva
            del df
            gc.collect()
            
            time.sleep(60)
            
        except KeyboardInterrupt:
            print("\\nEjecución detenida manualmente.")
            break
        except ccxt.NetworkError:
            print("Error de red con Binance. Se reintentará en el próximo ciclo.")
            time.sleep(60)
        except Exception as e:
            print(f"\\nFallo general en el ciclo: {e}")
            time.sleep(60)

if __name__ == "__main__":
    bot_daemon()