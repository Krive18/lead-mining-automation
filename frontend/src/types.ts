export interface DashboardData {
  task_count: number;
  lead_count: number;
  high_value_count: number;
  running_count: number;
  usage_summary: QccUsageSummary;
}

export interface TaskCreatePayload {
  source_type: string;
  industry: string;
  keywords: string[];
  target_city?: string;
  collect_limit: number;
  is_qcc_enabled: boolean;
  qcc_limit: number;
}

export interface BatchAutomationCreatePayload extends TaskCreatePayload {
  batch_count: number;
  batch_collect_limit: number;
  cooldown_seconds: number;
}

export interface BatchAutomationResult {
  automation_id: string;
  first_task_id: string;
  batch_count: number;
  batch_collect_limit: number;
  cooldown_seconds: number;
}

export interface TianyanchaEnrichmentPayload {
  task_id?: string;
  limit: number;
  pacing_mode?: string;
}

export interface TianyanchaEnrichmentResult {
  task_id: string;
  limit: number;
  source_task_id?: string;
  pacing_mode?: string;
}

export interface QixinApiStatus {
  configured: boolean;
  egress_ip: string;
  egress_region: string;
  message: string;
}

export interface TaskRecord {
  id: string;
  task_name: string;
  source_type: string;
  industry: string;
  keyword_text: string;
  target_city: string;
  collect_limit: number;
  is_qcc_enabled: number;
  qcc_limit: number;
  status: string;
  total_count: number;
  success_count: number;
  failed_count: number;
  gmt_create: string;
  gmt_modified: string;
}

export interface LeadRecord {
  id: string;
  task_id: string;
  source_type: string;
  source_keyword: string;
  industry: string;
  suspected_company_name: string;
  company_name: string;
  company_name_en: string;
  douyin_nickname: string;
  product_name: string;
  shop_level: string;
  contact_name: string;
  phone: string;
  phone_source: string;
  website_url: string;
  shop_url: string;
  profile_url: string;
  sample_video_url: string;
  is_blue_v: number;
  is_enterprise_verified: number;
  company_status: string;
  unified_social_credit_code: string;
  legal_person: string;
  business_scope: string;
  registered_address: string;
  province: string;
  city: string;
  district: string;
  city_source: string;
  city_confidence: string;
  risk_tag: string;
  verification_status: string;
  confidence: string;
  score: number;
  level: string;
  assignment_status: string;
  gmt_create: string;
  gmt_modified: string;
}

export interface LeadPageResult {
  items: LeadRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface LeadQueryParams {
  level?: string;
  source_type?: string;
  source_group?: string;
  industry?: string;
  keyword?: string;
  city?: string;
  assignment_status?: string;
  page?: number;
  page_size?: number;
}

export interface ExportCreatePayload {
  levels: string[];
  is_phone_masked: boolean;
  source_type?: string;
  source_group?: string;
  industry?: string;
  keyword?: string;
  city?: string;
  assignment_status?: string;
}

export interface QccUsageLog {
  id: string;
  task_id: string;
  company_name: string;
  interface_name: string;
  consume_count: number;
  is_success: number;
  failure_reason: string;
  gmt_create: string;
  gmt_modified: string;
}

export interface QccUsageSummary {
  daily_used: number;
  daily_quota: number;
  daily_remaining: number;
  monthly_used: number;
  monthly_quota: number;
  monthly_remaining: number;
  recent_usage: QccUsageLog[];
}

export interface UsageSetting {
  daily_quota: number;
  monthly_quota: number;
}

export interface TaskEvent {
  id: string;
  task_id: string;
  event_level: string;
  event_message: string;
  gmt_create: string;
  gmt_modified: string;
}

export interface ExportResult {
  file_name: string;
  file_path: string;
  download_url: string;
  total_count: number;
}

export interface Alibaba1688ExistenceVerificationPayload {
  file_name: string;
  file_content_base64: string;
  company_name_column_index: number;
}

export interface TianyanchaVerificationPayload {
  file_name: string;
  file_content_base64: string;
  company_name_column_index: number;
  batch_size: number;
  jitter_min_seconds: number;
  jitter_max_seconds: number;
  batch_cooldown_seconds: number;
}

export interface QixinVerificationPayload {
  file_name: string;
  file_content_base64: string;
  company_name_column_index: number;
  request_interval_seconds: number;
}

export type QixinVerificationColumnPreviewPayload = TianyanchaVerificationColumnPreviewPayload;
export type QixinVerificationColumnPreviewResult = TianyanchaVerificationColumnPreviewResult;
export type QixinVerificationResultItem = TianyanchaVerificationResultItem;
export type QixinVerificationResult = TianyanchaVerificationResult;
export type QixinVerificationHistoryItem = TianyanchaVerificationHistoryItem;

export interface Alibaba1688ExistenceColumnPreviewPayload {
  file_name: string;
  file_content_base64: string;
}

export interface TianyanchaVerificationColumnPreviewPayload {
  file_name: string;
  file_content_base64: string;
}

export interface Alibaba1688ExistenceColumnPreviewResult {
  headers: string[];
  suggested_column_index: number;
  suggested_column_name: string;
}

export interface TianyanchaVerificationColumnPreviewResult {
  headers: string[];
  suggested_column_index: number;
  suggested_column_name: string;
}

export interface Alibaba1688ExistenceResultItem {
  row_index: number;
  company_name: string;
  status: string;
  matched_company_name: string;
  search_url: string;
  search_keyword: string;
  remark: string;
  verified_at: string;
}

export interface Alibaba1688ExistenceVerificationResult {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  processed_count: number;
  current_row_index: number;
  current_company_name: string;
  current_search_keyword: string;
  error_message: string;
  file_name: string;
  file_path: string;
  download_url: string;
  exists_file_name: string;
  exists_file_path: string;
  exists_download_url: string;
  not_exists_file_name: string;
  not_exists_file_path: string;
  not_exists_download_url: string;
  total_count: number;
  exists_count: number;
  not_exists_count: number;
  unconfirmed_count: number;
  result_items: Alibaba1688ExistenceResultItem[];
}

export interface TianyanchaVerificationResultItem {
  row_index: number;
  company_name: string;
  status: string;
  matched_company_name: string;
  legal_person: string;
  contact_name: string;
  phone: string;
  phone_source: string;
  company_status: string;
  unified_social_credit_code: string;
  registered_address: string;
  business_scope: string;
  risk_tag: string;
  profile_url: string;
  search_keyword: string;
  remark: string;
  verified_at: string;
}

export interface TianyanchaVerificationEventItem {
  level: string;
  message: string;
  created_at: string;
}

export interface TianyanchaVerificationResult {
  job_id: string;
  status: 'pending' | 'running' | 'waiting_manual' | 'stopping' | 'stopped' | 'completed' | 'failed' | string;
  processed_count: number;
  current_row_index: number;
  current_company_name: string;
  current_search_keyword: string;
  current_batch_index: number;
  total_batch_count: number;
  current_message: string;
  error_message: string;
  file_name: string;
  file_path: string;
  download_url: string;
  export_file_name: string;
  created_at: string;
  updated_at: string;
  total_count: number;
  matched_count: number;
  not_found_count: number;
  unconfirmed_count: number;
  batch_size: number;
  jitter_min_seconds: number;
  jitter_max_seconds: number;
  batch_cooldown_seconds: number;
  result_items: TianyanchaVerificationResultItem[];
  event_items: TianyanchaVerificationEventItem[];
}

export interface TianyanchaVerificationHistoryItem {
  job_id: string;
  status: 'pending' | 'running' | 'waiting_manual' | 'stopping' | 'stopped' | 'completed' | 'failed' | string;
  file_name: string;
  download_url: string;
  export_file_name: string;
  total_count: number;
  processed_count: number;
  matched_count: number;
  not_found_count: number;
  unconfirmed_count: number;
  current_message: string;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface ClearLeadResult {
  deleted_count: number;
}

export interface BrowserWarmupResult {
  source_type: string;
  process_id: number;
  warmup_url: string;
  message: string;
}
