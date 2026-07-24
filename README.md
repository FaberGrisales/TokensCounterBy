# 🕹️ Retro Token Counter & Dashboard (Arcade Edition)

Un monitor financiero de tokens para modelos de lenguaje (LLMs) como Claude y Gemini, diseñado con una interfaz de terminal (TUI) que imita una máquina de arcade clásica de 8 bits.

Este proyecto está diseñado para ayudarte a visualizar exactamente cuánto dinero gastas en cada llamada a una API (incluyendo llamadas reales con herramientas / MCP en Claude), y ver en tiempo real qué sesiones de Claude Code están consumiendo tokens en tu máquina. Todos los números que ves vienen de una respuesta real de la API o de tus transcripts locales de Claude Code — no hay ningún modo simulado/estimado ni mecánicas de juego (billetera, monedas, high scores).

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
2. **Live Session Monitor**: Ve en tiempo real qué sesiones de Claude Code están activas en esta máquina y cuánto está gastando cada una (ver sección de abajo).
3. **Exit Machine**: Cierra la aplicación.

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

Presiona **Ctrl+C** para detener el monitor y volver al menú.

**Notas:**
- El costo se calcula con las tarifas de `tokens_counter/models_config.json`. Si una sesión usa un modelo que no está en esa tabla, su costo se muestra como `N/A` (los tokens sí se cuentan). Puedes agregar o ajustar precios editando ese archivo directamente.
- Puedes apuntar el monitor a una ubicación distinta de `~/.claude` definiendo la variable de entorno `CLAUDE_CONFIG_DIR` antes de lanzar `start.py`, igual que hace Claude Code.
- El formato interno de estos archivos `.jsonl` es un detalle de implementación de Claude Code y podría cambiar en versiones futuras; si eso ocurre, el monitor simplemente mostrará menos datos en vez de fallar.

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
