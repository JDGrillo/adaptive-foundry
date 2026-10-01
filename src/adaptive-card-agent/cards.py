from __future__ import annotations

from typing import Any

from microsoft_agents.activity import Attachment

from task_store import TaskItem

ADAPTIVE_CARD_CONTENT_TYPE = "application/vnd.microsoft.card.adaptive"
ADAPTIVE_ACTION_INVOKE = "adaptiveCard/action"


def build_tasks_card(tasks: list[TaskItem], error: str | None = None) -> dict[str, Any]:
    completed_count = sum(task.completed for task in tasks)
    open_count = len(tasks) - completed_count

    body: list[dict[str, Any]] = [
        {
            "type": "Container",
            "style": "emphasis",
            "items": [
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "auto",
                            "verticalContentAlignment": "Center",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "✓",
                                    "size": "ExtraLarge",
                                    "weight": "Bolder",
                                    "color": "Accent",
                                    "horizontalAlignment": "Center",
                                    "spacing": "None",
                                }
                            ],
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "Task board",
                                    "weight": "Bolder",
                                    "size": "Large",
                                    "spacing": "None",
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "Adaptive Card workspace",
                                    "isSubtle": True,
                                    "spacing": "None",
                                },
                            ],
                        },
                    ],
                }
            ],
        },
        {
            "type": "ColumnSet",
            "spacing": "Medium",
            "columns": [
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"{open_count} open",
                            "weight": "Bolder",
                            "color": "Accent",
                            "horizontalAlignment": "Center",
                        }
                    ],
                },
                {
                    "type": "Column",
                    "width": "stretch",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"{completed_count} completed",
                            "weight": "Bolder",
                            "color": "Good",
                            "horizontalAlignment": "Center",
                        }
                    ],
                },
            ],
        },
        {
            "type": "TextBlock",
            "text": "Create, update, complete, or delete a task.",
            "wrap": True,
            "isSubtle": True,
            "horizontalAlignment": "Center",
            "spacing": "Small",
        },
    ]

    if error:
        body.append(
            {
                "type": "TextBlock",
                "text": error,
                "wrap": True,
                "color": "Attention",
                "weight": "Bolder",
                "separator": True,
            }
        )

    if not tasks:
        body.append(
            {
                "type": "TextBlock",
                "text": "No tasks yet. Add one below.",
                "wrap": True,
                "isSubtle": True,
                "separator": True,
            }
        )

    for task in tasks:
        title = f"~~{task.title}~~" if task.completed else task.title
        status = "Completed" if task.completed else "Open"
        body.append(
            {
                "type": "Container",
                "separator": True,
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": title,
                                        "wrap": True,
                                        "weight": "Bolder",
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": status,
                                        "isSubtle": True,
                                        "spacing": "None",
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "type": "ActionSet",
                        "actions": [
                            {
                                "type": "Action.Execute",
                                "title": "Reopen" if task.completed else "Complete",
                                "verb": "toggle_task",
                                "associatedInputs": "none",
                                "data": {
                                    "taskId": task.id,
                                    "completed": not task.completed,
                                },
                            },
                            {
                                "type": "Action.ShowCard",
                                "title": "Edit",
                                "card": {
                                    "type": "AdaptiveCard",
                                    "body": [
                                        {
                                            "type": "Input.Text",
                                            "id": "updatedTitle",
                                            "label": "Task title",
                                            "value": task.title,
                                            "isRequired": True,
                                            "errorMessage": "Enter a task title.",
                                        }
                                    ],
                                    "actions": [
                                        {
                                            "type": "Action.Execute",
                                            "title": "Save",
                                            "verb": "update_task",
                                            "data": {"taskId": task.id},
                                        }
                                    ],
                                },
                            },
                            {
                                "type": "Action.Execute",
                                "title": "Delete",
                                "verb": "delete_task",
                                "style": "destructive",
                                "associatedInputs": "none",
                                "data": {"taskId": task.id},
                            },
                        ],
                    },
                ],
            }
        )

    body.append(
        {
            "type": "Input.Text",
            "id": "newTask",
            "label": "New task",
            "placeholder": "Describe the task",
            "separator": True,
        }
    )

    return {
        "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "body": body,
        "actions": [
            {
                "type": "Action.Execute",
                "title": "Add task",
                "verb": "add_task",
            },
            {
                "type": "Action.Execute",
                "title": "Refresh",
                "verb": "refresh_tasks",
                "associatedInputs": "none",
            },
        ],
    }


def tasks_card_attachment(
    tasks: list[TaskItem], error: str | None = None
) -> Attachment:
    return Attachment(
        content_type=ADAPTIVE_CARD_CONTENT_TYPE,
        content=build_tasks_card(tasks, error),
    )


def card_invoke_response(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "type": ADAPTIVE_CARD_CONTENT_TYPE,
        "value": card,
    }


def parse_action(activity: Any) -> tuple[str, dict[str, Any]] | None:
    value = _as_dict(getattr(activity, "value", None))
    if not value:
        return None

    action = _as_dict(value.get("action"))
    if action:
        verb = action.get("verb")
        data = _as_dict(action.get("data"))
    else:
        verb = value.get("verb")
        data = value

    if not isinstance(verb, str) or not verb:
        return None
    return verb, data


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(by_alias=True)
        return result if isinstance(result, dict) else {}
    return {}
