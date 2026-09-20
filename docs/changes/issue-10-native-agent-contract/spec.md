# Specification

The validator requires `name`, `description`, and `developer_instructions`.
It accepts documented optional `model`, `model_reasoning_effort`,
`sandbox_mode`, `mcp_servers`, and `skills.config` fields, preserving omitted
values for native inheritance. It rejects unknown fields, invalid enums,
wrong scalar/container types, and malformed nested MCP or skill values.

Acceptance is demonstrated by positive fixtures covering model, reasoning,
MCP, and skills settings and negative fixtures covering invalid enums, types,
nested values, and unsupported keys.
