import os
from typing import List, Optional

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field, validator
from starlette.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("TASKS_API_BASE_URL", "https://api-organiza-tb.vercel.app")
API_JWT = os.getenv("TASKS_API_JWT")

mcp = FastMCP(name="tasks-mcp")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request):
    return JSONResponse({"status": "ok"})


class ReminderInput(BaseModel):
    unit: str = Field(..., description="Time unit for the reminder (e.g., minutes)")
    value: int = Field(..., description="Quantity for the reminder unit")

    @validator("unit")
    def validate_unit(cls, v: str) -> str:
        allowed = {"minutes", "hours", "days"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v

    @validator("value")
    def validate_value(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("value must be greater than 0")
        return v


class TaskCreatePayload(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = Field(..., description="baja|media|alta")
    due_date: Optional[str] = Field(None, description="ISO 8601 string")
    reminders: Optional[List[ReminderInput]] = None

    @validator("priority")
    def validate_priority(cls, v: str) -> str:
        allowed = {"baja", "media", "alta"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {sorted(allowed)}")
        return v


class TaskUpdatePayload(BaseModel):
    title: Optional[str]
    description: Optional[str]
    priority: Optional[str]
    due_date: Optional[str]
    is_completed: Optional[bool]
    reminders: Optional[List[ReminderInput]]

    @validator("priority")
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"baja", "media", "alta"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {sorted(allowed)}")
        return v


async def _headers(token_override: Optional[str] = None) -> dict:
    headers = {"Content-Type": "application/json"}
    token = token_override or API_JWT
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _client(token_override: Optional[str] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=API_BASE_URL, timeout=15.0, headers=await _headers(token_override))


async def _request(method: str, path: str, token_override: Optional[str] = None, **kwargs):
    async with await _client(token_override) as client:
        try:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text
            raise RuntimeError(
                f"Backend request failed ({exc.response.status_code} {exc.response.reason_phrase}): {body}"
            ) from exc

        if resp.content:
            return resp.json()
        return None


@mcp.tool()
async def create_task(
    title: str,
    description: Optional[str] = None,
    priority: str = "media",
    due_date: Optional[str] = None,
    reminders: Optional[List[ReminderInput]] = None,
    jwt: Optional[str] = None,
):
    """Create a task using backend API."""
    payload = TaskCreatePayload(
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        reminders=reminders,
    )
    return await _request("POST", "/api/tasks/", token_override=jwt, json=payload.dict(exclude_none=True))


@mcp.tool()
async def list_tasks(
    view: str = "tasks",
    tab: Optional[str] = None,
    tag_ids: Optional[List[str]] = None,
    priority: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
    jwt: Optional[str] = None,
):
    """List tasks with filtering and pagination."""
    if view not in {"home", "tasks"}:
        raise ValueError("view must be 'home' or 'tasks'")
    if tab and tab not in {"pending", "completed"}:
        raise ValueError("tab must be pending or completed")
    if priority and priority not in {"baja", "media", "alta"}:
        raise ValueError("priority must be baja|media|alta")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")

    params = {"view": view, "limit": limit}
    if tab:
        params["tab"] = tab
    if tag_ids:
        params["tag_ids"] = tag_ids
    if priority:
        params["priority"] = priority
    if end_date:
        params["end_date"] = end_date
    if cursor:
        params["cursor"] = cursor

    return await _request("GET", "/api/tasks/", token_override=jwt, params=params)


@mcp.tool()
async def get_task(task_id: str, jwt: Optional[str] = None):
    """Get a task by id."""
    return await _request("GET", f"/api/tasks/{task_id}", token_override=jwt)


@mcp.tool()
async def get_task_related(task_id: str, jwt: Optional[str] = None):
    """Get tags, notes, and events related to a task."""
    return await _request("GET", f"/api/tasks/{task_id}/related", token_override=jwt)


@mcp.tool()
async def assign_tag_to_task(task_id: str, tag_id: str, jwt: Optional[str] = None):
    """Assign a tag to a task."""
    return await _request("POST", f"/api/tasks/{task_id}/tags", token_override=jwt, json={"tag_id": tag_id})


@mcp.tool()
async def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    is_completed: Optional[bool] = None,
    reminders: Optional[List[ReminderInput]] = None,
    jwt: Optional[str] = None,
):
    """Patch a task with partial fields."""
    payload = TaskUpdatePayload(
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        is_completed=is_completed,
        reminders=reminders,
    )
    return await _request("PATCH", f"/api/tasks/{task_id}", token_override=jwt, json=payload.dict(exclude_none=True))


@mcp.tool()
async def delete_task(task_id: str, jwt: Optional[str] = None):
    """Delete a task."""
    return await _request("DELETE", f"/api/tasks/{task_id}", token_override=jwt)


def main():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    transport = os.getenv("MCP_TRANSPORT", "http").lower()
    http_path = os.getenv("MCP_HTTP_PATH", "/mcp")

    if transport == "http":
        mcp.run(transport="http", host=host, port=port, path=http_path)
    else:
        mcp.run(transport="sse", host=host, port=port)


if __name__ == "__main__":
    main()
