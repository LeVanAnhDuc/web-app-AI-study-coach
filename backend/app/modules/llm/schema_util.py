from typing import Any

from pydantic import BaseModel

_GIU_LAI = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "description",
    "format",
    "nullable",
}


def to_provider_schema(model: type[BaseModel]) -> dict:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _rut_gon(_noi_tuyen(raw, defs))


def _noi_tuyen(node: Any, defs: dict) -> Any:
    """Thay mọi $ref bằng chính định nghĩa nó trỏ tới.

    Model tự tham chiếu làm hàm này đệ quy vô hạn khi giải quyết $ref.
    Các model hiện tại không tự tham chiếu nên không có xử lý chu kỳ.
    """
    if isinstance(node, list):
        return [_noi_tuyen(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        ten = node["$ref"].rsplit("/", 1)[-1]
        return _noi_tuyen(defs[ten], defs)

    # Pydantic biểu diễn `X | None` bằng anyOf gồm nhánh null.
    # Nhà cung cấp không hiểu anyOf, nên lấy nhánh không phải null.
    # LƯU Ý: Nếu có union thực sự của hai kiểu không null (ví dụ A | B),
    # hàm này sẽ chỉ giữ lại nhánh đầu tiên và bỏ các nhánh khác.
    # Các model hiện tại không dùng union như vậy, nhưng nếu thêm sau này
    # phải xem xét lại logic này.
    for tu_khoa in ("anyOf", "oneOf", "allOf"):
        if tu_khoa in node:
            nhanh = [
                b for b in node[tu_khoa] if not (isinstance(b, dict) and b.get("type") == "null")
            ]
            if not nhanh:
                raise ValueError(
                    f"Union không có nhánh không null và không thể chuyển đổi: {tu_khoa}"
                )
            goc = _noi_tuyen(nhanh[0], defs)
            khac = {k: v for k, v in node.items() if k != tu_khoa}
            return {**goc, **_noi_tuyen(khac, defs)}

    return {k: _noi_tuyen(v, defs) for k, v in node.items()}


def _rut_gon(node: Any, parent_key: str | None = None) -> Any:
    """Bỏ mọi khoá nhà cung cấp không hiểu, ví dụ title, default, $defs."""
    if isinstance(node, list):
        return [_rut_gon(item, parent_key) for item in node]
    if not isinstance(node, dict):
        return node

    # Inside properties, preserve property names but filter their value schemas
    if parent_key == "properties":
        return {k: _rut_gon(v, None) for k, v in node.items()}

    # Otherwise, filter schema keys and recurse with context
    result = {}
    for k, v in node.items():
        if k in _GIU_LAI:
            result[k] = _rut_gon(v, k)
    return result
