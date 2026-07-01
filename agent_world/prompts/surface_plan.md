You generate SurfacePlan fields from EnvironmentSpec and LogicalToolGraph.
Return only JSON fields required for SurfacePlan. Bind every logical tool to at least a python surface for the first executable slice.
Do not include artifact metadata.

Nested contract:

- bindings[] items must include binding_id, logical_tool_id, surface, exposure_name, input_mapping, output_mapping, error_mapping, auth_context, and state_scope.
- surface must be one of python, cli, http, or mcp.
- surface_status must be a map from surface name to a status string. Values must be planned, required_for_first_slice, deferred, or rejected.
- For the first executable slice, use surface_status.python = "required_for_first_slice".
