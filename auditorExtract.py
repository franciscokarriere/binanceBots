import ccxt
import pandas as pd
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

# Cuenta principal (BTC/USDT)
exchange_principal = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# Subcuenta Bot2 (BTC/FDUSD)
exchange_bot2 = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY_BOT2') or os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY_BOT2') or os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

ARCHIVO_TRADES    = 'registro_trades.csv'
ARCHIVO_SNAPSHOTS = 'registro_snapshots.csv'

def extraer_trades(exchange, simbolo, cuenta, limite=10):
    moneda_cotiz = simbolo.split('/')[1]
    try:
        trades = exchange.fetch_my_trades(simbolo, limit=limite)
        filas = []
        for t in trades:
            total_usd = t['cost'] if moneda_cotiz in ('USDT', 'FDUSD') else 0.0
            filas.append({
                'trade_id'       : t['id'],
                'cuenta'         : cuenta,
                'simbolo'        : simbolo,
                'fecha_trade'    : t['datetime'],
                'accion'         : t['side'].upper(),
                'precio'         : t['price'],
                'cantidad_btc'   : t['amount'],
                'total_cotiz'    : t['cost'],
                'moneda_cotiz'   : moneda_cotiz,
                'total_usd_aprox': round(total_usd, 4),
                'fee_costo'      : t['fee']['cost'] if t.get('fee') else 0,
                'fee_moneda'     : t['fee']['currency'] if t.get('fee') else '',
            })
        return filas
    except Exception as e:
        print(f"  Error extrayendo trades de {cuenta} ({simbolo}): {e}")
        return []

def guardar_trades(filas_nuevas, ts_extraccion):
    if not filas_nuevas:
        return 0

    df_nuevo = pd.DataFrame(filas_nuevas)
    df_nuevo.insert(0, 'ts_extraccion', ts_extraccion)

    if os.path.exists(ARCHIVO_TRADES):
        df_existente = pd.read_csv(ARCHIVO_TRADES, dtype={'trade_id': str})
        ids_existentes = set(df_existente['trade_id'].astype(str))
        df_nuevo = df_nuevo[~df_nuevo['trade_id'].astype(str).isin(ids_existentes)]
        if df_nuevo.empty:
            return 0
        df_nuevo.to_csv(ARCHIVO_TRADES, mode='a', header=False, index=False)
    else:
        df_nuevo.to_csv(ARCHIVO_TRADES, index=False)

    return len(df_nuevo)

def guardar_snapshot(ts_extraccion):
    try:
        ticker      = exchange_principal.fetch_ticker('BTC/USDT')
        precio_btc  = ticker['last']

        bal_p   = exchange_principal.fetch_balance()
        btc_p   = bal_p.get('BTC',  {}).get('total', 0.0)
        usdt_p  = bal_p.get('USDT', {}).get('total', 0.0)
        valor_p = round(btc_p * precio_btc + usdt_p, 4)

        bal_s    = exchange_bot2.fetch_balance()
        btc_s    = bal_s.get('BTC',   {}).get('total', 0.0)
        fdusd_s  = bal_s.get('FDUSD', {}).get('total', 0.0)
        valor_s  = round(btc_s * precio_btc + fdusd_s, 4)

        fila = {
            'ts_extraccion'     : ts_extraccion,
            'precio_btc_usd'    : precio_btc,
            'principal_btc'     : btc_p,
            'principal_usdt'    : usdt_p,
            'principal_valor_usd': valor_p,
            'bot2_btc'          : btc_s,
            'bot2_fdusd'        : fdusd_s,
            'bot2_valor_usd'    : valor_s,
            'total_usd'         : round(valor_p + valor_s, 4),
        }

        df_snap = pd.DataFrame([fila])
        if os.path.exists(ARCHIVO_SNAPSHOTS):
            df_snap.to_csv(ARCHIVO_SNAPSHOTS, mode='a', header=False, index=False)
        else:
            df_snap.to_csv(ARCHIVO_SNAPSHOTS, index=False)

        return fila

    except Exception as e:
        print(f"  Error generando snapshot: {e}")
        return None

def imprimir_resumen(trades_p, trades_s, snap, nuevos_p, nuevos_s):
    print(f"\n{'='*55}")
    print(f"  EXTRACCIÓN COMPLETADA — {snap['ts_extraccion']}")
    print(f"{'='*55}")
    print(f"  Trades nuevos guardados:")
    print(f"    Cuenta principal (BTC/USDT): {nuevos_p}")
    print(f"    Subcuenta Bot2  (BTC/FDUSD): {nuevos_s}")
    print(f"\n  Snapshot de portafolio:")
    print(f"    BTC precio:      ${snap['precio_btc_usd']:,.2f} USD")
    print(f"    Principal:       ${snap['principal_valor_usd']:,.4f} USD")
    print(f"    Subcuenta Bot2:  ${snap['bot2_valor_usd']:,.4f} USD")
    print(f"    ─────────────────────────────────")
    print(f"    TOTAL:           ${snap['total_usd']:,.4f} USD")
    print(f"\n  Archivos actualizados:")
    print(f"    → {ARCHIVO_TRADES}")
    print(f"    → {ARCHIVO_SNAPSHOTS}")

    # Evolución histórica del total si hay datos anteriores
    if os.path.exists(ARCHIVO_SNAPSHOTS):
        df_hist = pd.read_csv(ARCHIVO_SNAPSHOTS)
        if len(df_hist) > 1:
            primer_total = df_hist['total_usd'].iloc[0]
            ultimo_total = df_hist['total_usd'].iloc[-1]
            diff = ultimo_total - primer_total
            diff_pct = (diff / primer_total) * 100 if primer_total > 0 else 0
            signo = '+' if diff >= 0 else ''
            print(f"\n  Evolución histórica:")
            print(f"    Primera extracción: ${primer_total:,.4f} USD")
            print(f"    Última extracción:  ${ultimo_total:,.4f} USD")
            print(f"    Variación total:    {signo}{diff:,.4f} USD  ({signo}{diff_pct:.2f}%)")

    print(f"{'='*55}\n")

if __name__ == "__main__":
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f"\nExtrayendo datos al {ts}...")

    trades_p  = extraer_trades(exchange_principal, 'BTC/USDT',  'principal')
    trades_s  = extraer_trades(exchange_bot2,      'BTC/FDUSD', 'bot2')

    nuevos_p  = guardar_trades(trades_p, ts)
    nuevos_s  = guardar_trades(trades_s, ts)
    snap      = guardar_snapshot(ts)

    if snap:
        imprimir_resumen(trades_p, trades_s, snap, nuevos_p, nuevos_s)
