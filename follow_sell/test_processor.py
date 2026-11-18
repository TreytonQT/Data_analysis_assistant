from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import json
import os

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from follow_sell.processor import INVENTORY, MABANG_FIELDS, VIRTUAL, ValidationError, process_mabang, process_oa
from follow_sell.server import create_app


HEADERS = ['SKU', 'ZH_NAME', 'SITE', 'ASIN', 'LENGHT', 'DE_PRICE', 'FR_PRICE', 'ES_PRICE', 'IT_PRICE', 'NL_PRICE', 'UK_PRICE', 'FIRST_ORDER_NO']


def workbook(headers, rows, extra=False):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    if extra:
        wb.create_sheet('保留页')['A1'] = '不要改动'
    stream = BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


class ProcessorTests(TestCase):
    def setUp(self):
        root = Path(os.environ.get('FOLLOW_SELL_TEST_ROOT', r'D:\AI_project\Output\AmazonFollowSell\work\tests'))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.resources = Path(self.temp.name)
        self.resources.joinpath('oa_schema.json').write_text(json.dumps({'headers': HEADERS}), encoding='utf-8')
        self.resources.joinpath('oa_output.xlsx').write_bytes(workbook(HEADERS, [['说明'] * len(HEADERS)]))
        templates = self.resources / 'templates'
        templates.mkdir()
        (templates / '【1】SKU映射表.xlsx').write_bytes(workbook(['原SKU', '新SKU'], [['old', 'new']]))
        self.mapping = workbook(['原SKU', '新SKU'], [['old', 'new']])
        self.oa_headers = ['LENGTH' if h == 'LENGHT' else h for h in HEADERS]
        self.oa_row = ['old', '名称\n完整文本', 'de', 'B012345678', 12, 5, 6, 7, 8, None, None, '3303182353398497777']
        self.oa = workbook(self.oa_headers, [self.oa_row])
        self.price_headers = ['MSKU', '国家', '价格']
        self.price_rows = [['old', c, p] for c, p in [('德国', 9), ('法国', 10), ('西班牙', 11), ('意大利', 12)]]
        self.prices = workbook(self.price_headers, self.price_rows)

    def oa_result(self, **kwargs):
        return process_oa(kwargs.get('mapping', self.mapping), kwargs.get('oa', self.oa), kwargs.get('prices', self.prices), ['mapping.xlsx', 'oa.xlsx', 'prices.xlsx'], self.resources)

    def assert_invalid(self, call, text):
        with self.assertRaises(ValidationError) as context:
            call()
        self.assertTrue(any(text in item['message'] for item in context.exception.issues), context.exception.issues)
        return context.exception.issues

    def test_oa_alignment_identifiers_prices_and_long_text(self):
        result = self.oa_result()
        wb = load_workbook(BytesIO(result.content))
        ws = wb.active
        self.assertEqual(ws.max_column, len(HEADERS))
        self.assertEqual(ws.max_row, 3)
        self.assertEqual([ws.cell(3, c).value for c in range(1, 6)], ['new', '名称\n完整文本', 'de', 'B012345678', 12])
        self.assertEqual(ws['L3'].value, '3303182353398497777')
        self.assertEqual(ws['F3'].value, 9)
        wb.close()

    def test_fallback_missing_lingxing(self):
        result = self.oa_result(prices=workbook(self.price_headers, self.price_rows[1:]))
        self.assertEqual(result.summary['fallback_prices'], 1)
        self.assertEqual(result.rows[0]['DE_PRICE'], 5)

    def test_price_zero_is_real_price(self):
        result = self.oa_result(prices=workbook(self.price_headers, [['old', '德国', 0]] + self.price_rows[1:]))
        self.assertEqual(result.rows[0]['DE_PRICE'], 0)
        self.assertEqual(result.warnings, [])

    def test_both_prices_absent_blocks(self):
        row = list(self.oa_row); row[5] = None
        self.assert_invalid(lambda: self.oa_result(oa=workbook(self.oa_headers, [row]), prices=workbook(self.price_headers, self.price_rows[1:])), '均缺失')

    def test_duplicate_new_sku_blocks_with_row(self):
        errors = self.assert_invalid(lambda: self.oa_result(mapping=workbook(['原SKU', '新SKU'], [['old', 'new'], ['old', 'new']])), '新SKU重复')
        self.assertEqual(errors[0]['row'], 3)

    def test_one_old_multiple_new_keeps_mapping_order(self):
        result = self.oa_result(mapping=workbook(['原SKU', '新SKU'], [['old', 'new-B'], ['old', 'new-A']]))
        self.assertEqual([r['SKU'] for r in result.rows], ['new-B', 'new-A'])

    def test_price_conflict_blocks(self):
        self.assert_invalid(lambda: self.oa_result(prices=workbook(self.price_headers, self.price_rows + [['old', '德国', 100]])), '售价冲突')

    def test_same_price_duplicate_allowed(self):
        self.assertEqual(self.oa_result(prices=workbook(self.price_headers, self.price_rows + [self.price_rows[0]])).summary['output_rows'], 1)

    def test_invalid_price_blocks(self):
        self.assert_invalid(lambda: self.oa_result(prices=workbook(self.price_headers, [['old', '德国', -1]])), '有效数字')

    def test_missing_original_blocks(self):
        self.assert_invalid(lambda: self.oa_result(mapping=workbook(['原SKU', '新SKU'], [['missing', 'new']])), '不存在')

    def test_ambiguous_source_blocks(self):
        self.assert_invalid(lambda: self.oa_result(oa=workbook(self.oa_headers, [self.oa_row, self.oa_row])), '来源重复')

    def test_blank_rows_and_empty_sheets_ignored(self):
        result = self.oa_result(oa=workbook(self.oa_headers, [[None] * len(HEADERS), self.oa_row], extra=True))
        self.assertEqual(result.summary['source_rows'], 1)

    def test_duplicate_header_blocks(self):
        self.assert_invalid(lambda: self.oa_result(mapping=workbook(['原SKU', '新SKU', '新SKU'], [['old', 'new', 'other']])), '表头重复')

    def test_literal_formula_text_not_executed(self):
        row = list(self.oa_row); row[1] = '=HYPERLINK("bad")'
        original = workbook(self.oa_headers, [row])
        # Simulate an exported literal string, rather than a calculated Excel formula.
        wb = load_workbook(BytesIO(original)); wb.active['B2'].data_type = 's'; stream = BytesIO(); wb.save(stream); wb.close()
        result = self.oa_result(oa=stream.getvalue())
        wb = load_workbook(BytesIO(result.content))
        self.assertEqual(wb.active['B3'].data_type, 's'); wb.close()

    def mabang_files(self, values=None, virtual='new'):
        old_headers = ['虚拟sku'] + list(MABANG_FIELDS)
        source_values = ['原名称', None, '3.20000000', '3.10000000', '23.50', None, None, '备注', None, None, '开发员甲', '销售员乙']
        if values is not None:
            source_values = values
        target_headers = [INVENTORY, VIRTUAL] + list(MABANG_FIELDS.values()) + ['仓库', '供应商']
        target_row = ['MDEnew', virtual] + ['旧值'] * len(MABANG_FIELDS) + ['新店仓库', '新店供应商']
        return workbook(target_headers, [target_row], extra=True), workbook(old_headers, [['old'] + source_values])

    def mabang_result(self, **kwargs):
        generated, original = self.mabang_files()
        return process_mabang(kwargs.get('mapping', self.mapping), kwargs.get('generated', generated), kwargs.get('original', original), ['mapping.xlsx', 'generated.xlsx', 'original.xlsx'])

    def test_mabang_preserves_keys_other_columns_sheets_and_styles(self):
        generated, original = self.mabang_files()
        wb = load_workbook(BytesIO(generated)); wb.active['A2'].number_format = '@'; wb.active.column_dimensions['A'].width = 30
        stream = BytesIO(); wb.save(stream); wb.close()
        result = self.mabang_result(generated=stream.getvalue(), original=original)
        wb = load_workbook(BytesIO(result.content)); ws = wb.active
        self.assertEqual(ws['A2'].value, 'MDEnew'); self.assertEqual(ws['B2'].value, 'new')
        self.assertEqual(ws['A2'].number_format, '@'); self.assertEqual(ws.column_dimensions['A'].width, 30)
        self.assertEqual(ws.cell(2, ws.max_column).value, '新店供应商')
        self.assertEqual(wb['保留页']['A1'].value, '不要改动')
        self.assertEqual(result.summary['updated_fields'], 12); wb.close()

    def test_mabang_chinese_name_comes_from_source5_even_when_oa_name_differs(self):
        generated, original = self.mabang_files()
        wb = load_workbook(BytesIO(generated))
        wb.active['C2'] = 'OA原中文名称'
        target = BytesIO()
        wb.save(target)
        wb.close()
        for source_name in ['(A)马帮专用中文名称(2.5)', None]:
            with self.subTest(source_name=source_name):
                wb = load_workbook(BytesIO(original))
                wb.active['B2'] = source_name
                source = BytesIO()
                wb.save(source)
                wb.close()
                result = self.mabang_result(generated=target.getvalue(), original=source.getvalue())
                self.assertEqual(result.rows[0]['*库存sku名称'], source_name)
                wb = load_workbook(BytesIO(result.content))
                self.assertEqual(wb.active['C2'].value, source_name)
                wb.close()

    def test_mabang_blanks_are_blank_and_zero_is_zero(self):
        generated, original = self.mabang_files()
        wb = load_workbook(BytesIO(original)); wb.active['F2'] = 0; stream = BytesIO(); wb.save(stream); wb.close()
        result = self.mabang_result(original=stream.getvalue())
        wb = load_workbook(BytesIO(result.content)); ws = wb.active
        self.assertIsNone(ws['D2'].value)
        self.assertEqual(ws['G2'].value, 0); wb.close()

    def test_partial_source_only_updates_present_fields(self):
        result = self.mabang_result(original=workbook(['虚拟sku', '重量'], [['old', '99.00']]))
        self.assertEqual(result.summary['updated_fields'], 1)
        self.assertEqual(result.rows[0]['商品重量'], '99.00')
        self.assertEqual(result.rows[0]['*库存sku名称'], '旧值')

    def test_multiple_new_tokens_same_original_allowed(self):
        generated, original = self.mabang_files(virtual='new;new2')
        result = self.mabang_result(generated=generated, original=original, mapping=workbook(['原SKU', '新SKU'], [['old', 'new'], ['old', 'new2']]))
        self.assertEqual(result.summary['output_rows'], 1)

    def test_ambiguous_virtual_tokens_block(self):
        generated, original = self.mabang_files(virtual='new;new2')
        self.assert_invalid(lambda: self.mabang_result(generated=generated, original=original, mapping=workbook(['原SKU', '新SKU'], [['old', 'new'], ['other', 'new2']])), '无法唯一')

    def test_unknown_virtual_token_blocks(self):
        generated, _ = self.mabang_files(virtual='unknown')
        self.assert_invalid(lambda: self.mabang_result(generated=generated), '无法唯一')

    def test_api_save_is_explicit_idempotent_and_downloadable(self):
        app = create_app(resources=self.resources, home=self.resources)
        with TestClient(app) as client:
            token = client.get('/api/settings').json()['token']
            headers = {'X-Follow-Sell-Token': token}
            files = {'mapping': ('mapping.xlsx', self.mapping), 'oa': ('oa.xlsx', self.oa), 'prices': ('prices.xlsx', self.prices)}
            self.assertEqual(client.post('/api/process/oa', files=files).status_code, 403)
            response = client.post('/api/process/oa', files=files, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            result_id = response.json()['result_id']
            out = self.resources / 'output'
            self.assertFalse(out.exists())
            first = client.post(f'/api/results/{result_id}/save', json={'output_dir': str(out)}, headers=headers)
            second = client.post(f'/api/results/{result_id}/save', json={'output_dir': str(out)}, headers=headers)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json(), second.json()); self.assertEqual(len(list(out.glob('*.xlsx'))), 1)
            self.assertEqual(client.get(f'/api/results/{result_id}/download').content, Path(first.json()['path']).read_bytes())
            self.assertEqual(client.get('/api/templates/1').status_code, 200)
            self.assertEqual(client.get('/api/results/missing/download').status_code, 404)

    def test_api_errors_origin_and_unwritable_directory(self):
        with TestClient(create_app(resources=self.resources, home=self.resources)) as client:
            token = client.get('/api/settings').json()['token']; headers = {'X-Follow-Sell-Token': token}
            files = {'mapping': ('mapping.xlsx', self.mapping), 'oa': ('oa.xlsx', self.oa), 'prices': ('prices.xlsx', self.prices)}
            bad = dict(files); bad['oa'] = ('bad.xlsx', b'not a workbook')
            self.assertEqual(client.post('/api/process/oa', files=bad, headers=headers).status_code, 422)
            self.assertEqual(client.post('/api/process/oa', files=files, headers={**headers, 'Origin': 'https://example.org'}).status_code, 403)
            result_id = client.post('/api/process/oa', files=files, headers=headers).json()['result_id']
            with patch.object(Path, 'open', side_effect=PermissionError('locked')):
                response = client.post(f'/api/results/{result_id}/save', json={'output_dir': str(self.resources / 'locked')}, headers=headers)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(client.post(f'/api/results/{result_id}/save', json={'output_dir': 'relative'}, headers=headers).status_code, 422)


if __name__ == '__main__':
    main()
