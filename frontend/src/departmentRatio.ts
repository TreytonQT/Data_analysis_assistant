import { useEffect, useState } from 'react';
import type { DashboardSection } from './api';

export const ASSESSMENT_RATIO_STORAGE_KEY = 'department-assessment-local-ratio';
const CHANGE_EVENT = 'department-assessment-ratio-change';
export const FORECAST_ASSESSMENT_COLUMN = '预估月度考核销售额（前移7天）';

function readRatio() {
  try {
    const stored = localStorage.getItem(ASSESSMENT_RATIO_STORAGE_KEY);
    const value = stored?.trim() ? Number(stored) : 1;
    return Number.isFinite(value) && value >= 0 && value <= 1 ? value : 1;
  } catch { return 1; }
}

export function useDepartmentRatio() {
  const [ratio, setRatio] = useState(readRatio);
  const [ratioError, setRatioError] = useState('');
  useEffect(() => {
    const sync = () => { setRatio(readRatio()); setRatioError(''); };
    const localSync = (event: Event) => { setRatio((event as CustomEvent<number>).detail); setRatioError(''); };
    window.addEventListener('storage', sync);
    window.addEventListener(CHANGE_EVENT, localSync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener(CHANGE_EVENT, localSync);
    };
  }, []);
  const onRatioChange = (value: number | null) => {
    if (value === null || !Number.isFinite(value) || value < 0 || value > 1) {
      setRatioError('请输入 0～1 之间的比例');
      return;
    }
    setRatio(value);
    setRatioError('');
    try { localStorage.setItem(ASSESSMENT_RATIO_STORAGE_KEY, String(value)); } catch { /* 保留本次输入。 */ }
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: value }));
  };
  return { ratio, ratioError, onRatioChange };
}

export function withForecastAssessment(section: DashboardSection, ratio: number): DashboardSection {
  if (!section.columns.some(column => column.key === '开发员') || !section.columns.some(column => column.key === '预估本月销售额（元）')) return section;
  return {
    ...section,
    columns: section.columns.flatMap(column => column.key === '预估本月销售额（元）'
      ? [column, { key: FORECAST_ASSESSMENT_COLUMN, label: FORECAST_ASSESSMENT_COLUMN, format: '金额', unit: '元', precision: 2 }]
      : [column]),
    rows: section.rows.map(row => ({
      ...row,
      [FORECAST_ASSESSMENT_COLUMN]: row.forecast_sales
        ? row.forecast_sales.enterprise * 0.8 + row.forecast_sales.local * ratio
        : null,
    })),
  };
}
