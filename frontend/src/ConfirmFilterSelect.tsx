import { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Checkbox, Empty, Input, Popover, Radio, Space, Typography, theme } from 'antd';
import type { InputRef } from 'antd';
import { DownOutlined, SearchOutlined } from '@ant-design/icons';
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent } from 'react';

import { designTokens } from './designTokens';
import { useFilterPopoverMotion } from './useWorkspaceMotion';
export type FilterOptionValue = string | number;
export type ConfirmFilterValue = FilterOptionValue | FilterOptionValue[] | undefined;
export type ConfirmFilterMode = 'single' | 'multiple';

export interface ConfirmFilterSelectProps {
  value?: ConfirmFilterValue;
  options: Array<{ value: FilterOptionValue; label: string }>;
  onConfirm: (value: ConfirmFilterValue) => void;
  mode?: ConfirmFilterMode;
  placeholder: string;
  ariaLabel: string;
  selectionUnit?: string;
  normalizeValue?: (value: FilterOptionValue | undefined) => FilterOptionValue | undefined;
  style?: CSSProperties;
}

function sameValue(left: FilterOptionValue | undefined, right: FilterOptionValue | undefined) {
  return left === right;
}

function sameSelection(left: FilterOptionValue[], right: FilterOptionValue[]) {
  return left.length === right.length && left.every(value => right.includes(value));
}

export default function ConfirmFilterSelect({
  value,
  options,
  onConfirm,
  mode = 'multiple',
  placeholder,
  ariaLabel,
  selectionUnit = '项',
  normalizeValue,
  style,
}: ConfirmFilterSelectProps) {
  const { token } = theme.useToken();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [draft, setDraft] = useState<FilterOptionValue | FilterOptionValue[] | undefined>(value);
  const searchRef = useRef<InputRef>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useFilterPopoverMotion(panelRef, open);
  const multiple = mode === 'multiple';
  const selectedValues = multiple && Array.isArray(value) ? value : [];
  const selectedSingle = !multiple && !Array.isArray(value) ? value : undefined;
  const draftValues = multiple && Array.isArray(draft) ? draft : [];
  const draftSingle = !multiple && !Array.isArray(draft) ? draft : undefined;
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const visibleOptions = useMemo(
    () => normalizedSearch ? options.filter(option => option.label.toLocaleLowerCase().includes(normalizedSearch)) : options,
    [normalizedSearch, options],
  );
  const visibleValues = visibleOptions.map(option => option.value);
  const selectedVisibleCount = visibleValues.filter(option => draftValues.includes(option)).length;
  const allVisibleSelected = visibleValues.length > 0 && selectedVisibleCount === visibleValues.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;
  const selectedOption = options.find(option => option.value === selectedSingle);
  const selectedCount = selectedValues.length;
  const summary = multiple
    ? selectedCount === 0 || (options.length > 0 && options.every(option => selectedValues.includes(option.value)))
      ? placeholder
      : `已选 ${selectedCount}${selectionUnit ? ' ' + selectionUnit : ''}`
    : selectedOption?.label || placeholder;

  const openPanel = (nextOpen: boolean) => {
    if (nextOpen) {
      setDraft(multiple ? [...selectedValues] : selectedSingle);
      setSearch('');
    }
    setOpen(nextOpen);
  };

  useEffect(() => {
    if (open) searchRef.current?.focus();
  }, [open]);

  const cancel = () => setOpen(false);
  const confirm = (nextDraft: ConfirmFilterValue = draft) => {
    if (multiple) {
      const next = Array.isArray(nextDraft) ? nextDraft : [];
      const representsAll = (values: FilterOptionValue[]) => values.length === 0
        || options.length > 0 && options.every(option => values.includes(option.value));
      const isSame = sameSelection(selectedValues, next)
        || representsAll(selectedValues) && representsAll(next);
      if (!isSame) onConfirm(next);
    } else {
      const normalize = (candidate: FilterOptionValue | undefined) => normalizeValue ? normalizeValue(candidate) : candidate;
      const next = Array.isArray(nextDraft) ? undefined : nextDraft;
      if (!sameValue(normalize(selectedSingle), normalize(next))) onConfirm(next);
    }
    setOpen(false);
  };
  const clearDraft = () => setDraft(multiple ? [] : undefined);
  const toggleVisible = (checked: boolean) => {
    setDraft(current => {
      const currentValues = Array.isArray(current) ? current : [];
      if (checked) return Array.from(new Set([...currentValues, ...visibleValues]));
      const visible = new Set(visibleValues);
      return currentValues.filter(option => !visible.has(option));
    });
  };
  const handlePanelKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
    if (event.key === 'Enter' && event.target === searchRef.current?.input) {
      event.preventDefault();
      event.stopPropagation();
    }
  };
  const optionRows = visibleOptions.map(option => <div className="confirm-filter-option-row" key={String(option.value)}>
    {multiple ? <Checkbox
      checked={draftValues.includes(option.value)}
      onChange={event => toggleVisibleOption(option.value, event.target.checked)}
      className="confirm-filter-option"
    >{option.label}</Checkbox> : <Radio value={option.value} className="confirm-filter-option">{option.label}</Radio>}
    <Button
      type="link"
      size="small"
      className="confirm-filter-only"
      aria-label={`仅筛选此项：${option.label}`}
      onClick={() => confirm(multiple ? [option.value] : option.value)}
    >仅筛选此项</Button>
  </div>);

  const content = <div
    ref={panelRef}
    className="confirm-filter-panel"
    role="dialog"
    aria-label={`${ariaLabel}筛选选项`}
    onKeyDown={handlePanelKeyDown}
    style={{
      width: Math.max(Number(style?.width || style?.minWidth || 210), 300),
      maxWidth: 'calc(100vw - 24px)',
      color: token.colorText,
    }}
  >
    <Input
      ref={searchRef}
      allowClear
      value={search}
      prefix={<SearchOutlined />}
      placeholder={`搜索${ariaLabel}`}
      aria-label={`搜索${ariaLabel}`}
      onChange={event => setSearch(event.target.value)}
      onKeyDown={handlePanelKeyDown}
      size="small"
      className="confirm-filter-search"
    />
    {multiple && <Checkbox
      className="confirm-filter-select-all"
      checked={allVisibleSelected}
      indeterminate={someVisibleSelected}
      disabled={!visibleOptions.length}
      aria-label="全选当前搜索结果"
      onChange={event => toggleVisible(event.target.checked)}
    >全选</Checkbox>}
    <div
      className="confirm-filter-options"
      role={multiple ? 'group' : 'radiogroup'}
      aria-label={`${ariaLabel}选项`}
      style={{ borderColor: token.colorBorderSecondary }}
    >
      {visibleOptions.length ? multiple
        ? optionRows
        : <Radio.Group value={draftSingle} onChange={event => setDraft(event.target.value)} className="confirm-filter-radio-group">
          {optionRows}
        </Radio.Group>
        : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配项" />}
    </div>
    <div className="confirm-filter-footer" style={{ borderColor: token.colorBorderSecondary }}>
      <Space size={8} className="confirm-filter-footer-hint">
        <Button type="link" size="small" onClick={clearDraft}>清空</Button>
        {multiple && <Typography.Text type="secondary">未选择表示全部</Typography.Text>}
      </Space>
      <Space size={8}>
        <Button size="small" aria-label="取消" onClick={cancel}>取消</Button>
        <Button size="small" type="primary" aria-label="确定" onClick={() => confirm()}>确定</Button>
      </Space>
    </div>
  </div>;

  return <Popover
    trigger="click"
    placement="bottomLeft"
    open={open}
    onOpenChange={openPanel}
    content={content}
    overlayClassName="confirm-filter-popover"
    overlayStyle={{ zIndex: designTokens.layer.floating }}
    arrow={false}
  >
    <Button
      className={`confirm-filter-trigger${open ? ' is-open' : ''}`}
      aria-label={`${ariaLabel}: ${summary}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={() => openPanel(!open)}
      style={style}
    >
      <span className="confirm-filter-trigger-label" title={summary}>{summary}</span>
      <DownOutlined aria-hidden="true" />
    </Button>
  </Popover>;

  function toggleVisibleOption(option: FilterOptionValue, checked: boolean) {
    setDraft(current => {
      const currentValues = Array.isArray(current) ? current : [];
      return checked
        ? Array.from(new Set([...currentValues, option]))
        : currentValues.filter(value => value !== option);
    });
  }
}
