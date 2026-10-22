import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { exportSection } from './DashboardPage';
import { downloadBlobWithFeedback } from './feedback';
import { ASSESSMENT_RATIO_STORAGE_KEY, FORECAST_ASSESSMENT_COLUMN, useDepartmentRatio, withForecastAssessment } from './departmentRatio';
import type { DashboardSection } from './api';

const source: DashboardSection = {
  key: 'performance-0', title: '开发员业绩排行',
  columns: ['开发员', '预估本月销售额（元）', '9月7日销量'].map(key => ({ key, label: key })),
  rows: [
    { 开发员: '合计', '预估本月销售额（元）': 560, forecast_sales: { enterprise: 200, local: 400 } },
    { 开发员: '甲', '预估本月销售额（元）': 280, forecast_sales: { enterprise: 100, local: 200 } },
    { 开发员: '乙', '预估本月销售额（元）': 280, forecast_sales: { enterprise: 100, local: 200 } },
  ],
};

vi.mock('./feedback', () => ({
  feedbackMessage: {}, downloadBlobWithFeedback: vi.fn(), downloadWithFeedback: vi.fn(),
}));

describe('department forecast assessment', () => {
  beforeEach(() => localStorage.clear());
  it.each([[0, 80], [0.5, 180], [1, 280]])('calculates ratio %s without rounding or changing row order', (ratio, amount) => {
    const result = withForecastAssessment(source, ratio);
    expect(result.columns.map(column => column.key)).toEqual(['开发员', '预估本月销售额（元）', FORECAST_ASSESSMENT_COLUMN, '9月7日销量']);
    expect(result.rows.map(row => row[FORECAST_ASSESSMENT_COLUMN])).toEqual([amount * 2, amount, amount]);
    expect(result.rows.map(row => row.开发员)).toEqual(['合计', '甲', '乙']);
    expect(source.rows[1][FORECAST_ASSESSMENT_COLUMN]).toBeUndefined();
    expect(result.columns.some(column => column.key === 'forecast_sales')).toBe(false);
  });
  it('does not add columns to department or store rankings', () => {
    for (const label of ['部门', '店铺']) {
      const other = { ...source, columns: source.columns.map(column => column.key === '开发员' ? { key: label, label } : column) };
      expect(withForecastAssessment(other, 0.5)).toBe(other);
    }
  });
  it('exports the current unrounded calculation and hides auxiliary amounts', async () => {
    exportSection(withForecastAssessment(source, 0.5));
    const blob = vi.mocked(downloadBlobWithFeedback).mock.calls.at(-1)![0];
    const csv = await new Promise<string>(resolve => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blob);
    });
    expect(csv).toContain(FORECAST_ASSESSMENT_COLUMN);
    expect(csv).toContain('"甲","280","180"');
    expect(csv).toContain('"合计","560","360"');
    expect(csv).not.toContain('forecast_sales');
  });
  it('shares valid changes between mounted pages, remembers them and retains the last valid value', () => {
    const first = renderHook(useDepartmentRatio);
    const second = renderHook(useDepartmentRatio);
    expect(first.result.current.ratio).toBe(1);
    act(() => first.result.current.onRatioChange(0.45));
    expect(second.result.current.ratio).toBe(0.45);
    expect(localStorage.getItem(ASSESSMENT_RATIO_STORAGE_KEY)).toBe('0.45');
    for (const invalid of [null, -0.1, 1.1, NaN]) {
      act(() => second.result.current.onRatioChange(invalid));
      expect(second.result.current.ratio).toBe(0.45);
      expect(second.result.current.ratioError).toBeTruthy();
    }
    first.unmount();
    const remounted = renderHook(useDepartmentRatio);
    expect(remounted.result.current.ratio).toBe(0.45);
    act(() => { localStorage.setItem(ASSESSMENT_RATIO_STORAGE_KEY, '0'); window.dispatchEvent(new StorageEvent('storage')); });
    expect(second.result.current.ratio).toBe(0);
    expect(remounted.result.current.ratio).toBe(0);
  });
});
