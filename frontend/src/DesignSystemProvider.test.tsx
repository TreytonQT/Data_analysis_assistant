import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createPortal } from 'react-dom';
import { Button, Form, Input, Modal } from 'antd';
import { afterEach, describe, expect, it } from 'vitest';
import DesignSystemProvider, { useDarkTheme } from './DesignSystemProvider';

function PortalTheme() {
  const dark = useDarkTheme();
  return createPortal(<span>{dark ? '浮层深色' : '浮层浅色'}</span>, document.body);
}

afterEach(cleanup);

describe('DesignSystemProvider', () => {
  it('updates the document theme and portal context together, then restores the host', () => {
    const originalColor = document.documentElement.style.getPropertyValue('--app-color-page');
    const originalDark = document.documentElement.classList.contains('dark-mode');
    const { rerender, unmount } = render(<DesignSystemProvider dark={false}><PortalTheme /></DesignSystemProvider>);
    expect(document.documentElement.style.getPropertyValue('--app-color-page')).toBe('#f5f5f7');
    expect(screen.getByText('浮层浅色')).toBeInTheDocument();
    rerender(<DesignSystemProvider dark><PortalTheme /></DesignSystemProvider>);
    expect(document.documentElement).toHaveClass('dark-mode');
    expect(document.documentElement.style.getPropertyValue('--app-color-page')).toBe('#0b0b0d');
    expect(screen.getByText('浮层深色')).toBeInTheDocument();
    unmount();
    expect(document.documentElement.style.getPropertyValue('--app-color-page')).toBe(originalColor);
    expect(document.documentElement.classList.contains('dark-mode')).toBe(originalDark);
  });

  it('uses Chinese modal actions and field validation in portaled forms', async () => {
    render(<DesignSystemProvider dark={false}>
      <Modal open title="规范验证">
        <Form layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Button htmlType="submit">校验</Button>
        </Form>
      </Modal>
    </DesignSystemProvider>);
    expect(screen.getByRole('button', { name: '取 消' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '校 验' }));
    expect(await screen.findByText('名称不能为空')).toBeInTheDocument();
  });
});
