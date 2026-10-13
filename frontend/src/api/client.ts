import type {
  Alibaba1688ExistenceColumnPreviewPayload,
  Alibaba1688ExistenceColumnPreviewResult,
  Alibaba1688ExistenceVerificationPayload,
  Alibaba1688ExistenceVerificationResult,
  ClearLeadResult,
  BrowserWarmupResult,
  ExportCreatePayload,
  ExportResult,
  LeadPageResult,
  LeadQueryParams,
  QccUsageSummary,
  QixinApiStatus,
  QixinVerificationColumnPreviewPayload,
  QixinVerificationColumnPreviewResult,
  QixinVerificationHistoryItem,
  QixinVerificationPayload,
  QixinVerificationResult,
  BatchAutomationCreatePayload,
  BatchAutomationResult,
  TaskCreatePayload,
  TaskEvent,
  TaskRecord,
  TianyanchaEnrichmentPayload,
  TianyanchaEnrichmentResult,
  TianyanchaVerificationColumnPreviewPayload,
  TianyanchaVerificationColumnPreviewResult,
  TianyanchaVerificationHistoryItem,
  TianyanchaVerificationPayload,
  TianyanchaVerificationResult,
  UsageSetting,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api';

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
    ...options,
  });
  if (!response.ok) {
    const responseText = await response.text();
    let errorMessage = responseText || `Request failed: ${response.status}`;
    try {
      const errorBody = JSON.parse(responseText) as { detail?: string };
      errorMessage = errorBody.detail || errorMessage;
    } catch {
      // Keep raw response text when backend does not return JSON.
    }
    throw new Error(errorMessage);
  }
  return response.json() as Promise<T>;
}

export function getDashboard() {
  return requestJson('/dashboard');
}

export function listTask() {
  return requestJson<TaskRecord[]>('/tasks');
}

export function createTask(payload: TaskCreatePayload) {
  return requestJson<{ task_id: string }>('/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createAiLeadDiscoveryTask(payload: TaskCreatePayload) {
  return requestJson<{ task_id: string }>('/ai/lead-discovery/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createBatchAutomation(payload: BatchAutomationCreatePayload) {
  return requestJson<BatchAutomationResult>('/tasks/batch-automation', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createTianyanchaEnrichmentTask(payload: TianyanchaEnrichmentPayload) {
  return requestJson<TianyanchaEnrichmentResult>('/tasks/tianyancha-enrichment', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createQixinEnrichmentTask(payload: TianyanchaEnrichmentPayload) {
  return requestJson<TianyanchaEnrichmentResult>('/tasks/qixin-enrichment', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getQixinApiStatus() {
  return requestJson<QixinApiStatus>('/qixin/status');
}

export function stopActiveTask() {
  return requestJson<{ stopped_count: number; closed_browser_process_count: number }>('/tasks/stop-active', {
    method: 'POST',
  });
}

export function warmupTianyanchaBrowser() {
  return requestJson<BrowserWarmupResult>('/browser-warmup/tianyancha', {
    method: 'POST',
  });
}

export function warmupAlibaba1688Browser() {
  return requestJson<BrowserWarmupResult>('/browser-warmup/1688', {
    method: 'POST',
  });
}

export function warmupMadeInChinaBrowser() {
  return requestJson<BrowserWarmupResult>('/browser-warmup/made-in-china', {
    method: 'POST',
  });
}

export function listLead(params: LeadQueryParams = {}) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return;
    }
    searchParams.set(key, String(value));
  });
  const query = searchParams.toString();
  return requestJson<LeadPageResult>(`/leads${query ? `?${query}` : ''}`);
}

export function clearLead() {
  return requestJson<ClearLeadResult>('/leads', {
    method: 'DELETE',
  });
}

export function getUsageSummary() {
  return requestJson<QccUsageSummary>('/usage/summary');
}

export function getUsageSetting() {
  return requestJson<UsageSetting>('/usage/settings');
}

export function updateUsageSetting(payload: UsageSetting) {
  return requestJson<UsageSetting>('/usage/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function listTaskEvent() {
  return requestJson<TaskEvent[]>('/logs');
}

export function createExport(payload: ExportCreatePayload) {
  return requestJson<ExportResult>('/exports', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createAlibaba1688ExistenceVerification(payload: Alibaba1688ExistenceVerificationPayload) {
  return requestJson<Alibaba1688ExistenceVerificationResult>('/1688-existence-verifications', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getAlibaba1688ExistenceVerification(jobId: string) {
  return requestJson<Alibaba1688ExistenceVerificationResult>(`/1688-existence-verifications/${jobId}`);
}

export function previewAlibaba1688ExistenceColumns(payload: Alibaba1688ExistenceColumnPreviewPayload) {
  return requestJson<Alibaba1688ExistenceColumnPreviewResult>('/1688-existence-verifications/columns', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createTianyanchaVerification(payload: TianyanchaVerificationPayload) {
  return requestJson<TianyanchaVerificationResult>('/tianyancha-verifications', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getTianyanchaVerification(jobId: string) {
  return requestJson<TianyanchaVerificationResult>(`/tianyancha-verifications/${jobId}`);
}

export function getLatestTianyanchaVerification() {
  return requestJson<TianyanchaVerificationResult>('/tianyancha-verifications/latest');
}

export function listTianyanchaVerificationHistory(limit = 20) {
  return requestJson<TianyanchaVerificationHistoryItem[]>(`/tianyancha-verifications/history?limit=${limit}`);
}

export function stopTianyanchaVerification(jobId: string) {
  return requestJson<TianyanchaVerificationResult>(`/tianyancha-verifications/${jobId}/stop`, {
    method: 'POST',
  });
}

export function previewTianyanchaVerificationColumns(payload: TianyanchaVerificationColumnPreviewPayload) {
  return requestJson<TianyanchaVerificationColumnPreviewResult>('/tianyancha-verifications/columns', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createQixinVerification(payload: QixinVerificationPayload) {
  return requestJson<QixinVerificationResult>('/qixin-verifications', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getQixinVerification(jobId: string) {
  return requestJson<QixinVerificationResult>(`/qixin-verifications/${jobId}`);
}

export function getLatestQixinVerification() {
  return requestJson<QixinVerificationResult>('/qixin-verifications/latest');
}

export function listQixinVerificationHistory(limit = 20) {
  return requestJson<QixinVerificationHistoryItem[]>(`/qixin-verifications/history?limit=${limit}`);
}

export function stopQixinVerification(jobId: string) {
  return requestJson<QixinVerificationResult>(`/qixin-verifications/${jobId}/stop`, {
    method: 'POST',
  });
}

export function previewQixinVerificationColumns(payload: QixinVerificationColumnPreviewPayload) {
  return requestJson<QixinVerificationColumnPreviewResult>('/qixin-verifications/columns', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function buildDownloadUrl(downloadUrl: string) {
  return `${API_BASE_URL.replace('/api', '')}${downloadUrl}`;
}
