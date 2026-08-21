# bridge_erp Workspace — FAC Contribution + External Tool Agent Prompt

## Workspace
This workspace is: `~/bench/bridge/apps/bridge_erp`

The goal has TWO parts:
1. **Submit a PR to FAC core** (2 genuine bug fixes)
2. **Build a `filter_documents` external tool** inside this `bridge_erp` Frappe app

---

## Part 1 — FAC Core Bug Fixes (PR upstream)

### Context
FAC repo is at: `~/bench/bridge/apps/frappe_assistant_core`
Target file: `frappe_assistant_core/plugins/core/tools/list_documents.py`
Current version: v2.5.1

### Bug A — Count Query Scalar SQL Error (CRITICAL)

**Location:** ~line 385 in `list_documents.py`

The count query uses `fields=[{"COUNT": "name", "as": "count"}]` — a dict inside
a list. On MariaDB, this is not a supported form and causes:
`(1054, "Unknown column 'tabItem Price.scalar' in 'WHERE'")`
This affects ALL submittable DocTypes (Item Price, Sales Invoice, etc.) because
`apply_default_docstatus` appends `docstatus=1` and the broken code path is hit.

**Current broken code:**
```python
try:
    count_result = frappe.get_list(
        doctype, filters=filters,
        fields=[{"COUNT": "name", "as": "count"}],   # ← BROKEN
        limit=1, ignore_permissions=False,
    )
except AttributeError:
    count_result = frappe.get_list(
        doctype, filters=filters,
        fields=["count(name) as count"],
        limit=1, ignore_permissions=False,
    )
```

**Fix:**
```python
# Use string aggregate only — dict form causes "Unknown column 'table.scalar'"
# on MariaDB when filters include docstatus. See: FAC PR #XXX
try:
    count_result = frappe.get_list(
        doctype, filters=filters,
        fields=["count(name) as count"],
        limit=1, ignore_permissions=False,
    )
except Exception:
    count_result = []
```

---

### Bug B — Empty `order_by` Overrides Frappe's Default (MINOR)

**Location:** ~line 310 in `list_documents.py`

**Current code:**
```python
order_by = arguments.get("order_by", "creation desc")
```

Two problems:
1. When `order_by=""` is sent by an API client, the empty string bypasses the
   default and reaches `frappe.get_list(order_by="")`, which generates invalid SQL
2. Hardcoding `"creation desc"` overrides Frappe's own smart default
   (`KEEP_DEFAULT_ORDERING` → `idx desc, creation desc` from the list view config)

**Fix:**
```python
# Use Frappe's sentinel so it applies its own intelligent default ordering.
# Also guard against empty string from API clients.
order_by = arguments.get("order_by") or "KEEP_DEFAULT_ORDERING"
```

Also update the `inputSchema` description:
```python
"order_by": {
    "type": "string",
    "description": "Order results by field. Examples: 'creation desc', 'name asc', 'modified desc'. Leave empty to use Frappe default ordering.",
},
```

---

### Steps for FAC PR

```bash
cd ~/bench/bridge/apps/frappe_assistant_core

# 1. Create fix branch
git checkout main
git pull upstream main
git checkout -b fix/list-documents-count-query-and-order-by

# 2. Apply fixes to list_documents.py
#    - Replace the try/except count block with the string aggregate form
#    - Change order_by line to use "KEEP_DEFAULT_ORDERING" sentinel
#    (Edit the file directly or use the apply script at:
#     ~/.gemini/antigravity-ide/brain/90c63021-9298-462e-9d7c-76d16a28d6c6/scratch/apply_fac_fixes.py
#     NOTE: The apply script still uses "creation desc" — update it to
#     "KEEP_DEFAULT_ORDERING" before running, or apply manually)

# 3. Write regression tests
#    Copy to frappe_assistant_core/tests/test_list_documents_count_and_order.py
#    (See test file content in Part 1 Tests section below)

# 4. Run tests
cd ~/bench/bridge
bench run-tests --app frappe_assistant_core \
  --module frappe_assistant_core.tests.test_list_documents_count_and_order
bench run-tests --app frappe_assistant_core \
  --module frappe_assistant_core.tests.test_list_documents_docstatus

# 5. Commit
cd ~/bench/bridge/apps/frappe_assistant_core
git add frappe_assistant_core/plugins/core/tools/list_documents.py
git add frappe_assistant_core/tests/test_list_documents_count_and_order.py
git commit -m "fix: count query scalar error and order_by sentinel

Bug 1: Count query used fields=[{\"COUNT\": \"name\", \"as\": \"count\"}] which
fails on MariaDB with: (1054) Unknown column 'table.scalar' in 'WHERE'
when filters include docstatus (all submittable DocTypes).
Fix: use string aggregate 'count(name) as count' only.

Bug 2: order_by defaulted to 'creation desc', overriding Frappe's own
smart default ordering, and empty string '' from API clients bypassed
the default entirely causing potential SQL issues.
Fix: use Frappe's KEEP_DEFAULT_ORDERING sentinel as the fallback.
"

# 6. Fork and push
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/Frappe_Assistant_Core.git
git push origin fix/list-documents-count-query-and-order-by

# 7. Open PR on GitHub:
#    Base: buildswithpaul:main
#    Head: <YOUR_GITHUB_USERNAME>:fix/list-documents-count-query-and-order-by
```

---

### Part 1 Tests

Create `~/bench/bridge/apps/frappe_assistant_core/frappe_assistant_core/tests/test_list_documents_count_and_order.py`:

```python
"""
Regression tests for:
- Bug: count query causes "Unknown column 'table.scalar' in WHERE" on MariaDB
- Bug: order_by="" passes empty string to frappe.get_list; "creation desc" overrides Frappe defaults
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from frappe_assistant_core.plugins.core.tools.list_documents import DocumentList
from frappe_assistant_core.tests.base_test import BaseAssistantTest


@contextmanager
def list_harness(submittable=False, rows=None):
    rows = rows if rows is not None else [{"name": "REC-0001"}]
    with ExitStack() as stack:
        stack.enter_context(patch(
            "frappe_assistant_core.core.security_config.validate_document_access",
            return_value={"success": True, "role": "Default"},
        ))
        stack.enter_context(patch(
            "frappe_assistant_core.core.security_config.filter_sensitive_fields",
            side_effect=lambda doc, *a, **kw: doc,
        ))
        stack.enter_context(patch(
            "frappe_assistant_core.plugins.core.tools.list_documents.is_submittable",
            return_value=submittable,
        ))
        gl = stack.enter_context(patch("frappe.get_list"))
        gl.side_effect = [rows, [{"count": len(rows)}]]
        yield gl


class TestCountQueryNoDict(BaseAssistantTest):
    """Bug A: dict-in-fields on count call causes MariaDB scalar column error."""

    def test_count_field_is_string_not_dict(self):
        tool = DocumentList()
        with list_harness() as gl:
            tool.execute({"doctype": "Customer"})
            count_fields = gl.call_args_list[1][1].get("fields", [])
            for f in count_fields:
                self.assertIsInstance(f, str,
                    f"Count field must be str, not {type(f).__name__}: {f!r}. "
                    "Dict-in-fields causes 'Unknown column table.scalar' on MariaDB.")

    def test_count_does_not_raise_on_submittable_doctype(self):
        """Item Price + docstatus filter previously triggered the scalar error."""
        tool = DocumentList()
        with list_harness(submittable=True) as gl:
            result = tool.execute({
                "doctype": "Item Price",
                "filters": {"item_code": "MSE1070"},
            })
            self.assertTrue(result.get("success"), f"Got: {result}")

    def test_count_does_not_raise_on_sales_invoice(self):
        tool = DocumentList()
        with list_harness(submittable=True) as gl:
            result = tool.execute({"doctype": "Sales Invoice"})
            self.assertTrue(result.get("success"), f"Got: {result}")


class TestOrderByBehaviour(BaseAssistantTest):
    """Bug B: empty/missing order_by must not override Frappe's default ordering."""

    def test_empty_string_order_by_uses_frappe_default(self):
        """order_by='' must NOT reach frappe.get_list as empty string."""
        tool = DocumentList()
        with list_harness() as gl:
            tool.execute({"doctype": "Customer", "order_by": ""})
            actual = gl.call_args_list[0][1].get("order_by", "")
            self.assertNotEqual(actual, "",
                "Empty string order_by must be replaced with a valid default, "
                "not passed through as empty string to frappe.get_list.")

    def test_omitted_order_by_uses_frappe_sentinel(self):
        """When order_by is not supplied, Frappe's KEEP_DEFAULT_ORDERING must be used."""
        tool = DocumentList()
        with list_harness() as gl:
            tool.execute({"doctype": "Customer"})
            actual = gl.call_args_list[0][1].get("order_by", "")
            self.assertEqual(actual, "KEEP_DEFAULT_ORDERING",
                f"Expected 'KEEP_DEFAULT_ORDERING', got: {actual!r}")

    def test_explicit_order_by_is_honoured(self):
        """A non-empty order_by must still be passed through unchanged."""
        tool = DocumentList()
        with list_harness() as gl:
            tool.execute({"doctype": "Customer", "order_by": "modified desc"})
            actual = gl.call_args_list[0][1].get("order_by")
            self.assertEqual(actual, "modified desc")
```

---

## Part 2 — `filter_documents` External Tool in `bridge_erp`

### Why External (Not FAC Core)?

FAC's `list_documents` restricts `filters` to `"type": "object"` by design —
it may be intentional to keep the tool predictable. The recommended FAC approach
for custom features is an **external app tool via hooks**, not modifying core.

The `filter_documents` tool lives in `bridge_erp`, so:
- It deploys with your app, not with FAC
- No upstream approval needed
- You control the schema, defaults, and behaviour

---

### File Structure to Create

```
bridge_erp/                          ← app root
└── bridge_erp/                      ← inner Python package
    ├── hooks.py                     ← ADD assistant_tools registration here
    └── assistant_tools/
        ├── __init__.py
        └── filter_documents.py      ← NEW tool
```

---

### Step 1: Create directory

```bash
cd ~/bench/bridge/apps/bridge_erp
mkdir -p bridge_erp/assistant_tools
touch bridge_erp/assistant_tools/__init__.py
```

---

### Step 2: Create `filter_documents.py`

Create `bridge_erp/assistant_tools/filter_documents.py`:

```python
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
```

---

### Step 3: Register in `hooks.py`

Edit `bridge_erp/hooks.py` — find the `assistant_tools` list and add:

```python
# FAC external tool registration
# See: https://github.com/buildswithpaul/Frappe_Assistant_Core/blob/main/docs/development/EXTERNAL_APP_DEVELOPMENT.md
assistant_tools = [
    "bridge_erp.assistant_tools.filter_documents.FilterDocuments",
]
```

---

### Step 4: Install and test

```bash
cd ~/bench/bridge

# Install app on site (if not already installed)
bench --site local.bridge.ng install-app bridge_erp

# Restart to pick up new hooks
bench restart

# Verify tool is discovered by FAC
bench --site local.bridge.ng console
# In console:
# import frappe_assistant_core
# from frappe_assistant_core.core.tool_registry import ToolRegistry
# registry = ToolRegistry()
# print([t for t in registry.list_tools() if 'filter' in t])
```

---

### Step 5: Test the tool via MCP

Use Dify Tool Test UI or curl with these inputs:

**Test 1 — LIKE fuzzy search:**
```json
{
  "doctype": "Customer",
  "filters": [["Customer", "customer_name", "like", "%Huawei%"]],
  "limit": 5
}
```

**Test 2 — Item Price by code:**
```json
{
  "doctype": "Item Price",
  "filters": [["Item Price", "item_code", "=", "MSE1070"]]
}
```

**Test 3 — Non-group Warehouses:**
```json
{
  "doctype": "Warehouse",
  "filters": [["Warehouse", "is_group", "=", 0]]
}
```

---

## Done Criteria

### FAC PR
- [ ] Bug A (count scalar) fixed in `list_documents.py`
- [ ] Bug B (order_by sentinel) fixed — uses `"KEEP_DEFAULT_ORDERING"`
- [ ] `test_list_documents_count_and_order.py` passes
- [ ] Existing docstatus tests still pass
- [ ] Branch pushed, PR opened on `buildswithpaul/Frappe_Assistant_Core`

### bridge_erp External Tool
- [ ] `bridge_erp/assistant_tools/filter_documents.py` created
- [ ] `hooks.py` updated with `assistant_tools` registration
- [ ] App installed and restarted on `local.bridge.ng`
- [ ] Tool appears in FAC tool registry
- [ ] Fuzzy LIKE search works on Customer
- [ ] Item Price lookup by item_code works
- [ ] Warehouse non-group filter works
