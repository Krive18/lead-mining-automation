<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Download, FileSpreadsheet, ShieldCheck, Square } from 'lucide-vue-next';

import {
  buildDownloadUrl,
  createTianyanchaVerification,
  getLatestTianyanchaVerification,
  getTianyanchaVerification,
  listTianyanchaVerificationHistory,
  previewTianyanchaVerificationColumns,
  stopTianyanchaVerification,
} from '../api/client';
import type {
  TianyanchaVerificationHistoryItem,
  TianyanchaVerificationResult,
  TianyanchaVerificationResultItem,
} from '../types';

type ResultFilter = 'attention' | 'all' | 'matched' | 'not_found' | 'unconfirmed';

const RESULT_FILTER_LIST: Array<{ value: ResultFilter; label: string }> = [
  { value: 'attention', label: '需处理' },
  { value: 'all', label: '全部' },
  { value: 'matched', label: '已匹配' },
  { value: 'not_found', label: '未找到' },
  { value: 'unconfirmed', label: '未确认' },
];

const selectedFile = ref<File | null>(null);
const fileContentBase64 = ref('');
const headerList = ref<string[]>([]);
const selectedColumnIndex = ref(0);
const batchSize = ref(3);
const jitterMinSeconds = ref(8);
const jitterMaxSeconds = ref(22);
const batchCooldownSeconds = ref(45);
const isPreviewLoading = ref(false);
const isSubmitting = ref(false);
const isStopping = ref(false);
const errorMessage = ref('');
const historyErrorMessage = ref('');
const result = ref<TianyanchaVerificationResult | null>(null);
const historyList = ref<TianyanchaVerificationHistoryItem[]>([]);
const isHistoryLoading = ref(false);
const resultFilter = ref<ResultFilter>('attention');
let pollingTimer: number | undefined;
const latestJobStorageKey = 'lead-mining:tianyancha-verification:last-job-id';

const selectedFileName = computed(() => selectedFile.value?.name || '选择Excel文件');
const isVerificationActive = computed(() => {
  return ['pending', 'running', 'waiting_manual', 'stopping'].includes(result.value?.status || '');
});
const canSubmit = computed(() => {
  return Boolean(
    selectedFile.value
      && fileContentBase64.value
      && selectedColumnIndex.value > 0
      && !isPreviewLoading.value
      && !isVerificationActive.value,
  );
});
const verificationStatusText = computed(() => {
  if (!result.value) {
    return '';
  }
  if (result.value.status === 'completed') {
    return '反证完成';
  }
  if (result.value.status === 'failed') {
    return '反证失败';
  }
  if (result.value.status === 'stopped') {
    return '已安全停止';
  }
  if (result.value.status === 'stopping') {
    return '正在安全停止';
  }
  if (result.value.status === 'waiting_manual') {
    return '等待人工验证';
  }
  if (result.value.status === 'running') {
    return '正在反证';
  }
  return '等待开始';
});
const progressText = computed(() => {
  if (!result.value) {
    return '';
  }
  return `${result.value.processed_count}/${result.value.total_count}`;
});
const progressPercent = computed(() => {
  if (!result.value || result.value.total_count <= 0) {
    return 0;
  }
  return Math.round((result.value.processed_count / result.value.total_count) * 100);
});
const canDownloadResult = computed(() => {
  return Boolean(result.value?.download_url);
});
const eventItemList = computed(() => result.value?.event_items ?? []);
const filteredResultItems = computed(() => {
  const itemList = result.value?.result_items ?? [];
  if (resultFilter.value === 'attention') {
    return itemList.filter((item) => item.status !== '已匹配');
  }
  if (resultFilter.value === 'matched') {
    return itemList.filter((item) => item.status === '已匹配');
  }
  if (resultFilter.value === 'not_found') {
    return itemList.filter((item) => item.status === '未找到');
  }
  if (resultFilter.value === 'unconfirmed') {
    return itemList.filter((item) => item.status === '未确认');
  }
  return itemList;
});

async function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
  fileContentBase64.value = '';
  headerList.value = [];
  selectedColumnIndex.value = 0;
  errorMessage.value = '';
  result.value = null;
  resultFilter.value = 'attention';
  stopPolling();

  if (!selectedFile.value) {
    return;
  }
  if (!selectedFile.value.name.toLowerCase().endsWith('.xlsx')) {
    errorMessage.value = '仅支持 .xlsx 文件';
    return;
  }

  isPreviewLoading.value = true;
  try {
    fileContentBase64.value = await readFileAsBase64(selectedFile.value);
    const preview = await previewTianyanchaVerificationColumns({
      file_name: selectedFile.value.name,
      file_content_base64: fileContentBase64.value,
    });
    headerList.value = preview.headers;
    selectedColumnIndex.value = preview.suggested_column_index || 0;
    if (headerList.value.length > 0 && selectedColumnIndex.value <= 0) {
      errorMessage.value = '未自动识别公司名称列，请手动选择';
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Excel表头读取失败';
  } finally {
    isPreviewLoading.value = false;
  }
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',')[1] : value);
    };
    reader.onerror = () => reject(new Error('Excel文件读取失败'));
    reader.readAsDataURL(file);
  });
}

async function submitVerification() {
  if (!selectedFile.value) {
    errorMessage.value = '请选择Excel文件';
    return;
  }
  if (selectedColumnIndex.value <= 0) {
    errorMessage.value = '请选择公司名称所在列';
    return;
  }
  if (jitterMaxSeconds.value < jitterMinSeconds.value) {
    errorMessage.value = '随机等待最大值不能小于最小值';
    return;
  }

  isSubmitting.value = true;
  errorMessage.value = '';
  result.value = null;
  stopPolling();
  try {
    const createdJob = await createTianyanchaVerification({
      file_name: selectedFile.value.name,
      file_content_base64: fileContentBase64.value,
      company_name_column_index: selectedColumnIndex.value,
      batch_size: batchSize.value,
      jitter_min_seconds: jitterMinSeconds.value,
      jitter_max_seconds: jitterMaxSeconds.value,
      batch_cooldown_seconds: batchCooldownSeconds.value,
    });
    result.value = createdJob;
    rememberLatestJob(createdJob);
    void loadHistory();
    if (createdJob.job_id && isJobActive(createdJob)) {
      startPolling(createdJob.job_id);
    } else {
      finishPollingState(createdJob);
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天眼查反证失败';
    isSubmitting.value = false;
  }
}

async function stopVerification() {
  const jobId = result.value?.job_id || '';
  if (!jobId || !isVerificationActive.value || isStopping.value) {
    return;
  }
  if (!window.confirm('确认停止当前天眼查反证吗？已完成的数据会保存并生成部分结果。')) {
    return;
  }
  isStopping.value = true;
  errorMessage.value = '';
  try {
    const stoppingJob = await stopTianyanchaVerification(jobId);
    result.value = stoppingJob;
    rememberLatestJob(stoppingJob);
    startPolling(jobId);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '天眼查反证停止失败';
  } finally {
    isStopping.value = false;
  }
}

function startPolling(jobId: string) {
  stopPolling();
  pollingTimer = window.setInterval(() => {
    void refreshVerificationJob(jobId);
  }, 1500);
  void refreshVerificationJob(jobId);
}

function stopPolling() {
  if (pollingTimer !== undefined) {
    window.clearInterval(pollingTimer);
    pollingTimer = undefined;
  }
}

async function refreshVerificationJob(jobId: string) {
  try {
    const latestResult = await getTianyanchaVerification(jobId);
    result.value = latestResult;
    rememberLatestJob(latestResult);
    if (!isJobActive(latestResult)) {
      stopPolling();
      finishPollingState(latestResult);
      void loadHistory();
    }
  } catch (error) {
    stopPolling();
    isSubmitting.value = false;
    errorMessage.value = error instanceof Error ? error.message : '天眼查反证状态刷新失败';
  }
}

function finishPollingState(latestResult: TianyanchaVerificationResult) {
  isSubmitting.value = false;
  if (latestResult.status === 'failed') {
    errorMessage.value = latestResult.error_message || '天眼查反证失败';
    return;
  }
  resultFilter.value = latestResult.not_found_count > 0 || latestResult.unconfirmed_count > 0 ? 'attention' : 'all';
}

function rememberLatestJob(job: TianyanchaVerificationResult) {
  if (!job.job_id) {
    return;
  }
  window.localStorage.setItem(latestJobStorageKey, job.job_id);
}

async function restoreLatestJob(force = false) {
  if (!force && (result.value || selectedFile.value)) {
    return;
  }
  const storedJobId = result.value?.job_id || window.localStorage.getItem(latestJobStorageKey) || '';
  const restoredJob = await fetchRestoredJob(storedJobId);
  if (!restoredJob?.job_id) {
    return;
  }
  result.value = restoredJob;
  rememberLatestJob(restoredJob);
  if (isJobActive(restoredJob)) {
    startPolling(restoredJob.job_id);
  } else {
    finishPollingState(restoredJob);
  }
}

async function refreshLatestState() {
  await restoreLatestJob(true);
  await loadHistory();
}

async function loadHistory() {
  isHistoryLoading.value = true;
  historyErrorMessage.value = '';
  try {
    historyList.value = await listTianyanchaVerificationHistory(30);
  } catch (error) {
    historyErrorMessage.value = error instanceof Error ? error.message : '历史记录读取失败';
  } finally {
    isHistoryLoading.value = false;
  }
}

async function selectHistoryJob(item: TianyanchaVerificationHistoryItem) {
  if (!item.job_id) {
    return;
  }
  stopPolling();
  errorMessage.value = '';
  historyErrorMessage.value = '';
  try {
    const selectedJob = await getTianyanchaVerification(item.job_id);
    result.value = selectedJob;
    rememberLatestJob(selectedJob);
    if (isJobActive(selectedJob)) {
      startPolling(selectedJob.job_id);
    } else {
      finishPollingState(selectedJob);
    }
  } catch (error) {
    historyErrorMessage.value = error instanceof Error ? error.message : '历史任务读取失败';
  }
}

async function fetchRestoredJob(storedJobId: string) {
  if (storedJobId) {
    try {
      return await getTianyanchaVerification(storedJobId);
    } catch {
      window.localStorage.removeItem(latestJobStorageKey);
    }
  }
  try {
    return await getLatestTianyanchaVerification();
  } catch {
    return null;
  }
}

function isJobActive(job: TianyanchaVerificationResult) {
  return ['pending', 'running', 'waiting_manual', 'stopping'].includes(job.status);
}

function getFilterCount(filterValue: ResultFilter) {
  if (!result.value) {
    return 0;
  }
  if (filterValue === 'attention') {
    return result.value.not_found_count + result.value.unconfirmed_count;
  }
  if (filterValue === 'matched') {
    return result.value.matched_count;
  }
  if (filterValue === 'not_found') {
    return result.value.not_found_count;
  }
  if (filterValue === 'unconfirmed') {
    return result.value.unconfirmed_count;
  }
  return result.value.total_count;
}

function getStatusKey(item: TianyanchaVerificationResultItem) {
  if (item.status === '已匹配') {
    return 'exists';
  }
  if (item.status === '未找到') {
    return 'not-exists';
  }
  return 'unconfirmed';
}

function getJobStatusText(status: string) {
  if (status === 'completed') {
    return '完成';
  }
  if (status === 'failed') {
    return '失败';
  }
  if (status === 'stopped') {
    return '已停止';
  }
  if (status === 'stopping') {
    return '停止中';
  }
  if (status === 'waiting_manual') {
    return '待人工';
  }
  if (status === 'running') {
    return '运行中';
  }
  if (status === 'pending') {
    return '等待中';
  }
  return status || '未知';
}

function getHistoryStatusKey(status: string) {
  if (status === 'completed') {
    return 'completed';
  }
  if (status === 'failed') {
    return 'failed';
  }
  if (status === 'stopped') {
    return 'stopped';
  }
  if (status === 'waiting_manual') {
    return 'manual';
  }
  if (status === 'running' || status === 'pending' || status === 'stopping') {
    return 'running';
  }
  return 'unknown';
}

function getHistorySummaryText(item: TianyanchaVerificationHistoryItem) {
  return `${item.processed_count}/${item.total_count} · 匹配${item.matched_count} · 未找到${item.not_found_count} · 未确认${item.unconfirmed_count}`;
}

onMounted(() => {
  void loadHistory();
  void restoreLatestJob();
});

onUnmounted(() => {
  stopPolling();
});
</script>

<template>
  <div class="tianyancha-verification-layout">
    <div class="data-panel verifier-panel tianyancha-verifier-panel">
      <div class="panel-heading verifier-heading">
        <div>
          <h2>天眼查企业反证</h2>
          <span>上传公司名清单，按批次打开天眼查公开页精准匹配企业信息</span>
        </div>
        <ShieldCheck :size="18" />
      </div>

      <div class="verifier-body">
        <div class="upload-row">
          <label class="file-picker">
            <FileSpreadsheet :size="18" />
            <input type="file" accept=".xlsx" @change="handleFileChange" />
            <span>{{ selectedFileName }}</span>
          </label>
          <button class="primary-button" type="button" :disabled="isSubmitting || !canSubmit" @click="submitVerification">
            {{ isVerificationActive ? '正在反证' : isSubmitting ? '正在创建' : '开始天眼查反证' }}
          </button>
          <button
            v-if="isVerificationActive"
            class="danger-button"
            type="button"
            :disabled="isStopping || result?.status === 'stopping'"
            title="停止任务并保存已完成结果"
            @click="stopVerification"
          >
            <Square :size="15" />
            {{ isStopping || result?.status === 'stopping' ? '正在停止' : '停止并保存' }}
          </button>
          <button class="secondary-button" type="button" :disabled="isSubmitting" @click="refreshLatestState">
            刷新最新状态
          </button>
        </div>

        <label v-if="headerList.length > 0" class="column-picker">
          <span>公司名称列</span>
          <select v-model.number="selectedColumnIndex">
            <option :value="0" disabled>请选择公司名称所在列</option>
            <option v-for="(header, index) in headerList" :key="`${index}-${header}`" :value="index + 1">
              第{{ index + 1 }}列 - {{ header || '空表头' }}
            </option>
          </select>
        </label>

        <div class="pacing-grid">
          <label>
            <span>每批数量</span>
            <input v-model.number="batchSize" type="number" min="1" max="30" />
          </label>
          <label>
            <span>随机等待最小秒</span>
            <input v-model.number="jitterMinSeconds" type="number" min="0" max="900" />
          </label>
          <label>
            <span>随机等待最大秒</span>
            <input v-model.number="jitterMaxSeconds" type="number" min="0" max="1200" />
          </label>
          <label>
            <span>批次冷却秒</span>
            <input v-model.number="batchCooldownSeconds" type="number" min="0" max="1800" />
          </label>
        </div>

        <p class="hint-text">遇到天眼查登录、验证码或风控时，可人工完成后继续，也可点击“停止并保存”导出已完成结果。</p>
        <p v-if="isPreviewLoading" class="hint-text">正在读取Excel表头</p>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

        <div v-if="result" class="result-strip" :class="{ 'manual-strip': result.status === 'waiting_manual' }">
          <span>
            {{ verificationStatusText }}：{{ progressText }}，已匹配 {{ result.matched_count }} 条，未找到
            {{ result.not_found_count }} 条，未确认 {{ result.unconfirmed_count }} 条
          </span>
          <div v-if="canDownloadResult" class="result-downloads">
            <a :href="buildDownloadUrl(result.download_url)" target="_blank" rel="noreferrer">
              <Download :size="16" />
              下载结果
            </a>
          </div>
        </div>

        <div v-if="result" class="existence-live-status">
          <div class="existence-progress-line">
            <span :style="{ width: `${progressPercent}%` }"></span>
          </div>
          <div class="existence-live-grid tianyancha-live-grid">
            <span>当前企业：{{ result.current_company_name || '-' }}</span>
            <span>批次：{{ result.current_batch_index || 0 }}/{{ result.total_batch_count || 0 }}</span>
            <span>状态：{{ result.current_message || verificationStatusText }}</span>
            <span>已完成：{{ progressText }}</span>
          </div>
        </div>

        <div class="verification-event-list">
          <div class="verification-event-heading">实时工作日志</div>
          <div v-for="eventItem in eventItemList.slice().reverse().slice(0, 10)" :key="`${eventItem.created_at}-${eventItem.message}`">
            <strong>{{ eventItem.created_at }}</strong>
            <span>{{ eventItem.message }}</span>
          </div>
          <div v-if="eventItemList.length === 0" class="verification-event-empty">暂无工作日志</div>
        </div>

        <div v-if="result" class="existence-result-panel">
          <div class="result-filter-row">
            <button
              v-for="filterItem in RESULT_FILTER_LIST"
              :key="filterItem.value"
              :class="{ active: resultFilter === filterItem.value }"
              type="button"
              @click="resultFilter = filterItem.value"
            >
              {{ filterItem.label }}
              <strong>{{ getFilterCount(filterItem.value) }}</strong>
            </button>
          </div>

          <div class="table-wrap">
            <table class="existence-table tianyancha-table">
              <thead>
                <tr>
                  <th>原表行号</th>
                  <th>源企业名</th>
                  <th>状态</th>
                  <th>匹配企业</th>
                  <th>法人</th>
                  <th>联系人</th>
                  <th>电话</th>
                  <th>统一社会信用代码</th>
                  <th>企业地址</th>
                  <th>天眼查详情</th>
                  <th>备注</th>
                  <th>反证时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in filteredResultItems" :key="`${item.row_index}-${item.company_name}`">
                  <td>{{ item.row_index }}</td>
                  <td class="strong-cell wide-cell">{{ item.company_name || '-' }}</td>
                  <td><span class="existence-status" :data-status="getStatusKey(item)">{{ item.status }}</span></td>
                  <td class="wide-cell">{{ item.matched_company_name || '-' }}</td>
                  <td>{{ item.legal_person || '-' }}</td>
                  <td>{{ item.contact_name || '-' }}</td>
                  <td class="wide-cell">{{ item.phone || '-' }}</td>
                  <td class="wide-cell">{{ item.unified_social_credit_code || '-' }}</td>
                  <td class="wide-cell">{{ item.registered_address || '-' }}</td>
                  <td>
                    <a v-if="item.profile_url" :href="item.profile_url" target="_blank" rel="noreferrer">查看</a>
                    <span v-else>-</span>
                  </td>
                  <td class="wide-cell">{{ item.remark || '-' }}</td>
                  <td>{{ item.verified_at }}</td>
                </tr>
                <tr v-if="filteredResultItems.length === 0">
                  <td colspan="12" class="empty-cell">当前筛选下暂无结果</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <aside class="data-panel tianyancha-history-panel">
      <div class="tianyancha-history-heading">
        <div>
          <h2>历史记录</h2>
          <span>点击回看结果和日志</span>
        </div>
        <button class="secondary-button" type="button" :disabled="isHistoryLoading" @click="loadHistory">
          {{ isHistoryLoading ? '刷新中' : '刷新' }}
        </button>
      </div>

      <p v-if="historyErrorMessage" class="error-text">{{ historyErrorMessage }}</p>

      <div class="tianyancha-history-list">
        <div
          v-for="historyItem in historyList"
          :key="historyItem.job_id"
          class="tianyancha-history-item"
          :class="{ active: result?.job_id === historyItem.job_id }"
        >
          <button type="button" @click="selectHistoryJob(historyItem)">
            <span class="history-row">
              <strong>{{ historyItem.created_at || historyItem.updated_at || '未知时间' }}</strong>
              <em :data-status="getHistoryStatusKey(historyItem.status)">{{ getJobStatusText(historyItem.status) }}</em>
            </span>
            <span class="history-file">{{ historyItem.file_name || '未命名文件' }}</span>
            <span class="history-summary">{{ getHistorySummaryText(historyItem) }}</span>
          </button>
          <a v-if="historyItem.download_url" :href="buildDownloadUrl(historyItem.download_url)" target="_blank" rel="noreferrer">
            <Download :size="15" />
            下载
          </a>
        </div>
        <div v-if="historyList.length === 0 && !isHistoryLoading" class="tianyancha-history-empty">暂无天眼查反证历史</div>
      </div>
    </aside>
  </div>
</template>
