---
description: Plan to build an MCP server for chatbot-driven task CRUD
---
# MCP Tasks Chatbot Plan
Create an MCP server that lets the chatbot create, read, update, and delete tasks with validations matching the provided Tasks API contract.

## Context
- Repo is currently empty; no existing task modules or MCP scaffold to extend.
- User rules: read-before-edit, avoid duplicate files, comments in Spanish, code in English, explicit authorization for DB/config changes.

## Goals
1) Define MCP server endpoints/tools for task CRUD and listing with filters (views, tabs, tags, priority, pagination).
2) Align request/response schemas with the Tasks rules document (tasks/api.py and tasks/schemas.py parity once implemented).
3) Ensure reminders and tags handling follow the spec (AND filtering, reminders_data computation when due_date exists).

## Approach
- Use Python FastMCP for the server and ensure compatibility with MCP Inspector; add minimal scaffold for the tasks service.
- Model task schema with fields: id, title, description, due_date, is_completed, priority, user_id, calendar_event_id, media_url, created_at, updated_at, has_reminder, reminders_data, tags.
- Implement tools:
  - create_task(title, description?, priority, due_date?, reminders[]) → returns task with computed calendar_event_id and reminders_data when due_date present.
  - list_tasks(view, tab?, tag_ids?, priority?, end_date?, limit?, cursor?) → returns data[], next_cursor, has_more, enforcing AND on tag_ids and ordering rules per view.
  - get_task(id) → single task (without tags per spec).
  - get_task_related(id) → tags, notes, events collections.
  - assign_tag_to_task(id, tag_id) → message + assigned count.
  - update_task(id, partial fields) and delete_task(id) as needed for CRUD completeness.
- Storage layer: call the existing backend task endpoints for persistence (no local DB); keep code-ready for future Supabase integration but avoid DB/config changes without approval.
- Validation: enforce priority enum (baja|media|alta), view/tab rules, reminder units, pagination limits, and ordering logic as described.
- Testing: add unit tests for tool responses and ordering/filtering; include sample fixtures covering overdue, future, completed, no-due-date, tags intersection, and reminders.

## Deliverables
- MCP server code with task tools, schemas, and in-memory persistence.
- Validation and ordering logic matching spec; reminders_data computation.
- Tests for CRUD, listing rules, and tag AND filtering.
- README snippet for running the MCP server with the chatbot.

## Open Questions / Backend Details
- Backend base URL: https://api-organiza-tb.vercel.app
- Auth: JWT sent from frontend in headers; confirm exact header name (e.g., Authorization: Bearer <token>) and any required scopes/claims.
- Any authentication/authorization requirements for task operations beyond standard headers?
