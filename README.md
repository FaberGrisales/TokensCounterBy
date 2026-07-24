# 🕹️ Retro Token Counter & Dashboard (Arcade Edition)

Un monitor financiero de tokens para modelos de lenguaje (LLMs) como Claude y Gemini, diseñado con una interfaz de terminal (TUI) que imita una máquina de arcade clásica de 8 bits.

Este proyecto está diseñado para ayudarte a visualizar exactamente cuánto dinero gastas en cada llamada a una API (incluyendo llamadas reales con herramientas / MCP en Claude), ver en tiempo real qué sesiones de Claude Code están consumiendo tokens en tu máquina (incluyendo qué tan llena está su ventana de contexto), revisar el estado de tu suscripción de Claude y una foto fija de tu consumo global inspirada en el comando `/usage`, y ver qué servidores MCP y hooks tienes configurados (como `/mcp` y `/hooks`). Todos los números que ves vienen de una respuesta real de la API o de tus transcripts/config locales de Claude Code — no hay ningún modo simulado/estimado ni mecánicas de juego (billetera, monedas, high scores).

---

## 🚀 Instalación

Asegúrate de tener Python 3.8+ instalado en tu sistema. Se recomienda crear un entorno virtual (no se versiona en git):

```bash
python3 -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install rich anthropic google-genai
```

`rich` es obligatorio para la interfaz. `anthropic` y `google-genai` son opcionales: sin ellos la app funciona igual, pero la **Opción 1 (Call Live API)** se deshabilita para el proveedor cuyo SDK falte.

---

## 🎮 Cómo Jugar (Uso)

Para iniciar la máquina de arcade, ejecuta el script de lanzamiento desde la raíz del proyecto:

```bash
python3 start.py
```
*(También puedes darle permisos de ejecución con `chmod +x start.py` y correrlo como `./start.py`).*

Una vez iniciado, verás el menú principal con las siguientes opciones:

1. **Call Live API (Requires keys)**: Realiza consultas reales a Claude o Gemini. Debes tener tus API keys configuradas (ver sección de abajo).
2. **Live Session Monitor**: Ve en tiempo real qué sesiones de Claude Code están activas en esta máquina, cuánto está gastando cada una, y qué tan llena está su ventana de contexto (ver sección de abajo).
3. **Global Claude Usage (like /usage)**: Estado de tu suscripción de Claude y una foto fija de tu consumo en esta máquina, inspirada en el comando real `/usage` de Claude Code (ver sección de abajo).
4. **Claude Code Config (MCP & Hooks)**: Qué servidores MCP y qué hooks tienes configurados para este proyecto, inspirado en los comandos `/mcp` y `/hooks` (ver sección de abajo).
5. **Exit**: Cierra la aplicación.

Los precios por modelo viven en `tokens_counter/models_config.json` (editable a mano); ya no hay una pantalla de billetera/monedas ni un historial de llamadas dentro de la app — el costo de cada llamada real se muestra al momento, en la propia pantalla de resultado.

### 🔧 Tool-Use / MCP real en la Opción 1 (solo Claude)

Cuando eliges un modelo de Claude en la **Opción 1**, la app te pregunta si quieres **activar Tool-Use / MCP real** para esa llamada. Si aceptas, Claude puede invocar herramientas de verdad durante la conversación (no simuladas), y verás el desglose real de tokens y costo turno por turno al terminar:

- **Herramientas locales de demo** (opción por defecto, deja el campo de URL vacío): `get_current_time` (hora UTC), `calculate` (evalúa una expresión aritmética de forma segura) y `list_project_files` (lista los archivos `.py` del proyecto).
- **Servidor MCP remoto real**: si tienes tu propio servidor MCP, ingresa su URL (y un token de autorización opcional) cuando se te solicite. Claude usará el conector MCP de Anthropic para llamarlo directamente; la app registra los tokens reales que eso consume.

El costo real de la llamada (incluyendo el desglose por turno) se muestra al terminar, en la misma pantalla.

---

## 🔎 Live Session Monitor (Opción 2)

Muestra en tiempo real todas las sesiones de **Claude Code** activas o recientes en esta máquina (cualquier ventana/pestaña donde estés usando tu suscripción o API key de Claude, en cualquier proyecto), y cuánto ha consumido cada una — para que puedas controlar el gasto mientras trabajas.

Cómo funciona: Claude Code guarda automáticamente un transcript local por sesión en `~/.claude/projects/<proyecto>/<session-id>.jsonl` (y uno adicional por cada subagente/workflow que lances dentro de esa sesión). Esta opción lee esos archivos localmente — nunca sale nada de tu computador — y extrae **solo** metadatos de uso (modelo, tokens de entrada/salida/caché, timestamp); nunca lee ni muestra el contenido de tus prompts o respuestas.

Al entrar verás una tabla que se refresca sola cada pocos segundos con:

- **Status**: `● LIVE` si la sesión tuvo actividad en los últimos 5 minutos, `○ idle` si no.
- **Reqs**: número de turnos de la conversación principal, más cuántos subagentes/workflows lanzó (su consumo se suma al total de la sesión).
- **Session Tokens / Session Cost**: acumulado de toda la sesión (conversación principal + subagentes).
- **Last Prompt (in/out) / Last Prompt Cost**: tokens y costo del **último mensaje individual**, para ver en vivo cuánto cuesta cada petición a medida que la envías.
- **Context**: barra de color con el porcentaje de la ventana de contexto del modelo que está ocupando la conversación en este momento (lo mismo que muestra `/context` dentro de Claude Code). Se calcula con los tokens del último mensaje (input + cache read + cache write) contra el `context_window` del modelo en `models_config.json`. Verde por debajo de 50%, amarillo hasta 80%, rojo por encima.

Presiona **Ctrl+C** para detener el monitor y volver al menú.

**Notas:**
- El costo se calcula con las tarifas de `tokens_counter/models_config.json`. Si una sesión usa un modelo que no está en esa tabla, su costo se muestra como `N/A` (los tokens sí se cuentan). Puedes agregar o ajustar precios editando ese archivo directamente.
- Puedes apuntar el monitor a una ubicación distinta de `~/.claude` definiendo la variable de entorno `CLAUDE_CONFIG_DIR` antes de lanzar `start.py`, igual que hace Claude Code.
- El formato interno de estos archivos `.jsonl` es un detalle de implementación de Claude Code y podría cambiar en versiones futuras; si eso ocurre, el monitor simplemente mostrará menos datos en vez de fallar.

---

## 📊 Global Claude Usage (Opción 3)

Claude Code tiene su propio comando `/usage`, que muestra el costo y el desglose de tokens **de la sesión actual** ("Usage by model": tokens de entrada/salida/caché y costo por modelo — ver la [documentación oficial](https://code.claude.com/docs/en/costs#using-the-usage-command)). Esta opción hace lo mismo pero para **todas** las sesiones locales que encuentre en tu máquina, no solo la que tienes abierta, y además le agrega el estado de tu suscripción:

- **Claude Subscription Status**: cuenta, organización, tipo de plan (Free/Pro/Max/Team/Enterprise), seat tier, tier de rate-limit, y si tienes "extra usage" habilitado. Se lee de `~/.claude.json` (bloque `oauthAccount`) y `~/.claude/.credentials.json` (bloque `claudeAiOauth`) — **nunca** se lee ni se muestra tu access/refresh token, solo los metadatos de cuenta que los acompañan. Si esta máquina solo usa una API key (sin login de claude.ai), no hay nada que mostrar aquí y la app lo indica.
- **Recent Consumption**: cuántos tokens/costo real gastaste en las **últimas 5 horas** y en los **últimos 7 días** (ventana móvil real, sumada de tus transcripts locales) — el dato subyacente en el que se basan las ventanas de tu plan.
- **Total Estimated Cost** y **Total Requests**: sumados sobre todas las sesiones detectadas.
- **Usage by Model**: la misma idea que la lista de `/usage` (`modelo: input, output, cache read, cache write ($costo)`), pero agregada globalmente.
- **By Project**: desglose adicional por carpeta de proyecto (esto no existe en `/usage`, pero como esta app ve todas las sesiones a la vez, tiene sentido mostrarlo).

**Limitación honesta:** esta opción **no** puede mostrar el porcentaje exacto de tu límite de plan usado ni la hora en que se reinicia tu ventana de 5 horas / semanal — eso sí lo muestra `/usage` en cuentas Pro/Max/Team/Enterprise. Investigué a fondo si ese % o esa hora de reinicio quedan cacheados en algún archivo local (revisé `~/.claude.json`, `~/.claude/.credentials.json`, `~/.claude/policy-limits.json`) y no encontré nada: Anthropic calcula ese % contra una cuota por tier que no es pública, y lo hace en su servidor en el momento — no queda guardado en disco en ningún lado que esta app pueda leer. Lo que sí puedo mostrarte honestamente es "Recent Consumption" (arriba), que es el consumo real que alimentaría ese cálculo, sin fingir saber el % ni la hora exacta de reinicio.

---

## 🔧 Claude Code Config: MCP & Hooks (Opción 4)

Inspirada en los comandos `/mcp` y `/hooks` de Claude Code. Muestra:

- **Servidores MCP configurados**: leídos de `.mcp.json` en la raíz del proyecto (donde ejecutas `python3 start.py`) y de tu `~/.claude.json` (tanto servidores globales como los específicos de este proyecto).
- **Hooks configurados**: leídos de `.claude/settings.json` y `.claude/settings.local.json` del proyecto, y de tu `~/.claude/settings.json` de usuario — evento, matcher, y cuántos comandos tiene cada hook.

**Limitación honesta:** esta opción no lee políticas de configuración administradas a nivel de organización (managed settings / managed MCP), solo el alcance de proyecto + usuario. Como el resto de la app, es de solo lectura: nunca modifica tu configuración.

---

## 🔑 Configuración de APIs Reales

Para usar la **Opción 1** (llamadas reales, con o sin Tool-Use/MCP), configura tus claves de API como variables de entorno:

**En Linux / macOS:**
```bash
export ANTHROPIC_API_KEY="tu-clave-aqui"
export GEMINI_API_KEY="tu-clave-aqui"
```

**En Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY="tu-clave-aqui"
$env:GEMINI_API_KEY="tu-clave-aqui"
```

Puedes configurar solo una de las dos claves: la app detecta cuál proveedor está disponible y deshabilita el otro en el menú.

---

## 🧪 Tests

```bash
python3 -m unittest tests.test_calculator
```
