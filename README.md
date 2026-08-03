# 📊 Token Usage & Cost Visualizer

Un visualizador de terminal (TUI) del uso y costo real de **Claude Code** en tu máquina: qué sesiones están activas, cuánto han gastado, qué tan llena está su ventana de contexto, el estado de tu suscripción, y qué servidores MCP/hooks tienes configurados.

Esta app **no hace llamadas a ninguna API** y **no necesita ninguna clave**. Es de solo lectura: todo lo que muestra viene de leer los transcripts y archivos de configuración que **Claude Code ya guarda localmente** en tu máquina (`~/.claude/projects`, `~/.claude.json`, `.mcp.json`, `.claude/settings.json`). No hay modo simulado/estimado, ni mecánicas de juego, ni nada que se conecte a internet por su cuenta.

---

## 🚀 Instalación

Asegúrate de tener Python 3.8+ instalado en tu sistema. Se recomienda crear un entorno virtual (no se versiona en git):

```bash
python3 -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

La única dependencia es `rich` (la interfaz de terminal). No se necesita ninguna API key.

---

## Uso

Ejecuta el script de lanzamiento desde la raíz del proyecto:

```bash
python3 start.py
```
*(También puedes darle permisos de ejecución con `chmod +x start.py` y correrlo como `./start.py`).*

Una vez iniciado, verás el menú principal con las siguientes opciones:

1. **Live Session Monitor**: Ve en tiempo real qué sesiones de Claude Code están activas en esta máquina, cuánto está gastando cada una, y qué tan llena está su ventana de contexto (ver sección de abajo).
2. **Global Claude Usage (like /usage)**: Estado de tu suscripción de Claude y una foto fija de tu consumo en esta máquina, inspirada en el comando real `/usage` de Claude Code (ver sección de abajo).
3. **Claude Code Config (MCP & Hooks)**: Qué servidores MCP y qué hooks tienes configurados para este proyecto, inspirado en los comandos `/mcp` y `/hooks` (ver sección de abajo).
4. **Subagent Breakdown**: Elegís una sesión y ves, subagente por subagente, exactamente cuántos tokens/cuánto costó cada invocación individual (cada llamada a la herramienta "Task") (ver sección de abajo).
5. **Exit**: Cierra la aplicación.

Los precios por modelo de Claude viven en `tokens_counter/models_config.json` (editable a mano) — de ahí sale el costo que ves en las Opciones 1 y 2.

---

## 🔎 Live Session Monitor (Opción 1)

Muestra en tiempo real todas las sesiones de **Claude Code** activas o recientes en esta máquina (cualquier ventana/pestaña donde estés usando Claude Code, en cualquier proyecto), y cuánto ha consumido cada una — para que puedas controlar el gasto mientras trabajas.

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

## 📊 Global Claude Usage (Opción 2)

Claude Code tiene su propio comando `/usage`, que muestra el costo y el desglose de tokens **de la sesión actual** ("Usage by model": tokens de entrada/salida/caché y costo por modelo — ver la [documentación oficial](https://code.claude.com/docs/en/costs#using-the-usage-command)). Esta opción hace lo mismo pero para **todas** las sesiones locales que encuentre en tu máquina, no solo la que tienes abierta, y además le agrega el estado de tu suscripción.

**Se refresca sola** cada pocos segundos (igual que el Live Session Monitor) — no necesitas salir y volver a entrar para ver los minutos/porcentajes actualizados. Presiona **Ctrl+C** para detenerla y volver al menú.

Contenido:

- **Claude Subscription Status**: cuenta, organización, tipo de plan (Free/Pro/Max/Team/Enterprise), seat tier, tier de rate-limit, y si tienes "extra usage" habilitado. Se lee de `~/.claude.json` (bloque `oauthAccount`) y `~/.claude/.credentials.json` (bloque `claudeAiOauth`) — **nunca** se lee ni se muestra tu access/refresh token, solo los metadatos de cuenta que los acompañan. Si esta máquina solo usa una API key (sin login de claude.ai), no hay nada que mostrar aquí y la app lo indica.
- **Recent Consumption**: cuántos tokens/costo real gastaste en las **últimas 5 horas** y en los **últimos 7 días** (ventana móvil real, sumada de tus transcripts locales) — el dato subyacente en el que se basan las ventanas de tu plan.
- **Time-in-Window %**: para cada ventana (5h y 7 días), busca la petición real **más antigua que todavía sigue dentro** de esa ventana y muestra hace cuánto ocurrió: a qué hora (local, "Window Started") y cuánto tiempo lleva ahí ("Time Elapsed"), como un **% del tiempo total de la ventana**. Este % crece mientras sigues usando Claude Code de forma continua, y baja de nuevo cuando esa actividad antigua finalmente sale de la ventana sin que haya nada más reciente que la reemplace. Si la ventana está vacía (no has usado Claude Code en ese período), lo dice explícitamente en vez de inventar un número.
  - **Importante sobre el "%"**: es un **% de cuánto tiempo de la ventana está ocupado por actividad real tuya**, **no** el % de tu cuota de plan gastada — este dato no es lo mismo que "cuántos tokens/mensajes te quedan", solo cuánto tiempo real llevas usando Claude Code dentro de esa ventana. El título de la tabla y una nota de una línea debajo lo dejan explícito, precisamente porque comparar este % contra el "% used" real que muestra Claude Code (calculado en su servidor contra tu cuota de plan) es un error fácil de cometer si no se aclara.
  - El % se muestra con 2 decimales y el tiempo transcurrido incluye segundos (ej. `2h 14m 08s`) para que veas el avance en cada refresco de 5 segundos, en vez de que parezca congelado por minutos.
- **Total Estimated Cost** y **Total Requests**: sumados sobre todas las sesiones detectadas.
- **Usage by Model**: la misma idea que la lista de `/usage` (`modelo: input, output, cache read, cache write ($costo)`), pero agregada globalmente. Ordenado por costo, muestra hasta 8 modelos con una fila "+N more" si hay más (para que la vista en vivo no crezca más que una terminal típica).
- **By Project**: desglose adicional por carpeta de proyecto (esto no existe en `/usage`, pero como esta app ve todas las sesiones a la vez, tiene sentido mostrarlo). También limitado a 8 filas con "+N more" si aplica.

**Cómo calculo "Time-in-Window %"**: la primera versión intentaba adivinar "cuándo empezó tu sesión" buscando huecos de inactividad — engañoso, porque cualquier pausa de 5+ horas hacía que pareciera "recién empezada". Una segunda versión anclaba a tu petición **más reciente** y hacía una cuenta regresiva hasta que esa petición saliera de la ventana — matemáticamente correcto, pero como cada mensaje nuevo empuja ese momento hacia adelante, mientras estás trabajando activamente la cuenta regresiva nunca bajaba (parecía congelada). Esta versión ancla a tu petición **más antigua que sigue dentro de la ventana** y mide cuánto tiempo lleva ahí — así el tiempo/porcentaje crece de forma continua con tu uso real, sin reiniciarse en cada mensaje.

**Limitación honesta:** esta opción **no** puede mostrar el porcentaje exacto de tu límite de plan usado ni la hora exacta de reinicio que calcula Anthropic en su servidor contra una cuota por tier que no es pública. Investigué a fondo (`~/.claude.json`, `~/.claude/.credentials.json`, `~/.claude/policy-limits.json`) y confirmé que ese % y esa cuota no quedan cacheados en ningún archivo local. "Time-in-Window %" es lo más cercano y honesto que puedo calcular con datos 100% locales; solo el comando real `/usage` dentro de Claude Code puede mostrarte el % y reinicio autoritativos de tu plan.

---

## 🔧 Claude Code Config: MCP & Hooks (Opción 3)

Inspirada en los comandos `/mcp` y `/hooks` de Claude Code. Muestra:

- **Servidores MCP configurados**: leídos de `.mcp.json` en la raíz del proyecto (donde ejecutas `python3 start.py`) y de tu `~/.claude.json` (tanto servidores globales como los específicos de este proyecto).
- **Hooks configurados**: leídos de `.claude/settings.json` y `.claude/settings.local.json` del proyecto, y de tu `~/.claude/settings.json` de usuario — evento, matcher, y cuántos comandos tiene cada hook.
- **MCP Tool Usage**: cuánto has usado realmente cada servidor MCP configurado, escaneando todas tus transcripciones locales en busca de llamadas reales a herramientas (`tool_use`) cuyo nombre empiece con `mcp__<servidor>__<herramienta>`. Muestra, por servidor: qué herramientas llamaste y cuántas veces (**Calls**, exacto), y el costo de los turnos que usaron ese servidor al menos una vez (**Turn Cost**).
  - **Importante sobre "Turn Cost"**: Claude cobra por **turno** (todo el mensaje del asistente), no por llamada a herramienta individual, y un solo turno puede llamar a varias herramientas — incluso de servidores MCP distintos — junto con su propio texto/razonamiento. Por eso "Turn Cost" es el costo de los turnos que usaron ese servidor, no un costo exacto por llamada: si un turno toca dos servidores, ese turno se cuenta en ambos. Solo **Calls** (cuántas veces se ejecutó cada herramienta) es un número exacto.

**Limitación honesta:** esta opción no lee políticas de configuración administradas a nivel de organización (managed settings / managed MCP), solo el alcance de proyecto + usuario. Como el resto de la app, es de solo lectura: nunca modifica tu configuración ni lee los argumentos/resultados de las llamadas a herramientas, solo su nombre.

---

## 🧩 Subagent Breakdown (Opción 4)

El Live Session Monitor (Opción 1) suma el consumo de todos los subagentes de una sesión en un solo total. Esta opción lo desglosa: elegís una sesión de la lista (solo aparecen las que tienen al menos un subagente) y ves una tabla que se refresca sola con **una fila por subagente**, mostrando:

- **Agent Type**: qué tipo de subagente fue (`Explore`, `general-purpose`, etc.).
- **Task**: la descripción corta de la tarea que se le asignó — la misma etiqueta de una línea que ya se ve en la transcripción de Claude Code para cada llamada a la herramienta "Task". Nunca se lee ni se muestra el prompt/respuesta real del subagente, igual que en el resto de la app.
- **Model(s)**, **Reqs**, **Tokens (In/Out)**, **Cache (Read/Write)** y **Cost**: el consumo real de esa invocación puntual, calculado con las mismas tarifas de `models_config.json`.

Cómo funciona: Claude Code guarda cada subagente en su propio archivo `<session-id>/subagents/**/*.jsonl`, más un `.meta.json` al lado con el `agentType` y la descripción de la tarea. Esta opción lee ambos por separado en vez de fusionarlos en el total de la sesión.

Presiona **Ctrl+C** para detener y volver al menú.

---

## 🧪 Tests

```bash
python3 -m unittest tests.test_calculator
```
