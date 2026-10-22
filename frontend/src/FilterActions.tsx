import { Button } from 'antd';

export default function FilterActions({ onReset }: { onReset: () => void }) {
  return <Button onClick={onReset}>重置筛选</Button>;
}
