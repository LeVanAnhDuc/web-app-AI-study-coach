import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from app.modules.llm.providers.base import Provider
from app.modules.llm.types import CallSpec, LLMError, Usage


class FixtureMissing(LLMError):
    """Chạy ở chế độ replay nhưng chưa có bản ghi cho lời gọi này."""


def fixture_key(provider_name: str, model: str, spec: CallSpec) -> str:
    # timeout_seconds bị loại khỏi khóa có chủ đích: đó là hạn chót phía
    # client, không phải một phần ý nghĩa của lời gọi. Đưa nó vào sẽ làm
    # hỏng mọi fixture ngay khi ai đó chỉnh lại thời gian chờ.
    material = json.dumps(
        {
            "provider": provider_name,
            "model": model,
            "task": spec.task.value,
            "system": spec.system,
            "user": spec.user,
            "schema": spec.json_schema,
            "max_output_tokens": spec.max_output_tokens,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:32]


class FixtureProvider:
    """Bọc một provider để ghi lại hoặc phát lại phản hồi.

    off    — đi thẳng ra ngoài, không đụng đĩa
    record — gọi thật rồi lưu lại
    replay — chỉ đọc từ đĩa, không bao giờ ra mạng
    """

    def __init__(self, inner: Provider, mode: str, directory: Path) -> None:
        self._inner = inner
        self._mode = mode
        self._dir = Path(directory)
        self.name = inner.name
        self.model = inner.model
        self.capabilities = inner.capabilities

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        if self._mode == "off":
            return await self._inner.complete(spec)

        path = self._dir / f"{fixture_key(self.name, self.model, spec)}.json"

        if self._mode == "replay":
            if not path.exists():
                raise FixtureMissing(
                    f"Thiếu fixture cho {self.name}/{spec.task.value} tại {path}. "
                    f"Chạy lại ở chế độ record để tạo."
                )
            data = json.loads(path.read_text(encoding="utf-8"))
            return data["text"], Usage(**data["usage"])

        text, usage = await self._inner.complete(spec)
        self._dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "task": spec.task.value,
                    "text": text,
                    "usage": asdict(usage),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return text, usage

    async def aclose(self) -> None:
        await self._inner.aclose()
