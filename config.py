import json
import sys
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",          # лишние переменные в .env не ломают запуск
    )

    # обязательные
    BOT_TOKEN: str = Field(..., min_length=10, description="Токен от @BotFather")
    ADMIN_ID: int = Field(..., gt=0, description="Telegram-ID владельца бота")

    # опциональные
    CELESTIANA_ID: int = Field(5160386506, gt=0)
    DB_FILE: str = "users.db"
    WAIT_TIMEOUT: int = Field(90, ge=10, le=600)      # сек. ожидания картинки
    CROP_BOX: tuple[int, int, int, int] = (170, 450, 610, 567)

    @field_validator("BOT_TOKEN")
    @classmethod
    def _token_sane(cls, v: str) -> str:
        v = v.strip().strip('"\'')
        if v in {"ВСТАВЬ_ТОКЕН", "CHANGE_ME"}:
            raise ValueError("замените заглушку на реальный токен")
        if ":" not in v:  # валидный токен выглядит как "123456789:AA..."
            raise ValueError("не похоже на токен (ожидался формат '123456789:AA...')")
        return v

    @field_validator("CROP_BOX", mode="before")
    @classmethod
    def _crop_box_parse(cls, v):
        # Принимает и JSON-вид '[170, 450, 610, 567]', и '170,450,610,567'.
        if isinstance(v, str):
            v = v.strip()
            try:
                v = json.loads(v) if v.startswith("[") else v.replace(";", ",").split(",")
            except json.JSONDecodeError as e:
                raise ValueError(f"не могу разобрать CROP_BOX: {e}") from e
        box = tuple(int(x) for x in v)
        if len(box) != 4:
            raise ValueError("CROP_BOX должен состоять из 4 чисел")
        x1, y1, x2, y2 = box
        if x2 <= x1 or y2 <= y1:
            raise ValueError("CROP_BOX: x2/y2 должны быть больше x1/y1")
        return box


def _load() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        print("❌ Ошибка конфигурации:")
        for err in e.errors():
            loc = " -> ".join(str(x) for x in err["loc"])
            print(f"  • {loc}: {err['msg']}")
        print(f"\nСоздай {ENV_FILE.name} по примеру .env.example "
              f"или задай переменные окружения.")
        sys.exit(1)

Config = _load()