import ast
import operator
import os
from datetime import datetime, timezone

# Local demo "tools" used to exercise real Claude tool-use/MCP-style calls
# without requiring an external MCP server. Each tool is deliberately
# read-only / side-effect-free so it's safe to let the model invoke freely.

TOOL_DEFINITIONS = [
    {
        "name": "get_current_time",
        "description": "Returns the current UTC date and time on the machine running this app.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "calculate",
        "description": "Evaluates a basic arithmetic expression (+, -, *, /, parentheses) and returns the numeric result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Arithmetic expression, e.g. '12 * (3 + 4)'"}
            },
            "required": ["expression"]
        }
    },
    {
        "name": "list_project_files",
        "description": "Lists the Python filenames inside this project's tokens_counter package.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    }
]

_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval_node(node):
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BIN_OPS:
        return _ALLOWED_BIN_OPS[type(node.op)](_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY_OPS:
        return _ALLOWED_UNARY_OPS[type(node.op)](_safe_eval_node(node.operand))
    raise ValueError("Unsupported expression")


def safe_arithmetic_eval(expression):
    """Evaluate a plain arithmetic expression without using eval()."""
    parsed = ast.parse(expression, mode="eval")
    return _safe_eval_node(parsed)


def execute_tool(name, tool_input):
    """Execute a locally defined demo tool and return a JSON-serializable result dict."""
    tool_input = tool_input or {}

    if name == "get_current_time":
        return {"utc_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}

    if name == "calculate":
        expression = tool_input.get("expression", "")
        try:
            return {"expression": expression, "result": safe_arithmetic_eval(expression)}
        except Exception as e:
            return {"expression": expression, "error": f"Could not evaluate expression: {e}"}

    if name == "list_project_files":
        package_dir = os.path.dirname(os.path.abspath(__file__))
        try:
            files = sorted(f for f in os.listdir(package_dir) if f.endswith(".py"))
            return {"files": files}
        except OSError as e:
            return {"error": str(e)}

    return {"error": f"Unknown tool: {name}"}
