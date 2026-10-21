from google.adk.tools import FunctionTool
from rules.category_table import category_lookup
from rules.regulatory_flags import get_flags

category_tool = FunctionTool(category_lookup)
flags_tool = FunctionTool(get_flags)