# 📊 Token Usage & Cost Visualizer

[![CI](https://github.com/FaberGrisales/TokensCounterBy/actions/workflows/ci.yml/badge.svg)](https://github.com/FaberGrisales/TokensCounterBy/actions/workflows/ci.yml)

Un visualizador de terminal (TUI) del uso y costo real de **Claude Code**, **Claude Desktop** y **OpenCode** en tu máquina: qué sesiones están activas, cuánto han gastado, qué tan llena está su ventana de contexto, el porcentaje real de tu plan (5h y 7 días), el estado de tu suscripción y qué servidores MCP/hooks tienes configurados. Incluye una **ventana flotante** siempre visible con todo eso más el uso de tu equipo (CPU, RAM, GPU, disco).

Funciona en **Windows, macOS y Linux** — verificado en cada uno con CI (ver [Plataformas](#-plataformas)).

Esta app **no hace llamadas a ninguna API** y **no necesita ninguna clave**. Todo lo que muestra viene de leer los archivos que **Claude Code, Claude Desktop y OpenCode ya guardan localmente** en tu máquina (`~/.claude/projects`, `~/.claude.json`, `.mcp.json`, `.claude/settings.json`, el perfil local de Claude Desktop y la base de datos de OpenCode). No hay modo simulado/estimado, ni mecánicas de juego, ni nada que se conecte a internet por su cuenta.

Las Opciones 1-4 y 6 son de solo lectura. Hay dos excepciones, y las dos piden confirmación explícita antes de tocar nada: la **Opción 5** (Cleanup), que puede **borrar** transcripts de sesiones viejas, y la **Opción 7** (Real Plan Limits), que **escribe** una clave en tu `~/.claude/settings.json` (con copia de seguridad previa) para capturar tus límites reales.

---

## 📋 Requisitos

| | Requisito | Notas |
|---|---|---|
| **Sistema operativo** | Windows, macOS o Linux | Corriendo directamente en el sistema (en Windows, con Python de Windows). WSL no está soportado |
| **Python** | 3.8 o superior | Se valida al arrancar y aborta con un mensaje claro si es menor |
| **`rich`** | Requerido | La única dependencia obligatoria. La app la instala por ti si falta |
| **`tkinter`** | Opcional | **Solo** para la Opción 6 (ventana flotante). Todo lo demás funciona sin él |
| **`psutil`** | Opcional | **Solo** para CPU, RAM y disco en la ventana flotante (la GPU no lo necesita). Si falta, la Opción 6 te ofrece instalarlo |
| **Claude Code, Claude Desktop y/o OpenCode** | Usado alguna vez en esta máquina | Con Claude Code ves tokens, costo y contexto por sesión. Con Claude Desktop ves el % real de tu plan y la actividad de tus chats. Con OpenCode ves sus sesiones, modelos y tokens |
| **Red / API keys** | **Ninguna** | La app no hace ni una sola llamada de red y no usa ninguna clave |

### Sobre `tkinter` por sistema operativo

`tkinter` **no es un paquete de pip** — `pip install tkinter` instala un paquete abandonado y sin relación, que no sirve. Viene con Python o se instala con el sistema:

| Sistema | Situación |
|---|---|
| **Windows** | Ya viene con Python de python.org. Si faltara: re-ejecuta el instalador → Modify → marca `tcl/tk and IDLE` |
| **macOS** | Ya viene con Python de python.org. Con Homebrew: `brew install python-tk` |
| **Linux (Debian/Ubuntu)** | `sudo apt install python3-tk` |
| **Linux (Fedora/RHEL)** | `sudo dnf install python3-tkinter` |
| **Linux (Arch)** | `sudo pacman -S tk` |
| **Linux (openSUSE)** | `sudo zypper install python3-tk` |

No necesitas memorizar ninguno de estos: la app detecta tu gestor de paquetes y te ofrece correr el comando correcto.

---

## 🚀 Instalación

```bash
git clone git@github.com:FaberGrisales/TokensCounterBy.git
cd TokensCounterBy

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

En **Windows** (PowerShell o CMD):

```powershell
git clone https://github.com/FaberGrisales/TokensCounterBy.git
cd TokensCounterBy

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

**Ese último paso es opcional.** Al arrancar, la app verifica sus dependencias sola:

- Si falta **`rich`**, te muestra el comando exacto y te ofrece instalarlo antes de continuar.
- Si falta **`tkinter`** o **`psutil`**, te lo avisa en el menú y te ofrece instalarlo cuando elijas la Opción 6.

Nunca instala nada sin que le digas que sí, y siempre te enseña el comando antes de correrlo. En Linux, instalar `tkinter` usa el gestor de paquetes del sistema y te va a pedir tu contraseña — eso es normal y es la razón por la que se pide confirmación en vez de hacerlo en silencio.

---

## Uso

Ejecuta el script de lanzamiento desde la raíz del proyecto:

```bash
python3 start.py        # En Windows: python start.py
```
*(En Linux/macOS también puedes darle permisos de ejecución con `chmod +x start.py` y correrlo como `./start.py`).*

Una vez iniciado, verás el menú principal con las siguientes opciones:

1. **Live Session Monitor**: Ve en tiempo real qué sesiones de Claude Code y de OpenCode están activas en esta máquina, cuánto está gastando cada una, y qué tan llena está la ventana de contexto de las de Claude (ver sección de abajo).
2. **Global Claude Usage (like /usage)**: Estado de tu suscripción de Claude y una foto fija de tu consumo en esta máquina, inspirada en el comando real `/usage` de Claude Code (ver sección de abajo).
3. **Claude Code Config (MCP & Hooks)**: Qué servidores MCP y qué hooks tienes configurados para este proyecto, inspirado en los comandos `/mcp` y `/hooks` (ver sección de abajo).
4. **Session Breakdown**: Elegís una sesión y ves, subagente por subagente y **llamada MCP por llamada MCP**, exactamente cuántos tokens/cuánto costó cada invocación individual (ver sección de abajo).
5. **Cleanup Inactive Sessions**: Borra permanentemente sesiones locales sin actividad hace 7+ días, con selección manual y confirmación explícita (ver sección de abajo).
6. **Floating Monitor**: Abre una ventana pequeña que se queda **encima de las demás ventanas** con el uso de tu equipo (CPU, RAM, GPU, disco), el % real de tu plan, tus sesiones de Claude Code y la actividad de Claude Desktop, para verlo mientras trabajas en otra aplicación (ver sección de abajo).
7. **Enable Real Plan Limits**: Activa la captura de tus porcentajes reales de límite de plan (5h y 7 días) desde Claude Code (ver sección de abajo).
8. **Exit**: Cierra la aplicación.

### 🧭 Primeros pasos (recomendado)

**Si usas Claude Desktop**, no tienes que configurar nada: Desktop guarda el porcentaje real de tu plan y la app lo lee directamente. Abre la Opción 6 y listo.

**Si solo usas Claude Code**, la primera vez, en este orden:

1. **Opción 7 — Enable Real Plan Limits.** Instala un pequeño script en tu status line de Claude Code que captura tus porcentajes reales de límite (5h y 7 días). Te muestra exactamente qué va a escribir y te pide confirmación.
2. **Reinicia Claude Code.** Lee su configuración solo al arrancar, así que sin reiniciar el script no se ejecuta.
3. **Usa Claude Code un momento** (cualquier sesión). La primera lectura llega cuando Claude Code dibuja su status line.
4. **Opción 2 o Opción 6.** Ahí ya verás tus porcentajes reales en vez del gasto total.

Si en el paso 4 sigues viendo solo dólares, vuelve a la Opción 7: diagnostica qué está mal y te ofrece repararlo.

Todo lo demás (Opciones 1, 3, 4 y 5) funciona desde el primer momento sin configurar nada.

Los precios por modelo de Claude viven en `tokens_counter/models_config.json` (editable a mano) — de ahí sale el costo que ves en las Opciones 1 y 2.

---

## 🔎 Live Session Monitor (Opción 1)

Muestra en tiempo real todas las sesiones de **Claude Code** activas o recientes en esta máquina (cualquier ventana/pestaña donde estés usando Claude Code, en cualquier proyecto), y cuánto ha consumido cada una — para que puedas controlar el gasto mientras trabajas.

Cómo funciona: Claude Code guarda automáticamente un transcript local por sesión en `~/.claude/projects/<proyecto>/<session-id>.jsonl` (y uno adicional por cada subagente/workflow que lances dentro de esa sesión). Esta opción lee esos archivos localmente — nunca sale nada de tu computador — y extrae **solo** metadatos de uso (modelo, tokens de entrada/salida/caché, timestamp); nunca lee ni muestra el contenido de tus prompts o respuestas.

Al entrar verás una tabla que se refresca sola **cada 2 segundos** con:

- **Status**: `● LIVE` si la sesión tuvo actividad en los últimos 5 minutos, `○ idle` si no.
- **Reqs**: número de turnos de la conversación principal, más cuántos subagentes/workflows lanzó (su consumo se suma al total de la sesión).
- **Session Tokens / Session Cost**: acumulado de toda la sesión (conversación principal + subagentes).
- **Last Prompt (in/out) / Last Prompt Cost**: tokens y costo del **último mensaje individual**, para ver en vivo cuánto cuesta cada petición a medida que la envías.
- **Context**: barra de color con el porcentaje de la ventana de contexto del modelo que está ocupando la conversación en este momento (lo mismo que muestra `/context` dentro de Claude Code). Se calcula con los tokens del último mensaje (input + cache read + cache write) contra el `context_window` del modelo en `models_config.json`. Verde por debajo de 50%, amarillo hasta 80%, rojo por encima.

Presiona **Ctrl+C** para detener el monitor y volver al menú.

**Sesiones de OpenCode.** Si usas [OpenCode](https://opencode.ai), sus sesiones aparecen en la misma tabla marcadas `OpenCode ·`, con sus modelos (`proveedor/modelo`, p. ej. `opencode/big-pickle`, `openrouter/openai/gpt-oss-120b`, `ollama/qwen3.6`) y sus tokens. Se leen de su base de datos local (`~/.local/share/opencode/opencode.db`, la misma ruta en Windows, macOS y Linux), en modo de solo lectura:

- **Costo**: el que calcula OpenCode mismo. Si usas un modelo de pago a través de OpenCode (Claude, ChatGPT, Gemini…), ves lo que gastaste; con modelos gratuitos o locales dice `free`.
- **Sin % de contexto** (`N/A`): OpenCode no deja registrado cuánto de la ventana de contexto ocupa cada sesión.
- Los subagentes de OpenCode se suman a su sesión principal, igual que en Claude Code.
- Nunca lee el texto de tus conversaciones ni sus credenciales (`auth.json`).

Las Opciones 2, 4 y 5 siguen siendo solo de Claude Code.

**Se adapta al tamaño de tu terminal.** Si la achicas, la vista cambia sola en el siguiente refresco en vez de volverse ilegible:

| Ancho de la terminal | Qué ves |
|---|---|
| 100 columnas o más | La tabla completa, con todas las columnas de arriba |
| Entre 50 y 99 | Tabla compacta: estado, proyecto, tokens, costo y contexto |
| Menos de 50 | Una lista con cada sesión en dos líneas cortas |

En los modos angostos los números se abrevian (`933.1K`, `1.2M`), y un costo menor a un centavo sale como `<$0.01`, nunca como `$0.00` (que se leería como "gratis").

**Notas:**
- El costo se calcula con las tarifas de `tokens_counter/models_config.json`. Si una sesión usa un modelo que no está en esa tabla, su costo se muestra como `N/A` (los tokens sí se cuentan). Puedes agregar o ajustar precios editando ese archivo directamente.
- Puedes apuntar el monitor a una ubicación distinta de `~/.claude` definiendo la variable de entorno `CLAUDE_CONFIG_DIR` antes de lanzar `start.py`, igual que hace Claude Code.
- El formato interno de estos archivos `.jsonl` es un detalle de implementación de Claude Code y podría cambiar en versiones futuras; si eso ocurre, el monitor simplemente mostrará menos datos en vez de fallar.

---

## 📊 Global Claude Usage (Opción 2)

Claude Code tiene su propio comando `/usage`, que muestra el costo y el desglose de tokens **de la sesión actual** ("Usage by model": tokens de entrada/salida/caché y costo por modelo — ver la [documentación oficial](https://code.claude.com/docs/en/costs#using-the-usage-command)). Esta opción hace lo mismo pero para **todas** las sesiones locales que encuentre en tu máquina, no solo la que tienes abierta, y además le agrega el estado de tu suscripción.

**Se refresca sola** cada 5 segundos — no necesitas salir y volver a entrar para ver los minutos/porcentajes actualizados. Presiona **Ctrl+C** para detenerla y volver al menú.

Contenido:

- **Claude Subscription Status**: cuenta, organización, tipo de plan (Free/Pro/Max/Team/Enterprise), seat tier, tier de rate-limit, y si tienes "extra usage" habilitado. Se lee de `~/.claude.json` (bloque `oauthAccount`) y `~/.claude/.credentials.json` (bloque `claudeAiOauth`) — **nunca** se lee ni se muestra tu access/refresh token, solo los metadatos de cuenta que los acompañan. Si esta máquina solo usa una API key (sin login de claude.ai), no hay nada que mostrar aquí y la app lo indica.
- **Recent Consumption**: cuántos tokens/costo real gastaste en las **últimas 5 horas** y en los **últimos 7 días** (ventana móvil real, sumada de tus transcripts locales) — el dato subyacente en el que se basan las ventanas de tu plan.
- **Time-in-Window %**: para cada ventana (5h y 7 días), busca la petición real **más antigua que todavía sigue dentro** de esa ventana y muestra hace cuánto ocurrió: a qué hora (local, "Window Started") y cuánto tiempo lleva ahí ("Time Elapsed"), como un **% del tiempo total de la ventana**. Este % crece mientras sigues usando Claude Code de forma continua, y baja de nuevo cuando esa actividad antigua finalmente sale de la ventana sin que haya nada más reciente que la reemplace. Si la ventana está vacía (no has usado Claude Code en ese período), lo dice explícitamente en vez de inventar un número.
  - **Importante sobre el "%"**: es un **% de cuánto tiempo de la ventana está ocupado por actividad real tuya**, **no** el % de tu cuota de plan gastada — este dato no es lo mismo que "cuántos tokens/mensajes te quedan", solo cuánto tiempo real llevas usando Claude Code dentro de esa ventana. El título de la tabla y una nota de una línea debajo lo dejan explícito, precisamente porque comparar este % contra el "% used" real que muestra Claude Code (calculado en su servidor contra tu cuota de plan) es un error fácil de cometer si no se aclara.
  - El % se muestra con 2 decimales y el tiempo transcurrido incluye segundos (ej. `2h 14m 08s`) para que veas el avance en cada refresco de 5 segundos, en vez de que parezca congelado por minutos.
  - **Window Ends**: cuándo esa petición más antigua sale de la ventana ("Window Started" + 5 horas, o + 7 días), con una cuenta regresiva debajo (`in 1h14m`). Ojo: **no es un reinicio de cuota**. Cuando llega esa hora, la ventana simplemente pasa a medirse desde la siguiente petición más antigua.
- **Plan Limit Used (real)**: el porcentaje **real** de tu límite de plan de 5 horas y de 7 días, y cuándo se reinicia (`resets Sep 15 00:50`). Estos sí son los números de Anthropic, los mismos que ves en `/usage`. Salen de **Claude Desktop** (que los guarda solo, sin configurar nada; la hora de reinicio es estimada y lleva `~`) o de la **Opción 7** (con hora exacta); si hay las dos, gana la lectura más reciente. Sin ninguna de las dos la columna no aparece. Debajo de la tabla se indica de dónde y hace cuánto se capturó la lectura.
- **Total Estimated Cost** y **Total Requests**: sumados sobre todas las sesiones detectadas.
- **Usage by Model**: la misma idea que la lista de `/usage` (`modelo: input, output, cache read, cache write ($costo)`), pero agregada globalmente. Ordenado por costo, muestra hasta 8 modelos con una fila "+N more" si hay más (para que la vista en vivo no crezca más que una terminal típica).
- **By Project**: desglose adicional por carpeta de proyecto (esto no existe en `/usage`, pero como esta app ve todas las sesiones a la vez, tiene sentido mostrarlo). También limitado a 8 filas con "+N more" si aplica.

**Cómo calculo "Time-in-Window %"**: la primera versión intentaba adivinar "cuándo empezó tu sesión" buscando huecos de inactividad — engañoso, porque cualquier pausa de 5+ horas hacía que pareciera "recién empezada". Una segunda versión anclaba a tu petición **más reciente** y hacía una cuenta regresiva hasta que esa petición saliera de la ventana — matemáticamente correcto, pero como cada mensaje nuevo empuja ese momento hacia adelante, mientras estás trabajando activamente la cuenta regresiva nunca bajaba (parecía congelada). Esta versión ancla a tu petición **más antigua que sigue dentro de la ventana** y mide cuánto tiempo lleva ahí — así el tiempo/porcentaje crece de forma continua con tu uso real, sin reiniciarse en cada mensaje.

**Sobre el porcentaje real de tu plan:** Anthropic lo calcula en su servidor contra una cuota por tier que no es pública, y no queda guardado en ningún archivo local (se revisaron `~/.claude.json`, `~/.claude/.credentials.json` y `~/.claude/policy-limits.json`). Por eso esta app no puede leerlo directamente de tus archivos. Lo que sí puede hacer es recibirlo de Claude Code a través de su status line — eso es lo que activa la **Opción 7**, y es de donde sale la columna **Plan Limit Used (real)**.

Sin la Opción 7, lo más honesto que la app puede calcular con datos 100% locales es "Time-in-Window %" y "Window Ends" — útiles, pero **ninguno de los dos es tu cuota**.

### Tu propio presupuesto (columna "vs Your Budget")

La app **no puede** mostrarte el porcentaje de límite de tu plan: ese número se calcula en el servidor de Anthropic contra una cuota por tier que no está documentada y que no está guardada en ningún archivo local (se verificó `~/.claude.json`, `.credentials.json` y `policy-limits.json`). Inventar un denominador daría un número creíble y falso.

Lo que sí puede hacer es compararte contra **un límite que tú definas**. Edita `tokens_counter/budget_config.json`:

```json
{
    "5h": { "tokens": 40000000, "cost_usd": null },
    "7d": { "tokens": null,     "cost_usd": 200 }
}
```

- `tokens` cuenta entrada + salida + lectura de caché + escritura de caché.
- `cost_usd` es en dólares, con las tarifas de `models_config.json`.
- Si defines los dos en una ventana, manda `tokens`.
- Deja `null` (o borra el archivo) y la columna simplemente no aparece.

La barra se pone verde por debajo del 50%, amarilla hasta 80% y roja por encima — y **no se detiene en 100%**: pasarte de tu propio presupuesto es justo lo que quieres ver.

Los cambios al archivo se recogen en el siguiente refresco, sin reiniciar la app.

---

## 🔧 Claude Code Config: MCP & Hooks (Opción 3)

Inspirada en los comandos `/mcp` y `/hooks` de Claude Code. Muestra:

- **Servidores MCP configurados**: leídos de `.mcp.json` en la raíz del proyecto (donde ejecutas `python3 start.py`) y de tu `~/.claude.json` (tanto servidores globales como los específicos de este proyecto).
- **Hooks configurados**: leídos de `.claude/settings.json` y `.claude/settings.local.json` del proyecto, y de tu `~/.claude/settings.json` de usuario — evento, matcher, y cuántos comandos tiene cada hook.

**Limitación honesta:** esta opción no lee políticas de configuración administradas a nivel de organización (managed settings / managed MCP), solo el alcance de proyecto + usuario. Como el resto de la app, es de solo lectura: nunca modifica tu configuración.

(¿Buscas cuánto ha consumido realmente cada llamada MCP? Eso vive en la Opción 4 — ver abajo — porque el consumo real solo tiene sentido a nivel de una sesión/turno concreto, no como un listado de configuración.)

---

## 🧩 Session Breakdown (Opción 4)

El Live Session Monitor (Opción 1) suma el consumo de todos los subagentes y llamadas MCP de una sesión en un solo total. Esta opción lo desglosa: elegís una sesión de la lista y ves dos tablas que se refrescan solas:

**Subagents** — una fila por subagente:
- **Agent Type**: qué tipo de subagente fue (`Explore`, `general-purpose`, etc.).
- **Task**: la descripción corta de la tarea que se le asignó — la misma etiqueta de una línea que ya se ve en la transcripción de Claude Code para cada llamada a la herramienta "Task". Nunca se lee ni se muestra el prompt/respuesta real del subagente, igual que en el resto de la app.
- **Model(s)**, **Reqs**, **Tokens (In/Out)**, **Cache (Read/Write)** y **Cost**: el consumo real de esa invocación puntual, calculado con las mismas tarifas de `models_config.json`.

Cómo funciona: Claude Code guarda cada subagente en su propio archivo `<session-id>/subagents/**/*.jsonl`, más un `.meta.json` al lado con el `agentType` y la descripción de la tarea. Esta opción lee ambos por separado en vez de fusionarlos en el total de la sesión.

**MCP Calls** — una fila por **cada turno/instrucción real** dentro de esa sesión que ejecutó al menos una llamada a una herramienta MCP (nombre `mcp__<servidor>__<herramienta>`), ordenado del más reciente:
- **Time / Source**: cuándo ocurrió y si fue en la conversación principal o en un subagente.
- **Tool(s) Called**: qué herramienta(s) MCP se llamaron en ese turno (solo el nombre — nunca los argumentos ni el resultado de la llamada).
- **Tokens (In/Out) / Turn Cost**: el consumo real de ese turno específico.
  - **Importante sobre "Turn Cost"**: Claude cobra por **turno** completo (todo el mensaje del asistente), no por llamada a herramienta individual, y un solo turno puede llamar a varias herramientas — incluso de servidores MCP distintos — junto con su propio texto/razonamiento. Por eso es el costo del turno que hizo esa llamada, no un costo aislado exacto solo de la llamada; si un turno toca dos servidores, ambos figuran con ese mismo turno. La lista de qué herramientas se llamaron sí es exacta.

Presiona **Ctrl+C** para detener y volver al menú.

---

## 🗑️ Cleanup Inactive Sessions (Opción 5)

Con el tiempo, `~/.claude/projects` acumula un transcript por cada sesión que abriste alguna vez. Esta opción te deja borrar los que ya no te sirven — **es la única acción destructiva de toda la app**, así que tiene varias capas de seguridad antes de tocar un solo archivo.

Cómo funciona:

1. Busca sesiones **sin ninguna actividad en los últimos 7 días** (un umbral distinto y mucho más largo que el de 5 minutos que separa `● LIVE` de `○ idle` en el resto de la app) y las muestra en una tabla, ordenadas de la más vieja a la más reciente, con cuánto tiempo lleva inactiva, sus tokens y su costo acumulado.
2. Elegís cuáles borrar escribiendo los números separados por coma (`1,3,5`), `all` para todas las de la lista, o `c` para cancelar sin tocar nada.
3. Antes de borrar, te muestra la lista exacta de lo que vas a eliminar y te pide escribir **`DELETE`** (la palabra completa, en mayúsculas) para confirmar. Cualquier otra cosa cancela.
4. Borra el archivo `.jsonl` principal de cada sesión elegida, y si tenía subagentes, también su carpeta `<session-id>/subagents/`.

**Esto es permanente.** Una vez borrado, ni esta app ni Claude Code pueden recuperar ese historial — no hay papelera de reciclaje. Las sesiones con actividad reciente (menos de 7 días) nunca aparecen en la lista, así que no hay riesgo de borrar algo que estés usando activamente.

---

## 📌 Floating Monitor (Opción 6)

Funciona tanto si usas **Claude Code** como **Claude Desktop** (o los dos). Si usas Claude Desktop, el porcentaje real de tu plan aparece sin configurar nada; si solo usas Claude Code, activa antes la Opción 7 para verlo.

Una ventana pequeña (440×232) que se mantiene **siempre encima** del resto de ventanas, para dejarla en una esquina y seguir trabajando en el navegador o el editor sin perder de vista tu consumo. Se refresca sola cada 3 segundos.

```
CPU 51%   RAM 23.0/31.6 GB   GPU 5%   Disk 294 KB/s   Claude 0.6 GB
● 2 live   ○ 4 idle           5h 74% · 7d 17% · resets ~3h35m
●  chat  Resumen reunión…                      active 1m ago
●  code  TokensCounterBy        1.4M   $224.83    20%
○  desk  integracion-coti     297.7K     $6.50    76%
```

**La primera línea** muestra el uso de tu equipo, como el Administrador de tareas: **CPU**, **RAM** usada/total, **GPU** (la del motor más ocupado, igual que el Administrador de tareas), actividad del **disco** (MB/s leídos + escritos, no cuánto espacio ocupa) y cuánta RAM usan los procesos de **Claude** (Desktop y Claude Code). CPU, RAM y GPU se ponen amarillas desde 50% y rojas desde 80%. CPU, RAM y disco necesitan `psutil`; la GPU no necesita nada. En Windows la GPU funciona con cualquier marca; en Linux, con NVIDIA (`nvidia-smi`) y AMD; en macOS, con `ioreg`. Lo que no se pueda leer simplemente no aparece.

**El encabezado** muestra, a la derecha, lo mejor que haya disponible:

| Si… | Muestra |
|---|---|
| Claude Desktop o la Opción 7 tienen una lectura de tu plan | `5h 74% · 7d 17% · resets 3h35m` — el porcentaje **real** de tus límites de 5 horas y 7 días, y cuánto falta para que se reinicie la ventana de 5h |
| No, pero configuraste un presupuesto propio | `5h · 64%` — tu consumo contra **tu** límite (ver Opción 2) |
| Ninguna de las dos | `$1,299.99` — tu gasto total |

De dónde sale el porcentaje del plan:

- **Claude Desktop** lo guarda él mismo (`plan-usage-history.json`) cada ~15 minutos mientras está abierto. No trae hora de reinicio, así que se **estima** a partir de cuándo empezó a subir tu uso: por eso lleva `~` (`resets ~3h35m`), con un margen de unos 15 minutos y nunca prometiendo más tiempo del que tienes. El reinicio de 7 días no se estima.
- **La Opción 7** (status line de Claude Code) da la hora de reinicio exacta mientras haya una sesión de Claude Code abierta.
- Si están las dos, gana la lectura más reciente.

Si la lectura es vieja (más de 5 minutos para Claude Code, más de 20 para Desktop), sale con `?` (`5h 43%?`).

**Las filas** muestran Claude Code y Claude Desktop a la vez:

| Etiqueta | Qué es | Qué muestra |
|---|---|---|
| `chat` | Claude Desktop, mientras lo usas (últimos 5 minutos) | **Solo que está activo.** Desktop no guarda tokens, costo ni contexto por conversación en ningún archivo local, así que no hay nada real que mostrar |
| `code` | Una sesión de Claude Code (terminal o IDE) | Tokens, costo y porcentaje de la ventana de contexto |
| `desk` | Una sesión de la pestaña **Code** de Claude Desktop | Lo mismo que `code`: por dentro es Claude Code |
| `open` | Una sesión de **OpenCode** | Tokens y costo (`free` con modelos gratuitos o locales). Sin % de contexto |

**Título del chat de Desktop (opcional).** La primera vez que abres la Opción 6, la app pregunta si quieres ver el título del chat de Desktop en el que estás. Viene **desactivado** porque los títulos se generan a partir de tus mensajes, y en todo lo demás la app nunca lee contenido de tus conversaciones. Se lee de la caché local de Desktop, sin mandar nada a ningún lado. Tu respuesta queda guardada en `~/.config/tokenscounterby/settings.json` (Windows: `%APPDATA%\TokensCounterBy\settings.json`; macOS: `~/Library/Application Support/TokensCounterBy/settings.json`); bórralo para que vuelva a preguntar.

Controles:

- **Click** sobre la ventana: alterna entre "siempre encima" y ventana normal.
- **Esc** o la X: la cierra y vuelve al menú.

Funciona en Windows, macOS y Linux con el mismo código (`-topmost` de tkinter), corriendo la app directamente en el sistema (WSL no está soportado). En Linux con Wayland la ventana corre bajo XWayland, que es lo que permite que el compositor respete el "siempre encima" — probado en GNOME 46 / Ubuntu. Si tu compositor lo ignorara, la ventana sigue funcionando, solo que no se quedaría encima.

Mientras la ventana está abierta, la terminal queda esperando: se cierra la ventana y vuelves al menú. Es a propósito, para que salir de la app no deje ventanas huérfanas por ahí.

---

## 📶 Real Plan Limits (Opción 7)

Los porcentajes reales de tu plan (las barras de 5h y 7 días que ves en `/usage`) **se calculan en el servidor de Anthropic** y no están guardados en ningún archivo local. Esta app no hace llamadas de red, así que no puede pedirlos.

Pero Claude Code sí los tiene, y desde la v2.1.80 se los pasa a los scripts de *status line*. Esta opción instala un script pequeño que los guarda, y la app lee ese archivo:

```
Claude Code ──(JSON con rate_limits)──> statusline.py ──> cache
                                                            │
                                      TokensCounterBy <─────┘
```

**La app sigue sin hacer ni una llamada de red** — las hace Claude Code.

Qué hace la opción:

1. Te muestra el comando exacto que va a escribir en `~/.claude/settings.json`.
2. Te avisa de que tu status line de Claude Code cambiará de aspecto (pasará a mostrar `Opus 5 · 5h 12% · 7d 8%`).
3. Si ya tienes otro status line configurado, te lo dice y te deja cancelar.
4. Hace una copia de seguridad (`settings.json.bak-tokenscounter`) y conserva el resto de tus ajustes.

Después de instalarlo hay que **reiniciar Claude Code**: lee `settings.json` al arrancar.

La instalación incluye `refreshInterval: 30`, así que mientras tengas una sesión de Claude Code abierta el número se actualiza solo cada 30 segundos. No cuesta nada (el script es local, sin red ni tokens) y solo corre mientras hay sesión abierta — sin actividad, no se ejecuta nada.

**Limitaciones honestas:**

- **No hay "tokens restantes".** Claude entrega solo `used_percentage` y `resets_at`. No existe ningún campo con cantidades absolutas de tokens, así que ese número no se puede mostrar.
- **El dato puede estar viejo.** El cache solo se refresca mientras una sesión de Claude Code dibuja su status line. La app muestra hace cuánto se capturó, y el widget marca con `?` una lectura de más de 5 minutos.
- **Nada lo refresca si no usas Claude Code.** Si trabajas solo en Claude Desktop, esta copia no se actualiza hasta que abras Claude Code — pero no hace falta: la app lee también el porcentaje que guarda Claude Desktop (ver Opción 6). Se midió que `claude -p` **no** renderiza status line, así que un cron alrededor de eso gastaría cuota y no refrescaría nada.
- **No aplica a todo el mundo.** Con API key, Bedrock o Vertex, Claude Code informa `rate_limits_available: false` y no hay porcentaje que mostrar. La app lo dice en vez de inventar uno.

Si algo no funciona, vuelve a entrar a la Opción 7: diagnostica la instalación (ruta con espacios sin comillas, venv borrado, repo movido) y te ofrece repararla.

**Dónde queda cada cosa** (por si quieres revisarlo o desinstalarlo):

| Qué | Dónde |
|---|---|
| Configuración que se agrega | Clave `statusLine` en `~/.claude/settings.json` |
| Copia de seguridad previa | `~/.claude/settings.json.bak-tokenscounter` |
| Lecturas capturadas | Linux `~/.cache/tokenscounterby/` · macOS `~/Library/Caches/TokensCounterBy/` · Windows `%LOCALAPPDATA%\TokensCounterBy\` |

Para desinstalarlo, borra la clave `statusLine` de `~/.claude/settings.json` (o restaura la copia de seguridad) y reinicia Claude Code. La carpeta de lecturas se puede borrar sin problema. Si necesitas guardarlas en otro lugar, define la variable de entorno `TOKENS_COUNTER_CACHE` con la ruta del archivo.

---

## ✅ Plataformas

Cada cambio se prueba automáticamente en máquinas reales de **Linux, Windows y macOS** con GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)): los tests unitarios más una prueba de punta a punta que arranca el menú, lee CPU/RAM/GPU/disco, ejecuta el script del status line y abre y cierra la ventana flotante.

| Sistema | Tests + app | Ventana flotante | CPU / RAM / disco | GPU |
|---|---|---|---|---|
| **Windows** | ✅ CI + equipo real (Windows 11) | ✅ | ✅ | ✅ Cualquier marca (contadores del sistema, como el Administrador de tareas) |
| **macOS** | ✅ CI (Apple Silicon) | ✅ | ✅ | `ioreg`: probado solo con tests; los runners de CI no reportan GPU |
| **Linux** | ✅ CI (Ubuntu 22.04 y 24.04) | ✅ (probado con pantalla virtual) | ✅ | NVIDIA (`nvidia-smi`) y AMD: probado solo con tests. Intel integrada: no disponible |
| **Python** | 3.8 a 3.13 | | | |

Cuando algo no se puede leer en tu equipo (por ejemplo, una GPU sin herramientas de lectura), simplemente no se muestra — la app nunca inventa un número.

## 🧪 Tests

```bash
python3 -m unittest tests.test_calculator    # tests unitarios
python3 scripts/smoke_test.py                # prueba de punta a punta en tu sistema
```

La prueba de punta a punta usa una carpeta de configuración vacía (no toca tus datos reales) y abre la ventana flotante unos segundos; con `--no-window` se la salta.

Las opciones 1-4 y 6 son de solo lectura sobre los archivos locales de Claude Code. La Opción 5 es la única que borra algo, y la Opción 7 la única que modifica la configuración de Claude Code (solo la clave `statusLine`, con copia de seguridad).
