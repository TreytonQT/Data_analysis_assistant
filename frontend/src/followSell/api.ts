import { apiErrorMessage } from '../apiErrors';
import { downloadWithFeedback } from '../feedback';

export interface Issue { file: string; sheet?: string; row?: number; sku?: string; message: string }
export interface Preview {
  result_id: string;
  summary: Record<string, number>;
  columns: string[];
  rows: Record<string, unknown>[];
  warnings: Issue[];
  filename: string;
}
export class WorkbookError extends Error {
  constructor(message: string, public issues: Issue[] = []) { super(message); }
}
let sessionToken = '';

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method === 'POST') headers.set('X-Follow-Sell-Token', sessionToken);
  const response = await fetch(url, { ...init, headers, credentials: 'same-origin' });
  const payload = await response.json();
  if (!response.ok) {
    throw new WorkbookError(apiErrorMessage(payload), payload?.detail?.issues || []);
  }
  return payload as T;
}

export async function getSettings() {
  const settings = await request<{ output_dir: string; token: string }>('/api/settings');
  sessionToken = settings.token;
  return settings;
}
export function processFiles(stage: 'oa' | 'mabang', files: File[], signal: AbortSignal) {
  const form = new FormData();
  const names = stage === 'oa' ? ['mapping', 'oa', 'prices'] : ['mapping', 'generated', 'original'];
  files.forEach((file, index) => form.append(names[index], file));
  return request<Preview>(`/api/process/${stage}`, { method: 'POST', body: form, signal });
}
export const saveResult = (id: string, outputDir: string) => request<{ path: string }>(`/api/results/${id}/save`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ output_dir: outputDir }),
});
export const chooseDirectory = () => request<{ path: string | null }>('/api/choose-directory', { method: 'POST' });
export const shutdown = () => request('/api/shutdown', { method: 'POST' });
export const downloadResult = (preview: Preview) => downloadWithFeedback(`/api/results/${preview.result_id}/download`, preview.filename, '结果副本');
export const downloadTemplate = (number: number) => downloadWithFeedback(`/api/templates/${number}`, `模板${number}.xlsx`, `模板${number}`);
