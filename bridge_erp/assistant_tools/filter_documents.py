# Frappe Assistant Core — bridge_erp external tool
# filter_documents: supports both dict and tuple/LIKE filters via frappe.get_list

"""
Filter Documents Tool for bridge_erp.

Extends FAC's list_documents with full Frappe filter operator support:
- Dict filters: {"field": "value"}  (equality, same as list_documents)
- Tuple/array filters: [["DocType", "field", "like", "%value%"]]
  Supports: like, !=, >, <, >=, <=, in, not in, between, is

This tool is the recommended way to do fuzzy/partial-match searches when
list_documents returns 0 results with an exact equality filter.
"""

from typing import Any, Dict, List

import frappe
from frappe import _
from frappe_assistant_core.core.base_tool import BaseTool


# Smart field defaults per DocType — avoids returning only 'name'
_DEFAULT_FIELDS: Dict[str, List[str]] = {
    "Customer":    ["name", "customer_name", "customer_type", "territory"],
    "Supplier":    ["name", "supplier_name", "supplier_type"],
    "Item":        ["name", "item_code", "item_name", "item_group", "stock_uom"],
    "Item Price":  ["name", "item_code", "item_name", "price_list", "price_list_rate", "currency", "uom"],
    "Warehouse":   ["name", "warehouse_name", "is_group", "parent_warehouse", "company"],
    "Sales Invoice": ["name", "customer", "posting_date", "grand_total", "status"],
    "Purchase Order": ["name", "supplier", "transaction_date", "grand_total", "status"],
    "Price List":  ["name", "currency", "buying", "selling"],
    "Employee":    ["name", "employee_name", "department", "designation", "status"],
}


class FilterDocuments(BaseTool):
    """
    Filter records in any Frappe DocType using equality or advanced operators.

    Unlike list_documents, this tool accepts Frappe tuple-style filters that
    support LIKE, !=, >, in, between, and other operators.

    Use this tool when:
    - You need a fuzzy/partial-match search (LIKE with % wildcards)
    - list_documents returns 0 results with an exact filter
    - You need an operator other than = (e.g. >, <=, in, between)
    """

    def __init__(self):
        super().__init__()
        self.name = "filter_documents"
        self.description = (
            "Search Frappe DocType records using equality or advanced filter operators. "
            "Use for fuzzy/partial-match searches with LIKE, or for operators like !=, >, "
            "in, between. When the user gives a partial name, use: "
            "filters=[[\"DocType\", \"field\", \"like\", \"%partial%\"]]. "
            "For exact matches, use: filters={\"field\": \"value\"} (same as list_documents). "
            "Examples: find customers matching 'Huawei' → filters=[[\"Customer\",\"customer_name\",\"like\",\"%Huawei%\"]], "
            "find item prices for code MSE1070 → filters=[[\"Item Price\",\"item_code\",\"=\",\"MSE1070\"]], "
            "find all non-group warehouses → filters=[[\"Warehouse\",\"is_group\",\"=\",0]]."
        )
        self.category = "Document Management"
        self.source_app = "bridge_erp"
        self.requires_permission = None  # Checked dynamically per DocType

        self.inputSchema = {
            "type": "object",
            "required": ["doctype", "filters"],
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": (
                        "The Frappe DocType to search. Must match exact DocType name. "
                        "Examples: 'Customer', 'Item Price', 'Warehouse', 'Supplier'."
                    ),
                },
                "filters": {
                    "anyOf": [
                        {
                            "type": "object",
                            "description": (
                                "Equality filters as key-value pairs. "
                                "Example: {\"item_code\": \"MSE1070\", \"price_list\": \"Standard Selling\"}"
                            ),
                        },
                        {
                            "type": "array",
                            "description": (
                                "Frappe tuple-style filters for advanced operators. "
                                "Each element is [DocType, field, operator, value] or [field, operator, value]. "
                                "Operators: like, =, !=, >, <, >=, <=, in, not in, between, is. "
                                "Use % wildcards with like for fuzzy search. "
                                "Examples: "
                                "[[\"Customer\",\"customer_name\",\"like\",\"%Huawei%\"]], "
                                "[[\"Warehouse\",\"is_group\",\"=\",0]], "
                                "[[\"Item Price\",\"item_code\",\"=\",\"MSE1070\"]]"
                            ),
                            "items": {"type": "array"},
                        },
                    ],
                    "description": (
                        "Filters to apply. Use a dict {\"field\": \"value\"} for simple equality, "
                        "or an array of tuples for operators like LIKE, !=, >, in, between. "
                        "For fuzzy search: [[\"DocType\", \"field\", \"like\", \"%partial%\"]]."
                    ),
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to return. Leave empty to use smart defaults per DocType "
                        "(e.g. Item Price returns item_code, item_name, price_list_rate, currency automatically)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "maximum": 200,
                    "description": "Maximum records to return. Default 20.",
                },
            },
        }

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Filter documents with full operator support."""
        doctype = arguments.get("doctype")
        filters = arguments.get("filters", {})
        requested_fields = arguments.get("fields", [])
        limit = min(int(arguments.get("limit", 20)), 200)

        # Validate document access
        from frappe_assistant_core.core.security_config import (
            filter_sensitive_fields,
            validate_document_access,
        )

        validation_result = validate_document_access(
            user=frappe.session.user,
            doctype=doctype,
            name=None,
            perm_type="read",
        )
        if not validation_result["success"]:
            return validation_result

        user_role = validation_result["role"]

        # Apply smart field defaults if none requested
        fields = (
            requested_fields
            if requested_fields
            else _DEFAULT_FIELDS.get(doctype, ["name"])
        )

        # Ensure 'name' is always included
        if "name" not in fields:
            fields = ["name"] + fields

        try:
            documents = frappe.get_list(
                doctype,
                filters=filters,
                fields=fields,
                limit=limit,
                order_by="KEEP_DEFAULT_ORDERING",
                ignore_permissions=False,
            )

            # Filter sensitive fields
            filtered_documents = [
                filter_sensitive_fields(doc, doctype, user_role)
                for doc in documents
            ]

            return {
                "success": True,
                "doctype": doctype,
                "data": filtered_documents,
                "count": len(filtered_documents),
                "filters_applied": filters,
                "message": f"Found {len(filtered_documents)} {doctype} records",
            }

        except Exception as e:
            frappe.log_error(
                title=_("filter_documents Error"),
                message=f"Error filtering {doctype}: {e}",
            )
            return {"success": False, "error": str(e), "doctype": doctype}


# Required: class alias for discovery
filter_documents = FilterDocuments
