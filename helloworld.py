import os
import json
from pathlib import Path

from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, RunConfig, Runner
from agents.usage import serialize_usage


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_dotenv()


deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
if not deepseek_api_key:
    raise RuntimeError("Please set DEEPSEEK_API_KEY before running this example.")

deepseek_client = AsyncOpenAI(
    api_key=deepseek_api_key,
    base_url="https://api.deepseek.com",
)

model = OpenAIChatCompletionsModel(
    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    openai_client=deepseek_client,
)


agent = Agent(
    name="Hello World Agent",
    instructions="You are a concise assistant. Reply with a cheerful hello world.",
    model=model,
)

result = Runner.run_sync(
    agent,
    "Say hello world in one short sentence.",
    run_config=RunConfig(tracing_disabled=True),
)

print(result.final_output)
print(json.dumps(serialize_usage(result.context_wrapper.usage), indent=2))
