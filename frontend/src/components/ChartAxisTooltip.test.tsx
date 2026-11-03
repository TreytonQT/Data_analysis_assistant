import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAxisTooltip, { useChartAxisTooltip } from './ChartAxisTooltip';

const initialValues = [0, 25, null];
const rect = (x: number, y: number, width: number, height: number) => ({ x, y, left: x, top: y, right: x + width, bottom: y + height, width, height, toJSON: () => ({}) });

function Harness({ values = initialValues }: { values?: Array<number | null> }) {
  const axis = useChartAxisTooltip({
    points: values.map((_, index) => ({ x: values.length === 1 ? 100 : 20 + index * 80, y: 20 })),
    width: 200, height: 100, revision: values,
  });
  return <>
    <svg {...axis.svgProps} aria-label="交互图表">
      <rect {...axis.hitAreaProps} data-testid="hit-area" />
      {axis.activeIndex !== null && <line data-testid="crosshair" data-index={axis.activeIndex} />}
    </svg>
    {axis.activeIndex !== null && <ChartAxisTooltip
      id={axis.tooltipId}
      anchor={axis.anchor}
      title={`月份 ${axis.activeIndex}`}
      items={[{ label: '销量', value: values[axis.activeIndex] ?? '—' }]}
    />}
  </>;
}

beforeEach(() => {
  vi.spyOn(SVGSVGElement.prototype, 'getBoundingClientRect').mockReturnValue(rect(100, 60, 400, 200));
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(rect(0, 0, 220, 110));
  vi.stubGlobal('innerWidth', 1280);
  vi.stubGlobal('innerHeight', 800);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('chart axis interaction', () => {
  it('snaps by horizontal position after scaling, regardless of pointer height', () => {
    const { container } = render(<Harness />);
    const hitArea = screen.getByTestId('hit-area');
    fireEvent.pointerMove(hitArea, { clientX: 295, clientY: 1000, pointerType: 'mouse' });
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('月份 1');
    expect(tooltip).toHaveTextContent('销量 25');
    expect(container).not.toContainElement(tooltip);
    expect(screen.getByLabelText('交互图表')).toHaveAttribute('aria-describedby', tooltip.id);
    expect(screen.getByTestId('crosshair')).toHaveAttribute('data-index', '1');
    const position = tooltip.getAttribute('style');
    fireEvent.pointerMove(hitArea, { clientX: 295, clientY: -1000, pointerType: 'mouse' });
    expect(tooltip).toHaveAttribute('style', position);
    fireEvent.pointerLeave(hitArea, { pointerType: 'mouse' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('supports focus, arrow keys, Home, End, Escape and blur', () => {
    render(<Harness />);
    const svg = screen.getByLabelText('交互图表');
    fireEvent.focus(svg);
    expect(screen.getByRole('tooltip')).toHaveTextContent('销量 0');
    fireEvent.keyDown(svg, { key: 'ArrowRight' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('月份 1');
    fireEvent.keyDown(svg, { key: 'End' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('销量 —');
    fireEvent.keyDown(svg, { key: 'ArrowLeft' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('月份 1');
    fireEvent.keyDown(svg, { key: 'Home' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('月份 0');
    fireEvent.keyDown(svg, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.keyDown(svg, { key: 'Home' });
    fireEvent.blur(svg);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('retains touch selection until outside press or pointer cancellation', () => {
    render(<Harness />);
    const hitArea = screen.getByTestId('hit-area');
    fireEvent.pointerDown(hitArea, { clientX: 455, clientY: 60, pointerType: 'touch' });
    fireEvent.pointerLeave(hitArea, { pointerType: 'touch' });
    expect(screen.getByRole('tooltip')).toHaveTextContent('月份 2');
    fireEvent.pointerDown(document.body, { pointerType: 'touch' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.pointerDown(hitArea, { clientX: 140, pointerType: 'touch' });
    fireEvent.pointerCancel(hitArea);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('clears on scrolling, resizing, navigation, data replacement and unmount', () => {
    const { rerender, unmount } = render(<Harness />);
    const hitArea = screen.getByTestId('hit-area');
    for (const name of ['scroll', 'resize', 'popstate', 'sales-dashboard-route-change']) {
      fireEvent.pointerMove(hitArea, { clientX: 295, clientY: 60 });
      expect(screen.getByRole('tooltip')).toBeInTheDocument();
      fireEvent(window, new Event(name));
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    }
    fireEvent.pointerMove(hitArea, { clientX: 295, clientY: 60 });
    rerender(<Harness values={[1, 2, 3]} />);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.pointerMove(hitArea, { clientX: 295, clientY: 60 });
    unmount();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('handles empty data and a single zero without invalid indices', () => {
    const { rerender } = render(<Harness values={[]} />);
    fireEvent.pointerMove(screen.getByTestId('hit-area'), { clientX: 295 });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    rerender(<Harness values={[0]} />);
    fireEvent.pointerMove(screen.getByTestId('hit-area'), { clientX: 499 });
    expect(screen.getByRole('tooltip')).toHaveTextContent('销量 0');
    expect(screen.getByTestId('crosshair')).toHaveAttribute('data-index', '0');
  });

  it('flips below the anchor and clamps both horizontal viewport edges', () => {
    const items = [{ label: '销量', value: 47 }];
    const { rerender } = render(<ChartAxisTooltip id="edge" anchor={{ x: 1, y: 10 }} title="首月" items={items} />);
    expect(screen.getByRole('tooltip')).toHaveStyle({ left: '8px', top: '20px' });
    rerender(<ChartAxisTooltip id="edge" anchor={{ x: 1279, y: 795 }} title="末月" items={items} />);
    expect(screen.getByRole('tooltip')).toHaveStyle({ left: '1052px', top: '675px' });
  });
});
