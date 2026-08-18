"""Điểm ĐĂNG KÝ DUY NHẤT cho mọi model ORM vào `Base.metadata`.

`alembic/env.py` (autogenerate) và `tests/conftest.py` (create_all trong
test) đều CHỈ import module này để nạp metadata — không import trực tiếp
từng module model riêng lẻ nữa.

KHÔNG XOÁ MỘT DÒNG IMPORT NÀO Ở ĐÂY, kể cả khi linter báo "unused import":
mỗi model chỉ đăng ký được vào `Base.metadata` bằng cách được IMPORT ít nhất
một lần ở đâu đó trước khi `Base.metadata` được đọc. Nếu một model bị bỏ sót
(xoá nhầm dòng import, hoặc thêm model mới mà quên thêm vào đây), hậu quả
không phải là một lỗi ồn ào — nó là:

  - `alembic revision --autogenerate` sẽ coi bảng đó là "không còn được khai
    báo trong code" và tự sinh ra một migration chứa `DROP TABLE` (kèm mọi
    index của bảng đó). Migration này chạy `upgrade` sạch, review qua mắt
    nhanh cũng dễ lọt vì "đây là autogenerate, chắc đúng" — và hậu quả thật
    sự chỉ lộ ra khi ai đó chạy `alembic upgrade head` trên một CSDL có dữ
    liệu thật: bảng và toàn bộ dữ liệu trong đó biến mất.
  - Trong test, bảng có thể vẫn tồn tại "nhờ may mắn" nếu một file test khác
    tình cờ import module model đó trước (ví dụ qua top-level import của
    chính file test), khiến việc thiếu đăng ký ở đây không bị test nào phát
    hiện — cho tới khi thứ tự collect test đổi hoặc file test kia bị xoá.

Vì vậy: một model mới = một dòng import mới TẠI ĐÂY, không phải rải import
đăng ký riêng lẻ ở `alembic/env.py`/`tests/conftest.py`. `test_models.py`
(tests/test_models.py) pin cứng danh sách tên bảng kỳ vọng có mặt trong
`Base.metadata` khi chỉ import module này — xoá một dòng import ở đây sẽ làm
test đó đỏ ngay, thay vì để lộ ra qua một migration DROP TABLE.
"""

import app.modules.auth.models
import app.modules.llm.ledger  # noqa: F401  đăng ký bảng token_ledger
from app.db import Base  # noqa: F401  re-export tiện cho nơi chỉ cần Base.metadata
