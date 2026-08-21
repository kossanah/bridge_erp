import frappe
import frappe_assistant_core
from frappe_assistant_core.core.tool_registry import ToolRegistry

def check_tools():
    registry = ToolRegistry()
    tools = registry.get_available_tools()
    print("TOOLS:", [t["name"] for t in tools if 'filter' in t["name"]])
