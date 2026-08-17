from typing import Protocol, runtime_checkable

from app.modules.llm.types import Capability, CallSpec, Usage


@runtime_checkable
class Provider(Protocol):
    # Lưu ý: @runtime_checkable chỉ khiến isinstance() kiểm tra sự tồn tại của
    # các PHƯƠNG THỨC (complete, aclose) — nó không kiểm tra các thuộc tính
    # name, model, capabilities. Vì vậy KHÔNG dùng isinstance(x, Provider) để
    # xác nhận x là một provider dùng được; nó có thể trả True cho một đối
    # tượng thiếu các thuộc tính mà mọi nơi tiêu thụ đều cần đọc.
    name: str
    model: str
    capabilities: frozenset[Capability]

    async def complete(self, spec: CallSpec) -> tuple[str, Usage]:
        """Gửi một lời gọi và trả về (văn bản thô, số token đã dùng).

        Ném RateLimited, QuotaExhausted, hoặc ProviderUnavailable khi thất bại.
        Không tự retry — việc đó thuộc về tầng trên.
        """
        ...

    async def aclose(self) -> None: ...
