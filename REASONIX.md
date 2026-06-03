# Code Retrieval Policy

Before reading files:

1. Always query CodeGraph first
2. Prefer:
   - codegraph_context
   - codegraph_query
   - codegraph_callers
   - codegraph_callees
3. Only read full files after graph lookup
4. Avoid broad grep/search unless graph retrieval fails
5. Use graph relationships before semantic guessing