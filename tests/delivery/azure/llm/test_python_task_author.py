"""Azure OpenAI Python task author wire contract."""

import json

import httpx

from fdai.delivery.azure.llm.python_task_author import (
    AzureOpenAIPythonTaskAuthor,
    AzureOpenAIPythonTaskAuthorConfig,
)
from fdai.shared.providers.python_task_author import PythonTaskAuthorRequest
from fdai.shared.providers.testing.workload_identity import StaticWorkloadIdentity
from fdai.shared.providers.vm_task import PythonTaskCapability


async def test_author_requests_json_and_returns_validated_shape() -> None:
    seen: list[httpx.Request] = []
    generated = {
        "task_id": "ignored.by.server",
        "version": "1.0.0",
        "entrypoint": "main.py",
        "files": [{"path": "main.py", "content": "import torch\nprint('ok')\n"}],
        "required_modules": ["torch"],
        "capabilities": ["gpu"],
        "timeout_seconds": 300,
        "python_executable": "/usr/bin/python3",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(generated)}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        author = AzureOpenAIPythonTaskAuthor(
            identity=StaticWorkloadIdentity(
                audience="https://cognitiveservices.azure.com/.default",
                token="test-token",  # noqa: S106 - deterministic fake
            ),
            http_client=client,
            config=AzureOpenAIPythonTaskAuthorConfig(
                endpoint="https://example.openai.azure.com",
                deployment="task-author",
            ),
        )
        task = await author.author(
            PythonTaskAuthorRequest(
                intent="Check whether CUDA is available.",
                task_id_hint="gpu.health-check",
                target_capabilities=frozenset({PythonTaskCapability.GPU}),
                allowed_modules=("torch",),
            )
        )

    assert task.task_id == "gpu.health-check"
    assert task.required_modules == ("torch",)
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert "Check whether CUDA" in body["messages"][1]["content"]
