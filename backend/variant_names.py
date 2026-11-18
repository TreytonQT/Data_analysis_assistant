"""Operational name normalization, similarity and common character extraction."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


COLORS = sorted({
    "黑色", "白色", "红色", "蓝色", "绿色", "黄色", "粉色", "紫色", "灰色", "橙色", "棕色", "褐色",
    "咖啡色", "米白色", "米色", "杏色", "卡其色", "银色", "金色", "玫瑰金", "香槟金", "枪色",
    "透明色", "透明", "无色", "彩色", "混色", "多色", "墨绿", "浅绿", "深绿", "浅蓝", "深蓝",
    "藏蓝", "天蓝", "宝蓝", "浅粉", "深粉", "浅灰", "深灰", "酒红", "玳瑁色", "磨砂黑", "电镀色",
    "黑", "白", "红", "蓝", "绿", "黄", "粉", "紫", "灰", "橙", "棕", "银", "金",
    "black", "white", "red", "blue", "green", "yellow", "pink", "purple", "grey", "gray",
    "orange", "brown", "silver", "gold", "beige", "transparent",
}, key=lambda value: (-len(value), value))
NUMBER = r"\d+(?:\.\d+)?"
SIZE = rf"(?:长|宽|高|直径|[Øφ])?{NUMBER}(?:[-~～]{NUMBER})?(?:[x×*]{NUMBER})*(?:mm|cm|m|inches|inch|in|毫米|厘米|英寸|米|寸|码|号)(?:长|宽|高)?"
CLOTHING_SIZE = r"(?:[2-6]?X{1,3}[LS]|XS|S|M|L)(?:码)?"
ATTRIBUTE = re.compile(
    rf"(?:{'|'.join(re.escape(value) for value in COLORS)}|{SIZE}|{CLOTHING_SIZE}|小号|中号|大号|加大号|特大号)",
    re.IGNORECASE,
)
TRAILING_MARKER = re.compile(r"\s*(?:\(\s*\d+\.\d+\s*\)|【[A-Za-z]+】|\[[A-Za-z]+\])\s*$")


def clean_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    while TRAILING_MARKER.search(text):
        text = TRAILING_MARKER.sub("", text).strip()
    return text


def _is_attribute(text: str) -> bool:
    text = re.sub(r"^(?:颜色|色彩|尺寸|规格|color|colour|size)\s*[:：]\s*", "", text.strip(), flags=re.IGNORECASE)
    remaining = ATTRIBUTE.sub("", text)
    remaining = re.sub(r"各\d+(?:个|条|只|对|件)?", "", remaining)
    return bool(ATTRIBUTE.search(text)) and not re.sub(r"[\s,+＋/、&*×x-]+", "", remaining)


def split_variant_name(value: str) -> tuple[str, str]:
    """Strip only recognized trailing colour/size attributes, never product specs in the body."""
    text = clean_name(value)
    attributes = []
    while text:
        bracket = re.fullmatch(r"(.*)\(([^()]*)\)\s*", text)
        if bracket and bracket[1].strip() and _is_attribute(bracket[2]):
            attributes.insert(0, bracket[2].strip())
            text = bracket[1].rstrip(" -_/")
            continue
        matches = list(re.finditer(r"[\s/_-]+", text))
        suffix = next(((text[:match.start()], text[match.end():]) for match in matches
                       if text[:match.start()].strip() and _is_attribute(text[match.end():])), None)
        if suffix:
            text, attribute = suffix
            attributes.insert(0, attribute.strip())
            text = text.rstrip(" -_/")
            continue
        attached_size = re.fullmatch(rf"(.+?)({SIZE}|(?:[2-6]?X{{1,3}}[LS]|XS|S|M|L)码)", text, re.IGNORECASE)
        if attached_size:
            text = attached_size[1].rstrip(" -_/")
            attributes.insert(0, attached_size[2])
            continue
        break
    return text.strip(), " / ".join(attributes)


def normalized_product_name(value: str) -> str:
    return re.sub(r"\s+", " ", clean_name(value)).strip().upper()


def product_name_similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, first, second, autojunk=False).ratio()


def _common_subsequence(first: str, second: str) -> str:
    lengths = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for i in range(len(first) - 1, -1, -1):
        for j in range(len(second) - 1, -1, -1):
            lengths[i][j] = (1 + lengths[i + 1][j + 1] if first[i] == second[j]
                             else max(lengths[i + 1][j], lengths[i][j + 1]))
    i = j = 0
    common = []
    while i < len(first) and j < len(second):
        if first[i] == second[j]:
            common.append(first[i])
            i += 1
            j += 1
        elif lengths[i + 1][j] > lengths[i][j + 1]:
            i += 1
        else:
            # On a tie, retain the earlier character in the lower-numbered SKU.
            j += 1
    return "".join(common)


def common_product_name(names: list[str]) -> str:
    """Intersect in SKU order; normalization keeps attributes in the comparison."""
    normalized = [normalized_product_name(name) for name in names]
    if not normalized or any(not name for name in normalized):
        return ""
    common = normalized[0]
    for name in normalized[1:]:
        common = _common_subsequence(common, name)
    previous = None
    while previous != common:
        previous = common
        common = re.sub(r"\(\s*\)|\[\s*\]|【\s*】|\{\s*\}", "", common)
    common = re.sub(r"([\s\-_/、,，:：;；|+])\1+", r"\1", common)
    return common.strip(" -_/、,，:：;；|+")
