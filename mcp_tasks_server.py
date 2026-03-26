"""
MCP server for task management.

This server forwards authentication headers from the incoming MCP request to the
backend API so the backend can authorize the user on every call.
"""

import datetime
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, field_validator
from starlette.responses import JSONResponse

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.getenv("TASKS_API_BASE_URL", "https://api-organiza-tb.vercel.app")
API_JWT = os.getenv("TASKS_API_JWT")

mcp = FastMCP(name="tasks-mcp")


@mcp.custom_route("/health", methods=["GET"])
async def health_check(_request):
    return JSONResponse({"status": "ok"})


class ReminderInput(BaseModel):
    unit: str = Field(..., description="Time unit for the reminder (e.g., minutes)")
    value: int = Field(..., description="Quantity for the reminder unit")

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        allowed = {"minutes", "hours", "days"}
        if v not in allowed:
            raise ValueError(f"unit must be one of {sorted(allowed)}")
        return v

    @field_validator("value")
    @classmethod
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

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = {"baja", "media", "alta"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {sorted(allowed)}")
        return v


class TaskUpdatePayload(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    is_completed: Optional[bool] = None
    reminders: Optional[List[ReminderInput]] = None

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"baja", "media", "alta"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {sorted(allowed)}")
        return v


class APIClient:
    """Reusable client for the Tasks REST API."""

    def __init__(self) -> None:
        self.base_url = API_BASE_URL.rstrip("/")
        self.base_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_http_headers(self) -> Dict[str, str]:
        try:
            return get_http_headers(include_all=True)
        except Exception as exc:
            logger.warning("Could not read MCP headers: %s", exc)
            return {}

    def get_bearer_token_from_headers(self) -> Optional[str]:
        headers = self._get_http_headers()
        authorization = headers.get("authorization") or headers.get("Authorization")
        if not authorization:
            return None
        # Soporta "Bearer <token>" (estándar) y token directo sin prefijo (MCP Inspector)
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return authorization.strip()

    def build_headers(self, api_key_override: Optional[str] = None) -> Dict[str, str]:
        headers = dict(self.base_headers)

        token = api_key_override or self.get_bearer_token_from_headers() or API_JWT
        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        api_key_override: Optional[str] = None,
    ) -> Any:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        headers = self.build_headers(api_key_override=api_key_override)

        logger.info("Backend request about to be sent")
        logger.info("Method: %s", method)
        logger.info("URL: %s", url)
        logger.info("Params: %s", params)
        logger.info("JSON body: %s", json)
        logger.info(
            "Outgoing headers: %s",
            {
                key: (
                    "Bearer ***" if key.lower() == "authorization" and value else value
                )
                for key, value in headers.items()
            },
        )

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json,
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error("Error calling backend API: %s", exc)
            raise RuntimeError(f"Error calling backend API: {exc}") from exc

        if response.status_code >= 400:
            body = response.text
            logger.error("Backend response status: %s", response.status_code)
            logger.error("Backend response body: %s", body)
            raise RuntimeError(
                f"Backend request failed ({response.status_code} {response.reason}): {body}"
            )

        if response.content:
            try:
                return response.json()
            except ValueError:
                return response.text

        return None

    def extract_headers_info(self) -> Dict[str, Any]:
        """
        Extrae y formatea los headers HTTP de la request MCP actual.

        Útil para debuggear si el JWT está llegando correctamente al servidor
        antes de que se reenvíe al backend.

        Retorna un dict con:
        - authorization: token parcialmente oculto (si existe)
        - custom_headers: headers no estándar (valores sensibles ofuscados)
        - raw_header_keys: lista de todas las keys recibidas (para diagnóstico)
        - token_source: indica si el token viene del header, del env o no existe
        - timestamp: ISO 8601
        """
        try:
            headers = self._get_http_headers()

            # Headers estándar HTTP/navegador que no aportan info útil
            standard_headers = {
                "host",
                "user-agent",
                "accept",
                "accept-encoding",
                "accept-language",
                "connection",
                "content-type",
                "content-length",
                "cache-control",
                "pragma",
                "sec-fetch-dest",
                "sec-fetch-mode",
                "sec-fetch-site",
                "upgrade-insecure-requests",
                "dnt",
                "te",
            }

            authorization = headers.get("authorization") or headers.get("Authorization")

            # Procesar headers personalizados (no estándar)
            custom_headers: Dict[str, str] = {}
            for key, value in headers.items():
                if key.lower() not in standard_headers:
                    sensitive_terms = ["key", "token", "auth", "secret"]
                    if any(term in key.lower() for term in sensitive_terms):
                        str_val = str(value)
                        if len(str_val) > 8:
                            custom_headers[key] = f"{str_val[:4]}***{str_val[-4:]}"
                        else:
                            custom_headers[key] = "***"
                    else:
                        custom_headers[key] = value

            # Determinar origen del token para facilitar el diagnóstico
            token_from_header = self.get_bearer_token_from_headers()
            if token_from_header:
                token_source = "header (✅ forwarded to backend)"
            elif API_JWT:
                token_source = "env TASKS_API_JWT (⚠️ fallback, not from client)"
            else:
                token_source = "none (❌ no token available — backend will reject)"

            result: Dict[str, Any] = {
                "token_source": token_source,
                "timestamp": datetime.datetime.now().isoformat(),
            }

            if authorization:
                result["authorization"] = (
                    f"{authorization[:10]}***{authorization[-4:]}"
                    if len(authorization) > 14
                    else authorization
                )

            if custom_headers:
                result["custom_headers"] = custom_headers

            # Lista plana de keys para diagnóstico cuando no llega nada
            result["raw_header_keys"] = list(headers.keys())

            return result

        except Exception as exc:
            return {
                "timestamp": datetime.datetime.now().isoformat(),
                "error": f"No se pudo acceder al contexto HTTP: {str(exc)}",
            }


api_client = APIClient()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def debug_authorization_header() -> Any:
    """
    Muestra los headers HTTP que está recibiendo el servidor MCP.

    Usar para verificar si el JWT está llegando correctamente desde el cliente
    antes de ser reenviado al backend. Los valores sensibles se muestran parcialmente.
    """
    return api_client.extract_headers_info()


@mcp.tool()
def create_task(
    title: str,
    description: Optional[str] = None,
    priority: str = "media",
    due_date: Optional[str] = None,
    reminders: Optional[List[ReminderInput]] = None,
) -> Any:
    """Create a task using backend API."""
    payload = TaskCreatePayload(
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        reminders=reminders,
    )
    return api_client.request(
        "POST",
        "/api/tasks/",
        json=payload.model_dump(exclude_none=True),
    )


@mcp.tool()
def list_tasks(
    view: str = "tasks",
    tab: Optional[str] = None,
    tag_ids: Optional[List[str]] = None,
    priority: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
) -> Any:
    """List tasks with filtering and pagination."""
    if view not in {"home", "tasks"}:
        raise ValueError("view must be 'home' or 'tasks'")
    if tab and tab not in {"pending", "completed"}:
        raise ValueError("tab must be pending or completed")
    if priority and priority not in {"baja", "media", "alta"}:
        raise ValueError("priority must be baja|media|alta")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")

    params: Dict[str, Any] = {"view": view, "limit": limit}
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

    return api_client.request("GET", "/api/tasks/", params=params)


@mcp.tool()
def get_task(task_id: str) -> Any:
    """Get a task by id."""
    return api_client.request("GET", f"/api/tasks/{task_id}")


@mcp.tool()
def get_task_related(task_id: str) -> Any:
    """Get tags, notes, and events related to a task."""
    return api_client.request("GET", f"/api/tasks/{task_id}/related")


@mcp.tool()
def assign_tag_to_task(task_id: str, tag_id: str) -> Any:
    """Assign a tag to a task."""
    return api_client.request(
        "POST",
        f"/api/tasks/{task_id}/tags",
        json={"tag_id": tag_id},
    )


@mcp.tool()
def update_task(
    task_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    due_date: Optional[str] = None,
    is_completed: Optional[bool] = None,
    reminders: Optional[List[ReminderInput]] = None,
) -> Any:
    """Patch a task with partial fields."""
    payload = TaskUpdatePayload(
        title=title,
        description=description,
        priority=priority,
        due_date=due_date,
        is_completed=is_completed,
        reminders=reminders,
    )
    return api_client.request(
        "PATCH",
        f"/api/tasks/{task_id}",
        json=payload.model_dump(exclude_none=True),
    )


@mcp.tool()
def delete_task(task_id: str) -> Any:
    """Delete a task."""
    return api_client.request("DELETE", f"/api/tasks/{task_id}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
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
