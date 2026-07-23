# 🕹️ Retro Token Counter & Dashboard (Arcade Edition)

Un monitor financiero y simulador de tokens para modelos de lenguaje (LLMs) como Claude y Gemini, diseñado con una interfaz de terminal (TUI) que imita una máquina de arcade clásica de 8 bits. 

Este proyecto está diseñado para ayudarte a visualizar exactamente cuánto dinero gastas en cada llamada a una API, visualizar los ahorros obtenidos al usar **Prompt Caching**, y ver un historial de tus transacciones más caras como si fuera la tabla de "High Scores" de un videojuego.

---

## 🚀 Instalación

Asegúrate de tener Python 3.8+ instalado en tu sistema. Luego, instala las dependencias requeridas:

```bash
pip install rich anthropic google-genai
```

---

## 🎮 Cómo Jugar (Uso)

Para iniciar la máquina de arcade, simplemente ejecuta el script de lanzamiento desde la raíz del proyecto:

```bash
python3 start.py
```
*(También puedes darle permisos de ejecución con `chmod +x start.py` y correrlo como `./start.py`).*

Una vez iniciado, verás el menú principal con las siguientes opciones:

1. **Call Live API (Requires keys)**: Realiza consultas reales a Claude o Gemini. Debes tener tus API keys configuradas y tener saldo en tu billetera virtual de la app.
2. **MCP Token Cost Simulator**: Simula llamadas usando el protocolo de herramientas (MCP). Ideal para ver cómo el costo de los tokens se dispara al usar herramientas y cómo el **Prompt Caching** puede salvarte la vida (y tu dinero).
3. **View High Scores**: Revisa el historial de tus llamadas y descubre cuáles han sido las consultas más caras.
4. **Pay Table**: Revisa la tabla de precios actual por cada millón de tokens. Puedes modificar estos precios directamente editando el archivo `tokens_counter/models_config.json`.
5. **Insert Coin**: ¡Añade dinero a tu billetera virtual para poder seguir jugando/simulando! 🪙
6. **Real Account Dashboard (Analyze CSV)**: Analiza el consumo **real** de tu cuenta de Anthropic. (Requiere archivo CSV, ver instrucciones abajo).
7. **Exit Machine**: Cierra la aplicación.

---

## 📊 Usar el Dashboard Real de Anthropic (Opción 6)

Si tienes una suscripción o cuenta de pago en Anthropic, puedes ver un análisis exacto de tus gastos:

1. Ve a la consola web de Anthropic (sección de Billing/Usage).
2. Exporta tu consumo en formato CSV.
3. Guarda el archivo en la raíz de este proyecto con el nombre **`anthropic_usage.csv`**.
4. Abre la aplicación (`python3 start.py`) y selecciona la **Opción 6**. 
5. ¡Disfruta de tus gráficas retro de línea de tiempo y métricas de dinero ahorrado por caché!

---

## 🔑 Configuración de APIs Reales (Opcional)

Si deseas usar la **Opción 1** para hacer llamadas reales a los modelos desde esta consola, debes configurar tus claves de API en las variables de entorno de tu sistema operativo:

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