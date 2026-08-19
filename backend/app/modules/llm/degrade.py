"""Tầng hạ cấp JSON: ép, kiểm, thử lại.

Gemini ép được JSON Schema gốc, nhưng Groq và Mistral thì không (xem
docstring của GroqProvider/MistralProvider) — cả hai chỉ đảm bảo cú pháp JSON
hợp lệ, không đảm bảo khớp schema. Ở cấu hình free tier, hai provider "yếu"
này là đường chạy THƯỜNG XUYÊN chứ không phải trường hợp hiếm, nên tầng này
phải tự làm phần việc mà provider không làm: bóc JSON ra khỏi văn bản thô,
kiểm bằng model_cls, và thử lại có kèm thông báo lỗi khi kiểm thất bại.

Ranh giới quan trọng nhất của module này: chỉ retry khi PROVIDER ĐÃ TRẢ LỜI
nhưng câu trả lời sai schema. Khi provider tự thất bại (RateLimited,
QuotaExhausted, ProviderUnavailable) — nghẽn mạng, hết hạn mức, bị chặn an
toàn — retry ở đây không chữa được gì, chỉ đốt thêm một lượt gọi hạn mức miễn
phí. Những lỗi đó phải thoát ra NGAY để tầng định tuyến (Task 18) rơi xuống
provider dự phòng.

complete_structured() CÓ một try/except HẸP quanh provider.complete(), nhưng
nó không retry: khối except đó chỉ gắn usages đã tích luỹ từ các lần thử
TRƯỚC (đã tốn token thật vì provider đã trả lời, chỉ là trả lời sai schema)
vào ngoại lệ rồi `raise` lại NGUYÊN VẸN ngay lập tức — không có `continue`,
không gọi lại provider, không đổi loại ngoại lệ. Nếu thiếu bước gắn usages
này, một lỗi hạ tầng xảy ra ở lần thử thứ hai trở đi sẽ làm mất usages của
(các) lần thử thứ nhất đã thành công về mặt mạng — cùng một kiểu mất dữ liệu
mà việc gắn usages vào SchemaViolation (xem cuối hàm) đã xử lý cho nhánh hết
lượt retry, chỉ khác ở nhánh thoát.
"""

import dataclasses
import re

from pydantic import BaseModel, ValidationError

from app.modules.llm.providers.base import Provider
from app.modules.llm.types import (
    CallSpec,
    Capability,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimited,
    SchemaViolation,
    Usage,
)

# Số lần thử lại mặc định sau lần gọi đầu tiên. Mỗi lần thử lại là một lượt
# gọi API thật, tính vào hạn mức miễn phí dùng chung với người dùng thật —
# đặt thành hằng số có tên thay vì số 2 rải rác trong vòng lặp, để bất kỳ ai
# muốn đổi ngân sách retry chỉ cần sửa một chỗ và thấy ngay lý do nó tồn tại.
_SO_LAN_THU_LAI_MAC_DINH = 2

_KHOI_MA = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_CHI_DAN_JSON = (
    "\n\nChỉ trả về đúng một đối tượng JSON hợp lệ, không kèm lời dẫn, "
    "không bọc trong khối mã, không giải thích thêm."
)


def extract_json(text: str) -> str:
    """Bóc phần JSON ra khỏi văn bản mô hình trả về.

    Chỉ làm việc AN TOÀN: gỡ khối mã markdown và văn bản thừa hai bên một
    đối tượng {...}. KHÔNG thử đoán/sửa JSON hỏng (thêm dấu ngoặc thiếu, sửa
    dấu phẩy thừa...) — một lần sửa đoán sai có thể biến JSON hỏng thành JSON
    hợp lệ nhưng SAI DỮ LIỆU, và dữ liệu đó sẽ chảy thẳng vào ứng dụng như
    một giá trị đáng tin. Nếu không bóc được gì chắc chắn, trả lại nguyên văn
    để bước kiểm schema phía sau thất bại một cách tường minh.
    """
    khoi = _KHOI_MA.search(text)
    if khoi:
        text = khoi.group(1)

    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    dau = text.find("{")
    cuoi = text.rfind("}")
    if dau != -1 and cuoi > dau:
        return text[dau : cuoi + 1]
    return text


async def complete_structured(
    provider: Provider,
    spec: CallSpec,
    model_cls: type[BaseModel],
    max_retries: int = _SO_LAN_THU_LAI_MAC_DINH,
) -> tuple[BaseModel, list[Usage]]:
    """Gọi provider và trả về đối tượng đã kiểm theo model_cls.

    Nếu provider không khai báo Capability.STRUCTURED_OUTPUT (Groq, Mistral
    hiện tại), thêm chỉ dẫn JSON vào prompt hệ thống — provider có ép schema
    gốc (Gemini) thì không cần, vì thêm chỉ dẫn thừa vào đó không sai nhưng
    làm phình prompt vô ích.

    Sai schema thì thử lại tối đa max_retries lần, mỗi lần kèm thông báo lỗi
    cụ thể để mô hình biết chỗ cần sửa. Hết lượt thì ném SchemaViolation.

    Trả về usage của TỪNG lần gọi (kể cả các lần thất bại), không chỉ lần
    cuối cùng thành công — mỗi lần gọi provider đều tốn token thật trong hạn
    mức miễn phí, và bộ đếm hạn mức (task sau) cần con số đúng để không tưởng
    nhầm là còn dư quota trong khi thực ra đã cạn.

    Lỗi hạ tầng (RateLimited, QuotaExhausted, ProviderUnavailable) từ
    provider.complete() KHÔNG bị retry ở đây — chỉ được gắn thêm usages đã
    tích luỹ từ các lần thử trước rồi thoát ra ngay lập tức để tầng định
    tuyến phía trên xử lý (xem docstring module ở đầu file), vì thử lại một
    lỗi hạ tầng không chữa được gì.
    """
    hien_tai = spec
    if Capability.STRUCTURED_OUTPUT not in provider.capabilities:
        hien_tai = dataclasses.replace(spec, system=spec.system + _CHI_DAN_JSON)

    usages: list[Usage] = []
    loi_cuoi = ""

    for lan in range(max_retries + 1):
        try:
            text, usage = await provider.complete(hien_tai)
        except (RateLimited, QuotaExhausted, ProviderUnavailable) as exc:
            # GẮN RỒI NÉM LẠI, KHÔNG RETRY: khối này không có continue, không
            # gọi lại provider — nó chỉ gắn usages vào chính ngoại lệ rồi để nó
            # thoát ra NGAY, y hệt trước khi có khối try này.
            #
            # PHÉP CỘNG, KHÔNG PHẢI PHÉP GÁN — và đây là chỗ dễ "dọn gọn" thành
            # sai nhất trong file này, vì có HAI nguồn usage khác nhau cùng đổ
            # về một dòng:
            #   (a) `usages` — các lần thử TRƯỚC trong chính vòng lặp này: đã
            #       tốn token thật, vì provider ĐÃ trả lời ở các lần đó, chỉ là
            #       trả lời sai schema. Thiếu chúng là đúng lỗi dữ liệu mà việc
            #       gắn usages vào SchemaViolation bên dưới xử lý cho nhánh
            #       "hết lượt retry".
            #   (b) `exc.usages` — usage mà CHÍNH ADAPTER đã gắn TẠI CHỖ NÉM.
            #       Mọi chỗ ném sau một HTTP 200 (finishReason MAX_TOKENS /
            #       finish_reason "length" đã tiêu TRỌN ngân sách output; prompt
            #       bị chặn vẫn tiêu trọn token prompt; không có candidate) đều
            #       kèm `usages=[usage]` — xem chú thích trong gemini.py và
            #       openai_compat.py.
            # Một phép GÁN THẲNG (`exc.usages = usages`) xoá sạch (b) và thay
            # bằng (a) — mà (a) RỖNG ở lần thử ĐẦU TIÊN, đúng lúc (b) hay xuất
            # hiện nhất. Hậu quả đã đo: một phản hồi MAX_TOKENS (800 vào, 512
            # ra) đi qua LLMService.run() cho một tác vụ ép schema ném
            # AllProvidersFailed với usages rỗng và KHÔNG ghi dòng sổ nào. Phép
            # gán từng vô hại vì hồi nó được viết, adapter chưa gắn gì cả — nó
            # trở thành mất dữ liệu thật ngay khi adapter bắt đầu gắn.
            #
            # THỨ TỰ cũng phải giữ: tích luỹ trước, phần ngoại lệ tự mang sau —
            # giống routing.py, để không có gì bị bỏ hay bị đếm hai lần.
            exc.usages = usages + exc.usages
            raise
        usages.append(usage)

        try:
            # Bắt đúng ValidationError, KHÔNG bắt thêm ValueError/JSONDecodeError:
            # model_validate_json là điểm parse JSON DUY NHẤT ở đây, và nó luôn
            # ném ValidationError (type json_invalid) khi chuỗi không parse được,
            # không bao giờ ném json.JSONDecodeError. Nếu sau này đổi sang
            # json.loads(...) rồi model_validate(...), phải mở rộng except này.
            return model_cls.model_validate_json(extract_json(text)), usages
        except ValidationError as exc:
            loi_cuoi = _tom_tat_loi(exc)

        if lan < max_retries:
            hien_tai = dataclasses.replace(
                hien_tai,
                user=(
                    f"{spec.user}\n\n"
                    f"Lần trả lời trước không dùng được. Lỗi: {loi_cuoi}\n"
                    f"Hãy trả lại đúng một đối tượng JSON khớp yêu cầu."
                ),
            )

    # usages truyền qua tham số usages= của constructor (kế thừa từ LLMError),
    # KHÔNG gắn động sau khi dựng: tầng định tuyến (Task 18) rơi xuống
    # provider dự phòng khi gặp SchemaViolation, và nếu không đọc được usages
    # từ đây thì các lần gọi đã tốn token thật của provider vừa hỏng sẽ biến
    # mất khỏi sổ token, dù chúng đã tiêu hạn mức miễn phí thật sự.
    raise SchemaViolation(
        f"{provider.name} không trả được JSON khớp schema sau "
        f"{max_retries + 1} lần thử. Lỗi cuối: {loi_cuoi}",
        usages=usages,
    )


def _tom_tat_loi(exc: ValidationError) -> str:
    """Rút gọn ValidationError thành một dòng ngắn để nhét vào prompt thử lại.

    Giới hạn 5 lỗi đầu vì pydantic có thể liệt kê rất nhiều lỗi cho một JSON
    lệch cấu trúc nặng — nhét hết vào prompt vừa tốn token vừa không giúp mô
    hình sửa tốt hơn so với vài lỗi đầu tiên.
    """
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
