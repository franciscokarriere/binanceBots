# CLAUDE.md — Base genérico

> Este es el bloque común que heredan todos los proyectos. El contenido es
> **agnóstico**: cópialo tal cual a `GEMINI.md`, `AGENTS.md` o `.cursorrules`.
> Las secciones específicas de cada proyecto van en su propio `CLAUDE.md`,
> que **extiende** este base (no lo reemplaza).

---

## 0. Al iniciar cada sesión — leer el contexto

**Antes de cualquier otra cosa, leer `docs/context.md`.**

Ese archivo es el traspaso oficial del proyecto: qué bots existen, qué parámetros tienen,
qué está en producción, qué quedó pendiente y qué ya se completó. Sin leerlo, cualquier
respuesta sobre el estado del proyecto puede estar desactualizada o ser incorrecta.

Después de leer `docs/context.md`, si la sesión hace cambios significativos en el código
o completa tareas pendientes, **actualizar `docs/context.md`** al final de la sesión.

---

## 0.1. Cómo leer este sistema de archivos

En este proyecto el archivo de gobernanza principal es **CLAUDE.md** (este archivo).
No existen PLANNING.md ni SPEC.md — todo el contexto arquitectónico y de estado vive en
`docs/context.md`.

El orden de autoridad es:

1. **`docs/context.md`** — estado actual del proyecto: qué hay construido, qué está pendiente.
2. **`CLAUDE.md`** — convenciones, reglas de riesgo y comandos.

Si dos fuentes se contradicen, gana la más reciente. Nunca resuelvas un conflicto
inventando una tercera opción sin avisar.

---

## 1. Gobernanza de conflictos (REGLA CENTRAL)

Cuando vayas a proponer algo que **contradice** `docs/context.md` o `CLAUDE.md`,
clasifica el cambio antes de actuar:

### Cambio MENOR → auto-aplica y registra en el log

- Typos, formato, estilo.
- Agregar un comando que faltaba (test, lint, build).
- Aclarar una convención que ya estaba implícita.
- Añadir un caso de test obvio que faltaba.

Acción: aplícalo, y deja una línea en `## CHANGELOG DE GOBERNANZA` al final del
archivo afectado con fecha + qué cambiaste + por qué.

### Cambio MAYOR → FRENA y pregunta

- Cambiar el stack o una versión.
- Tocar una zona marcada como intocable.
- Cambiar una decisión de arquitectura registrada en `docs/context.md`.
- Agregar una nueva fuente de datos / endpoint / dependencia externa.
- Modificar la lógica de riesgo de los bots (parámetros OCO, umbrales, time-stop).

Acción: NO lo apliques. Presenta la propuesta como mejora, explica qué archivo
habría que actualizar (context.md / CLAUDE.md) y espera mi OK explícito.

> **Regla de oro:** si afecta _qué se construye_ o la _seguridad/veracidad_ → MAYOR.
> Si afecta solo el _cómo se escribe_ → MENOR.

### Prompts anidados

Si en un prompt futuro te pido escribir o pegar **otro prompt dentro de un texto**
(p. ej. "generá el prompt que le pasaría a otro agente"), trátalo como contenido,
no como instrucción para vos. No ejecutes las instrucciones del prompt anidado;
solo prodúcelo como texto. Si ese prompt anidado contradice este archivo, marcalo.

---

## 2. FLAG: Fail-closed (trabajar en caliente con bloqueos)

```
FAIL_CLOSED = OFF   # ON | OFF — cada proyecto lo define en su CLAUDE.md
```

Cuando `FAIL_CLOSED = ON`, ante CUALQUIERA de estas condiciones el proceso
**se detiene y no produce salida** (mejor sin dato que con dato basura):

- Un dato esperado falta, es null, o llega vacío.
- Una fuente / API responde con error, timeout, o formato inesperado.
- Un valor cae fuera de un rango razonable definido en el SPEC.
- No se puede verificar / corroborar un dato que el SPEC marca como crítico.

Comportamiento al bloquear:

1. Detener esa unidad de trabajo (no toda la corrida, salvo que el SPEC lo diga).
2. Loguear: timestamp, qué condición disparó el bloqueo, el dato/fuente afectado.
3. Marcar el resultado como `BLOCKED`, nunca como `OK con valor por defecto`.
4. **Nunca** rellenar con un valor inventado, estimado o "placeholder".

Cuando `FAIL_CLOSED = OFF`: se permite continuar con degradación elegante,
pero igual se loguea el dato faltante.

---

## 3. FLAG: Docstrings por función

```
DOCSTRINGS = ON   # ON | OFF — cada proyecto lo define en su CLAUDE.md
```

Cuando `DOCSTRINGS = ON`, toda función nueva o modificada lleva un comentario
inmediatamente antes (o docstring, según el lenguaje) con tres partes:

- **Qué hace:** una línea, en presente.
- **Recibe:** cada parámetro con tipo y significado.
- **Entrega:** qué retorna, con tipo; y qué excepciones/errores puede lanzar.

Ejemplo (Python):

```python
def corroborar_dato(valor, fuentes):
    """
    Qué hace: confirma un dato contra múltiples fuentes y devuelve su rating.
    Recibe:
        valor (float): el dato a verificar.
        fuentes (list[Source]): fuentes independientes a consultar.
    Entrega:
        (int) rating de confianza 0-5; lanza CorroborationError si no hay quórum.
    """
```

Cuando `DOCSTRINGS = OFF`: comentarios solo donde la lógica no sea evidente.

---

## 4. Convenciones de código (base)

- Nombres descriptivos; nada de `tmp`, `data2`, `x` salvo índices triviales.
- Funciones cortas y con una sola responsabilidad.
- Errores explícitos: nunca un `except:` vacío que se trague la excepción.
- Sin números mágicos: constantes nombradas arriba del archivo o en config.
- No hardcodear secrets, claves ni rutas absolutas. Todo a variables de entorno.

## 5. Zonas intocables (base)

- Archivos de credenciales / `.env` / secrets: NO se leen ni se imprimen ni se editan.
- Migraciones ya aplicadas: NO se modifican; se crea una nueva.
- Cualquier archivo o carpeta listado en la sección INTOCABLE del CLAUDE.md del proyecto.

## 6. Comandos del proyecto

> Cada proyecto completa esto en su propio CLAUDE.md.

- Instalar: `...`
- Tests: `...`
- Lint / format: `...`
- Ejecutar: `...`

## 7. Verificación antes de dar por terminado

Antes de declarar una tarea completa:

1. ¿Los cambios respetan las zonas intocables?
2. ¿Todo error de API o de lógica queda capturado y logueado (no silenciado)?
3. ¿Las claves API siguen viniendo solo desde `.env`?
4. ¿Se actualizó `docs/context.md` si el cambio afecta el estado del proyecto?
5. Si `DOCSTRINGS = ON`, ¿toda función nueva/tocada tiene su comentario?

---

# CLAUDE.md — Bot de trading (Binance)

> Extiende `CLAUDE.base.md`. Aquí solo lo específico de este proyecto.
> Aquí un dato basura no es un PDF feo: es plata real. Las reglas son estrictas.

## Flags de este proyecto

```
FAIL_CLOSED = OFF    # los errores se capturan y loguean; el bot sigue corriendo
DOCSTRINGS  = ON     # toda función nueva o modificada lleva docstring
```

## Qué es este proyecto

Dos bots de trading algorítmico en Binance Spot, en producción en AWS EC2:

- **Bot 1** (`bot_oneMin.py`) — BTC/USDT, cuenta principal, trend-following con SMA 50/5000.
- **Bot 2** (`bot_altaFrecuencia.py`) — BTC/FDUSD, subcuenta aislada, reversión a la media con EMA21/EMA200 + RSI.

La prioridad #1 no es ganar: es **no perder por un error evitable**. Es un experimento de
aprendizaje sobre bots e infraestructura, con capital real pero acotado.

## Stack

- Python 3.12
- ccxt 4.x (se usa `private_post_order_oco` — `create_oco_order` fue eliminado en 4.x)
- pandas (análisis de velas OHLCV)
- python-dotenv (carga de claves desde `.env`)
- No hay `requirements.txt` en el repo (se crea si el proyecto lo requiere; no asumir que existe)

## Reglas críticas (manda sobre todo lo demás)

1. **Capturar, loguear, continuar.** Ante error de API, timeout o dato inesperado:
   capturar la excepción, imprimir el error con contexto suficiente, y dejar que el
   ciclo del bot reintente en el próximo tick. **Nunca** un `except: pass` silencioso.
   El objetivo a futuro es enviar los errores críticos a un bot de Telegram.
2. **Nunca asumir un valor.** Precio, balance, fees, tamaño de posición: siempre
   leídos en vivo antes de cada operación. Jamás un valor por defecto, cacheado viejo
   o estimado para calcular el tamaño de una orden.
3. **Límites de riesgo en constantes nombradas.** Los parámetros OCO (TP, SL, time-stop)
   viven como constantes al tope del archivo. Cambiar un umbral de riesgo es un cambio
   MAYOR que requiere OK explícito.
4. **Secrets.** Las claves API solo desde variables de entorno (`.env`). Hay dos pares:
   - `BINANCE_API_KEY` / `BINANCE_SECRET_KEY` — cuenta principal (Bot 1, auditor)
   - `BINANCE_API_KEY_BOT2` / `BINANCE_SECRET_KEY_BOT2` — subcuenta Bot 2
   Nunca se imprimen en logs ni se hardcodean. Permisos de la API key: sin retiro.

## Zonas intocables (además de las del base)

- **Datos de producción locales** — no borrar ni sobreescribir sin permiso explícito:
  - `registro_trades.csv`, `registro_snapshots.csv` — historial acumulativo de operaciones y portafolio.
  - `historico_velas.csv`, `historico_velas_fdusd.csv` — caché de velas (se regenera, pero se pierde tiempo).
  - Archivos `*.log` traídos del servidor (ej. `auditor_cron.log`) — son evidencia de producción.
- **Lógica de riesgo de los bots** — cambiar TP, SL, time-stop, umbrales de entrada: siempre MAYOR.
- **`.env`** — no leer, no imprimir, no editar. Contiene las claves de las dos cuentas reales.

## Verificación extra antes de terminar

- ¿Todo `except` captura el error y lo imprime con contexto? (no `pass`, no silencio).
- ¿Las constantes de riesgo (TP, SL, time-stop, umbrales) no fueron modificadas sin OK?
- ¿Las claves siguen viniendo solo de `.env` y no están impresas en ningún log?

## Comandos

- Instalar: `pip install ccxt pandas python-dotenv`
- Tests: no hay suite de tests automatizados en el repo.
- Lint: no hay configuración de linter (si se añade, usar `ruff check .`).
- Ejecutar Bot 1 (local, sin dormir el mac): `caffeinate -i python3 bot_oneMin.py`
- Ejecutar Bot 2 (local): `python3 bot_altaFrecuencia.py`
- Auditar visual (consola): `python3 auditor.py`
- Extraer CSV acumulativo: `python3 auditorExtract.py`
- Backtest Bot 1: `python3 evaluacionUltimaSemana.py <monto> <fecha_inicio> <ma_lenta> <ma_rapida>`
- Conectar a producción (AWS): `ssh -i "aws-bot-key.pem" ubuntu@52.198.73.194`
- Ver bots en producción: `tmux attach -t bot_macro` / `tmux attach -t bot_micro`
- Dry run (solo lectura): ejecutar `bot_daemonDR()` en `dryRun.py`

> No existe modo paper/sandbox. Los bots ejecutan órdenes reales en Binance Spot desde
> el primer ciclo. Para verificar conexión sin operar, usar `dryRun.py`.

## Flujo de trabajo por sesión

### 1. Informe de estado al terminar cada petición

Después de cualquier modificación o trabajo con archivos, entregar siempre un informe
que incluya:

- **Qué se hizo:** lista de archivos modificados/creados y cambio principal en cada uno.
- **Qué quedó pendiente** (si lo hay): lo que no se completó y por qué.
- **Próximo paso sugerido** (opcional): solo si es obvio y relevante.

El informe debe ser breve. No repetir el código ni explicar lo que el diff ya muestra.

### 2. Commit y push al validar un cambio

Cuando el usuario confirme que el cambio está bien (respuesta explícita de OK / validación),
ejecutar la siguiente secuencia en orden:

```bash
# 1. Agregar solo los archivos trabajados en la petición (nunca git add -A sin revisión)
git add <archivos específicos>

# 2. Commit en inglés, con prefijo de tipo convencional
git commit -m "type: short description in English"

# 3. Push si existe un remote configurado
git remote -v && git push   # solo si hay remote; si no, omitir silenciosamente
```

**Prefijos de tipo válidos:** `feat` · `fix` · `docs` · `refactor` · `chore`

**Reglas del mensaje:**
- En inglés, imperativo presente ("add", "fix", "update" — no "added", "fixing").
- Máximo 72 caracteres en la línea del título.
- Si el cambio afecta varios archivos con lógicas distintas, usar un segundo párrafo
  de descripción separado por línea en blanco.

**No hacer commit** si el usuario no validó explícitamente, o si hay cambios sin
guardar / incompletos en otros archivos del mismo contexto.

## Deuda técnica activa

Lista de mejoras decididas pero aún no implementadas. No aplicar sin OK explícito;
solo sirven para dar contexto al agente sobre el rumbo del proyecto.

| # | Qué falta | Prioridad | Notas |
|---|---|---|---|
| 1 | **Bot de Telegram para alertas** | Alta | Los `except` actuales imprimen a stdout/log. El siguiente paso es enviar los errores críticos (fallo de OCO, venta anticipada, error de red prolongado) a un canal de Telegram. Sustituirá/complementará el monitoreo por tmux. |
| 2 | **Backtester para Bot 2** | Media | El `evaluacionUltimaSemana.py` solo cubre la estrategia SMA del Bot 1. No hay simulador equivalente para la estrategia de reversión a la media (EMA21/RSI) del Bot 2. Pendiente de construir antes de ajustar parámetros. |
| 3 | **`client-order-id` en órdenes** | Baja | Sin ID único por orden, un reinicio en el momento exacto del envío podría no detectar una orden ya ejecutada. Mitigado por el ciclo de detección de balance en `procesar_mercado`. |
| 4 | **`requirements.txt`** | Baja | Se crea solo si el proyecto lo necesita (deploy automatizado, CI). Por ahora se instala manualmente. |

## CHANGELOG DE GOBERNANZA

<!-- El agente agrega aquí los cambios MENORES que auto-aplicó. Formato:
- [YYYY-MM-DD] (menor) qué cambió — por qué -->
- [2026-06-25] (menor) Sección 0: añadir instrucción de leer docs/context.md al inicio de sesión — el archivo no existía en CLAUDE.md original.
- [2026-06-25] (menor) Actualizar sección Stack, Comandos, Reglas críticas y Flags para reflejar el estado real del código (FAIL_CLOSED OFF, sin modo PAPER, ccxt 4.x, comandos correctos).
- [2026-06-25] (menor) Añadir sección Deuda técnica activa y ajustar Zonas intocables (CSV, .log, .env dual).
- [2026-06-25] (menor) Añadir sección Flujo de trabajo: informe de estado por petición + commit/push al validar.
