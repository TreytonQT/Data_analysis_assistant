import { describe, expect, it } from 'vitest';
import {
  ancestorKeysForRoute,
  navigationLeaves,
  navigationTree,
  routeLeafForSearch,
  searchForRoute,
  topLevelLabelForRoute,
} from './navigation';

describe('navigation registry', () => {
  it('keeps every leaf key unique and includes the requested grouped views', () => {
    const keys = navigationLeaves.map(route => route.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys).toEqual(expect.arrayContaining([
      'department:performance',
      'department:commission',
      'department:assessment',
      'slow-moving:promotion',
      'uploads:monthly',
      'config:replenishment_product_tags',
    ]));
    expect(navigationTree.find(node => node.key === 'department')?.kind).toBe('group');
  });

  it('resolves legacy and invalid URLs to stable default leaves', () => {
    expect(routeLeafForSearch('?page=department').key).toBe('department:performance');
    expect(routeLeafForSearch('?page=department&tab=assessment').key).toBe('department:assessment');
    expect(routeLeafForSearch('?page=slow-moving&tab=promotion').key).toBe('slow-moving:promotion');
    expect(routeLeafForSearch('?page=slow-moving&tab=promotion&promotion_view=unknown').key).toBe('slow-moving:promotion');
    expect(routeLeafForSearch('?page=config&config_tab=unknown').key).toBe('config:metrics_config');
    expect(routeLeafForSearch('?page=missing').key).toBe('overview');
  });

  it('builds canonical URLs while preserving page-local filters', () => {
    expect(searchForRoute('department:assessment', '?page=department&month=2026-08')).toBe('?page=department&month=2026-08&tab=assessment');
    expect(searchForRoute('slow-moving:promotion', '?page=slow-moving&search=SKU&tab=promotion&promotion_view=candidates-8')).toBe('?page=slow-moving&search=SKU&tab=promotion&promotion_view=candidates-8');
    expect(searchForRoute('config:store_config')).toBe('?page=config&config_tab=store_config');
    expect(ancestorKeysForRoute('slow-moving:promotion')).toEqual(['slow-moving']);
    expect(topLevelLabelForRoute('department:commission')).toBe('部门监控');
  });
});
