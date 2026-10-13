<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { storeToRefs } from 'pinia';
import {
  Activity,
  ClipboardList,
  Database,
  Download,
  KeyRound,
  ListChecks,
  RefreshCw,
} from 'lucide-vue-next';

import AppSidebar from './components/AppSidebar.vue';
import Alibaba1688ExistenceVerifier from './components/Alibaba1688ExistenceVerifier.vue';
import LeadTable from './components/LeadTable.vue';
import LogPanel from './components/LogPanel.vue';
import MetricTile from './components/MetricTile.vue';
import TaskComposer from './components/TaskComposer.vue';
import TaskTable from './components/TaskTable.vue';
import TianyanchaVerificationPanel from './components/TianyanchaVerificationPanel.vue';
import QixinVerificationPanel from './components/QixinVerificationPanel.vue';
import UsagePanel from './components/UsagePanel.vue';
import { buildDownloadUrl } from './api/client';
import { useLeadStore } from './stores/leadStore';
import { isActiveTaskStatus } from './utils/format';

const activePage = ref('tasks');
const isPhoneMasked = ref(false);
const exportSourceGroup = ref('all');
const exportSourceGroupOptions = [
  { value: 'all', label: '全部路线' },
  { value: 'qixin', label: '启信宝' },
  { value: 'tianyancha', label: '天眼查' },
  { value: 'ai_web', label: 'AI 1688搜企' },
  { value: 'douyin', label: '抖音线索' },
  { value: 'alibaba_tianyancha', label: '1688采集' },
  { value: 'alibaba_international', label: '阿里国际站' },
  { value: 'made_in_china', label: '中国制造网+天眼查' },
  { value: 'alibaba', label: '1688普通页面' },
];
const exportIndustry = ref('');
const exportIndustryOptions = ['', '服装', '美妆个护', '3C数码', '其他'];
const exportAssignmentStatus = ref('');
const exportAssignmentStatusOptions = [
  { value: '', label: '全部' },
  { value: 'unassigned', label: '未分配' },
  { value: 'assigned', label: '已分配' },
];

const store = useLeadStore();
const {
  dashboard,
  exportResult,
  isLoading,
  leadFilters,
  leadPage,
  leads,
  taskEvents,
  tasks,
  usageSetting,
  usageSummary,
} = storeToRefs(store);

let refreshTimer: number | undefined;

const pageTitle = computed(() => {
  const titleMap: Record<string, string> = {
    tasks: '任务中心',
    leads: '线索库',
    '1688-existence': '1688企业反证',
    'tianyancha-verification': '天眼查企业反证',
    'qixin-verification': '启信宝企业反证',
    usage: '额度管理',
    logs: '系统日志',
  };
  return titleMap[activePage.value] ?? '任务中心';
});

const qccUsagePercent = computed(() => {
  if (!usageSummary.value || usageSummary.value.daily_quota === 0) {
    return 0;
  }
  return Math.round((usageSummary.value.daily_used / usageSummary.value.daily_quota) * 100);
});

const hasActiveTask = computed(() => {
  return tasks.value.some((task) => isActiveTaskStatus(task.status));
});

async function refreshAll() {
  await store.refreshAll();
}

async function handleTaskCreated() {
  await refreshAll();
}

function buildRouteExportFilters() {
  return {
    ...leadFilters.value,
    source_type: '',
    source_group: exportSourceGroup.value === 'all' ? '' : exportSourceGroup.value,
    industry: exportIndustry.value,
    assignment_status: exportAssignmentStatus.value,
  };
}

async function exportLead() {
  await store.exportLead(['A', 'B'], isPhoneMasked.value, buildRouteExportFilters());
}

async function exportSelectedAssignmentLead() {
  await store.exportLead(['A', 'B', 'C', 'D'], isPhoneMasked.value, buildRouteExportFilters());
}

async function exportCurrentModuleLead() {
  await store.exportLead(['A', 'B', 'C', 'D'], isPhoneMasked.value, {
    ...leadFilters.value,
    industry: exportIndustry.value,
    assignment_status: exportAssignmentStatus.value,
  });
}

async function clearLead() {
  if (hasActiveTask.value) {
    window.alert('当前有任务正在运行，请等待任务完成后再清空线索库。');
    return;
  }
  if (leadPage.value.total === 0) {
    return;
  }
  const isConfirmed = window.confirm('确认清空线索库吗？该操作只删除线索名单，不会删除任务记录、系统日志和额度记录。');
  if (!isConfirmed) {
    return;
  }
  await store.clearLead();
}

async function stopActiveTask() {
  const isConfirmed = window.confirm('确认停止当前运行中的任务吗？');
  if (!isConfirmed) {
    return;
  }
  await store.stopActiveTask();
}

onMounted(async () => {
  await refreshAll();
  refreshTimer = window.setInterval(async () => {
    if (hasActiveTask.value) {
      await store.refreshAll({ silent: true });
    }
  }, 2000);
});

onUnmounted(() => {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer);
  }
});
</script>

<template>
  <div class="app-shell">
    <AppSidebar :active-page="activePage" @change="activePage = $event" />

    <main class="main-panel">
      <header class="topbar">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>本地轻量版 · 启信宝 / 天眼查 / 抖音线索 / 1688 / 中国制造网</p>
        </div>
        <div class="topbar-actions">
          <button class="icon-button" title="刷新数据" @click="refreshAll">
            <RefreshCw :size="17" />
          </button>
          <label class="switch-row">
            <input v-model="isPhoneMasked" type="checkbox" />
            <span>导出脱敏</span>
          </label>
          <label class="export-source-row">
            <span>采集路线</span>
            <select v-model="exportSourceGroup">
              <option
                v-for="sourceOption in exportSourceGroupOptions"
                :key="sourceOption.value"
                :value="sourceOption.value"
              >
                {{ sourceOption.label }}
              </option>
            </select>
          </label>
          <label class="export-industry-row">
            <span>行业</span>
            <select v-model="exportIndustry">
              <option v-for="industry in exportIndustryOptions" :key="industry || 'all'" :value="industry">
                {{ industry || '全部' }}
              </option>
            </select>
          </label>
          <label class="export-assignment-row">
            <span>分配</span>
            <select v-model="exportAssignmentStatus">
              <option
                v-for="statusOption in exportAssignmentStatusOptions"
                :key="statusOption.value || 'all'"
                :value="statusOption.value"
              >
                {{ statusOption.label }}
              </option>
            </select>
          </label>
          <button
            v-if="activePage === 'leads'"
            class="secondary-button"
            title="按当前线索库筛选、行业和分配状态导出"
            @click="exportCurrentModuleLead"
          >
            <Download :size="17" />
            当前模块
          </button>
          <button class="secondary-button" title="按采集路线、行业、分配状态和当前线索筛选导出" @click="exportSelectedAssignmentLead">
            <Download :size="17" />
            导出筛选
          </button>
          <button class="primary-button" title="按采集路线及当前筛选导出A/B高价值线索" @click="exportLead">
            <Download :size="17" />
            导出高价值
          </button>
        </div>
      </header>

      <section class="metric-grid">
        <MetricTile label="任务总数" :value="dashboard?.task_count ?? 0" tone="blue">
          <template #icon><ClipboardList :size="18" /></template>
        </MetricTile>
        <MetricTile label="线索总数" :value="dashboard?.lead_count ?? 0" tone="green">
          <template #icon><Database :size="18" /></template>
        </MetricTile>
        <MetricTile
          label="高价值线索"
          hint="本地线索评分：A≥80，B=60-79"
          :value="dashboard?.high_value_count ?? 0"
          tone="gold"
        >
          <template #icon><ListChecks :size="18" /></template>
        </MetricTile>
        <MetricTile label="今日额度使用" :value="`${qccUsagePercent}%`" tone="orange">
          <template #icon><KeyRound :size="18" /></template>
        </MetricTile>
      </section>

      <section v-if="activePage === 'tasks'" class="content-grid two-column">
        <TaskComposer
          :disabled="isLoading || hasActiveTask"
          :tasks="tasks"
          :usage-summary="usageSummary"
          @created="handleTaskCreated"
        />
        <TaskTable :tasks="tasks" @stop="stopActiveTask" />
      </section>

      <section v-if="activePage === 'leads'" class="content-grid">
        <div v-if="exportResult" class="export-strip">
          <span>已生成 {{ exportResult.total_count }} 条线索：</span>
          <a :href="buildDownloadUrl(exportResult.download_url)" target="_blank">{{ exportResult.file_name }}</a>
        </div>
        <LeadTable
          :filters="leadFilters"
          :leads="leads"
          :page="leadPage.page"
          :page-size="leadPage.page_size"
          :total="leadPage.total"
          @clear="clearLead"
          @filter="store.updateLeadFilters"
          @page="store.updateLeadPage"
        />
      </section>

      <section v-if="activePage === 'usage'" class="content-grid">
        <UsagePanel :setting="usageSetting" :summary="usageSummary" @save="store.saveUsageSetting" />
      </section>

      <section v-if="activePage === '1688-existence'" class="content-grid">
        <Alibaba1688ExistenceVerifier />
      </section>

      <section v-if="activePage === 'tianyancha-verification'" class="content-grid">
        <TianyanchaVerificationPanel />
      </section>

      <section v-if="activePage === 'qixin-verification'" class="content-grid">
        <QixinVerificationPanel />
      </section>

      <section v-if="activePage === 'logs'" class="content-grid">
        <LogPanel :events="taskEvents" />
      </section>

      <div v-if="isLoading" class="loading-bar">
        <Activity :size="16" />
        正在同步数据
      </div>
    </main>
  </div>
</template>
