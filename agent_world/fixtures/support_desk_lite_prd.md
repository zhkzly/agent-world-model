# Support Desk Lite PRD

This local PRD is the first source-grounded fixture for the environment generation pipeline.
It is synthetic, local-only, and does not contain real customer data.

## State Objects

- `customer` state: fields=id,name,tier,region,email; relations=
- `ticket` state: fields=id,customer_id,status,priority,subject,description; relations=customer
- `ticket_note` state: fields=ticket_id,visibility,body; relations=ticket
- `assignment` state: fields=ticket_id,assignee,queue; relations=ticket
- `audit_event` state: fields=ticket_id,event_type,field,old_value,new_value,note; relations=ticket

## Operations

- `search_tickets` operation: required=; optional=status,customer_tier,keyword,queue; reads=ticket,customer,assignment; writes=; idempotency=safe
- `get_ticket` operation: required=ticket_id; optional=; reads=ticket,customer,assignment,ticket_note,audit_event; writes=; idempotency=safe
- `add_ticket_note` operation: required=ticket_id,visibility,body; optional=; reads=ticket; writes=ticket_note,audit_event; idempotency=non_idempotent
- `update_ticket_priority` operation: required=ticket_id,priority,note; optional=; reads=ticket; writes=ticket,audit_event; idempotency=idempotent_by_target_value
- `assign_ticket` operation: required=ticket_id,queue,assignee,note; optional=; reads=assignment; writes=assignment,audit_event; idempotency=idempotent_by_target_value
- `resolve_ticket` operation: required=ticket_id,resolution_note; optional=; reads=ticket; writes=ticket,ticket_note,audit_event; idempotency=idempotent_by_status

## Business Rules

- `audit-on-write` rule: Every state-changing operation writes an audit_event.
- `python-required` rule: The first runnable surface is Python callable; CLI, HTTP, and MCP remain planned surfaces unless a later goal implements them.
- `no-real-customer-data` rule: The fixture must use synthetic local data only.

## Fixture Tasks

- `task-1`: Find the VIP customer's open refund case and leave an internal note explaining the refund follow-up.
- `task-2`: Move the idle high-priority login outage case to enterprise support and assign it to iris.
- `task-3`: Raise the under-prioritized VIP refund issue to high priority and record why.
- `task-4`: For Acme Corp, report how many open cases they have and the highest current priority.
- `task-5`: Inspect the duplicate refund confirmation case, then close it with a customer-visible resolution note.
