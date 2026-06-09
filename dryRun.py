import ccxt
import time
import os
from dotenv import load_dotenv
# Cargar variables del archivo .env
load_dotenv()


# 1. Instanciación segura del exchange
exchange = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot', # Cambiar a 'future' si decides operar derivados
        'adjustForTimeDifference': True, # Agrega esta línea crítica
    }
})

def ejecutar_orden(simbolo, senal):
    """
    Evalúa el estado del portafolio y ejecuta la orden de mercado
    solo si es estrictamente necesario según la señal.
    """
    try:
        moneda_base = simbolo.split('/')[0]   # Ej: BTC
        moneda_cotiz = simbolo.split('/')[1]  # Ej: USDT
        
        # Obtener balances actualizados
        balances = exchange.fetch_balance()
        balance_base = balances[moneda_base]['free']
        balance_usdt = balances[moneda_cotiz]['free']
        
        # Definir si estamos "en posición" (Tener más de 0.0001 BTC se considera posición abierta)
        en_posicion = balance_base > 0.0001 

        if senal == "COMPRAR" and not en_posicion:
            # Consultar el precio actual del libro de órdenes
            precio_actual = exchange.fetch_ticker(simbolo)['last']
            
            # Gestión de riesgo dinámico: Usar el 98% del USDT disponible
            # para prevenir errores de "Saldo Insuficiente" por fluctuaciones de microsegundos
            tamano_compra = (balance_usdt * 0.98) / precio_actual
            
            print(f"Señal de COMPRA confirmada. Ejecutando orden por {tamano_compra:.6f} {moneda_base}...")
            orden = exchange.create_market_buy_order(simbolo, tamano_compra)
            print(f"Orden ejecutada con éxito. ID: {orden['id']}")
            return orden

        elif senal == "VENDER" and en_posicion:
            print(f"Señal de VENTA confirmada. Cerrando posición de {balance_base:.6f} {moneda_base}...")
            # En spot, vender el largo significa liquidar el balance total de la moneda base
            orden = exchange.create_market_sell_order(simbolo, balance_base)
            print(f"Posición cerrada con éxito. ID: {orden['id']}")
            return orden
        
        else:
            # La señal es MANTENER, o la señal es de COMPRA pero ya estamos en posición.
            print(f"Monitoreando. Señal calculada: {senal} | Posición activa: {en_posicion}")
            return None

    except ccxt.InsufficientFunds as e:
        print("Error: Fondos insuficientes para ejecutar la orden. Revisa los saldos.")
    except ccxt.NetworkError as e:
        print("Error de red al conectar con Binance. Se reintentará en el próximo ciclo.")
    except Exception as e:
        print(f"Excepción general en la ejecución: {e}")
        
    return None

# Ciclo de ejecución continuo (Daemon)
def bot_daemon():
    simbolo = 'BTC/USDT'
    print("Iniciando bot de trading algorítmico...")
    
    while True:
        try:
            # 1. Aquí llamarías a la función obtener_datos() desarrollada anteriormente
            # df = obtener_datos(simbolo, '1m', 5000)
            
            # 2. Calcular la señal con la SMA
            # senal = calcular_senal(df)
            
            # Simulación de señal para prueba estructural
            # senal_simulada = "COMPRAR" 
            # senal_simulada = "VENDER"
            senal_simulada = "MANTENER"
            
            # 3. Módulo de ejecución
            ejecutar_orden(simbolo, senal_simulada)
            
            # Pausa de 60 segundos para coincidir con el cierre de la vela de 1 minuto
            time.sleep(60)
            
        except KeyboardInterrupt:
            print("Ejecución detenida manualmente por el usuario.")
            break
        except Exception as e:
            print(f"Fallo en el ciclo principal: {e}")
            time.sleep(60) # Esperar antes de reintentar para no saturar la API

# Ciclo de ejecución para PRUEBA DE CONEXIÓN (Dry Run)
def bot_daemonDR():
    simbolo = 'BTC/USDT'
    print("Iniciando prueba de conexión segura (Dry Run)...")
    
    try:
        # 1. Prueba directa de conexión y lectura
        print("Consultando la API de Binance...")
        balances = exchange.fetch_balance()
        
        saldo_usdt = balances['USDT']['free']
        saldo_btc = balances['BTC']['free']
        
        print(f"✅ Conexión exitosa.")
        print(f"📊 Saldo detectado: {saldo_usdt:.2f} USDT | {saldo_btc:.6f} BTC")
        
        # 2. Prueba del módulo de ejecución con señal neutra
        print("\nProbando módulo de ejecución con señal neutra...")
        senal_simulada = "MANTENER" 
        ejecutar_orden(simbolo, senal_simulada)
        
    except ccxt.AuthenticationError:
        print("❌ Error de Autenticación: Verifica que la API Key y Secret sean correctos y no tengan espacios extra.")
    except ccxt.PermissionDenied:
        print("❌ Permiso Denegado: Verifica que tu IP pública esté en la lista blanca de Binance y que 'Habilitar Lectura' esté marcado.")
    except Exception as e:
        print(f"❌ Fallo general en la prueba: {e}")

if __name__ == "__main__":
    #bot_daemon()
    # Prueba (Dry Run)
    bot_daemonDR()