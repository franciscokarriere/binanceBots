import ccxt
import gc
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

# Cantidad de trades a consultar por cuenta. 20 cubre ~10 ciclos completos.
# Valor conservador para no causar OOM en t3.micro (1GB RAM, dos bots ya activos).
LIMITE_TRADES = 20

# Parámetros activos de cada bot — actualizar aquí al cambiar el código del bot.
# Se imprimen en cada snapshot para mantener trazabilidad en el log.
PARAMS_BOT1 = {'TP': '+1.75%', 'SL': '-0.60%', 'ciclo': '60s'}
PARAMS_BOT2 = {'TP': '+0.70%', 'SL': '-0.50%', 'time_stop': '360min', 'ciclo': '15s'}


def extraer_trades(exchange, simbolo, cuenta, limite=LIMITE_TRADES):
    """
    Qué hace: descarga los últimos trades de un par y los formatea para CSV.
    Recibe:
        exchange: instancia ccxt autenticada.
        simbolo (str): par operado (ej. 'BTC/USDT').
        cuenta (str): etiqueta de la cuenta ('principal' | 'bot2').
        limite (int): cantidad de trades a consultar.
    Entrega:
        (list[dict], list[dict]): filas formateadas para CSV y trades raw de la API.
        Devuelve ([], []) si falla la consulta.
    """
    moneda_cotiz = simbolo.split('/')[1]
    try:
        trades_raw = exchange.fetch_my_trades(simbolo, limit=limite)
        filas = []
        for t in trades_raw:
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
        return filas, trades_raw
    except Exception as e:
        print(f"  Error extrayendo trades de {cuenta} ({simbolo}): {e}")
        return [], []


def calcular_pnl_ciclos(trades_raw):
    """
    Qué hace: empareja trades BUY->SELL cronológicamente y calcula P&L bruto por ciclo.
    Recibe:
        trades_raw (list): trades de la API ccxt (dicts con side, price, datetime, timestamp).
    Entrega:
        list[dict] con: fecha_cierre, compra_px, venta_px, delta_pct, neto_pct, resultado.
        neto_pct descuenta el costo round-trip estimado de Binance (0.20% = 0.10% x 2 legs).
        Solo ciclos completos (BUY seguido de SELL). Posición abierta sin cerrar: no se cuenta.
    """
    ciclos = []
    pendiente = None
    for t in sorted(trades_raw, key=lambda x: x['timestamp']):
        if t['side'] == 'buy':
            pendiente = t
        elif t['side'] == 'sell' and pendiente is not None:
            compra_px = pendiente['price']
            venta_px  = t['price']
            delta_pct = (venta_px / compra_px - 1) * 100
            neto_pct  = delta_pct - 0.20  # descuenta comisión round-trip estándar Binance
            ciclos.append({
                'fecha_cierre': t['datetime'][:16],
                'compra_px'   : compra_px,
                'venta_px'    : venta_px,
                'delta_pct'   : delta_pct,
                'neto_pct'    : neto_pct,
                'resultado'   : 'WIN' if delta_pct > 0 else 'LOSS',
            })
            pendiente = None
    return ciclos


def guardar_trades(filas_nuevas, ts_extraccion):
    """
    Qué hace: agrega filas nuevas al CSV acumulativo evitando duplicados por trade_id.
    Recibe:
        filas_nuevas (list[dict]): trades formateados por extraer_trades.
        ts_extraccion (str): timestamp ISO de la extracción actual.
    Entrega:
        (int) cantidad de filas efectivamente guardadas (0 si todas ya existían).
    """
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
    """
    Qué hace: toma un snapshot del portafolio completo (ambas cuentas) y lo guarda en CSV.
    Recibe:
        ts_extraccion (str): timestamp ISO de la extracción.
    Entrega:
        dict con los campos del snapshot, o None si falló la consulta a la API.
    """
    try:
        ticker     = exchange_principal.fetch_ticker('BTC/USDT')
        precio_btc = ticker['last']

        bal_p   = exchange_principal.fetch_balance()
        btc_p   = bal_p.get('BTC',  {}).get('total', 0.0)
        usdt_p  = bal_p.get('USDT', {}).get('total', 0.0)
        valor_p = round(btc_p * precio_btc + usdt_p, 4)
        del bal_p

        bal_s   = exchange_bot2.fetch_balance()
        btc_s   = bal_s.get('BTC',   {}).get('total', 0.0)
        fdusd_s = bal_s.get('FDUSD', {}).get('total', 0.0)
        valor_s = round(btc_s * precio_btc + fdusd_s, 4)
        del bal_s
        gc.collect()

        fila = {
            'ts_extraccion'      : ts_extraccion,
            'precio_btc_usd'     : precio_btc,
            'principal_btc'      : btc_p,
            'principal_usdt'     : usdt_p,
            'principal_valor_usd': valor_p,
            'bot2_btc'           : btc_s,
            'bot2_fdusd'         : fdusd_s,
            'bot2_valor_usd'     : valor_s,
            'total_usd'          : round(valor_p + valor_s, 4),
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


def _imprimir_ciclos(etiqueta, ciclos, params):
    """
    Qué hace: imprime la tabla de ciclos P&L de un bot y su resumen W/L.
    Recibe:
        etiqueta (str): nombre del bot para encabezado.
        ciclos (list[dict]): salida de calcular_pnl_ciclos.
        params (dict): parámetros activos del bot (TP, SL, etc.) para mostrar contexto.
    Entrega:
        None (imprime a stdout).
    """
    tp  = params.get('TP', '?')
    sl  = params.get('SL', '?')
    print(f"\n  Ciclos {etiqueta}  [TP {tp} / SL {sl}]:")
    if not ciclos:
        print(f"    Sin ciclos completos en los ultimos {LIMITE_TRADES} trades.")
        return
    for c in ciclos:
        marca = '[W]' if c['resultado'] == 'WIN' else '[L]'
        print(f"    {marca} {c['fecha_cierre']}  "
              f"${c['compra_px']:,.2f} -> ${c['venta_px']:,.2f}  "
              f"{c['delta_pct']:+.2f}% bruto  ({c['neto_pct']:+.2f}% neto)")
    wins  = sum(1 for c in ciclos if c['resultado'] == 'WIN')
    loses = len(ciclos) - wins
    balance_neto = sum(c['neto_pct'] for c in ciclos)
    estado = 'RENTABLE' if balance_neto > 0 else 'EN PERDIDA'
    print(f"    Resumen: {wins}W / {loses}L  |  neto acumulado: {balance_neto:+.2f}%  [{estado}]")


def imprimir_resumen(snap, nuevos_p, nuevos_s, ciclos_p, ciclos_s):
    """
    Qué hace: imprime el resumen completo de la extracción: ciclos P&L, snapshot y evolución histórica.
    Recibe:
        snap (dict): snapshot de portafolio generado por guardar_snapshot.
        nuevos_p (int): trades nuevos guardados de la cuenta principal.
        nuevos_s (int): trades nuevos guardados de la subcuenta Bot2.
        ciclos_p (list[dict]): ciclos de Bot1 de calcular_pnl_ciclos.
        ciclos_s (list[dict]): ciclos de Bot2 de calcular_pnl_ciclos.
    Entrega:
        None (imprime a stdout).
    """
    print(f"\n{'='*60}")
    print(f"  EXTRACCION COMPLETADA — {snap['ts_extraccion']}")
    print(f"{'='*60}")

    print(f"\n  Trades nuevos guardados:")
    print(f"    Cuenta principal (BTC/USDT): {nuevos_p}")
    print(f"    Subcuenta Bot2  (BTC/FDUSD): {nuevos_s}")

    _imprimir_ciclos('Bot1 BTC/USDT',  ciclos_p, PARAMS_BOT1)
    _imprimir_ciclos('Bot2 BTC/FDUSD', ciclos_s, PARAMS_BOT2)

    print(f"\n  Snapshot de portafolio:")
    print(f"    BTC precio:      ${snap['precio_btc_usd']:,.2f} USD")
    print(f"    Principal:       ${snap['principal_valor_usd']:,.4f} USD"
          f"  [TP {PARAMS_BOT1['TP']} / SL {PARAMS_BOT1['SL']}]")
    print(f"    Subcuenta Bot2:  ${snap['bot2_valor_usd']:,.4f} USD"
          f"  [TP {PARAMS_BOT2['TP']} / SL {PARAMS_BOT2['SL']} / T-Stop {PARAMS_BOT2['time_stop']}]")
    print(f"    {'─'*42}")
    print(f"    TOTAL:           ${snap['total_usd']:,.4f} USD")

    if os.path.exists(ARCHIVO_SNAPSHOTS):
        df_hist = pd.read_csv(ARCHIVO_SNAPSHOTS)
        if len(df_hist) > 1:
            primer_total = df_hist['total_usd'].iloc[0]
            ultimo_total = df_hist['total_usd'].iloc[-1]
            diff     = ultimo_total - primer_total
            diff_pct = (diff / primer_total) * 100 if primer_total > 0 else 0
            signo    = '+' if diff >= 0 else ''
            print(f"\n  Evolucion historica:")
            print(f"    Primera extraccion: ${primer_total:,.4f} USD")
            print(f"    Ultima extraccion:  ${ultimo_total:,.4f} USD")
            print(f"    Variacion total:    {signo}{diff:,.4f} USD  ({signo}{diff_pct:.2f}%)")

    print(f"\n  Archivos actualizados:")
    print(f"    -> {ARCHIVO_TRADES}")
    print(f"    -> {ARCHIVO_SNAPSHOTS}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f"\nExtrayendo datos al {ts}...")

    trades_p, raw_p = extraer_trades(exchange_principal, 'BTC/USDT',  'principal')
    trades_s, raw_s = extraer_trades(exchange_bot2,      'BTC/FDUSD', 'bot2')

    nuevos_p = guardar_trades(trades_p, ts)
    nuevos_s = guardar_trades(trades_s, ts)
    snap     = guardar_snapshot(ts)

    ciclos_p = calcular_pnl_ciclos(raw_p)
    ciclos_s = calcular_pnl_ciclos(raw_s)
    del raw_p, raw_s
    gc.collect()

    if snap:
        imprimir_resumen(snap, nuevos_p, nuevos_s, ciclos_p, ciclos_s)
