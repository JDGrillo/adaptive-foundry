from __future__ import annotations

import pytest

from task_store import TaskStore


def test_task_store_crud(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")

    created = store.add_task("conversation-1", "Prepare demo")
    assert store.list_tasks("conversation-1") == [created]

    updated = store.update_task(
        "conversation-1",
        created.id,
        title="Prepare Teams demo",
        completed=True,
    )
    assert updated.title == "Prepare Teams demo"
    assert updated.completed is True

    store.delete_task("conversation-1", created.id)
    assert store.list_tasks("conversation-1") == []


def test_task_store_isolated_by_conversation(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    store.add_task("conversation-1", "First")
    store.add_task("conversation-2", "Second")

    assert [task.title for task in store.list_tasks("conversation-1")] == ["First"]
    assert [task.title for task in store.list_tasks("conversation-2")] == ["Second"]


def test_task_store_rejects_blank_titles(tmp_path) -> None:
    store = TaskStore(tmp_path / "tasks.json")

    with pytest.raises(ValueError, match="required"):
        store.add_task("conversation-1", "   ")
