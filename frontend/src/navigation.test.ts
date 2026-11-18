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
      'products:diagnosis',
      'products:variants',
      'uploads:monthly',
      'config:replenishment_product_tags',
    ]));
    expect(navigationTree.find(node => node.key === 'department')?.kind).toBe('group');
  });

  it('resolves legacy and invalid URLs to stable default leaves', () => {
    expect(routeLeafForSearch('?page=department').key).toBe('department:performance');
    expect(routeLeafForSearch('?page=department&tab=assessment').key).toBe('department:assessment');
    expect(routeLeafForSearch('?page=slow-moving&tab=promotion').key).toBe('products:diagnosis');
    expect(routeLeafForSearch('?page=slow-moving&tab=promotion&promotion_view=unknown').key).toBe('products:diagnosis');
    expect(routeLeafForSearch('?page=config&config_tab=unknown').key).toBe('config:metrics_config');
    expect(routeLeafForSearch('?page=missing').key).toBe('overview');
  });

  it('builds canonical URLs while preserving page-local filters', () => {
    expect(searchForRoute('department:assessment', '?page=department&month=2026-08')).toBe('?page=department&month=2026-08&tab=assessment');
    expect(searchForRoute('slow-moving:promotion', '?page=slow-moving&search=SKU&tab=promotion&promotion_view=candidates-8')).toBe('?page=product-operations&search=SKU&scene=clearance');
    expect(searchForRoute('config:store_config')).toBe('?page=config&config_tab=store_config');
    expect(routeLeafForSearch(searchForRoute('products:variants')).key).toBe('products:variants');
    expect(ancestorKeysForRoute('products:variants')).toEqual([]);
    expect(ancestorKeysForRoute('slow-moving:promotion')).toEqual(['products']);
    expect(topLevelLabelForRoute('products:price-up')).toBe('产品经营');
    expect(routeLeafForSearch(searchForRoute('products:price-down')).key).toBe('products:price-down');
    expect(topLevelLabelForRoute('department:commission')).toBe('部门监控');
    expect(routeLeafForSearch('?page=department').label).toBe('业绩监控（统计报表）');
    expect(routeLeafForSearch('?page=department&tab=commission').label).toBe('提成监控（业绩报表）');
    expect(routeLeafForSearch('?page=department&tab=assessment').label).toBe('考核监控（业绩报表）');
  });
  it('has exactly three product operations entries and maps old scenes', () => {
    const group = navigationTree.find(node => node.key === 'products');
    expect(group?.kind === 'group' ? group.children.map(node => node.label) : []).toEqual(['经营诊断', '涨价追踪', '降价追踪']);
    for (const [url, scene] of [['?page=new-products', 'new'], ['?page=products&tab=low-margin', 'margin'], ['?page=slow-moving', 'clearance']]) {
      const route = routeLeafForSearch(url);
      expect(route.key).toBe('products:diagnosis');
      expect(new URLSearchParams(searchForRoute(route.key, url)).get('scene')).toBe(scene);
    }
    expect(routeLeafForSearch('?page=slow-moving&promotion_view=actual-prices').key).toBe('products:price-up');
  });
});
