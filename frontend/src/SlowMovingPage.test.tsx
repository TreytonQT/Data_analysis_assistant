import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SlowMovingPage, { slowMovingTabFromSearch } from './SlowMovingPage';

const pageMocks = vi.hoisted(() => ({ dashboard: vi.fn() }));

vi.mock('./DashboardPage', () => ({
  default: (props: { refreshVersion?: number }) => {
    pageMocks.dashboard(props);
    return <div>滞销明细内容</div>;
  },
}));
vi.mock('./PromotionBoard', () => ({ default: () => <div>促销提醒内容</div> }));

describe('SlowMovingPage', () => {
  afterEach(() => {
    pageMocks.dashboard.mockClear();
    window.history.replaceState({}, '', '/');
  });

  it('parses and restores the tab from the URL', () => {
    expect(slowMovingTabFromSearch('?page=slow-moving&tab=promotion')).toBe('promotion');
    expect(slowMovingTabFromSearch('?page=slow-moving')).toBe('details');
  });

  it('syncs tab clicks and browser history with the URL', async () => {
    window.history.replaceState({}, '', '/?page=slow-moving');
    render(<SlowMovingPage />);
    expect(screen.getByText('滞销明细内容')).toBeInTheDocument();

    window.history.pushState({}, '', '/?page=slow-moving&tab=promotion');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(screen.getByText('促销提醒内容')).toBeInTheDocument());
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('promotion');
    expect(await screen.findByText('促销提醒内容')).toBeInTheDocument();

    window.history.pushState({}, '', '/?page=slow-moving&tab=details');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByText('滞销明细内容')).toBeInTheDocument();
  });

  it('refreshes details when either dashboard or promotion data changes', () => {
    window.history.replaceState({}, '', '/?page=slow-moving');
    render(<SlowMovingPage dashboardRefreshVersion={2} promotionsRefreshVersion={3} />);

    expect(pageMocks.dashboard).toHaveBeenLastCalledWith(
      expect.objectContaining({ refreshVersion: 5 }),
    );
  });
});
