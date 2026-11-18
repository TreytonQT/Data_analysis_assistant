import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const output = process.argv[2];
const number = process.argv[3];
const snapshots = JSON.parse(await fs.readFile(path.join(output, 'work/asset_snapshot.json'), 'utf8'));
const sample = snapshots[number === 'oa' ? '结果1' : number];
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('Sheet1');
const columns = sample.headers.length;
const textUnits = value => [...String(value ?? '')].reduce((sum, char) => sum + (/[^\x00-\x7F]/.test(char) ? 2 : 1), 0);
const widths = sample.headers.map((header, c) => Math.max(sample.widths[c],
  /sku|asin|order_no/i.test(header) ? 24 : Math.min(35, Math.max(12, textUnits(header) + 2)),
  textUnits(sample.sample[c]) > 50 ? 35 : 12));
const headerHeight = Math.max(32, ...sample.headers.map((header, c) => Math.ceil(textUnits(header) / widths[c]) * 16 + 12));
const sampleHeight = Math.min(240, Math.max(42, ...sample.sample.map((value, c) => Math.ceil(textUnits(value) / widths[c]) * 15 + 12)));
sheet.getRangeByIndexes(0, 0, 2, columns).values = [sample.headers, sample.sample];
sheet.getRangeByIndexes(0, 0, 2, columns).format.font = { name: 'Microsoft YaHei', size: 11 };
sheet.getRangeByIndexes(0, 0, 2, columns).format.verticalAlignment = 'top';
sheet.getRangeByIndexes(0, 0, 1, columns).format = {
  fill: '#F0F0F3', font: { bold: true, color: '#1D1D1F' }, rowHeight: headerHeight, wrapText: true,
};
sheet.getRangeByIndexes(1, 0, 1, columns).format.rowHeight = sampleHeight;
sheet.getRangeByIndexes(1, 0, 1, columns).format.font.color = number === 'oa' ? '#626268' : '#FF0000';
sheet.getRangeByIndexes(1, 0, 1, columns).format.wrapText = true;
for (let c = 0; c < columns; c += 1) {
  sheet.getRangeByIndexes(0, c, 2, 1).format.columnWidth = widths[c];
}
sheet.freezePanes.freezeRows(number === 'oa' ? 2 : 1);
workbook.recalculate();
const target = number === 'oa'
  ? path.join(output, 'work/resources/oa_output.xlsx')
  : path.join(output, 'work/resources/templates', sample.filename);
await fs.mkdir(path.dirname(target), { recursive: true });
await (await SpreadsheetFile.exportXlsx(workbook)).save(target);
if (number !== 'oa') {
  const delivery = path.join(output, '模板', sample.filename);
  await fs.mkdir(path.dirname(delivery), { recursive: true });
  await fs.copyFile(target, delivery);
}
const preview = await workbook.render({ sheetName: 'Sheet1', range: `A1:${String.fromCharCode(64 + Math.min(columns, 5))}2`, scale: 1.5 });
await fs.writeFile(path.join(output, 'work', `template-${number}.png`), new Uint8Array(await preview.arrayBuffer()));
console.log(JSON.stringify({ target, columns, rows: 2 }));
