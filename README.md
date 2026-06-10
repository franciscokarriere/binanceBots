# Algoritmo Cuantitativo de Trading V4.1 (Trend Following)

## Descripción General

Este repositorio contiene un algoritmo de trading automatizado de alta frecuencia diseñado para operar en el mercado Spot de Binance (específicamente el par BTC/USDT). El bot opera bajo una arquitectura de "Estado Desacoplado con Amnesia Reactiva", lo que significa que la lógica de entrada al mercado es completamente independiente de la lógica de salida, priorizando la gestión estricta del riesgo y la captura de tendencias con inercia confirmada.

El sistema evalúa el mercado utilizando velas de 1 minuto (1m) a través de un caché local optimizado, ejecutando operaciones únicamente cuando convergen tres filtros cuantitativos estrictos, y delegando la salida del mercado directamente al motor de emparejamiento de Binance mediante el protocolo OCO.

---

## Arquitectura y Lógica de Operación

### 1. Sistema de Entrada (Filtros Cuantitativos)

El algoritmo no reacciona al precio instantáneo, sino al promedio direccional. Para ejecutar una orden de compra a mercado (Taker), deben cumplirse simultáneamente tres condiciones matemáticas:

- **Cruce Direccional (Golden Cross):** La Media Móvil Simple Rápida (SMA 50) debe cruzar por encima de la Media Móvil Simple Lenta (SMA 5000). Esto confirma el inicio de un impulso alcista macroeconómico.
- **Filtro de Volatilidad (ATR Estricto):** El Rango Verdadero Promedio (ATR de 14 periodos) expresado en porcentaje debe ser mayor o igual a **0.25%**. Esto bloquea operaciones durante lateralizaciones, fines de semana o madrugadas sin volumen operativo, evitando el sangrado por comisiones.
- **Confirmación de Brecha (Gap):** La distancia porcentual entre la SMA 50 y la SMA 5000 debe superar el umbral del **0.05%**. Esto erradica los falsos positivos producidos por "cruces pegados" o ruido de mercado temporal.

### 2. Sistema de Salida (Gestión de Riesgo OCO)

Una vez ejecutada la compra, el bot despliega inmediatamente un escudo protector utilizando órdenes **OCO (One-Cancels-the-Other)**. La monitorización de la salida se delega a los servidores de Binance para eliminar latencias locales y problemas de red.

- **Take Profit (Toma de Ganancias):** Ejecuta una orden Limit (Maker) estática al **+1.75%** del precio de entrada. Absorbe el impulso direccional asegurando capital antes del retroceso.
- **Stop Loss (Corte de Pérdidas):** Ejecuta una orden Stop-Limit de emergencia si el precio cae al **-0.60%** (Trigger) garantizando la venta al -0.70% (Limit). Este margen otorga al precio el espacio necesario para fluctuar sin activar ventas accidentales, manteniendo una relación Riesgo-Recompensa matemática cercana a 1:3.

---

## Características de Infraestructura

- **Eficiencia de Datos (Smart Caching):** Implementa un sistema de descarga Delta. Descarga el bloque pesado de 5000 velas solo en la primera ejecución y lo almacena en `historico_velas.csv`. En los ciclos siguientes, solo solicita a la API las velas faltantes, minimizando el consumo del _Rate Limit_ de Binance.
- **Gestión de Memoria en la Nube:** Diseñado para ejecución ininterrumpida (Daemon). Utiliza `gc.collect()` para forzar la recolección destructiva de basura en la memoria RAM tras procesar las estructuras pesadas de Pandas, evitando fugas de memoria (Memory Leaks) en servidores de capa gratuita.
- **Recuperación de Estado (State Failsafe):** Si el bot sufre una interrupción de energía o un reinicio forzado mientras hay activos retenidos, se conectará al historial de _trades_ de Binance, recuperará el precio exacto de la compra anterior y reestructurará las barreras OCO automáticamente.
- **Sincronización Reloj Atómico:** Utiliza `adjustForTimeDifference: True` en CCXT para sincronizar el servidor local con la API de Binance, erradicando desfasajes de marca de tiempo (timestamps) en la validación de firmas criptográficas.

---

## Telemetría Visual (Dashboard)

El bot imprime un panel de control en tiempo real en la terminal, evitando la necesidad de monitorear gráficos externos. La línea de estado se lee de la siguiente manera:

`Dashboard | USDT: 40.86 | Fase: BAJISTA | Gap: -0.542% | Vol: 0.070% [BLOQUEADO]`

- **USDT:** Capital líquido disponible en la cuenta para la próxima operación.
- **Fase:** Indica la estructura general del mercado (ALCISTA si SMA 50 > SMA 5000, BAJISTA en caso contrario).
- **Gap:** Distancia porcentual matemática entre las dos medias móviles.
- **Vol:** Nivel de volatilidad actual. Muestra `[OK]` si supera el 0.25% y permite operar, o `[BLOQUEADO]` si el mercado carece de fuerza direccional.

---

## Requisitos de Despliegue

1. Python 3.9+
2. Librerías principales: `ccxt`, `pandas`, `python-dotenv`.
3. Archivo `.env` en la raíz del proyecto conteniendo las credenciales con permisos de lectura y operaciones en Spot:

```env
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_SECRET_KEY=tu_secret_key_aqui

```

4. Comando de ejecución segura (en entornos Unix/macOS) para evitar la suspensión del proceso:

```bash
caffeinate -i python3 bot_oneMin.py

```
