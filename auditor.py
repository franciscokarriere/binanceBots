import ccxt
import pandas as pd
import os
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

def formatear_trades(trades, moneda_cotiz):
    datos = []
    for t in trades:
        datos.append({
            'Fecha/Hora'       : t['datetime'],
            'Acción'           : t['side'].upper(),
            f'Precio ({moneda_cotiz})': round(t['price'], 2),
            'Cantidad (BTC)'   : round(t['amount'], 6),
            f'Total ({moneda_cotiz})' : round(t['cost'], 2),
            'Comisión'         : f"{round(t['fee']['cost'], 6)} {t['fee']['currency']}" if t.get('fee') else '0'
        })
    return pd.DataFrame(datos)

def auditar_cuenta(exchange, simbolo, etiqueta, limite=10):
    moneda_cotiz = simbolo.split('/')[1]
    print(f"\n{'='*60}")
    print(f"  {etiqueta} ({simbolo}) — últimas {limite} transacciones")
    print(f"{'='*60}")

    try:
        trades = exchange.fetch_my_trades(simbolo, limit=limite)

        if not trades:
            print("  Sin transacciones ejecutadas para este par.")
            return None, None, None

        df = formatear_trades(trades, moneda_cotiz)
        print(df.to_string(index=False))

        primera = trades[0]
        ultima  = trades[-1]
        print(f"\n  Primera operación: {primera['datetime'][:16]}  "
              f"{primera['side'].upper()} {primera['amount']:.6f} BTC "
              f"@ {primera['price']:,.2f} {moneda_cotiz}  "
              f"→ valor: {primera['cost']:,.2f} {moneda_cotiz}")
        print(f"  Última operación:  {ultima['datetime'][:16]}  "
              f"{ultima['side'].upper()} {ultima['amount']:.6f} BTC "
              f"@ {ultima['price']:,.2f} {moneda_cotiz}  "
              f"→ valor: {ultima['cost']:,.2f} {moneda_cotiz}")

        return exchange, simbolo, moneda_cotiz

    except Exception as e:
        print(f"  Error al consultar la API: {e}")
        return None, None, None

def resumen_combinado():
    print(f"\n{'='*60}")
    print("  RESUMEN COMBINADO — valor estimado actual")
    print(f"{'='*60}")

    try:
        # Precio BTC actual en USDT (referencia USD)
        ticker = exchange_principal.fetch_ticker('BTC/USDT')
        precio_btc_usd = ticker['last']

        # Balances cuenta principal
        bal_p = exchange_principal.fetch_balance()
        btc_p    = bal_p.get('BTC', {}).get('total', 0.0)
        usdt_p   = bal_p.get('USDT', {}).get('total', 0.0)
        valor_p  = btc_p * precio_btc_usd + usdt_p

        # Balances subcuenta
        bal_s = exchange_bot2.fetch_balance()
        btc_s    = bal_s.get('BTC', {}).get('total', 0.0)
        fdusd_s  = bal_s.get('FDUSD', {}).get('total', 0.0)
        valor_s  = btc_s * precio_btc_usd + fdusd_s   # FDUSD ≈ 1 USD

        total = valor_p + valor_s

        print(f"\n  BTC precio referencia:  ${precio_btc_usd:,.2f} USD")
        print(f"\n  Cuenta principal:")
        print(f"    BTC:  {btc_p:.6f}  (~${btc_p * precio_btc_usd:,.2f} USD)")
        print(f"    USDT: {usdt_p:.2f}  (~${usdt_p:,.2f} USD)")
        print(f"    Subtotal: ~${valor_p:,.2f} USD")
        print(f"\n  Subcuenta (Bot2):")
        print(f"    BTC:   {btc_s:.6f}  (~${btc_s * precio_btc_usd:,.2f} USD)")
        print(f"    FDUSD: {fdusd_s:.2f}  (~${fdusd_s:,.2f} USD)")
        print(f"    Subtotal: ~${valor_s:,.2f} USD")
        print(f"\n  {'─'*40}")
        print(f"  TOTAL ESTIMADO: ~${total:,.2f} USD")
        print(f"  {'─'*40}\n")

    except Exception as e:
        print(f"  Error al calcular resumen: {e}")

if __name__ == "__main__":
    auditar_cuenta(exchange_principal, 'BTC/USDT',  'CUENTA PRINCIPAL')
    auditar_cuenta(exchange_bot2,      'BTC/FDUSD', 'SUBCUENTA BOT2')
    resumen_combinado()
