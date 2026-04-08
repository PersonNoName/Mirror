import shutil
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING

from domain.task import Task, TaskResult
from interfaces.agents import SubAgent

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface


class FileAgent(SubAgent):
    """
    FileAgent：文件操作 Sub-agent，处理本地文件读写、复制、移动等操作。
    高风险操作（删除、覆盖）需要用户确认。
    """

    name = "file_agent"
    domain = "file"

    HIGH_RISK_OPERATIONS = {"delete", "remove", "rm", "overwrite", "chmod", "chown"}

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        blackboard: Any,
        allowed_dirs: Optional[list[str]] = None,
    ):
        self.task_store = task_store
        self.blackboard = blackboard
        self.allowed_dirs = allowed_dirs or ["."]
        self._operation_history: list[dict] = []

    async def execute(self, task: Task) -> TaskResult:
        try:
            operation = task.metadata.get("operation", "read")
            target_path = task.metadata.get("path", "")
            content = task.metadata.get("content", "")

            if not self._is_path_safe(target_path):
                await self.blackboard.on_task_failed(
                    task, "FATAL: Path outside allowed directories"
                )
                return TaskResult(
                    task_id=task.id,
                    status="failed",
                    error_trace="FATAL: Path outside allowed directories",
                )

            if operation in self.HIGH_RISK_OPERATIONS and not task.metadata.get(
                "confirmed", False
            ):
                await self.blackboard.on_task_failed(
                    task, f"HITL_REQUIRED: high_risk_operation={operation}"
                )
                return TaskResult(
                    task_id=task.id,
                    status="failed",
                    error_trace=f"HITL_REQUIRED: high_risk_operation={operation}",
                )

            result = await self._execute_operation(
                operation, target_path, content, task
            )
            await self.blackboard.on_task_complete(task)

            self._operation_history.append(
                {
                    "operation": operation,
                    "path": target_path,
                    "success": True,
                }
            )

            return TaskResult(
                task_id=task.id,
                status="done",
                result=result,
                summary=result.get("summary", ""),
            )

        except PermissionError as e:
            error_msg = f"Permission denied: {e}"
            await self.blackboard.on_task_failed(task, f"FATAL: {error_msg}")
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace=f"FATAL: {error_msg}",
            )
        except FileNotFoundError as e:
            error_msg = f"File not found: {e}"
            await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace=f"RETRYABLE: {error_msg}",
            )
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace=f"RETRYABLE: {error_msg}",
            )

    async def estimate_capability(self, task: Task) -> float:
        text = task.intent.lower()
        keywords = [
            "文件",
            "读写",
            "复制",
            "移动",
            "删除",
            "编辑",
            "file",
            "read",
            "write",
        ]
        score = sum(0.2 for kw in keywords if kw in text)
        return min(1.0, score)

    async def cancel(self) -> None:
        print(f"[FileAgent] cancel called for {self.name}")

    async def emit_heartbeat(self, task: Task) -> None:
        task.last_heartbeat_at = task.last_heartbeat_at
        await self.task_store.update_heartbeat(task.id, task.last_heartbeat_at)

    async def resume(self, task: Task, hitl_result: dict) -> TaskResult:
        if hitl_result.get("approved"):
            task.metadata["confirmed"] = True
            return await self.execute(task)
        else:
            await self.blackboard.on_task_failed(
                task, "HITL_REJECTED: User denied operation"
            )
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace="HITL_REJECTED: User denied operation",
            )

    def _is_path_safe(self, path: str) -> bool:
        try:
            abs_path = Path(path).resolve()
            for allowed in self.allowed_dirs:
                allowed_abs = Path(allowed).resolve()
                if str(abs_path).startswith(str(allowed_abs)):
                    return True
            return False
        except Exception:
            return False

    async def _execute_operation(
        self, operation: str, target_path: str, content: str, task: Task
    ) -> dict:
        match operation:
            case "read":
                return await self._read_file(target_path)
            case "write" | "create":
                return await self._write_file(target_path, content)
            case "append":
                return await self._append_file(target_path, content)
            case "copy":
                dest = task.metadata.get("dest", "")
                return await self._copy_file(target_path, dest)
            case "move":
                dest = task.metadata.get("dest", "")
                return await self._move_file(target_path, dest)
            case "delete":
                return await self._delete_file(target_path)
            case "list":
                return await self._list_directory(target_path)
            case "exists":
                return await self._check_exists(target_path)
            case _:
                raise ValueError(f"Unknown operation: {operation}")

    async def _read_file(self, path: str) -> dict:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content = p.read_text(encoding="utf-8")
        lines = content.split("\n")
        return {
            "summary": f"读取文件成功: {path} ({len(lines)} 行)",
            "content": content,
            "lines": len(lines),
            "path": path,
        }

    async def _write_file(self, path: str, content: str) -> dict:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        lines = content.split("\n")
        return {
            "summary": f"写入文件成功: {path} ({len(lines)} 行)",
            "bytes_written": len(content.encode("utf-8")),
            "path": path,
        }

    async def _append_file(self, path: str, content: str) -> dict:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return {
            "summary": f"追加内容到文件: {path}",
            "bytes_appended": len(content.encode("utf-8")),
            "path": path,
        }

    async def _copy_file(self, src: str, dest: str) -> dict:
        shutil.copy2(src, dest)
        return {
            "summary": f"复制文件: {src} -> {dest}",
            "src": src,
            "dest": dest,
        }

    async def _move_file(self, src: str, dest: str) -> dict:
        shutil.move(src, dest)
        return {
            "summary": f"移动文件: {src} -> {dest}",
            "src": src,
            "dest": dest,
        }

    async def _delete_file(self, path: str) -> dict:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(path)
        else:
            p.unlink()
        return {
            "summary": f"删除: {path}",
            "path": path,
            "deleted": True,
        }

    async def _list_directory(self, path: str) -> dict:
        p = Path(path)
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        entries = []
        for item in p.iterdir():
            entries.append(
                {
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                }
            )

        return {
            "summary": f"列出目录: {path} ({len(entries)} 项)",
            "entries": entries,
            "path": path,
        }

    async def _check_exists(self, path: str) -> dict:
        p = Path(path)
        exists = p.exists()
        return {
            "summary": f"{path} {'存在' if exists else '不存在'}",
            "exists": exists,
            "is_file": p.is_file() if exists else False,
            "is_dir": p.is_dir() if exists else False,
            "path": path,
        }
