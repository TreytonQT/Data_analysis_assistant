import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent, PointerEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';

type ChartPoint = { x: number; y: number };

export function useChartAxisTooltip({ points, width, height, revision }: {
  points: ChartPoint[];
  width: number;
  height: number;
  revision: unknown;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tooltipId = useId();
  const [selection, setSelection] = useState<{ index: number; anchor: ChartPoint } | null>(null);
  const clear = useCallback(() => setSelection(null), []);
  const open = selection !== null;

  useLayoutEffect(clear, [clear, revision, width, height]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: globalThis.PointerEvent) => {
      if (!svgRef.current?.contains(event.target as Node)) clear();
    };
    const escape = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') clear(); };
    window.addEventListener('scroll', clear, true);
    window.addEventListener('resize', clear);
    window.addEventListener('popstate', clear);
    window.addEventListener('sales-dashboard-route-change', clear);
    document.addEventListener('pointerdown', outside, true);
    document.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('scroll', clear, true);
      window.removeEventListener('resize', clear);
      window.removeEventListener('popstate', clear);
      window.removeEventListener('sales-dashboard-route-change', clear);
      document.removeEventListener('pointerdown', outside, true);
      document.removeEventListener('keydown', escape);
    };
  }, [clear, open]);

  const activate = (index: number) => {
    const svg = svgRef.current;
    const point = points[index];
    const rect = svg?.getBoundingClientRect();
    if (!svg || !point || !rect?.width || !rect.height) return;
    const matrix = svg.getScreenCTM?.();
    const anchor = matrix
      ? { x: matrix.a * point.x + matrix.c * point.y + matrix.e, y: matrix.b * point.x + matrix.d * point.y + matrix.f }
      : { x: rect.left + point.x / width * rect.width, y: rect.top + point.y / height * rect.height };
    setSelection(current => current?.index === index && current.anchor.x === anchor.x && current.anchor.y === anchor.y
      ? current : { index, anchor });
  };
  const onPointerMove = (event: PointerEvent<SVGRectElement>) => {
    const svg = svgRef.current;
    const rect = svg?.getBoundingClientRect();
    if (!svg || !rect?.width || !points.length) return;
    const inverse = svg.getScreenCTM?.()?.inverse();
    const localX = inverse
      ? inverse.a * event.clientX + inverse.c * event.clientY + inverse.e
      : (event.clientX - rect.left) / rect.width * width;
    let nearest = 0;
    for (let index = 1; index < points.length; index += 1) {
      if (Math.abs(points[index].x - localX) <= Math.abs(points[nearest].x - localX)) nearest = index;
    }
    activate(nearest);
  };
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const index = selection?.index ?? 0;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1
      : event.key === 'ArrowLeft' ? Math.max(0, index - 1)
        : event.key === 'ArrowRight' ? Math.min(points.length - 1, index + 1) : null;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      clear();
    } else if (next !== null && points.length) {
      event.preventDefault();
      event.stopPropagation();
      activate(next);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.stopPropagation();
    }
  };

  return {
    activeIndex: selection && selection.index < points.length ? selection.index : null,
    anchor: selection?.anchor ?? null,
    tooltipId,
    svgProps: {
      ref: svgRef,
      tabIndex: points.length ? 0 : undefined,
      'aria-describedby': open ? tooltipId : undefined,
      'aria-keyshortcuts': 'ArrowLeft ArrowRight Home End Escape',
      onFocus: () => activate(0),
      onBlur: clear,
      onKeyDown,
    },
    hitAreaProps: {
      onPointerMove,
      onPointerDown: (event: PointerEvent<SVGRectElement>) => {
        svgRef.current?.focus({ preventScroll: true });
        onPointerMove(event);
      },
      onPointerLeave: (event: PointerEvent<SVGRectElement>) => { if (event.pointerType !== 'touch') clear(); },
      onPointerCancel: clear,
    },
  };
}

export default function ChartAxisTooltip({ id, anchor, title, items, footer }: {
  id: string;
  anchor: ChartPoint | null;
  title: ReactNode;
  items: Array<{ label: string; value: ReactNode; color?: string }>;
  footer?: ReactNode;
}) {
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<ChartPoint | null>(null);
  useLayoutEffect(() => {
    const element = tooltipRef.current;
    if (!anchor || !element) return;
    const bounds = element.getBoundingClientRect();
    const x = Math.max(8, Math.min(window.innerWidth - bounds.width - 8, anchor.x - bounds.width / 2));
    const above = anchor.y - bounds.height - 10;
    const y = Math.max(8, Math.min(window.innerHeight - bounds.height - 8, above >= 8 ? above : anchor.y + 10));
    setPosition(current => current?.x === x && current.y === y ? current : { x, y });
  }, [anchor, title, items, footer]);
  if (!anchor) return null;
  return createPortal(<div
    ref={tooltipRef}
    id={id}
    role="tooltip"
    className="app-chart-tooltip"
    style={{ left: position?.x ?? anchor.x, top: position?.y ?? anchor.y, visibility: position ? undefined : 'hidden' }}
  >
    <strong className="app-chart-tooltip-title">{title}</strong>
    {items.map(item => <div className="app-chart-tooltip-row" key={item.label}>
      {item.color && <i aria-hidden="true" style={{ backgroundColor: item.color }} />}
      <span>{item.label}</span>{' '}<b>{item.value}</b>
    </div>)}
    {footer && <div className="app-chart-tooltip-footer">{footer}</div>}
  </div>, document.body);
}
