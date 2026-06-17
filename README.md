# Algoritmos Cuantitativos de Trading — Binance Spot

## Descripción General

Este repositorio contiene dos bots de trading automatizado que operan en el mercado Spot de Binance sobre pares aislados (sin colisión de liquidez entre ellos). Ambos comparten la misma filosofía: arquitectura de "Estado Desacoplado con Amnesia Reactiva" (la lógica de entrada es independiente de la de salida), evaluación con velas de 1 minuto vía caché local, y delegación de la salida al motor de emparejamiento de Binance mediante órdenes **OCO (One-Cancels-the-Other)**.

|                  | Bot 1                        | Bot 2                              |
| ---------------- | ---------------------------- | ---------------------------------- |
| Archivo          | `bot_oneMin.py`              | `bot_altaFrecuencia.py`            |
| Par              | BTC/USDT                     | BTC/FDUSD                          |
| Estrategia       | Trend Following (V4.1)       | Reversión a la Media (V2)          |
| Ciclo de escaneo | 60 s                         | 15 s                               |
| Caché de velas   | `historico_velas.csv` (5000) | `historico_velas_fdusd.csv` (1500) |

---

## Bot 1 — Trend Following V4.1 (`bot_oneMin.py`, BTC/USDT)

### Sistema de Entrada (3 filtros simultáneos)

El algoritmo no reacciona al precio instantáneo, sino al promedio direccional. Para ejecutar una compra a mercado (Taker) deben cumplirse simultáneamente:

- **Cruce Direccional (Golden Cross):** la SMA rápida (50) debe estar por encima de la SMA lenta (5000). Confirma el inicio de un impulso alcista macro.
- **Filtro de Volatilidad (ATR Estricto):** el ATR de 14 periodos expresado en porcentaje debe ser **≥ 0.25%** (`UMBRAL_ATR_PCT`). Bloquea lateralizaciones, fines de semana y madrugadas sin volumen, evitando el sangrado por comisiones.
- **Confirmación de Brecha (Gap):** la distancia porcentual entre la SMA 50 y la SMA 5000 debe superar el **0.05%** (`DISTANCIA_CRUCE_PCT`). Erradica falsos positivos por "cruces pegados".

### Sistema de Salida (OCO)

- **Take Profit:** orden Limit (Maker) al **+1.75%** del precio de entrada (`TAKE_PROFIT_PCT = 1.0175`).
- **Stop Loss:** orden Stop-Limit con disparador al **-0.60%** (`STOP_LOSS_TRIGGER_PCT = 0.9940`) y precio límite al **-0.70%** (`STOP_LOSS_LIMIT_PCT = 0.9930`). Relación Riesgo-Recompensa cercana a 1:3.

---

## Bot 2 — Reversión a la Media V2 (`bot_altaFrecuencia.py`, BTC/FDUSD)

### Sistema de Entrada (caza de dips en tendencia alcista)

Compra capitulaciones de corto plazo solo cuando la estructura macro es ascendente. Deben cumplirse simultáneamente:

- **Dip de Capitulación:** el precio debe caer **≥ 0.60%** por debajo de la EMA 21 (`DIP_ENTRADA_PCT`).
- **Sobreventa Confirmada:** el RSI de 14 periodos debe ser **≤ 40** (`RSI_MAXIMO`).
- **Tendencia Macro Ascendente:** la EMA 200 actual debe ser mayor que la de hace 60 velas (`PENDIENTE_EMA200_VELAS`). Bloquea compras de dips dentro de tendencias bajistas ("cuchillos cayendo").

Requisito adicional: liquidez disponible ≥ 5 FDUSD (`MIN_NOTIONAL_FDUSD`, mínimo operable del par).

### Sistema de Salida (OCO asimétrico + Time-Stop)

Protocolo calibrado por backtesting multi-ventana:

- **Take Profit:** orden Limit (Maker) al **+0.70%** (`TAKE_PROFIT_PCT = 1.0070`) — objetivo principal de salida.
- **Stop Loss:** disparador al **-1.00%** (`STOP_LOSS_TRIGGER_PCT = 0.9900`) y límite al **-1.05%** (`STOP_LOSS_LIMIT_PCT = 0.9895`). Es una barrera de catástrofe, rara vez tocada.
- **Venta Anticipada (Time-Stop):** si el TP no se materializa en **360 minutos** (`TIME_STOP_MINUTOS`, 6 horas), el bot cancela el OCO y liquida a mercado, liberando el capital con pérdida/ganancia marginal en lugar de esperar el deterioro hasta el SL.

---

## Telemetría Visual (Dashboard)

Ambos bots imprimen un panel de control por ciclo en la terminal, evitando la necesidad de monitorear gráficos externos.

### Bot 1 (`bot_oneMin.py`)

```
Dashboard | USDT: 40.86 | Fase: BAJISTA | Gap: -0.542% | Vol: 0.070% [BLOQUEADO]
```

- **USDT:** capital líquido disponible para la próxima operación.
- **Fase:** estructura del mercado (ALCISTA si SMA 50 > SMA 5000, BAJISTA en caso contrario).
- **Gap:** distancia porcentual entre las dos medias (debe superar 0.05% para operar).
- **Vol:** volatilidad ATR actual. `[OK]` si ≥ 0.25% y permite operar; `[BLOQUEADO]` si no.

### Bot 2 (`bot_altaFrecuencia.py`)

**Modo liquidez** (esperando señal de compra):

```
Dashboard HF | FDUSD: 40.86 | Px: $63,560.00 | Macro: ALCISTA [ARMADO] | Dip: -0.003% (req >0.6%) | RSI: 35.2 (req <40)
```

- **FDUSD:** capital líquido disponible.
- **Px:** precio actual de BTC/FDUSD.
- **Macro:** `ALCISTA [ARMADO]` si la EMA 200 es ascendente (puede comprar); `BAJISTA [BLOQUEADO]` si no.
- **Dip:** distancia actual del precio bajo la EMA 21, con el umbral requerido (> 0.60%).
- **RSI:** valor actual, con el umbral requerido (< 40).

**Modo posición** (BTC delegado a la red OCO de Binance):

```
Posición Segura | 0.000318 BTC en red OCO | Px: $63,560.00 | PnL: +0.02% | TP: $63,993.84 (faltan +0.68%) | SL: $62,913.51 | T-Stop: 42/360 min
```

- **Px / PnL:** precio actual y resultado flotante vs el precio de entrada recuperado del historial de trades.
- **TP / SL:** barreras OCO vigentes; entre paréntesis, el porcentaje que falta para alcanzar el TP.
- **T-Stop:** minutos transcurridos en posición sobre la ventana máxima de 360. Al llegar al límite se ejecuta la venta anticipada a mercado.

---

## Características de Infraestructura

- **Eficiencia de Datos (Smart Caching):** descarga Delta. El bloque pesado de velas se baja solo en la primera ejecución y se persiste en CSV; en los ciclos siguientes solo se piden las velas faltantes, minimizando el consumo del _Rate Limit_ de Binance.
- **Compatibilidad OCO con ccxt 4.x:** ccxt 4.x eliminó el método unificado `create_oco_order`. Ambos bots detectan la versión en tiempo de ejecución: si el método legado existe lo usan; si no, llaman al endpoint implícito `privatePostOrderListOco` (POST `/api/v3/orderList/oco`) con la pata superior `LIMIT_MAKER` (TP) y la inferior `STOP_LOSS_LIMIT` con vigencia `GTC`. Precios y cantidades se envían como strings formateados con `price_to_precision` / `amount_to_precision`.
- **Gestión de Memoria en la Nube:** diseñados para ejecución ininterrumpida (Daemon). Usan `gc.collect()` tras procesar las estructuras pesadas de Pandas, evitando fugas de memoria en servidores de capa gratuita (t3.micro).
- **Recuperación de Estado (State Failsafe):** ante un reinicio forzado con activos retenidos, el bot consulta el historial de _trades_ de Binance, recupera el precio exacto de la compra anterior y reestructura las barreras OCO automáticamente.
- **Sincronización Reloj Atómico:** `adjustForTimeDifference: True` en CCXT sincroniza el reloj local con la API de Binance, erradicando desfasajes de timestamp en la validación de firmas.

---

## Requisitos de Despliegue

1. Python 3.9+
2. Librerías principales: `ccxt`, `pandas`, `python-dotenv`.
3. Archivo `.env` en la raíz del proyecto con credenciales con permisos de lectura y operaciones en Spot. **Importante:** si la API key tiene restricción de IP (recomendado en producción), la IP de la máquina que ejecuta el bot debe estar en la lista blanca; de lo contrario Binance rechaza las llamadas firmadas con el error `-2015`.

```env
# Bot 1 (cuenta principal, BTC/USDT)
BINANCE_API_KEY=tu_api_key_aqui
BINANCE_SECRET_KEY=tu_secret_key_aqui

# Bot 2 (subcuenta aislada, BTC/FDUSD) — opcional:
# si no se definen, el Bot 2 usa las credenciales generales
BINANCE_API_KEY_BOT2=api_key_de_la_subcuenta
BINANCE_SECRET_KEY_BOT2=secret_key_de_la_subcuenta

```

### Aislamiento de capital (subcuentas)

Ambos bots gestionan el saldo de BTC de la cuenta donde operan: si comparten cuenta, el Bot 2 detectará como "BTC libre" lo que el Bot 1 acaba de comprar y le colocará su propio OCO con umbrales distintos. Para evitarlo, cada bot debe operar en una cuenta separada:

- **Bot 1** opera con las credenciales de la cuenta principal (USDT).
- **Bot 2** opera con `BINANCE_API_KEY_BOT2` apuntando a una subcuenta que solo contiene FDUSD.

Las subcuentas se crean desde la cuenta principal (Perfil → Dashboard → Sub Accounts), las transferencias principal ↔ subcuenta son instantáneas y sin comisión, y cada subcuenta emite sus propias API keys con whitelist de IP independiente.

4. Comando de ejecución segura (en macOS, para evitar la suspensión del proceso durante pruebas locales):

```bash
caffeinate -i python3 bot_oneMin.py
caffeinate -i python3 bot_altaFrecuencia.py

```

### Entorno virtual en el servidor (AWS EC2)

En el servidor las dependencias se instalan dentro de un entorno virtual (venv), no en el Python del sistema. Si el bot lanza `ModuleNotFoundError: No module named 'ccxt'`, es porque se ejecutó con el Python del sistema en lugar del venv.

```bash
cd ~/robotbinance

# Crear el venv (solo la primera vez)
python3 -m venv venv

# Activar e instalar dependencias DENTRO del venv
source venv/bin/activate
pip install ccxt pandas python-dotenv

# Ejecutar con el venv activo
python3 bot_altaFrecuencia.py

```

Checklist tras un despliegue nuevo en el servidor:

1. El archivo `.env` existe en la carpeta del bot (`ls -a`) — no viaja con `scp *.py`.
2. La IP pública de la instancia EC2 está en la whitelist de **ambas** API keys (principal y subcuenta); si no, Binance responde con el error `-2015`.
3. Las dependencias quedaron en el venv: `venv/bin/pip show ccxt`.

---

## Operación Autónoma en Producción (AWS EC2)

### Scripts de arranque con auto-reinicio

Cada bot tiene un script shell que lo mantiene vivo: si el proceso Python cae por cualquier motivo (error de red, excepción no capturada, etc.), el script lo reinicia automáticamente en 15 segundos.

**`start_onemin.sh`**
```bash
#!/bin/bash
cd /home/ubuntu/robotbinance
source venv/bin/activate
while true; do
    python3 bot_oneMin.py
    echo "[$(date)] Bot oneMin detenido. Reiniciando en 15s..."
    sleep 15
done
```

**`start_altafrecuencia.sh`**
```bash
#!/bin/bash
cd /home/ubuntu/robotbinance
source venv/bin/activate
while true; do
    python3 bot_altaFrecuencia.py
    echo "[$(date)] Bot altaFrecuencia detenido. Reiniciando en 15s..."
    sleep 15
done
```

Hacerlos ejecutables (solo la primera vez):
```bash
chmod +x ~/robotbinance/start_onemin.sh
chmod +x ~/robotbinance/start_altafrecuencia.sh
```

---

### tmux — Uso para supervisión y arranque manual

Cada bot corre en su propia sesión tmux nombrada. Esto permite desconectarse del SSH sin detener los procesos.

```bash
# Ver sesiones activas
tmux ls

# Crear e iniciar bot_oneMin
tmux new-session -d -s onemin '/home/ubuntu/robotbinance/start_onemin.sh'

# Crear e iniciar bot_altaFrecuencia
tmux new-session -d -s altafrecuencia '/home/ubuntu/robotbinance/start_altafrecuencia.sh'

# Entrar a revisar un bot (se queda en tiempo real)
tmux attach -t onemin
tmux attach -t altafrecuencia

# Salir sin matar el proceso (detach)
Ctrl+B  luego  D

# Matar una sesión si es necesario
tmux kill-session -t onemin
```

#### Checklist de supervisión antes de dejar correr sin vigilancia

Observar al menos 5–10 ciclos de cada bot después de un arranque o actualización:

| Verificación | Bot 1 (oneMin) | Bot 2 (altaFrecuencia) |
|---|---|---|
| Dashboard imprime sin errores Python | ✓ | ✓ |
| Indicadores [x]/[o] muestran el saldo correcto | ✓ | ✓ |
| Estado esperado según mercado | `OCO activo` o `BYPASS-TENDENCIA` | `[ARMADO]` o `[BLOQUEADO]` |
| No aparece `[COOLDOWN-SL]` repetido cada ciclo | ✓ | — |
| No se ve `Fallo crítico` ni `Error` en los últimos ciclos | ✓ | ✓ |

Si todo lo anterior está limpio durante 10 minutos consecutivos, es seguro desconectarse.

---

### Crontab — Arranque automático tras reinicio de instancia

El crontab garantiza que ambos bots y el auditor arranquen solos si AWS reinicia la instancia (mantenimiento, actualización de hipervisor, etc.).

```bash
# Editar el crontab del usuario ubuntu
crontab -e
```

Contenido completo del crontab:
```
# Arranque automático de bots tras reinicio de instancia
@reboot tmux new-session -d -s onemin '/home/ubuntu/robotbinance/start_onemin.sh'
@reboot tmux new-session -d -s altafrecuencia '/home/ubuntu/robotbinance/start_altafrecuencia.sh'

# Extracción diaria del auditor (medianoche UTC)
0 0 * * * /bin/bash -c 'cd /home/ubuntu/robotbinance && source venv/bin/activate && python3 auditorExtract.py >> /home/ubuntu/robotbinance/auditor_cron.log 2>&1'
```

Verificar que quedó guardado:
```bash
crontab -l
```

Ver el log del auditor automático:
```bash
cat ~/robotbinance/auditor_cron.log
```

#### Mecanismos de resiliencia por capa

| Situación | Mecanismo que responde |
|---|---|
| El archivo `.py` cae por excepción | `while true` en el script `.sh` — reinicia en 15s |
| La instancia AWS se reinicia | `@reboot` en crontab — levanta todo solo |
| Te desconectás del SSH | tmux `-d` — el proceso sigue corriendo |
| Querés ver qué pasó mientras no estabas | `tmux attach -t nombre` |
