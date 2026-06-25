# Contexto unificado del proyecto Binance

> Documento de traspaso (handoff) para retomar el trabajo desde cualquier sesión.
> Última actualización: **2026-06-25** (revisión completa del código).

---

## Estado actual del proyecto (resumen ejecutivo)

Dos bots en producción en AWS EC2 (t3.micro, Ubuntu), corriendo en sesiones tmux separadas:

| Bot | Archivo | Par | Sesión tmux | Estado |
|---|---|---|---|---|
| Bot 1 (macro) | `bot_oneMin.py` | BTC/USDT | `bot_macro` | Activo — SMA trend-following |
| Bot 2 (micro) | `bot_altaFrecuencia.py` | BTC/FDUSD | `bot_micro` | Activo — reversión a la media |

Portafolio total en la última extracción conocida: **~$40 USD** (registro_snapshots.csv).

---

## Conversaciones que resume este documento

| Conversación | Fecha | Alcance |
| --- | --- | --- |
| Creación del Bot 2 + rediseño de estrategia + fix de OCO | **2026-06-25** | Sesión principal: Bot 2 y toda su infraestructura, rediseño de estrategia, fix OCO en Bot 2. |
| "Corregir create_oco_order obsoleto en bot_oneMin.py" | **2026-06-25** | Fix OCO aplicado también al Bot 1. **COMPLETADO** en commit `81475e7`. |
| Auditor dual + extractor CSV + cooldown SL | **2026-06-25** | `auditor.py` (reporte visual), `auditorExtract.py` (CSV acumulativo). |
| Licencia GPLv3 + README | **2026-06-25** | Licencia añadida. **COMPLETADO** en commit `67f1e52`. |

---

## Arquitectura de archivos (estado real del repo)

```
bot_oneMin.py          — Bot 1: BTC/USDT, trend-following SMA 50/5000
bot_altaFrecuencia.py  — Bot 2: BTC/FDUSD, reversión a la media EMA21/EMA200
auditor.py             — Reporte visual en consola (últimas N transacciones + resumen combinado)
auditorExtract.py      — Extractor CSV acumulativo (registro_trades.csv, registro_snapshots.csv)
dryRun.py              — Prototipo de conexión inicial. YA NO SE USA activamente.
evaluacionUltimaSemana.py — Backtesting 7 días para Bot 1 (SMA, ATR, parámetros configurables por CLI)
.env                   — Claves API (en .gitignore — no commitear nunca)
registro_trades.csv    — Historial de trades extraídos (en .gitignore)
registro_snapshots.csv — Snapshots de portafolio por extracción (en .gitignore)
historico_velas.csv    — Caché local de velas BTC/USDT (en .gitignore)
historico_velas_fdusd.csv — Caché local de velas BTC/FDUSD (en .gitignore)
```

---

## Detalles de cada componente (estado del código revisado)

### Bot 1 — `bot_oneMin.py` (v4.1)

**Estrategia:** trend-following con cruce SMA 50/5000 (1-minuto), filtro ATR y brecha de confirmación.

**Parámetros clave:**
- `TAKE_PROFIT_PCT = 1.0175` → TP +1.75%
- `STOP_LOSS_TRIGGER_PCT = 0.9940` → SL trigger −0.60%
- `STOP_LOSS_LIMIT_PCT = 0.9930` → SL limit −0.70%
- `UMBRAL_ATR_PCT = 0.25` — volatilidad mínima requerida
- `DISTANCIA_CRUCE_PCT = 0.05` — brecha mínima entre SMAs
- `BYPASS_ATR_GAP_PCT = 1.5` — si el gap es ≥1.5%, omite filtro ATR
- `COOLDOWN_SL_MINUTOS = 45` — pausa post stop-loss antes de volver a comprar
- Ciclo: cada 60 segundos
- Par: BTC/USDT (cuenta principal, claves `BINANCE_API_KEY` / `BINANCE_SECRET_KEY`)

**OCO:** usa `exchange.private_post_order_oco()` (endpoint legacy de ccxt 4.x). **Bug `create_oco_order` ya corregido.**

**Caché local:** `historico_velas.csv` (últimas 5000 velas de 1m, actualización incremental).

---

### Bot 2 — `bot_altaFrecuencia.py` (v2)

**Estrategia:** reversión a la media — compra dips en tendencia macro alcista.

**Parámetros clave:**
- `TAKE_PROFIT_PCT = 1.0070` → TP +0.70%
- `STOP_LOSS_TRIGGER_PCT = 0.9900` → SL trigger −1.00% (barrera de catástrofe)
- `STOP_LOSS_LIMIT_PCT = 0.9895` → SL limit −1.05%
- `TIME_STOP_MINUTOS = 360` — si en 6h no toca el TP, vende a mercado (venta anticipada)
- `DIP_ENTRADA_PCT = 0.30` — caída mínima del precio bajo EMA21 (⚠️ ver nota abajo)
- `RSI_MAXIMO = 50` — RSI máximo para confirmar sobreventa (⚠️ ver nota abajo)
- `PENDIENTE_EMA200_VELAS = 60` — ventana para verificar que EMA200 sube
- `VELAS_CACHE = 1500` — ventana de datos (ligera para t3.micro)
- `CICLO_SEGUNDOS = 15` — alta frecuencia (escaneo cada 15s)
- Par: BTC/FDUSD (subcuenta Bot2, claves `BINANCE_API_KEY_BOT2` / `BINANCE_SECRET_KEY_BOT2`)

> **⚠️ Discrepancia con context.md anterior:** el contexto previo describía DIP ≥ 0.60% y RSI ≤ 40 (valores del backtest inicial). El código actual tiene DIP ≥ 0.30% y RSI ≤ 50 — parámetros relajados probablemente para aumentar frecuencia de operaciones. Verificar si esto fue intencional o si requiere validación con nuevo backtest.

**OCO:** igual que Bot 1 — `exchange.private_post_order_oco()` (legacy). **Bug ya corregido.**

**Lógica de venta anticipada (time-stop):** si `ts_entrada_ms > 0` y `minutos_en_posicion >= 360`, cancela todas las órdenes abiertas y vende a mercado. Corre antes de la verificación de OCO activo.

**Caché local:** `historico_velas_fdusd.csv` (últimas 1500 velas de 1m, actualización incremental).

---

### `auditor.py` — Reporte visual

- Lee últimas 10 transacciones de ambos pares (BTC/USDT y BTC/FDUSD).
- Muestra tabla formateada + resumen combinado con precio BTC en tiempo real.
- No escribe a disco. Ejecución manual: `python3 auditor.py`.

### `auditorExtract.py` — Extractor CSV acumulativo

- Extrae trades de ambas cuentas y los guarda en `registro_trades.csv` (deduplicado por `trade_id`).
- Toma snapshot de portafolio completo en `registro_snapshots.csv` (precio BTC + balances de ambas cuentas + totales en USD).
- Muestra evolución histórica si hay más de 1 snapshot.
- Corre como **cron job en AWS** cada 5 minutos (watchdog + extracción periódica).

### `dryRun.py` — Prototipo (legado)

- Script inicial de prueba de conexión. Tiene `bot_daemon()` (modo real) y `bot_daemonDR()` (dry run de lectura).
- El `__main__` solo ejecuta `bot_daemonDR()`. **No es un bot activo.**
- No tiene la lógica moderna de indicadores. Se conserva como referencia histórica.

### `evaluacionUltimaSemana.py` — Backtesting Bot 1

- Backtesting de 7 días completo con datos OHLCV reales de Binance.
- Soporta parámetros por CLI: `python3 evaluacionUltimaSemana.py <monto> <fecha_inicio> <ma_lenta> <ma_rapida>`
- Simula los mismos filtros de Bot 1 (ATR ≥ 0.25%, gap ≥ 0.05%), descuenta comisión 0.1% por operación.
- **No existe backtester equivalente para Bot 2** (el simulador mencionado en contexto anterior no está en el repo principal).

---

## Variables de entorno (.env)

```
BINANCE_API_KEY          — Cuenta principal (Bot 1, auditor, extractores)
BINANCE_SECRET_KEY       — Cuenta principal
BINANCE_API_KEY_BOT2     — Subcuenta Bot 2
BINANCE_SECRET_KEY_BOT2  — Subcuenta Bot 2
```

El `.env` está en `.gitignore`. Si `BINANCE_API_KEY_BOT2` no está definida, `bot_altaFrecuencia.py` y `auditor.py` caen back a las claves principales.

---

## Infraestructura de producción

- **Servidor:** AWS EC2 t3.micro, Ubuntu — IP: `52.198.73.194`
- **Conexión:** `ssh -i "aws-bot-key.pem" ubuntu@52.198.73.194`
- **Bots en tmux:**
  - `bot_macro` → `python3 bot_oneMin.py`
  - `bot_micro` → `python3 bot_altaFrecuencia.py`
  - Reconectar: `tmux attach -t bot_macro` / `tmux attach -t bot_micro`
- **Crontab en EC2:** watchdog cada 5 minutos que relanza sesiones tmux caídas (sin reboot). También corre `auditorExtract.py` periódicamente.
- **Local (mac):** `caffeinate -i python3 bot_oneMin.py` para pruebas sin que el mac duerma.

---

## Tareas pendientes / por verificar

- [x] ~~**`bot_oneMin.py` (Bot 1) — bug OCO `create_oco_order`**~~ → Corregido en commit `81475e7`.
- [x] ~~**Licencia GPLv3**~~ → Añadida en commit `67f1e52`.
- [ ] **Validar parámetros de entrada Bot 2:** DIP_ENTRADA_PCT=0.30% y RSI_MAXIMO=50 son más relajados que el backtest original (0.60% / 40). Correr el simulador de Bot 2 (si existe) o construir uno para validar.
- [ ] **No existe backtester para Bot 2** — el simulador que se mencionó en la sesión de creación no está en el repo principal. Si se quiere evaluar la estrategia de reversión antes de ajustar parámetros, hay que construirlo o trasladarlo.
- [ ] **Idempotencia de órdenes:** ningún bot usa `clientOrderId`. Si el bot se reinicia justo después de enviar una compra pero antes de leer la respuesta, podría no detectar la orden. Bajo FAIL_CLOSED estricto esto es un riesgo menor pero real.
- [ ] **`dryRun.py` desactualizado:** no refleja la lógica actual de ningún bot. Considerar eliminarlo o actualizarlo como herramienta de health-check.
- [ ] Correr el backtester de Bot 1 sobre más fechas para acumular evidencia del winrate real antes de aumentar el capital.

---

## Entorno técnico

- **ccxt:** 4.5.57 (localmente) — `create_oco_order` eliminado en 4.x; se usa `private_post_order_oco`.
- **Python:** 3.12
- **Dependencias implícitas:** `ccxt`, `pandas`, `python-dotenv` (no hay `requirements.txt` en el repo).
- Backtests ejecutados con datos OHLCV reales de Binance (velas de 1 minuto).
