import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DashboardSectionCard } from './DashboardPage';
import type { DashboardSection } from './api';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function renderChart(section: DashboardSection) {
  const result = render(<DashboardSectionCard initialSection={section} dashboardPage="overview" filters={{}} compactSales={false} />);
  const svg = result.container.querySelector('svg.app-chart-interactive') as SVGSVGElement;
  const [,, width, height] = svg.getAttribute('viewBox')!.split(' ').map(Number);
  vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width, height, right: width, bottom: height, x: 0, y: 0, toJSON: () => ({}) });
  return { ...result, svg, hit: svg.querySelector('.app-chart-hit-area')! };
}

describe('dashboard chart tooltips', () => {
  it('groups both store sales series at the nearest category center and removes permanent values', () => {
    const { svg, hit } = renderChart({
      key: 'store-chart', title: '店铺销量', columns: [],
      rows: [{ 店铺: 'DE-01', 昨日订单: 0, '30天日均': 1.25 }, { 店铺: 'FR-02', 昨日订单: 8, '30天日均': null }],
      chart: { x: '店铺', series: [{ key: '昨日订单', label: '昨天销量', format: 'integer' }, { key: '30天日均', label: '30 天日均销量' }] },
    });
    expect(svg.querySelector('.store-chart-value')).not.toBeInTheDocument();
    expect(svg.querySelector('title')).not.toBeInTheDocument();
    fireEvent.pointerMove(hit, { clientX: 300, clientY: 40, pointerType: 'mouse' });
    let tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('DE-01');
    expect(tooltip).toHaveTextContent('昨天销量 0');
    expect(tooltip).toHaveTextContent('30 天日均销量 1.25');
    expect(svg.querySelectorAll('.app-chart-active-band')).toHaveLength(1);
    fireEvent.pointerMove(hit, { clientX: 900, clientY: 200, pointerType: 'mouse' });
    tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('FR-02');
    expect(tooltip).toHaveTextContent('昨天销量 8');
    expect(tooltip).toHaveTextContent('30 天日均销量 -');
    expect(svg.querySelector('.app-chart-crosshair')).toHaveAttribute('data-index', '1');
  });

  it('keeps the source amount format and missing-value placeholder in line tooltips', () => {
    const { svg, hit } = renderChart({
      key: 'trend', title: '月度趋势', columns: [],
      rows: [{ 月份: '2026-01', 销售额: 12345 }, { 月份: '2026-02', 销售额: null }],
      chart: { kind: 'line', x: '月份', series: [{ key: '销售额', format: 'amount' }] },
    });
    expect(svg.querySelector('.line-chart-value')).not.toBeInTheDocument();
    fireEvent.pointerMove(hit, { clientX: 80, clientY: 220, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('2026-01');
    expect(screen.getByRole('tooltip')).toHaveTextContent('1.23 万');
    fireEvent.keyDown(svg, { key: 'End' });
    expect(within(screen.getByRole('tooltip')).getByText('-')).toBeInTheDocument();
    expect(svg.querySelectorAll('.line-chart-point.is-active')).toHaveLength(1);
  });

  it('retains ratio scaling and precision for a single-point percentage series', () => {
    const { hit } = renderChart({ key: 'ratio', title: '比例趋势', columns: [], rows: [{ 月份: '2026-01', 毛利率: .225 }], chart: { kind: 'line', x: '月份', series: [{ key: '毛利率', format: 'percent', precision: 2 }] } });
    fireEvent.pointerMove(hit, { clientX: 500, clientY: 200, pointerType: 'mouse' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('22.5%');
  });
});
