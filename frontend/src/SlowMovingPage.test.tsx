import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SlowMovingPage, { slowMovingTabFromSearch } from './SlowMovingPage';

vi.mock('./DashboardPage', () => ({ default: () => <div>滞销明细内容</div> }));
vi.mock('./PromotionBoard', () => ({ default: () => <div>促销提醒内容</div> }));

describe('SlowMovingPage', () => {
  afterEach(() => window.history.replaceState({}, '', '/'));

  it('parses and restores the tab from the URL', () => {
    expect(slowMovingTabFromSearch('?page=slow-moving&tab=promotion')).toBe('promotion');
    expect(slowMovingTabFromSearch('?page=slow-moving')).toBe('details');
  });

  it('syncs tab clicks and browser history with the URL', async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, '', '/?page=slow-moving');
    render(<SlowMovingPage />);
    expect(screen.getByText('滞销明细内容')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: '促销提醒' }));
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('promotion');
    expect(await screen.findByText('促销提醒内容')).toBeInTheDocument();

    window.history.pushState({}, '', '/?page=slow-moving&tab=details');
    window.dispatchEvent(new PopStateEvent('popstate'));
    expect(await screen.findByText('滞销明细内容')).toBeInTheDocument();
  });
});
