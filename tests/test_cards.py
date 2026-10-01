from __future__ import annotations

from types import SimpleNamespace

from cards import build_tasks_card, card_invoke_response, parse_action
from task_store import TaskItem


def test_build_tasks_card_contains_crud_actions() -> None:
    card = build_tasks_card(
        [TaskItem(id="task-1", title="Prepare demo", completed=False)]
    )

    serialized = str(card)
    assert "add_task" in serialized
    assert "update_task" in serialized
    assert "toggle_task" in serialized
    assert "delete_task" in serialized
    assert card["version"] == "1.5"
    assert "Adaptive Card workspace" in serialized
    assert "1 open" in serialized
    assert "0 completed" in serialized


def test_parse_execute_action() -> None:
    activity = SimpleNamespace(
        value={
            "action": {
                "verb": "add_task",
                "data": {"newTask": "Prepare demo"},
            }
        }
    )

    assert parse_action(activity) == (
        "add_task",
        {"newTask": "Prepare demo"},
    )


def test_card_invoke_response_replaces_card() -> None:
    card = build_tasks_card([])
    response = card_invoke_response(card)

    assert response["statusCode"] == 200
    assert response["value"] is card
