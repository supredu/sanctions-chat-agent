import os
from dataclasses import dataclass
from pathlib import Path

from agents import AsyncOpenAI, OpenAIChatCompletionsModel, RunConfig


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class AppConfig:
    deepseek_api_key: str
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    tracing_disabled: bool = True


def get_config() -> AppConfig:
    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Please set DEEPSEEK_API_KEY in your environment or .env file.")

    return AppConfig(
        deepseek_api_key=api_key,
        deepseek_model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        deepseek_base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def build_model(config: AppConfig | None = None) -> OpenAIChatCompletionsModel:
    app_config = config or get_config()
    client = AsyncOpenAI(
        api_key=app_config.deepseek_api_key,
        base_url=app_config.deepseek_base_url,
    )

    return OpenAIChatCompletionsModel(
        model=app_config.deepseek_model,
        openai_client=client,
    )


def build_run_config(config: AppConfig | None = None) -> RunConfig:
    app_config = config or get_config()
    return RunConfig(tracing_disabled=app_config.tracing_disabled)
