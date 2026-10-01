from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskItem:
    id: str
    title: str
    completed: bool = False


class TaskStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()

    def list_tasks(self, conversation_id: str) -> list[TaskItem]:
        with self._lock:
            data = self._read()
            return [
                TaskItem(**task)
                for task in data["conversations"].get(conversation_id, [])
            ]

    def add_task(self, conversation_id: str, title: str) -> TaskItem:
        normalized = title.strip()
        if not normalized:
            raise ValueError("Task title is required.")

        with self._lock:
            data = self._read()
            task = TaskItem(id=uuid.uuid4().hex[:10], title=normalized)
            data["conversations"].setdefault(conversation_id, []).append(asdict(task))
            self._write(data)
            return task

    def update_task(
        self,
        conversation_id: str,
        task_id: str,
        *,
        title: str | None = None,
        completed: bool | None = None,
    ) -> TaskItem:
        with self._lock:
            data = self._read()
            tasks = data["conversations"].get(conversation_id, [])
            for index, raw_task in enumerate(tasks):
                if raw_task["id"] != task_id:
                    continue

                next_title = raw_task["title"] if title is None else title.strip()
                if not next_title:
                    raise ValueError("Task title is required.")

                updated = TaskItem(
                    id=task_id,
                    title=next_title,
                    completed=raw_task["completed"] if completed is None else completed,
                )
                tasks[index] = asdict(updated)
                self._write(data)
                return updated

        raise KeyError(f"Task '{task_id}' was not found.")

    def delete_task(self, conversation_id: str, task_id: str) -> None:
        with self._lock:
            data = self._read()
            tasks = data["conversations"].get(conversation_id, [])
            remaining = [task for task in tasks if task["id"] != task_id]
            if len(remaining) == len(tasks):
                raise KeyError(f"Task '{task_id}' was not found.")
            data["conversations"][conversation_id] = remaining
            self._write(data)

    def _read(self) -> dict:
        if not self._path.exists():
            return {"conversations": {}}

        with self._path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if not isinstance(data, dict) or not isinstance(
            data.get("conversations"), dict
        ):
            raise ValueError(f"Task store '{self._path}' has an invalid shape.")
        return data

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.write(os.linesep)
        temporary.replace(self._path)
