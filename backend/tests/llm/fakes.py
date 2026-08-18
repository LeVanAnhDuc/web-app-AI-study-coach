from collections import deque

from app.modules.llm.types import CallSpec, Capability, Usage


class FakeProvider:
    """Provider giả: trả lần lượt các phản hồi đã nạp sẵn, hoặc ném lỗi đã nạp sẵn."""

    def __init__(
        self,
        name: str = "fake",
        model: str = "fake-1",
        capabilities: frozenset[Capability] = frozenset(),
        responses: list[str] | None = None,
        errors: list[Exception | None] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.capabilities = capabilities
        self._responses = deque(responses or [])
        self._errors = deque(errors or [])
        self.calls: list[CallSpec] = []
        self.closed = False

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        self.calls.append(spec)
        if self._errors:
            error = self._errors.popleft()
            if error is not None:
                raise error
        text = self._responses.popleft() if self._responses else "{}"
        return text, Usage(provider=self.name, model=self.model, input_tokens=10, output_tokens=20)

    async def aclose(self) -> None:
        self.closed = True
