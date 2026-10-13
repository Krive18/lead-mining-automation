<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue';
import { Download, FileSpreadsheet, SearchCheck } from 'lucide-vue-next';

import {
  buildDownloadUrl,
  createAlibaba1688ExistenceVerification,
  getAlibaba1688ExistenceVerification,
  previewAlibaba1688ExistenceColumns,
} from '../api/client';
import type { Alibaba1688ExistenceResultItem, Alibaba1688ExistenceVerificationResult } from '../types';

type ResultFilter = 'attention' | 'all' | 'exists' | 'not_exists' | 'unconfirmed';

const RESULT_FILTER_LIST: Array<{ value: ResultFilter; label: string }> = [
  { value: 'attention', label: '需处理' },
  { value: 'all', label: '全部' },
  { value: 'exists', label: '存在' },
  { value: 'not_exists', label: '不存在' },
  { value: 'unconfirmed', label: '未确认' },
];

const selectedFile = ref<File | null>(null);
const fileContentBase64 = ref('');
const headerList = ref<string[]>([]);
const selectedColumnIndex = ref(0);
const isPreviewLoading = ref(false);
const isSubmitting = ref(false);
const errorMessage = ref('');
const result = ref<Alibaba1688ExistenceVerificationResult | null>(null);
const resultFilter = ref<ResultFilter>('attention');
let pollingTimer: number | undefined;

const selectedFileName = computed(() => selectedFile.value?.name || '选择Excel文件');
const isVerificationActive = computed(() => {
  return result.value?.status === 'pending' || result.value?.status === 'running';
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
  return result.value?.status === 'completed' && Boolean(result.value.download_url);
});
const filteredResultItems = computed(() => {
  const itemList = result.value?.result_items ?? [];
  if (resultFilter.value === 'attention') {
    return itemList.filter((item) => item.status !== '存在');
  }
  if (resultFilter.value === 'exists') {
    return itemList.filter((item) => item.status === '存在');
  }
  if (resultFilter.value === 'not_exists') {
    return itemList.filter((item) => item.status === '不存在');
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
    const preview = await previewAlibaba1688ExistenceColumns({
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
  if (!selectedFile.value.name.toLowerCase().endsWith('.xlsx')) {
    errorMessage.value = '仅支持 .xlsx 文件';
    return;
  }
  if (!fileContentBase64.value) {
    errorMessage.value = '请重新选择Excel文件';
    return;
  }
  if (selectedColumnIndex.value <= 0) {
    errorMessage.value = '请选择公司名称所在列';
    return;
  }

  isSubmitting.value = true;
  errorMessage.value = '';
  result.value = null;
  stopPolling();
  try {
    const createdJob = await createAlibaba1688ExistenceVerification({
      file_name: selectedFile.value.name,
      file_content_base64: fileContentBase64.value,
      company_name_column_index: selectedColumnIndex.value,
    });
    result.value = createdJob;
    if (createdJob.job_id && isJobActive(createdJob)) {
      startPolling(createdJob.job_id);
    } else {
      finishPollingState(createdJob);
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '1688反证失败';
    isSubmitting.value = false;
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
    const latestResult = await getAlibaba1688ExistenceVerification(jobId);
    result.value = latestResult;
    if (!isJobActive(latestResult)) {
      stopPolling();
      finishPollingState(latestResult);
    }
  } catch (error) {
    stopPolling();
    isSubmitting.value = false;
    errorMessage.value = error instanceof Error ? error.message : '1688反证状态刷新失败';
  }
}

function finishPollingState(latestResult: Alibaba1688ExistenceVerificationResult) {
  isSubmitting.value = false;
  if (latestResult.status === 'failed') {
    errorMessage.value = latestResult.error_message || '1688反证失败';
    return;
  }
  resultFilter.value = latestResult.not_exists_count > 0 || latestResult.unconfirmed_count > 0 ? 'attention' : 'all';
}

function isJobActive(job: Alibaba1688ExistenceVerificationResult) {
  return job.status === 'pending' || job.status === 'running';
}

function getFilterCount(filterValue: ResultFilter) {
  if (!result.value) {
    return 0;
  }
  if (filterValue === 'attention') {
    return result.value.not_exists_count + result.value.unconfirmed_count;
  }
  if (filterValue === 'exists') {
    return result.value.exists_count;
  }
  if (filterValue === 'not_exists') {
    return result.value.not_exists_count;
  }
  if (filterValue === 'unconfirmed') {
    return result.value.unconfirmed_count;
  }
  return result.value.total_count;
}

function getStatusKey(item: Alibaba1688ExistenceResultItem) {
  if (item.status === '存在') {
    return 'exists';
  }
  if (item.status === '不存在') {
    return 'not-exists';
  }
  return 'unconfirmed';
}

onUnmounted(() => {
  stopPolling();
});
</script>

<template>
  <div class="data-panel verifier-panel">
    <div class="panel-heading verifier-heading">
      <div>
        <h2>1688企业反证</h2>
        <span>自选公司名称列 · 搜索引擎公开索引验证 · 不进入1688详情页</span>
      </div>
      <SearchCheck :size="18" />
    </div>

    <div class="verifier-body">
      <div class="upload-row">
        <label class="file-picker">
          <FileSpreadsheet :size="18" />
          <input type="file" accept=".xlsx" @change="handleFileChange" />
          <span>{{ selectedFileName }}</span>
        </label>
        <button class="primary-button" type="button" :disabled="isSubmitting || !canSubmit" @click="submitVerification">
          {{ isVerificationActive ? '正在反证' : isSubmitting ? '正在创建' : '开始反证' }}
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

      <p v-if="isPreviewLoading" class="hint-text">正在读取Excel表头</p>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

      <div v-if="result" class="result-strip">
        <span>
          {{ verificationStatusText }}：{{ progressText }}，存在 {{ result.exists_count }} 条，不存在
          {{ result.not_exists_count }} 条，未确认 {{ result.unconfirmed_count }} 条
        </span>
        <div v-if="canDownloadResult" class="result-downloads">
          <a :href="buildDownloadUrl(result.download_url)" target="_blank" rel="noreferrer">
            <Download :size="16" />
            下载全部
          </a>
          <a :href="buildDownloadUrl(result.exists_download_url)" target="_blank" rel="noreferrer">
            <Download :size="16" />
            下载存在
          </a>
          <a :href="buildDownloadUrl(result.not_exists_download_url)" target="_blank" rel="noreferrer">
            <Download :size="16" />
            下载不存在
          </a>
        </div>
      </div>

      <div v-if="result" class="existence-live-status">
        <div class="existence-progress-line">
          <span :style="{ width: `${progressPercent}%` }"></span>
        </div>
        <div class="existence-live-grid">
          <span>当前企业：{{ result.current_company_name || '-' }}</span>
          <span>搜索词：{{ result.current_search_keyword || '-' }}</span>
          <span>已完成：{{ progressText }}</span>
        </div>
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
          <table class="existence-table">
            <thead>
              <tr>
                <th>原表行号</th>
                <th>企业名称</th>
                <th>状态</th>
                <th>1688匹配企业名</th>
                <th>1688证据链接</th>
                <th>1688检索词</th>
                <th>备注</th>
                <th>验证时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredResultItems" :key="`${item.row_index}-${item.company_name}`">
                <td>{{ item.row_index }}</td>
                <td class="strong-cell wide-cell">{{ item.company_name || '-' }}</td>
                <td><span class="existence-status" :data-status="getStatusKey(item)">{{ item.status }}</span></td>
                <td class="wide-cell">{{ item.matched_company_name || '-' }}</td>
                <td>
                  <a v-if="item.search_url" :href="item.search_url" target="_blank" rel="noreferrer">查看证据</a>
                  <span v-else>-</span>
                </td>
                <td class="wide-cell">{{ item.search_keyword || '-' }}</td>
                <td class="wide-cell">{{ item.remark || '-' }}</td>
                <td>{{ item.verified_at }}</td>
              </tr>
              <tr v-if="filteredResultItems.length === 0">
                <td colspan="8" class="empty-cell">当前筛选下暂无结果</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>
