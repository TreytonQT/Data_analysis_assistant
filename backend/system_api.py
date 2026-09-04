from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status

from backend.system_control import SystemAction, system_controller


router = APIRouter(prefix="/api/system", tags=["system"])
CONTROL_HEADER = "X-Dashboard-Control"
CONTROL_HEADER_VALUE = "sales-dashboard"
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _require_local_control_request(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if client_host not in LOOPBACK_HOSTS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "系统控制仅允许本机访问")
    if request.headers.get(CONTROL_HEADER) != CONTROL_HEADER_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "缺少系统控制请求标识")


def _status_payload() -> dict[str, str | bool | None]:
    current = system_controller.status()
    return {
        "control_available": current.control_available,
        "instance_id": current.instance_id,
        "pending_action": current.pending_action,
    }


@router.get("/status")
def system_status(request: Request) -> dict[str, str | bool | None]:
    _require_local_control_request(request)
    return _status_payload()


def _request_action(action: SystemAction, request: Request, background_tasks: BackgroundTasks) -> dict[str, str | bool | None]:
    _require_local_control_request(request)
    reservation = system_controller.reserve(action)
    if reservation == "unavailable":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "当前启动方式不支持系统控制")
    if reservation == "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "已有系统控制操作正在执行")
    background_tasks.add_task(system_controller.request_exit)
    return {"ok": True, "action": action, **_status_payload()}


@router.post("/restart", status_code=status.HTTP_202_ACCEPTED)
def restart_system(request: Request, background_tasks: BackgroundTasks) -> dict[str, str | bool | None]:
    return _request_action("restart", request, background_tasks)


@router.post("/shutdown", status_code=status.HTTP_202_ACCEPTED)
def shutdown_system(request: Request, background_tasks: BackgroundTasks) -> dict[str, str | bool | None]:
    return _request_action("shutdown", request, background_tasks)
