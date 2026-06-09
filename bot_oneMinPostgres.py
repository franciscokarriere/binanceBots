import ccxt
import pandas as pd
import time
import os
import gc
import logging
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

# ==========================================
# CONFIGURACIÓN DEL SISTEMA DE LOGS SEGMENTADO
# ==========================================
def configurar_logger(nombre, archivo, nivel=logging.INFO):
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler = logging.FileHandler(archivo, mode='a', encoding='utf-8')
    handler.setFormatter(formatter)
    
    logger = logging.getLogger(nombre)
    logger.setLevel(nivel)
    logger.addHandler(handler)
    return logger

# Inicializar los tres canales independientes solicitados
log_monitoreo = configurar_logger('Monitoreo', 'MensajesDeMonitoreo.log')
log_operacion = configurar_logger('Operacion', 'MensajesDeOperacion.log')
log_transaccion = configurar_logger('Transaccion', 'MensajesDeTransaccion.log')

# Conexión a PostgreSQL (Asegura tener las variables en tu .env)
# Ejemplo: DB_URL=postgresql://usuario:password@localhost:5432/tu_base_datos
DB_URL=postgresql://postgres:cuchuMan1984@localhost:5432/postgres
db_engine = create_engine(os.getenv('DB_URL'))

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
        'adjustForTimeDifference': True,
    }
})

def obtener_datos_postgres(simbolo='BTC/USDT', timeframe='1m', limit=5000):
    """
    Gestiona el historial en PostgreSQL. Solo descarga el delta (últimas velas)
    y extrae estrictamente las 5000 necesarias para el cálculo de las medias.
    """
    try:
        # 1. Averiguar la fecha de la última vela almacenada en la DB
        with db_engine.connect() as conn:
            resultado = conn.execute(text("SELECT MAX(timestamp) FROM historico_velas")).fetchone()
            ultima_fecha = resultado[0]

        if ultima_fecha is not None:
            # Convertir a milisegundos para la API de Binance
            ultimo_ms = int(pd.Timestamp(ultima_fecha).timestamp() * 1000)
            log_monitoreo.info(f"Sincronizando delta desde el último registro en DB: {ultima_fecha}")
            velas_nuevas = exchange.fetch_ohlcv(simbolo, timeframe, since=ultimo_ms, limit=1000)
        else:
            # Si la tabla está vacía, descarga inicial pesada
            log_monitoreo.warning("Tabla vacía. Descargando bloque histórico inicial...")
            desde_ms = exchange.milliseconds() - (limit * 60 * 1000)
            velas_nuevas = []
            while len(velas_nuevas) < limit:
                velas = exchange.fetch_ohlcv(simbolo, timeframe, since=desde_ms, limit=1000)
                if not velas:
                    break
                desde_ms = velas[-1][0] + 1
                velas_nuevas.extend(velas)
                time.sleep(0.1)

        # 2. Insertar solo los registros nuevos/actualizados (Upsert condicional)
        if velas_nuevas:
            df_nuevas = pd.DataFrame(velas_nuevas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_nuevas['timestamp'] = pd.to_datetime(df_nuevas['timestamp'], unit='ms')
            
            # Guardar en tablas temporales o usar inserción directa con control de duplicados
            # Para simplificar de manera eficiente sin saturar conexiones:
            for _, fila in df_nuevas.iterrows():
                query = text("""
                    INSERT INTO historico_velas (timestamp, open, high, low, close, volume)
                    VALUES (:ts, :op, :hi, :lo, :cl, :vo)
                    ON CONFLICT (timestamp) DO UPDATE 
                    SET open = EXCLUDED.open, high = EXCLUDED.high, 
                        low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume;
                """)
                with db_engine.connect() as conn:
                    conn.execute(query, {
                        'ts': fila['timestamp'], 'op': fila['open'], 'hi': fila['high'],
                        'lo': fila['low'], 'cl': fila['close'], 'vo': fila['volume']
                    })
                    conn.commit()
            log_monitoreo.info(f"Se procesaron e insertaron {len(df_nuevas)} registros de velas.")

        # 3. Extraer estrictamente las últimas 5000 velas indexadas para el cálculo matemático
        query_fetch = text("""
            SELECT timestamp, open, high, low, close, volume 
            FROM historico_velas 
            ORDER BY timestamp DESC 
            LIMIT :limite
        """)
        with db_engine.connect() as conn:
            df_resultado = pd.read_sql(query_fetch, conn, params={'limite': limit})
        
        # El bot necesita el orden cronológico ascendente para calcular las medias móviles de forma correcta
        df_resultado = df_resultado.iloc[::-1].reset_index(drop=True)
        return df_resultado

    except Exception as e:
        log_monitoreo.error(f"Fallo en el módulo de datos/PostgreSQL: {str(e)}")
        raise e

def calcular_senal(df, sma_rapida_window=50, sma_lenta_window=5000):
    df['SMA_rapida'] = df['close'].rolling(window=sma_rapida_window).mean()
    df['SMA_lenta'] = df['close'].rolling(window=sma_lenta_window).mean()
    
    ultima_rapida = df['SMA_rapida'].iloc[-1]
    ultima_lenta = df['SMA_lenta'].iloc[-1]
    precio_cierre = df['close'].iloc[-1]
    
    if pd.isna(ultima_lenta) or pd.isna(ultima_rapida):
        log_operacion.info("Estrategia en espera: Ventana de datos (5000) insuficiente para calcular SMA_lenta.")
        return "MANTENER"
        
    log_operacion.info(f"Métricas calculadas -> Precio: {precio_cierre:.2f} | SMA 50: {ultima_rapida:.2f} | SMA 5000: {ultima_lenta:.2f}")
    
    if ultima_rapida > ultima_lenta:
        return "COMPRAR"
    elif ultima_rapida < ultima_lenta:
        return "VENDER"
    return "MANTENER"

def ejecutar_orden(simbolo, senal):
    try:
        moneda_base = simbolo.split('/')[0]
        moneda_cotiz = simbolo.split('/')[1]
        
        balances = exchange.fetch_balance()
        balance_base = balances[moneda_base]['free']
        balance_usdt = balances[moneda_cotiz]['free']
        
        en_posicion = balance_base > 0.0001 

        if senal == "COMPRAR" and not en_posicion:
            precio_actual = exchange.fetch_ticker(simbolo)['last']
            tamano_compra = (balance_usdt * 0.98) / precio_actual
            
            log_transaccion.warning(f"EJECUTANDO ORDEN COMPRA SPOT -> Cantidad: {tamano_compra:.6f} {moneda_base} a precio aprx: {precio_actual}")
            orden = exchange.create_market_buy_order(simbolo, tamano_compra)
            log_transaccion.info(f"Confirmación de Orden de Compra Exitosa ID: {orden.get('id')}")
            return orden

        elif senal == "VENDER" and en_posicion:
            log_transaccion.warning(f"EJECUTANDO ORDEN VENTA SPOT -> Liquidando total de posición: {balance_base:.6f} {moneda_base}")
            orden = exchange.create_market_sell_order(simbolo, balance_base)
            log_transaccion.info(f"Confirmación de Orden de Venta Exitosa ID: {orden.get('id')}")
            return orden
        
        else:
            estado = "DENTRO DEL MERCADO (Largo)" if en_posicion else "FUERA DEL MERCADO (Liquidez USDT)"
            log_operacion.info(f"Evaluación de ciclo completa. Señal: {senal} | Estado: {estado} | Portafolio: {balance_usdt:.2f} USDT / {balance_base:.6f} BTC")
            return None
            
    except ccxt.InsufficientFunds:
        log_transaccion.error("Transacción rechazada: Fondos insuficientes en la cuenta de Binance para cumplir con el mínimo requerido.")
    except Exception as e:
        log_transaccion.error(f"Error crítico en la ejecución de órdenes de mercado: {str(e)}")
    return None

def bot_daemon():
    simbolo = 'BTC/USDT'
    log_monitoreo.info("=== INICIANDO DAEMON DE MONITOREO EN VIVO (ENTORNO SEGURO) ===")
    
    while True:
        try:
            log_monitoreo.info("Ciclo de monitoreo iniciado. Consultando mercado...")
            df = obtener_datos_postgres(simbolo, '1m', 5000)
            senal = calcular_senal(df)
            ejecutar_orden(simbolo, senal)
            
            del df
            gc.collect()
            time.sleep(60)
            
        except KeyboardInterrupt:
            log_monitoreo.warning("Interrupción manual detectada (Ctrl+C). Apagando daemon.")
            break
        except Exception as e:
            log_monitoreo.critical(f"Fallo sistémico general detectado en el loop principal: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    bot_daemon()