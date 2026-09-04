import { Image } from 'antd';
import type { KeyboardEvent, MouseEvent } from 'react';
import type { DashboardImage } from './api';

export const SKU_IMAGE_FALLBACK = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2248%22 height=%2248%22 viewBox=%220 0 48 48%22%3E%3Crect width=%2248%22 height=%2248%22 rx=%226%22 fill=%22%23e8eef5%22/%3E%3Cpath d=%22M12 34l8-9 6 6 4-5 7 8H12z%22 fill=%22%2395a7bb%22/%3E%3Ccircle cx=%2219%22 cy=%2218%22 r=%224%22 fill=%22%2395a7bb%22/%3E%3C/svg%3E';

interface SkuImagePreviewProps {
  image?: DashboardImage | null;
  alt: string;
  placeholderLabel?: string;
  className?: string;
  placeholderClassName?: string;
  width?: number;
  height?: number;
}

export default function SkuImagePreview({
  image,
  alt,
  placeholderLabel,
  className = 'sku-image-preview',
  placeholderClassName = 'sku-image-placeholder',
  width = 48,
  height = 48,
}: SkuImagePreviewProps) {
  const stopPropagation = (event: MouseEvent | KeyboardEvent) => event.stopPropagation();
  if (!image?.url) {
    return <span className={placeholderClassName} aria-label={placeholderLabel || `${alt}暂无图片`} />;
  }
  return <Image
    className={className}
    src={image.url}
    alt={alt}
    width={width}
    height={height}
    loading="lazy"
    fallback={SKU_IMAGE_FALLBACK}
    preview
    onClick={stopPropagation}
    onKeyDown={stopPropagation}
  />;
}
