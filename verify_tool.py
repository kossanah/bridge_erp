import frappe_assistant_core
from frappe_assistant_core.core.tool_registry import ToolRegistry

def verify_filter_tool():
    registry = ToolRegistry()
    tools = registry.list_tools()
    print([t for t in tools if 'filter' in t])
