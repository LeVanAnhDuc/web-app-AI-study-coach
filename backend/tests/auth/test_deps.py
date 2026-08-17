from app.modules.auth.deps import _chua_dang_nhap


def test_chua_dang_nhap_tra_ve_instance_moi_moi_lan_goi():
    # Đây là lá chắn hồi quy: nếu ai đó "tối ưu" _chua_dang_nhap() trở lại thành một
    # hằng số HTTPException dùng chung, test này sẽ báo lỗi trước khi rò rỉ tái xuất hiện.
    thu_nhat = _chua_dang_nhap()
    thu_hai = _chua_dang_nhap()
    assert thu_nhat is not thu_hai
