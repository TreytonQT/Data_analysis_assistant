import { Modal, type ModalProps } from 'antd';

export interface MutationModalProps extends Omit<ModalProps, 'confirmLoading' | 'closable' | 'maskClosable' | 'keyboard'> {
  busy: boolean;
}

// Reuse Ant Modal; keep the in-flight submission and its draft on screen.
export default function MutationModal({ busy, onCancel, onOk, cancelButtonProps, ...props }: MutationModalProps) {
  return <Modal cancelText="取消" {...props}
    confirmLoading={busy} closable={!busy} maskClosable={!busy} keyboard={!busy}
    cancelButtonProps={{ ...cancelButtonProps, disabled: busy || cancelButtonProps?.disabled }}
    onCancel={event => { if (!busy) onCancel?.(event); }}
    onOk={event => { if (!busy) return onOk?.(event); }}
  />;
}
