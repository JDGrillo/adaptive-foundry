from __future__ import annotations

import os

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential


class ConversationAgent:
    def __init__(self) -> None:
        self._credential: DefaultAzureCredential | None = None
        self._agent: Agent | None = None

        endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if endpoint and model:
            self._credential = DefaultAzureCredential()
            client = FoundryChatClient(
                project_endpoint=endpoint,
                model=model,
                credential=self._credential,
            )
            self._agent = Agent(
                client=client,
                name="AdaptiveCardCrudAssistant",
                instructions=(
                    "You are the conversational fallback for a task-board demo. "
                    "Keep responses concise. Tell users to type 'tasks' when they "
                    "want the interactive CRUD card."
                ),
                default_options={"store": False},
            )

    @property
    def enabled(self) -> bool:
        return self._agent is not None

    async def answer(self, prompt: str) -> str:
        if self._agent is None:
            return "Type `tasks` to open the interactive task board."
        response = await self._agent.run(prompt)
        return response.text or str(response)

    async def close(self) -> None:
        if self._credential is not None:
            await self._credential.close()
