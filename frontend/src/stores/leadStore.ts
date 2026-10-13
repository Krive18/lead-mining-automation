import { defineStore } from 'pinia';
import { reactive, ref } from 'vue';

import {
  clearLead as requestClearLead,
  createExport,
  getDashboard,
  getUsageSetting,
  getUsageSummary,
  listLead,
  listTask,
  listTaskEvent,
  stopActiveTask as requestStopActiveTask,
  updateUsageSetting,
} from '../api/client';
import type {
  DashboardData,
  ExportResult,
  LeadQueryParams,
  LeadRecord,
  QccUsageSummary,
  TaskEvent,
  TaskRecord,
  UsageSetting,
} from '../types';

export const useLeadStore = defineStore('leadStore', () => {
  const dashboard = ref<DashboardData | null>(null);
  const tasks = ref<TaskRecord[]>([]);
  const leads = ref<LeadRecord[]>([]);
  const leadPage = ref({ total: 0, page: 1, page_size: 50 });
  const leadFilters = reactive<LeadQueryParams>({
    source_group: 'all',
    keyword: '',
    city: '',
    assignment_status: '',
    page: 1,
    page_size: 50,
  });
  const usageSummary = ref<QccUsageSummary | null>(null);
  const usageSetting = ref<UsageSetting | null>(null);
  const taskEvents = ref<TaskEvent[]>([]);
  const exportResult = ref<ExportResult | null>(null);
  const isLoading = ref(false);
  const isRefreshing = ref(false);

  async function refreshAll(options: { silent?: boolean } = {}) {
    if (isRefreshing.value) {
      return;
    }
    isRefreshing.value = true;
    if (!options.silent) {
      isLoading.value = true;
    }
    try {
      const [dashboardResult, taskResult, leadResult, usageResult, settingResult, eventResult] = await Promise.all([
        getDashboard() as Promise<DashboardData>,
        listTask(),
        listLead(leadFilters),
        getUsageSummary(),
        getUsageSetting(),
        listTaskEvent(),
      ]);
      dashboard.value = dashboardResult;
      tasks.value = taskResult;
      leads.value = leadResult.items;
      leadPage.value = {
        total: leadResult.total,
        page: leadResult.page,
        page_size: leadResult.page_size,
      };
      usageSummary.value = usageResult;
      usageSetting.value = settingResult;
      taskEvents.value = eventResult;
    } finally {
      isRefreshing.value = false;
      if (!options.silent) {
        isLoading.value = false;
      }
    }
  }

  async function exportLead(levels: string[], isPhoneMasked: boolean, filters: LeadQueryParams = {}) {
    exportResult.value = await createExport({
      levels,
      is_phone_masked: isPhoneMasked,
      source_type: filters.source_type || '',
      source_group: filters.source_group || '',
      industry: filters.industry || '',
      keyword: filters.keyword || '',
      city: filters.city || '',
      assignment_status: filters.assignment_status || '',
    });
    await refreshAll();
  }

  async function saveUsageSetting(payload: UsageSetting) {
    usageSetting.value = await updateUsageSetting(payload);
    await refreshAll({ silent: true });
  }

  async function clearLead() {
    exportResult.value = null;
    await requestClearLead();
    leadFilters.page = 1;
    await refreshAll();
  }

  async function updateLeadFilters(payload: Partial<LeadQueryParams>) {
    Object.assign(leadFilters, payload);
    leadFilters.page = payload.page ?? 1;
    await refreshAll({ silent: true });
  }

  async function updateLeadPage(page: number) {
    leadFilters.page = page;
    await refreshAll({ silent: true });
  }

  async function stopActiveTask() {
    await requestStopActiveTask();
    await refreshAll();
  }

  return {
    dashboard,
    exportResult,
    isLoading,
    leadFilters,
    leadPage,
    leads,
    refreshAll,
    taskEvents,
    tasks,
    usageSummary,
    usageSetting,
    clearLead,
    exportLead,
    saveUsageSetting,
    stopActiveTask,
    updateLeadFilters,
    updateLeadPage,
  };
});
