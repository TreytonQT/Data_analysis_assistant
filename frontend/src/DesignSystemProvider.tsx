import { createContext, useContext, useLayoutEffect, type ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';

import { appCssVariables, appTheme } from './designTokens';
dayjs.locale('zh-cn');
const DarkThemeContext = createContext(false);
export const useDarkTheme = () => useContext(DarkThemeContext);

export default function DesignSystemProvider({ dark, children }: { dark: boolean; children: ReactNode }) {
  useLayoutEffect(() => {
    // Portals are mounted under body, so theme variables/classes belong to html.
    const root = document.documentElement;
    const previousDark = root.classList.contains('dark-mode');
    const variables = appCssVariables(dark);
    const previous = Object.keys(variables).map(key => [key, root.style.getPropertyValue(key)] as const);
    root.classList.toggle('dark-mode', dark);
    Object.entries(variables).forEach(([key, value]) => root.style.setProperty(key, value));
    return () => {
      root.classList.toggle('dark-mode', previousDark);
      previous.forEach(([key, value]) => value ? root.style.setProperty(key, value) : root.style.removeProperty(key));
    };
  }, [dark]);

  return <DarkThemeContext.Provider value={dark}>
    <ConfigProvider locale={zhCN} theme={appTheme(dark)} form={{ validateMessages: { required: '${label}不能为空' } }}>
      {children}
    </ConfigProvider>
  </DarkThemeContext.Provider>;
}
