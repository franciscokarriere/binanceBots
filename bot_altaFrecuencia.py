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

# Credenciales propias del Bot 2 (subcuenta aislada). Si no están definidas,
# usa las generales para no romper entornos sin subcuenta configurada.
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY_BOT2') or os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY_BOT2') or os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
    }
})

exchange.load_markets()

# Par aislado del Bot 1 (BTC/USDT) para evitar colisiones de liquidez
SIMBOLO = 'BTC/FDUSD'
ARCHIVO_CACHE = 'historico_velas_fdusd.csv'

# Protocolo OCO asimétrico (calibrado por backtesting multi-ventana)
TAKE_PROFIT_PCT = 1.0070        # +0.70% (objetivo principal de salida)
STOP_LOSS_TRIGGER_PCT = 0.9900  # -1.00% (barrera de catástrofe, rara vez tocada)
STOP_LOSS_LIMIT_PCT = 0.9895    # -1.05%

# Venta anticipada: la posición se liquida a mercado ANTES de alcanzar el
# umbral de pérdida si el TP no se materializa dentro de la ventana del scalp
TIME_STOP_MINUTOS = 360         # 6 horas

# Filtros de entrada (Reversión a la Media)
DIP_ENTRADA_PCT = 0.60          # Caída mínima del precio bajo la EMA21
RSI_MAXIMO = 40                 # Sobreventa de corto plazo confirmada
PENDIENTE_EMA200_VELAS = 60     # La EMA200 debe ser ascendente vs hace 60 velas

VELAS_CACHE = 1500              # Ventana ligera para t3.micro
MIN_NOTIONAL_FDUSD = 5.0        # Mínimo operable del par en Binance
CICLO_SEGUNDOS = 15             # Frecuencia de escaneo (alta frecuencia)

# ==========================================
# 2. OBTENCIÓN DE DATOS (CACHÉ LOCAL DELTA)
# ==========================================
def obtener_datos(simbolo=SIMBOLO, timeframe='1m', limit=VELAS_CACHE):
    if os.path.exists(ARCHIVO_CACHE):
        df = pd.read_csv(ARCHIVO_CACHE)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        ultimo_ms = int(df['timestamp'].iloc[-1].timestamp() * 1000)

        velas_nuevas = exchange.fetch_ohlcv(simbolo, timeframe, since=ultimo_ms, limit=1000)

        if velas_nuevas:
            df_nuevo = pd.DataFrame(velas_nuevas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_nuevo['timestamp'] = pd.to_datetime(df_nuevo['timestamp'], unit='ms')
            df = pd.concat([df, df_nuevo]).drop_duplicates(subset=['timestamp'])
            df = df.tail(limit)
            del df_nuevo
    else:
        print(f"Caché no encontrado. Descargando bloque de {limit} velas de {simbolo}...")
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

    df.to_csv(ARCHIVO_CACHE, index=False)
    return df

# ==========================================
# 3. MOTOR ALGORÍTMICO (REVERSIÓN A LA MEDIA)
# ==========================================
def calcular_indicadores(df, ema_media=21, ema_macro=200, periodo_rsi=14):
    df['EMA21'] = df['close'].ewm(span=ema_media, adjust=False).mean()
    df['EMA200'] = df['close'].ewm(span=ema_macro, adjust=False).mean()

    delta = df['close'].diff()
    ganancia = delta.clip(lower=0).ewm(alpha=1 / periodo_rsi, adjust=False).mean()
    perdida = (-delta.clip(upper=0)).ewm(alpha=1 / periodo_rsi, adjust=False).mean()
    rs = ganancia / perdida.replace(0, 1e-10)
    df['RSI'] = 100 - (100 / (1 + rs))

    return df

def hay_senal_compra(df):
    """Dip >= 0.6% bajo la EMA21 + RSI <= 40 + tendencia macro (EMA200) ascendente."""
    if len(df) < PENDIENTE_EMA200_VELAS + 201:
        return False

    precio = df['close'].iloc[-1]
    ema21 = df['EMA21'].iloc[-1]
    ema200_actual = df['EMA200'].iloc[-1]
    ema200_previa = df['EMA200'].iloc[-(PENDIENTE_EMA200_VELAS + 1)]
    rsi = df['RSI'].iloc[-1]

    if pd.isna(ema21) or pd.isna(rsi) or pd.isna(ema200_previa):
        return False

    dip_pct = (ema21 - precio) / ema21 * 100

    dip_ok = dip_pct >= DIP_ENTRADA_PCT
    sobreventa_ok = rsi <= RSI_MAXIMO
    tendencia_ok = ema200_actual > ema200_previa

    return dip_ok and sobreventa_ok and tendencia_ok

def recuperar_entrada(simbolo):
    """Devuelve (precio, timestamp_ms) de la última compra registrada en Binance.

    Si el BTC no se adquirió en este par (p. ej. llegó comprado vía BTC/USDT o
    manualmente), reconstruye la entrada desde la pata TP del OCO vigente:
    precio_entrada = abovePrice / TAKE_PROFIT_PCT. El timestamp de esa orden
    mantiene operativo el time-stop."""
    try:
        trades = exchange.fetch_my_trades(simbolo, limit=20)
        compras = [t for t in trades if t['side'] == 'buy']
        if compras:
            return compras[-1]['price'], compras[-1]['timestamp']

        for orden in exchange.fetch_open_orders(simbolo):
            es_tp = orden['side'] == 'sell' and not orden.get('stopPrice') and orden.get('price')
            if es_tp:
                return float(orden['price']) / TAKE_PROFIT_PCT, orden.get('timestamp') or 0
    except Exception as e:
        print(f"Error recuperando historial: {e}")
    return 0.0, 0

def colocar_orden_oco(simbolo, cantidad, precio_entrada):
    # Strings con la precisión exacta del par (la API REST exige decimales válidos)
    tp = exchange.price_to_precision(simbolo, precio_entrada * TAKE_PROFIT_PCT)
    sl_trig = exchange.price_to_precision(simbolo, precio_entrada * STOP_LOSS_TRIGGER_PCT)
    sl_lim = exchange.price_to_precision(simbolo, precio_entrada * STOP_LOSS_LIMIT_PCT)
    qty = exchange.amount_to_precision(simbolo, cantidad)

    print(f"[!] ENVIANDO PROTOCOLO OCO -> TP: ${tp} | SL: ${sl_trig}")

    try:
        if hasattr(exchange, 'create_oco_order'):
            # ccxt legado (< 4.x): método unificado
            exchange.create_oco_order(
                symbol=simbolo,
                side='sell',
                amount=float(qty),
                price=float(tp),
                stopPrice=float(sl_trig),
                stopLimitPrice=float(sl_lim)
            )
        else:
            # ccxt moderno: endpoint implícito POST /api/v3/orderList/oco
            # Venta OCO: pata superior = TP (LIMIT_MAKER), pata inferior = Stop-Limit
            exchange.privatePostOrderListOco({
                'symbol': exchange.market_id(simbolo),
                'side': 'SELL',
                'quantity': qty,
                'aboveType': 'LIMIT_MAKER',
                'abovePrice': tp,
                'belowType': 'STOP_LOSS_LIMIT',
                'belowStopPrice': sl_trig,
                'belowPrice': sl_lim,
                'belowTimeInForce': 'GTC',
            })
        print("Protocolo OCO establecido con éxito en Binance.")

    except Exception as e:
        print(f"Fallo crítico al colocar OCO: {e}")

def venta_anticipada(simbolo):
    """Cancela el OCO y liquida a mercado ANTES de cruzar el umbral de pérdida.

    Se activa cuando el TP no se materializó dentro de la ventana del scalp
    (TIME_STOP_MINUTOS). Libera el capital con una pérdida/ganancia marginal
    en lugar de esperar a que el precio deteriore hasta el Stop Loss."""
    try:
        print(f"[!] VENTA ANTICIPADA: el TP no se alcanzó en {TIME_STOP_MINUTOS} min. Liquidando a mercado...")
        exchange.cancel_all_orders(simbolo)
        time.sleep(2)

        balance = exchange.fetch_balance()
        btc_free = balance[simbolo.split('/')[0]]['free']
        cantidad = float(exchange.amount_to_precision(simbolo, btc_free))

        if cantidad > 0:
            exchange.create_market_sell_order(simbolo, cantidad)
            print("Posición liquidada. Capital liberado para el siguiente dip.")
        del balance
    except Exception as e:
        print(f"Fallo en venta anticipada: {e}")

def procesar_mercado(simbolo, df, btc_total, btc_free, fdusd_free):
    precio_actual = df['close'].iloc[-1]

    # A. ESCENARIO CON ACTIVOS (Gestión de OCO + Time-Stop)
    if btc_total * precio_actual > MIN_NOTIONAL_FDUSD:
        precio_entrada, ts_entrada_ms = recuperar_entrada(simbolo)

        # Venta anticipada: salir a mercado antes de deteriorar hasta el SL
        minutos_en_posicion = (exchange.milliseconds() - ts_entrada_ms) / 60000 if ts_entrada_ms > 0 else 0.0
        if ts_entrada_ms > 0 and minutos_en_posicion >= TIME_STOP_MINUTOS:
            venta_anticipada(simbolo)
            return

        if btc_free * precio_actual < MIN_NOTIONAL_FDUSD:
            valor_fdusd = btc_total * precio_actual
            if precio_entrada:
                pnl_pct = ((precio_actual / precio_entrada) - 1) * 100
                tp = precio_entrada * TAKE_PROFIT_PCT
                sl = precio_entrada * STOP_LOSS_TRIGGER_PCT
                dist_tp_pct = ((tp / precio_actual) - 1) * 100
                print(f"Posición Segura | {btc_total:.6f} BTC (~{valor_fdusd:.2f} FDUSD) en red OCO | "
                      f"Px: ${precio_actual:,.2f} | PnL: {pnl_pct:+.2f}% | "
                      f"TP: ${tp:,.2f} (faltan {dist_tp_pct:+.2f}%) | SL: ${sl:,.2f} | "
                      f"T-Stop: {minutos_en_posicion:.0f}/{TIME_STOP_MINUTOS} min")
            else:
                print(f"Posición Segura | {btc_total:.6f} BTC (~{valor_fdusd:.2f} FDUSD) en red OCO | "
                      f"Px: ${precio_actual:,.2f} | PnL: n/d (entrada no recuperada del historial)")
            return
        else:
            print("Detectado BTC libre sin protección OCO. Estructurando barreras...")
            if precio_entrada == 0.0: precio_entrada = precio_actual
            colocar_orden_oco(simbolo, btc_free, precio_entrada)
            return

    # B. ESCENARIO LIQUIDEZ (Caza de dips en tendencia alcista)
    if len(df) < PENDIENTE_EMA200_VELAS + 201:
        print("Calentando indicadores: historial insuficiente todavía...")
        return

    ema21 = df['EMA21'].iloc[-1]
    rsi = df['RSI'].iloc[-1]
    dip_pct = (ema21 - precio_actual) / ema21 * 100 if not pd.isna(ema21) else 0.0
    ema200_ok = df['EMA200'].iloc[-1] > df['EMA200'].iloc[-(PENDIENTE_EMA200_VELAS + 1)]
    fase = "ALCISTA" if ema200_ok else "BAJISTA"
    estado = "[ARMADO]" if fase == "ALCISTA" else "[BLOQUEADO]"

    print(f"Dashboard HF | FDUSD: {fdusd_free:.2f} | Px: ${precio_actual:,.2f} | Macro: {fase} {estado} | "
          f"Dip: {dip_pct:+.3f}% (req >{DIP_ENTRADA_PCT}%) | RSI: {rsi:.1f} (req <{RSI_MAXIMO})")

    if fdusd_free < MIN_NOTIONAL_FDUSD:
        return

    if hay_senal_compra(df):
        try:
            tamano_compra = (fdusd_free * 0.98) / precio_actual
            print(f"\n[!] DIP CAPITULADO EN TENDENCIA ALCISTA. COMPRA de {tamano_compra:.6f} BTC a ${precio_actual:.2f}")
            orden_compra = exchange.create_market_buy_order(simbolo, tamano_compra)

            precio_ejecutado = orden_compra.get('average', orden_compra.get('price', precio_actual))
            time.sleep(2)
            balance_post = exchange.fetch_balance()
            btc_adquirido = balance_post[simbolo.split('/')[0]]['free']

            colocar_orden_oco(simbolo, btc_adquirido, precio_ejecutado)

        except Exception as e:
            print(f"Error en ejecución de compra: {e}")

# ==========================================
# 4. CICLO PRINCIPAL (DAEMON ALTA FRECUENCIA)
# ==========================================
def bot_daemon():
    moneda_base = SIMBOLO.split('/')[0]
    moneda_cotiz = SIMBOLO.split('/')[1]

    print("=== INICIANDO BOT 2 V2 (REVERSIÓN A LA MEDIA BTC/FDUSD) ===")

    while True:
        try:
            print(f"\n[{pd.Timestamp.now().strftime('%H:%M:%S')}] Escaneando micro-mercado...")

            balance_raw = exchange.fetch_balance()
            btc_total = balance_raw[moneda_base]['total']
            btc_free = balance_raw[moneda_base]['free']
            fdusd_free = balance_raw.get(moneda_cotiz, {}).get('free', 0.0)

            df = obtener_datos(SIMBOLO, '1m', VELAS_CACHE)
            df = calcular_indicadores(df)

            procesar_mercado(SIMBOLO, df, btc_total, btc_free, fdusd_free)

            del df
            del balance_raw
            gc.collect()

            time.sleep(CICLO_SEGUNDOS)

        except KeyboardInterrupt:
            print("\nEjecución detenida manualmente.")
            break
        except ccxt.NetworkError:
            print("Error de red. Se reintentará en el próximo ciclo.")
            time.sleep(CICLO_SEGUNDOS)
        except Exception as e:
            print(f"\nFallo general: {e}")
            time.sleep(CICLO_SEGUNDOS)

if __name__ == "__main__":
    bot_daemon()
