<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { AlertTriangle, Gauge, ShieldCheck } from 'lucide-vue-next';

import type { QccUsageSummary, UsageSetting } from '../types';

type RiskLevel = 'safe' | 'watch' | 'warning' | 'critical';

interface RiskInfo {
  level: RiskLevel;
  label: string;
  advice: string;
  order: number;
}

const props = defineProps<{
  summary: QccUsageSummary | null;
  setting: UsageSetting | null;
}>();

const emit = defineEmits<{
  save: [value: UsageSetting];
}>();

const formData = reactive({
  daily_quota: 200,
  monthly_quota: 5000,
});

const riskMetaMap: Record<RiskLevel, RiskInfo> = {
  safe: {
    level: 'safe',
    label: '安全',
    advice: '额度充足，可以按当前采集节奏继续执行。',
    order: 1,
  },
  watch: {
    level: 'watch',
    label: '关注',
    advice: '额度开始进入消耗区，建议控制单次任务额度，优先核验高意向线索。',
    order: 2,
  },
  warning: {
    level: 'warning',
    label: '高风险',
    advice: '额度偏紧，建议降低本任务额度上限，或先充值/调高本地额度。',
    order: 3,
  },
  critical: {
    level: 'critical',
    label: '紧急',
    advice: '额度即将耗尽，建议暂停新任务，先处理充值或额度调整。',
    order: 4,
  },
};

watch(
  () => props.setting,
  (setting) => {
    if (!setting) {
      return;
    }
    formData.daily_quota = setting.daily_quota;
    formData.monthly_quota = setting.monthly_quota;
  },
  { immediate: true }
);

const dailyPercent = computed(() => {
  if (!props.summary || props.summary.daily_quota === 0) {
    return 0;
  }
  return Math.round((props.summary.daily_used / props.summary.daily_quota) * 100);
});

const monthlyPercent = computed(() => {
  if (!props.summary || props.summary.monthly_quota === 0) {
    return 0;
  }
  return Math.round((props.summary.monthly_used / props.summary.monthly_quota) * 100);
});

const dailyRisk = computed(() => {
  if (!props.summary) {
    return riskMetaMap.safe;
  }
  return getQuotaRisk(dailyPercent.value, props.summary.daily_remaining, 20, 5);
});

const monthlyRisk = computed(() => {
  if (!props.summary) {
    return riskMetaMap.safe;
  }
  return getQuotaRisk(monthlyPercent.value, props.summary.monthly_remaining, 100, 20);
});

const overallRisk = computed(() => {
  return dailyRisk.value.order >= monthlyRisk.value.order ? dailyRisk.value : monthlyRisk.value;
});

const overallRiskPercent = computed(() => clampPercent(Math.max(dailyPercent.value, monthlyPercent.value)));
const dailyMeterPercent = computed(() => clampPercent(dailyPercent.value));
const monthlyMeterPercent = computed(() => clampPercent(monthlyPercent.value));

function clampPercent(value: number) {
  return Math.min(Math.max(value, 0), 100);
}

function getQuotaRisk(
  percent: number,
  remaining: number,
  warningRemaining: number,
  criticalRemaining: number
) {
  if (percent >= 95 || remaining <= criticalRemaining) {
    return riskMetaMap.critical;
  }
  if (percent >= 80 || remaining <= warningRemaining) {
    return riskMetaMap.warning;
  }
  if (percent >= 60) {
    return riskMetaMap.watch;
  }
  return riskMetaMap.safe;
}

function saveSetting() {
  emit('save', {
    daily_quota: formData.daily_quota,
    monthly_quota: formData.monthly_quota,
  });
}
</script>

<template>
  <div class="usage-grid">
    <div class="data-panel quota-risk-panel" :data-risk="overallRisk.level">
      <div class="risk-hero">
        <div class="risk-icon">
          <ShieldCheck v-if="overallRisk.level === 'safe'" :size="22" />
          <AlertTriangle v-else :size="22" />
        </div>
        <div class="risk-title">
          <h2>启信宝额度风险仪表</h2>
          <p>按启信宝今日额度与本月额度中风险更高的一项判断。</p>
        </div>
        <div class="risk-state">
          <span>当前风险</span>
          <strong>{{ overallRisk.label }}</strong>
        </div>
      </div>

      <div class="risk-meter">
        <div class="risk-meter-head">
          <span>综合使用率</span>
          <strong>{{ overallRiskPercent }}%</strong>
        </div>
        <div class="risk-meter-bar">
          <span :style="{ width: `${overallRiskPercent}%` }" />
        </div>
        <div class="risk-scale">
          <span>安全</span>
          <span>关注</span>
          <span>高风险</span>
          <span>紧急</span>
        </div>
      </div>

      <div class="risk-card-grid">
        <div class="risk-card" :data-risk="dailyRisk.level">
          <div class="risk-card-head">
            <span>今日额度</span>
            <strong>{{ dailyRisk.label }}</strong>
          </div>
          <div class="risk-card-number">{{ dailyPercent }}%</div>
          <p>{{ summary?.daily_used ?? 0 }} / {{ summary?.daily_quota ?? 0 }}，剩余 {{ summary?.daily_remaining ?? 0 }} 次</p>
          <div class="mini-meter">
            <span :style="{ width: `${dailyMeterPercent}%` }" />
          </div>
        </div>
        <div class="risk-card" :data-risk="monthlyRisk.level">
          <div class="risk-card-head">
            <span>本月额度</span>
            <strong>{{ monthlyRisk.label }}</strong>
          </div>
          <div class="risk-card-number">{{ monthlyPercent }}%</div>
          <p>{{ summary?.monthly_used ?? 0 }} / {{ summary?.monthly_quota ?? 0 }}，剩余 {{ summary?.monthly_remaining ?? 0 }} 次</p>
          <div class="mini-meter">
            <span :style="{ width: `${monthlyMeterPercent}%` }" />
          </div>
        </div>
      </div>

      <div class="risk-advice">
        <Gauge :size="16" />
        <span>{{ overallRisk.advice }}</span>
      </div>
    </div>

    <form class="data-panel usage-setting-panel" @submit.prevent="saveSetting">
      <div class="panel-heading">
        <h2>额度上限设置</h2>
        <span>本地保护阈值</span>
      </div>
      <div class="usage-setting-grid">
        <label>
          <span>今日额度上限</span>
          <input v-model.number="formData.daily_quota" min="1" max="1000000" type="number" />
        </label>
        <label>
          <span>本月额度上限</span>
          <input v-model.number="formData.monthly_quota" min="1" max="10000000" type="number" />
        </label>
        <button class="primary-button" type="submit">保存额度</button>
      </div>
    </form>

    <div class="data-panel usage-log-panel">
      <div class="panel-heading">
        <h2>最近调用</h2>
        <span>{{ summary?.recent_usage.length ?? 0 }} 条</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>企业</th>
              <th>接口</th>
              <th>消耗</th>
              <th>状态</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in summary?.recent_usage ?? []" :key="item.id">
              <td>{{ item.company_name }}</td>
              <td>{{ item.interface_name }}</td>
              <td>{{ item.consume_count }}</td>
              <td>{{ item.is_success ? '成功' : '失败' }}</td>
              <td>{{ item.gmt_create }}</td>
            </tr>
            <tr v-if="!summary || summary.recent_usage.length === 0">
              <td colspan="5" class="empty-cell">暂无调用记录</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
