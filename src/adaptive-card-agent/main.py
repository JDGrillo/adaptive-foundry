from __future__ import annotations

import logging
import os
from pathlib import Path

from azure.ai.agentserver.activity import ActivityAgentServerHost
from dotenv import load_dotenv
from microsoft_agents.activity import Activity, ActivityTypes, InvokeResponse

import cards
from agent_service import ConversationAgent
from task_store import TaskStore

load_dotenv()

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("adaptive-card-agent")

SOURCE_ROOT = Path(__file__).resolve().parent
store_path = Path(os.getenv("TASK_STORE_PATH", "data/tasks.json"))
if not store_path.is_absolute():
    store_path = SOURCE_ROOT / store_path

store = TaskStore(store_path)
conversation_agent = ConversationAgent()
host = ActivityAgentServerHost()
app = host.agent_app


def _conversation_id(activity) -> str:
    conversation = getattr(activity, "conversation", None)
    return getattr(conversation, "id", None) or "local"


async def _send_tasks_card(context, conversation_id: str) -> None:
    attachment = cards.tasks_card_attachment(store.list_tasks(conversation_id))
    await context.send_activity(
        Activity(type=ActivityTypes.message, attachments=[attachment])
    )


def _apply_action(conversation_id: str, verb: str, data: dict) -> None:
    task_id = str(data.get("taskId") or "")

    if verb == "add_task":
        store.add_task(conversation_id, str(data.get("newTask") or ""))
    elif verb == "update_task":
        store.update_task(
            conversation_id,
            task_id,
            title=str(data.get("updatedTitle") or ""),
        )
    elif verb == "toggle_task":
        store.update_task(
            conversation_id,
            task_id,
            completed=bool(data.get("completed")),
        )
    elif verb == "delete_task":
        store.delete_task(conversation_id, task_id)
    elif verb != "refresh_tasks":
        raise ValueError(f"Unsupported card action '{verb}'.")


@app.activity("message")
async def on_message(context, _state):
    activity = context.activity
    conversation_id = _conversation_id(activity)

    submitted = cards.parse_action(activity)
    if submitted:
        verb, data = submitted
        try:
            _apply_action(conversation_id, verb, data)
        except (KeyError, ValueError) as error:
            await context.send_activity(str(error))
            return
        await _send_tasks_card(context, conversation_id)
        return

    user_text = (activity.text or "").strip()
    if user_text.lower() in {"tasks", "task", "/tasks", "show tasks", "show my tasks"}:
        await _send_tasks_card(context, conversation_id)
        return

    if user_text.lower() in {"help", "/help"}:
        await context.send_activity(
            "Type `tasks` to open the CRUD card. Other messages use the "
            "Agent Framework fallback when Foundry model settings are configured."
        )
        return

    if user_text:
        await context.send_activity(await conversation_agent.answer(user_text))


@app.activity("invoke")
async def on_invoke(context, _state):
    activity = context.activity
    if getattr(activity, "name", None) != cards.ADAPTIVE_ACTION_INVOKE:
        return

    parsed = cards.parse_action(activity)
    if not parsed:
        await context.send_activity(
            Activity(
                type=ActivityTypes.invoke_response,
                value=InvokeResponse(
                    status=400,
                    body={"statusCode": 400, "value": "Invalid card action."},
                ),
            )
        )
        return

    conversation_id = _conversation_id(activity)
    verb, data = parsed
    try:
        _apply_action(conversation_id, verb, data)
    except (KeyError, ValueError) as error:
        error_card = cards.build_tasks_card(
            store.list_tasks(conversation_id), error=str(error)
        )
        await context.send_activity(
            Activity(
                type=ActivityTypes.invoke_response,
                value=InvokeResponse(
                    status=200,
                    body=cards.card_invoke_response(error_card),
                ),
            )
        )
        return

    refreshed_card = cards.build_tasks_card(store.list_tasks(conversation_id))
    await context.send_activity(
        Activity(
            type=ActivityTypes.invoke_response,
            value=InvokeResponse(
                status=200,
                body=cards.card_invoke_response(refreshed_card),
            ),
        )
    )


@app.activity("conversationUpdate")
async def on_members_added(context, _state):
    members = context.activity.members_added or []
    for member in members:
        if member.id != context.activity.recipient.id:
            await context.send_activity(
                "Welcome. Type `tasks` to open the Adaptive Card CRUD demo."
            )


@app.error
async def on_error(context, error):
    logger.error(
        "Activity handler failed: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    await context.send_activity(
        "The request failed. Check the agent logs for details and try again."
    )


if __name__ == "__main__":
    logger.info(
        "Starting Adaptive Card CRUD agent; conversational fallback enabled=%s",
        conversation_agent.enabled,
    )
    host.run()
