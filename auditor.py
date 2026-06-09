import ccxt
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

def auditar_trades(simbolo='BTC/USDT', limite=10):
    print(f"Auditando las últimas {limite} transacciones reales para {simbolo}...\n")
    try:
        # fetch_my_trades extrae exclusivamente el historial de transacciones ejecutadas
        trades = exchange.fetch_my_trades(simbolo, limit=limite)
        
        if not trades:
            print("No se encontraron transacciones ejecutadas en el historial de esta cuenta para este par.")
            return

        # Formatear la salida estructurada
        datos = []
        for t in trades:
            datos.append({
                'Fecha/Hora': t['datetime'],
                'Acción': t['side'].upper(),
                'Precio (USDT)': t['price'],
                'Cantidad (BTC)': t['amount'],
                'Costo Total': t['cost'],
                'Comisión': f"{t['fee']['cost']} {t['fee']['currency']}" if t.get('fee') else '0'
            })
            
        df = pd.DataFrame(datos)
        print(df.to_string(index=False))

    except Exception as e:
        print(f"Error al consultar la API: {e}")

if __name__ == "__main__":
    auditar_trades()