import { theme, type ThemeConfig } from 'antd';

// Keep product values here; CSS and Ant Design consume the same theme mapping.
export const designTokens = {
  colorPrimary: '#3b82f6',
  fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  feedback: { top: 24, maxCount: 3, duration: 2.5 },
  radius: { control: 4, tooltip: 6, matrix: 8, card: 10 },
  space: { control: 8, card: 16, section: 18, heading: 24, page: 28, pageNarrow: 18 },
  layout: { contentMax: 1800, headerHeight: 56, sidebarWidth: 240, controlHeight: 32 },
  motion: { page: 0.22, popover: 0.28, expand: 0.32 },
  layer: { sticky: 5, toolbar: 10, floating: 1200, system: 2200 },
} as const;

const palettes = {
  light: {
    page: '#f5f5f7', surface: '#ffffff', elevated: '#ffffff', navigation: '#f5f5f7',
    text: '#1d1d1f', secondary: '#626268', tertiary: '#6e6e73', border: '#e5e5e9',
    selected: '#e8e8ed', hover: '#f0f0f3', controlBorder: '#d2d2d7',
    action: '#1d1d1f', actionHover: '#363638', onAction: '#ffffff',
    chartGrid: '#e8e8ec', chartMuted: '#a1a1a6', chartLine: '#2563eb', chartComparison: '#f97316',
    matrixSurface: '#ffffff', matrixAlternate: '#f5f9fd', matrixHeader: '#c9eeec',
    matrixHeaderText: '#102c48', matrixBorder: '#a9c3df', matrixOuterBorder: '#213d60',
    positive: '#16a34a', negative: '#ef4444',
  },
  dark: {
    page: '#0b0b0d', surface: '#171719', elevated: '#222225', navigation: '#0b0b0d',
    text: '#f5f5f7', secondary: '#b4b4b8', tertiary: '#96969d', border: '#303034',
    selected: '#29292d', hover: '#222225', controlBorder: '#49494f',
    action: '#f5f5f7', actionHover: '#dcdce2', onAction: '#1d1d1f',
    chartGrid: '#303034', chartMuted: '#76767d', chartLine: '#60a5fa', chartComparison: '#fb923c',
    matrixSurface: '#171719', matrixAlternate: '#1e1e21', matrixHeader: '#bce7e5',
    matrixHeaderText: '#07131e', matrixBorder: '#31577f', matrixOuterBorder: '#315982',
    positive: '#4ade80', negative: '#f87171',
  },
} as const;

export function appTheme(dark: boolean): ThemeConfig {
  const colors = palettes[dark ? 'dark' : 'light'];
  return {
    algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: designTokens.colorPrimary,
      borderRadius: designTokens.radius.card,
      fontFamily: designTokens.fontFamily,
      colorBgBase: dark ? colors.page : colors.surface,
      colorBgLayout: colors.page,
      colorBgContainer: colors.surface,
      colorBgElevated: colors.elevated,
      colorText: colors.text,
      colorTextSecondary: colors.secondary,
      colorBorder: colors.border,
      colorBorderSecondary: colors.border,
      colorFillAlter: colors.hover,
      controlHeight: designTokens.layout.controlHeight,
      motionDurationMid: `${designTokens.motion.popover}s`,
      motionDurationSlow: `${designTokens.motion.expand}s`,
    },
    components: {
      Button: {
        colorPrimary: colors.action, colorPrimaryHover: colors.actionHover,
        colorPrimaryActive: colors.action, primaryColor: colors.onAction,
        primaryShadow: 'none', defaultShadow: 'none', borderRadius: designTokens.radius.control,
      },
      Menu: {
        itemBg: colors.navigation, subMenuItemBg: colors.navigation,
        itemSelectedBg: colors.selected, itemSelectedColor: colors.text,
        itemHoverBg: colors.hover, itemHoverColor: colors.text,
        darkItemBg: colors.navigation, darkSubMenuItemBg: colors.navigation,
        darkItemSelectedBg: colors.selected, darkItemSelectedColor: colors.text,
        darkItemColor: colors.secondary, darkItemHoverBg: colors.hover,
      },
      Tabs: { inkBarColor: colors.text, itemSelectedColor: colors.text, itemActiveColor: colors.text, itemHoverColor: colors.text },
      Table: {
        headerBg: colors.surface, headerColor: colors.secondary, rowHoverBg: colors.hover,
        headerSortActiveBg: colors.hover, headerSortHoverBg: colors.hover,
        bodySortBg: colors.hover, borderColor: colors.border,
      },
      Switch: { colorPrimary: colors.action, colorPrimaryHover: colors.actionHover },
      Layout: { headerBg: colors.navigation, siderBg: colors.navigation },
    },
  };
}

export function appCssVariables(dark: boolean): Record<string, string> {
  const colors = palettes[dark ? 'dark' : 'light'];
  return {
    '--app-color-primary': designTokens.colorPrimary,
    '--app-font-family': designTokens.fontFamily,
    ...Object.fromEntries(Object.entries(colors).map(([key, value]) => [
      `--app-color-${key.replace(/[A-Z]/g, letter => '-' + letter.toLowerCase())}`, value,
    ])),
    ...Object.fromEntries(Object.entries(designTokens.space).map(([key, value]) => [
      `--app-space-${key.replace(/[A-Z]/g, letter => '-' + letter.toLowerCase())}`, `${value}px`,
    ])),
    ...Object.fromEntries(Object.entries(designTokens.radius).map(([key, value]) => [`--app-radius-${key}`, `${value}px`])),
    ...Object.fromEntries(Object.entries(designTokens.layer).map(([key, value]) => [`--app-layer-${key}`, String(value)])),
    '--app-content-max': `${designTokens.layout.contentMax}px`,
    '--app-header-height': `${designTokens.layout.headerHeight}px`,
    '--app-control-height': `${designTokens.layout.controlHeight}px`,
    '--app-motion-expand': `${designTokens.motion.expand}s`,
  };
}
