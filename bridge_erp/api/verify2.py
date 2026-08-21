import frappe
from bridge_erp.assistant_tools.filter_documents import FilterDocuments

def run_test():
    tool = FilterDocuments()
    print("INSTANTIATED:", tool.name)
