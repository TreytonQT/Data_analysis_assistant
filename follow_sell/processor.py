from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import json
import zipfile

from openpyxl import load_workbook


VIRTUAL = "虚拟sku(多个用英文';'分割)"
INVENTORY = '*库存sku编号'
COUNTRIES = {'德国': 'DE_PRICE', '法国': 'FR_PRICE', '西班牙': 'ES_PRICE', '意大利': 'IT_PRICE'}
MABANG_FIELDS = {
    '库存SKU中文名称': '*库存sku名称',
    '库存SKU英文名称': '库存sku英文名称',
    '统一成本价': '统一成本价',
    '最新采购价': '最新采购价',
    '重量': '商品重量',
    '原厂SKU': '原厂SKU',
    '库存图片链接': '库存图片地址',
    '商品备注': '商品备注',
    '销售备注': '销售备注',
    '采购备注': '采购备注',
    '开发员': '开发员',
    '销售负责人': '销售负责人',
}


def blank(value):
    return value is None or value == ''


def key(value):
    return '' if blank(value) else str(value).strip()


def issue(file, message, row=None, sku='', sheet=''):
    return {'file': file, 'sheet': sheet, 'row': row, 'sku': sku, 'message': message}


class ValidationError(Exception):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('整批暂停，请修正以下问题后重新校验。')


@dataclass
class Table:
    name: str
    sheet: str
    headers: list
    rows: list


@dataclass
class Result:
    content: bytes
    filename: str
    summary: dict
    columns: list
    rows: list
    warnings: list = field(default_factory=list)


def read_table(content: bytes, name: str, required) -> Table:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 200 * 1024 * 1024:
                raise ValueError('解压后的工作簿超过200MB，请拆分文件。')
        wb = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:
        raise ValidationError([issue(name, f'无法读取xlsx工作簿：{exc}')]) from exc
    try:
        candidates = []
        for ws in wb:
            header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
            headers = [key(v) for v in header]
            if set(required) <= set(headers):
                candidates.append((ws, headers))
        if len(candidates) != 1:
            if candidates:
                message = '多个数据页符合模板，请保留一个需要处理的数据页后重新上传。'
            else:
                listed = ', '.join(required[:8])
                message = f'未找到符合模板的数据页，需要表头：{listed}'
                if len(required) > 8:
                    message += f'等{len(required)}列；请检查是否上传了正确的文件。'
            raise ValidationError([issue(name, message, 1)])
        ws, headers = candidates[0]
        populated = [h for h in headers if h]
        if len(populated) != len(set(populated)):
            raise ValidationError([issue(name, '表头重复，无法确定字段。', 1, sheet=ws.title)])
        rows = []
        for index, values in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
            if all(blank(v) for v in values):
                continue
            if any(not h and not blank(v) for h, v in zip(headers, values)):
                raise ValidationError([issue(name, '存在没有表头的数据列。', index, sheet=ws.title)])
            rows.append((index, {h: v for h, v in zip(headers, values) if h}))
        if not rows:
            raise ValidationError([issue(name, '没有实际数据，请填写模板后重新上传。', sheet=ws.title)])
        return Table(name, ws.title, populated, rows)
    finally:
        wb.close()


def mapping_table(content, name):
    table = read_table(content, name, ['原SKU', '新SKU'])
    seen = {}
    mappings = []
    errors = []
    for row, values in table.rows:
        old, new = key(values['原SKU']), key(values['新SKU'])
        if not old or not new:
            errors.append(issue(name, '原SKU和新SKU均不能为空。', row, new or old, table.sheet))
        elif new in seen:
            errors.append(issue(name, f'新SKU重复，首次出现在第{seen[new]}行。', row, new, table.sheet))
        else:
            seen[new] = row
            mappings.append((row, old, new))
    if errors:
        raise ValidationError(errors)
    return table, mappings


def unique_index(table, field, needed, split=False):
    index = {}
    errors = []
    for row, values in table.rows:
        tokens = [t.strip() for t in key(values.get(field)).split(';')] if split else [key(values.get(field))]
        for token in set(tokens):
            if token not in needed:
                continue
            if token in index:
                errors.append(issue(table.name, f'原SKU来源重复，首次出现在第{index[token][0]}行。', row, token, table.sheet))
            else:
                index[token] = (row, values)
    return index, errors


def price_number(value):
    if blank(value):
        return None
    try:
        number = Decimal(str(value).strip())
        if not number.is_finite() or number < 0:
            raise InvalidOperation
        return number
    except (InvalidOperation, ValueError):
        raise ValueError('售价必须是大于或等于0的有效数字。') from None


def literal(cell, value):
    cell.value = None if blank(value) else value
    if isinstance(value, str):
        cell.data_type = 's'


def serialize(wb):
    stream = BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


def process_oa(mapping, oa, prices, names, resources: Path):
    schema = json.loads((resources / 'oa_schema.json').read_text(encoding='utf-8'))
    headers = schema['headers']
    mt, mappings = mapping_table(mapping, names[0])
    required = ['LENGTH' if h == 'LENGHT' else h for h in headers]
    ot = read_table(oa, names[1], required)
    pt = read_table(prices, names[2], ['MSKU', '国家', '价格'])
    needed = {old for _, old, _ in mappings}
    original, errors = unique_index(ot, 'SKU', needed)
    price_index = {}
    for row, values in pt.rows:
        sku, country = key(values['MSKU']), key(values['国家'])
        if sku not in needed or country not in COUNTRIES:
            continue
        try:
            number = price_number(values['价格'])
        except ValueError as exc:
            errors.append(issue(pt.name, str(exc), row, sku, pt.sheet))
            continue
        if number is None:
            continue
        pair = (sku, country)
        if pair in price_index and price_index[pair][1] != number:
            errors.append(issue(pt.name, f'{country}售价冲突，首次出现在第{price_index[pair][0]}行。', row, sku, pt.sheet))
        else:
            price_index[pair] = (row, number)
    output = []
    warnings = []
    for row, old, new in mappings:
        if old not in original:
            errors.append(issue(mt.name, '原SKU在OA信息中不存在。', row, old, mt.sheet))
            continue
        source_row, source = original[old]
        record = {h: source.get('LENGTH' if h == 'LENGHT' else h) for h in headers}
        record['SKU'] = new
        for country, header in COUNTRIES.items():
            found = price_index.get((old, country))
            if found:
                record[header] = float(found[1])
            else:
                try:
                    fallback = price_number(source.get(header))
                except ValueError as exc:
                    errors.append(issue(ot.name, f'{country}回退{exc}', source_row, old, ot.sheet))
                    continue
                if fallback is None:
                    errors.append(issue(mt.name, f'{country}领星售价与OA原售价均缺失。', row, old, mt.sheet))
                else:
                    record[header] = float(fallback)
                    warnings.append(issue(ot.name, f'{country}领星售价缺失，已沿用OA原售价{fallback}。', source_row, old, ot.sheet))
        output.append(record)
    if errors:
        raise ValidationError(errors)
    wb = load_workbook(resources / 'oa_output.xlsx')
    ws = wb.worksheets[0]
    for r, record in enumerate(output, 3):
        for c, header in enumerate(headers, 1):
            literal(ws.cell(r, c), record[header])
            if header.endswith('_PRICE') and isinstance(record[header], (int, float)):
                ws.cell(r, c).number_format = '0.00'
    preview = ['SKU', 'ZH_NAME', 'SITE', 'ASIN', 'DE_PRICE', 'FR_PRICE', 'ES_PRICE', 'IT_PRICE']
    return Result(serialize(wb), '新SKU的OA批量更新表.xlsx',
                  {'mapping_rows': len(mappings), 'source_rows': len(ot.rows), 'price_rows': len(pt.rows),
                   'matched_rows': len(output), 'output_rows': len(output), 'fallback_prices': len(warnings)},
                  preview, [{h: record[h] for h in preview} for record in output], warnings)


def process_mabang(mapping, generated, original, names):
    mt, mappings = mapping_table(mapping, names[0])
    gt = read_table(generated, names[1], [INVENTORY, VIRTUAL])
    ot = read_table(original, names[2], ['虚拟sku'])
    fields = {src: dst for src, dst in MABANG_FIELDS.items() if src in ot.headers}
    missing = [dst for dst in fields.values() if dst not in gt.headers]
    if missing or not fields:
        raise ValidationError([issue(gt.name, f'没有可更新字段或目标缺少表头：{", ".join(missing)}', 1)])
    new_old = {new: old for _, old, new in mappings}
    needed = set(new_old.values())
    source, errors = unique_index(ot, '虚拟sku', needed, split=True)
    output = []
    updates = []
    seen_inventory = {}
    for row, record in gt.rows:
        inventory = key(record[INVENTORY])
        tokens = {token.strip() for token in key(record[VIRTUAL]).split(';') if token.strip()}
        unknown = tokens - new_old.keys()
        originals = {new_old[token] for token in tokens if token in new_old}
        if not inventory or inventory in seen_inventory:
            errors.append(issue(gt.name, '新库存SKU编号为空或重复。', row, inventory, gt.sheet))
        seen_inventory[inventory] = row
        if not tokens or unknown or len(originals) != 1:
            errors.append(issue(gt.name, '虚拟SKU无法唯一映射到同一原SKU。', row, key(record[VIRTUAL]), gt.sheet))
            continue
        old = next(iter(originals))
        if old not in source:
            errors.append(issue(gt.name, f'原SKU {old} 在原马帮表中不存在。', row, key(record[VIRTUAL]), gt.sheet))
            continue
        values = source[old][1]
        updated = dict(record)
        for src, dst in fields.items():
            updated[dst] = values[src]
        output.append(updated)
        updates.append((row, updated))
    if errors:
        raise ValidationError(errors)
    wb = load_workbook(BytesIO(generated))
    ws = wb[gt.sheet]
    columns = {key(cell.value): cell.column for cell in ws[1] if not blank(cell.value)}
    for row, updated in updates:
        for dst in fields.values():
            literal(ws.cell(row, columns[dst]), updated[dst])
    preview = [h for h in [INVENTORY, '*库存sku名称', VIRTUAL, '商品重量', '统一成本价', '原厂SKU'] if h in gt.headers]
    return Result(serialize(wb), '新SKU的马帮上架表1.xlsx',
                  {'mapping_rows': len(mappings), 'source_rows': len(ot.rows), 'matched_rows': len(output),
                   'output_rows': len(output), 'updated_fields': len(fields)},
                  preview, [{h: record.get(h) for h in preview} for record in output])
