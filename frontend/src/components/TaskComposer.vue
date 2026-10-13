<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { Play, RefreshCw, SearchCheck, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-vue-next';

import {
  createAiLeadDiscoveryTask,
  createBatchAutomation,
  createQixinEnrichmentTask,
  createTask,
  createTianyanchaEnrichmentTask,
  getQixinApiStatus,
  warmupAlibaba1688Browser,
  warmupMadeInChinaBrowser,
  warmupTianyanchaBrowser,
} from '../api/client';
import type { QccUsageSummary, QixinApiStatus, TaskRecord } from '../types';

const props = defineProps<{
  disabled: boolean;
  tasks: TaskRecord[];
  usageSummary: QccUsageSummary | null;
}>();

const emit = defineEmits<{
  created: [];
}>();

const formData = reactive({
  source_type: 'alibaba_1688',
  industry: '服装',
  keyword_text: '',
  target_city: '广东省',
  target_city_list: ['广东省'] as string[],
  collect_limit: 30,
  is_qcc_enabled: false,
  qcc_limit: 0,
});

const batchAutomationData = reactive({
  batch_count: 8,
});

const tianyanchaEnrichmentData = reactive({
  provider: 'tianyancha',
  task_id: '',
  limit: 20,
  pacing_mode: 'conservative',
});

const isWarmupStarting = ref(false);
const isAiTaskSubmitting = ref(false);
const isTaskSubmitting = ref(false);
const isBatchAutomationSubmitting = ref(false);
const isTianyanchaEnrichmentSubmitting = ref(false);
const isQixinStatusLoading = ref(false);
const warmupMessage = ref('');
const qixinApiStatus = ref<QixinApiStatus | null>(null);
const qixinApiStatusError = ref('');

const batchAutomationCollectLimit = 10;
const batchAutomationCooldownSeconds = 90;
const tianyanchaEnrichmentPacingOptionList = [
  { value: 'conservative', label: '保守模式', hint: '5条/批，约3分钟冷却，默认更稳' },
  { value: 'standard', label: '标准模式', hint: '10条/批，约90秒冷却' },
  { value: 'manual', label: '人工接管', hint: '3条/批，约4分钟冷却，适合刚触发过验证' },
];
const enrichmentProviderOptionList = [
  { value: 'tianyancha', label: '天眼查', hint: '使用浏览器公开页补全联系人、法人、电话和企业地址。' },
  { value: 'qixin', label: '启信宝API', hint: '通过1.41工商照面、1.51企业联系方式和1.43工商股东接口补全所选1688批次。' },
];

const industryKeywordMap: Record<string, string> = {
  服装: '服装工厂,女装批发,服装OEM,跨境服装',
  '3C数码': '3C批发,手机壳工厂,数据线厂家,跨境3C',
  美妆个护: '化妆品工厂,护肤品OEM,彩妆代工,美妆供应链',
  其他: '',
};

const publicWebSourceTypeList = [
  'qixin_public_web',
  'tianyancha_public_web',
  'ai_web_search',
  'douyin_qcc',
  'alibaba_1688',
  'alibaba_international',
  'made_in_china_tianyancha',
];

const sourceButtonList = [
  { value: 'qixin_public_web', label: '启信宝' },
  { value: 'tianyancha_public_web', label: '天眼查' },
  { value: 'ai_web_search', label: 'AI 1688搜企' },
  { value: 'douyin_qcc', label: '抖音线索' },
  { value: 'alibaba_1688', label: '1688采集' },
  { value: 'alibaba_international', label: '阿里国际站采集' },
  { value: 'made_in_china_tianyancha', label: '中国制造网 + 天眼查' },
];

const guangdongCityOptionList = [
  '广东省',
  '广州市',
  '深圳市',
  '珠海市',
  '汕头市',
  '佛山市',
  '韶关市',
  '湛江市',
  '肇庆市',
  '江门市',
  '茂名市',
  '惠州市',
  '梅州市',
  '汕尾市',
  '河源市',
  '阳江市',
  '清远市',
  '东莞市',
  '中山市',
  '潮州市',
  '揭阳市',
  '云浮市',
];

const qccRemaining = computed(() => {
  if (!props.usageSummary) {
    return 0;
  }
  return Math.min(props.usageSummary.daily_remaining, props.usageSummary.monthly_remaining);
});

const isPublicWebSource = computed(() => publicWebSourceTypeList.includes(formData.source_type));
const isTianyanchaSource = computed(() => formData.source_type === 'tianyancha_public_web');
const isAlibaba1688Source = computed(() => formData.source_type === 'alibaba_1688');
const isAlibabaInternationalSource = computed(() => formData.source_type === 'alibaba_international');
const isMadeInChinaSource = computed(() => formData.source_type === 'made_in_china_tianyancha');
const usesGuangdongTargetCity = computed(() => isAlibaba1688Source.value || isAlibabaInternationalSource.value);
const usesMultiGuangdongTargetCity = computed(() => isAlibaba1688Source.value || isAlibabaInternationalSource.value);
const isOtherIndustry = computed(() => formData.industry === '其他');
const isKeywordMissing = computed(() => splitKeywords(formData.keyword_text).length === 0);
const isAlibabaInternationalKeywordInvalid = computed(() => {
  return isAlibabaInternationalSource.value && splitKeywords(formData.keyword_text).some(hasChineseText);
});
const canWarmupBrowser = computed(() => isTianyanchaSource.value || isAlibaba1688Source.value || isMadeInChinaSource.value);
const alibaba1688TaskOptionList = computed(() => {
  return props.tasks
    .filter((task) => task.source_type === 'alibaba_1688' && Number(task.total_count || task.success_count || 0) > 0)
    .slice(0, 40);
});
const selectedTianyanchaEnrichmentTask = computed(() => {
  return alibaba1688TaskOptionList.value.find((task) => task.id === tianyanchaEnrichmentData.task_id) ?? null;
});
const selectedTianyanchaEnrichmentPacing = computed(() => {
  return (
    tianyanchaEnrichmentPacingOptionList.find((item) => item.value === tianyanchaEnrichmentData.pacing_mode) ??
    tianyanchaEnrichmentPacingOptionList[0]
  );
});
const selectedEnrichmentProvider = computed(() => {
  return (
    enrichmentProviderOptionList.find((item) => item.value === tianyanchaEnrichmentData.provider) ??
    enrichmentProviderOptionList[0]
  );
});
const enrichmentProviderName = computed(() => selectedEnrichmentProvider.value.label);
const qixinApiStatusText = computed(() => {
  if (isQixinStatusLoading.value) {
    return '正在检查启信宝配置和当前出口 IP...';
  }
  if (qixinApiStatusError.value) {
    return qixinApiStatusError.value;
  }
  if (!qixinApiStatus.value?.configured) {
    return '启信宝 API 密钥未配置，暂时不能启动补全。';
  }
  if (!qixinApiStatus.value.egress_ip) {
    return qixinApiStatus.value.message || '已配置启信宝 API，但未能识别当前出口 IP。';
  }
  const region = qixinApiStatus.value.egress_region ? `（${qixinApiStatus.value.egress_region}）` : '';
  return `当前启信宝出口 IP：${qixinApiStatus.value.egress_ip}${region}；请确认该 IP 已加入启信宝白名单。`;
});
const isQixinStatusWarning = computed(() => Boolean(qixinApiStatusError.value) || !qixinApiStatus.value?.configured);
const tianyanchaEnrichmentPacingHintText = computed(() => {
  if (tianyanchaEnrichmentData.provider === 'qixin') {
    return selectedEnrichmentProvider.value.hint;
  }
  return selectedTianyanchaEnrichmentPacing.value.hint;
});
const tianyanchaEnrichmentHintText = computed(() => {
  const task = selectedTianyanchaEnrichmentTask.value;
  const limit = Math.max(1, Math.min(300, tianyanchaEnrichmentData.limit || 1));
  if (!task) {
    return `请选择要补全的1688采集批次，本次只会处理所选批次里的未补全${enrichmentProviderName.value}线索。`;
  }
  const savedCount = Number(task.success_count || task.total_count || 0);
  return `${task.gmt_create} 创建，已保存 ${savedCount} 条；本次最多用${enrichmentProviderName.value}补全该批次中的 ${limit} 条。`;
});

const warmupButtonText = computed(() => {
  if (isWarmupStarting.value) {
    return '正在打开预登录浏览器';
  }
  if (isAlibaba1688Source.value) {
    return '预登录1688';
  }
  if (isMadeInChinaSource.value) {
    return '预登录中国制造网';
  }
  return '预热天眼查验证';
});

const aiLeadDiscoveryButtonText = computed(() => {
  if (props.disabled) {
    return '任务运行中';
  }
  if (isAiTaskSubmitting.value) {
    return 'AI正在生成采集策略';
  }
  if (formData.source_type === 'ai_web_search') {
    return 'AI 1688找广东企业';
  }
  return 'AI智能线索发现';
});

const keywordPlaceholder = computed(() => {
  if (isAlibabaInternationalSource.value) {
    return 'English keywords only, e.g. garment steamer, game controller';
  }
  if (isAlibaba1688Source.value) {
    return '请输入你自己的产品关键词，多个用逗号分隔，例如 蓝牙耳机,数据线';
  }
  if (isOtherIndustry.value) {
    return '请输入产品关键词，多个用逗号分隔';
  }
  return industryKeywordMap[formData.industry] ?? '';
});

const selectedTargetCityText = computed(() => {
  if (!usesMultiGuangdongTargetCity.value) {
    return formData.target_city || '广东省';
  }
  return formData.target_city_list.length > 0 ? formData.target_city_list.join('、') : '广东省';
});

const keywordGuideText = computed(() => {
  if (formData.source_type === 'qcc_public_web') {
    return '企业公开页采集适合使用“地区 + 品类 + 经营形态”的关键词。';
  }
  if (['qixin_public_web', 'tianyancha_public_web'].includes(formData.source_type)) {
    return '企业信息公开页只采集页面可见字段，登录或验证需要人工处理。';
  }
  if (formData.source_type === 'ai_web_search') {
    return 'AI只查询搜索引擎已收录的1688公开摘要，不自动进入1688页面；候选入库后再用天眼查补全联系人和电话。';
  }
  if (formData.source_type === 'alibaba_1688') {
    return `按你选择的“${selectedTargetCityText.value}”和你输入的关键词逐个采集1688公开企业线索；不自动扩写关键词，不自动跳转天眼查，产品小类目读不到也会保留企业。`;
  }
  if (formData.source_type === 'alibaba_international') {
    if (isAlibabaInternationalKeywordInvalid.value) {
      return '阿里国际站请使用英文产品关键词，例如 garment steamer、game controller；中文关键词会降低搜索精准性，已禁止提交。';
    }
    return `按“${selectedTargetCityText.value} + 英文产品关键词”采集阿里国际站供应商列表页，仅保存英文公司名、主营小类目和平台店铺等级，不进入详情页。`;
  }
  if (formData.source_type === 'made_in_china_tianyancha') {
    return '先在中国制造网按产品词采集华南/广东企业名，再回到天眼查精准匹配法人、电话和企业信息。';
  }
  return '先读取公开账号/视频线索，再用企业公开页补充核验。';
});

const plannedQccUsage = computed(() => {
  if (!formData.is_qcc_enabled || isPublicWebSource.value) {
    return 0;
  }
  return Math.min(formData.collect_limit, formData.qcc_limit);
});

const isQuotaInsufficient = computed(() => {
  return formData.is_qcc_enabled && plannedQccUsage.value > qccRemaining.value;
});

const batchAutomationTotalCount = computed(() => {
  return Math.max(1, batchAutomationData.batch_count || 1) * batchAutomationCollectLimit;
});

const batchAutomationQccUsage = computed(() => {
  if (!formData.is_qcc_enabled || isPublicWebSource.value) {
    return 0;
  }
  return Math.min(batchAutomationCollectLimit, formData.qcc_limit) * Math.max(1, batchAutomationData.batch_count || 1);
});

const isBatchAutomationQuotaInsufficient = computed(() => {
  return formData.is_qcc_enabled && batchAutomationQccUsage.value > qccRemaining.value;
});

const batchAutomationHintText = computed(() => {
  if (isAlibaba1688Source.value || isAlibabaInternationalSource.value) {
    return `自动化目标：${Math.max(1, batchAutomationData.batch_count || 1)} 批 × ${batchAutomationCollectLimit} 条；每批至少间隔 ${batchAutomationCooldownSeconds} 秒并加入随机抖动，已抓结果会逐批保存。`;
  }
  return `自动化目标：${Math.max(1, batchAutomationData.batch_count || 1)} 轮 × ${batchAutomationCollectLimit} 条，间隔 ${batchAutomationCooldownSeconds} 秒，目标新增 ${batchAutomationTotalCount.value} 条；AI 1688搜企会按有效新增自动补采。`;
});

const quotaHintText = computed(() => {
  if (formData.source_type === 'douyin_qcc') {
    return '抖音公开页采集后会用企业公开页核验，不消耗接口额度。';
  }
  if (isPublicWebSource.value) {
    return '公开页采集不调用 API，不消耗接口额度。';
  }
  if (!formData.is_qcc_enabled) {
    return '本任务不调用企业信息核验，不消耗核验额度。';
  }
  return `预计消耗 ${plannedQccUsage.value} 次，当前可用 ${qccRemaining.value} 次。`;
});

watch(
  () => formData.industry,
  (industry) => {
    if (formData.source_type === 'alibaba_international') {
      formData.keyword_text = '';
      return;
    }
    if (formData.source_type === 'alibaba_1688') {
      if (isIndustryDefaultKeywordText(formData.keyword_text)) {
        formData.keyword_text = '';
      }
      return;
    }
    formData.keyword_text = industryKeywordMap[industry] ?? '';
  }
);

watch(
  () => formData.source_type,
  (sourceType) => {
    warmupMessage.value = '';
    if (publicWebSourceTypeList.includes(sourceType)) {
      formData.is_qcc_enabled = false;
      formData.qcc_limit = 0;
      if (sourceType === 'alibaba_1688' || sourceType === 'alibaba_international') {
        ensureGuangdongTargetCityList();
      }
      if (sourceType === 'alibaba_1688') {
        if (isIndustryDefaultKeywordText(formData.keyword_text)) {
          formData.keyword_text = '';
        }
      }
      if (sourceType === 'alibaba_international' && hasChineseText(formData.keyword_text)) {
        formData.keyword_text = '';
      }
      if (sourceType !== 'alibaba_international' && sourceType !== 'alibaba_1688' && !formData.keyword_text.trim()) {
        formData.keyword_text = industryKeywordMap[formData.industry] ?? '';
      }
      return;
    }
    formData.is_qcc_enabled = true;
    formData.qcc_limit = Math.min(formData.collect_limit, 20);
  }
);

watch(
  alibaba1688TaskOptionList,
  (taskList) => {
    if (taskList.some((task) => task.id === tianyanchaEnrichmentData.task_id)) {
      return;
    }
    tianyanchaEnrichmentData.task_id = taskList[0]?.id ?? '';
  },
  { immediate: true }
);

watch(
  () => tianyanchaEnrichmentData.provider,
  (provider) => {
    if (provider === 'qixin') {
      void loadQixinApiStatus();
    }
  },
  { immediate: true }
);

async function loadQixinApiStatus() {
  if (isQixinStatusLoading.value) {
    return;
  }
  isQixinStatusLoading.value = true;
  qixinApiStatusError.value = '';
  try {
    qixinApiStatus.value = await getQixinApiStatus();
  } catch (error) {
    qixinApiStatus.value = null;
    qixinApiStatusError.value = error instanceof Error ? error.message : '无法读取启信宝 API 状态。';
  } finally {
    isQixinStatusLoading.value = false;
  }
}

function splitKeywords(value: string) {
  return value
    .split(/[,，、\n\r]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isIndustryDefaultKeywordText(value: string) {
  const cleanValue = value.trim();
  return Object.values(industryKeywordMap).some((keywordText) => keywordText && keywordText === cleanValue);
}

function hasChineseText(value: string) {
  return /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(value);
}

function ensureGuangdongTargetCityList() {
  if (formData.target_city_list.length === 0) {
    formData.target_city_list = ['广东省'];
  }
  formData.target_city = formData.target_city_list.join(',');
}

function isTargetCitySelected(city: string) {
  return formData.target_city_list.includes(city);
}

function toggleTargetCity(city: string) {
  if (city === '广东省') {
    formData.target_city_list = ['广东省'];
    formData.target_city = '广东省';
    return;
  }
  const nextCityList = formData.target_city_list.filter((item) => item !== '广东省' && item !== city);
  if (!formData.target_city_list.includes(city)) {
    nextCityList.push(city);
  }
  formData.target_city_list = nextCityList.length > 0 ? nextCityList : ['广东省'];
  formData.target_city = formData.target_city_list.join(',');
}

function getTargetCityPayload() {
  if (!usesMultiGuangdongTargetCity.value) {
    return formData.target_city;
  }
  ensureGuangdongTargetCityList();
  return formData.target_city_list.join(',');
}

async function submitAiLeadDiscoveryTask() {
  if (isAiTaskSubmitting.value) {
    return;
  }
  isAiTaskSubmitting.value = true;
  try {
    await createAiLeadDiscoveryTask({
      source_type: formData.source_type,
      industry: formData.industry,
      keywords: splitKeywords(formData.keyword_text),
      target_city: getTargetCityPayload(),
      collect_limit: formData.collect_limit,
      is_qcc_enabled: formData.is_qcc_enabled,
      qcc_limit: formData.qcc_limit,
    });
    emit('created');
  } catch (error) {
    window.alert(error instanceof Error ? error.message : 'AI智能线索发现任务创建失败，请查看系统日志。');
  } finally {
    isAiTaskSubmitting.value = false;
  }
}

async function submitTask() {
  if (isTaskSubmitting.value) {
    return;
  }
  isTaskSubmitting.value = true;
  try {
    await createTask({
      source_type: formData.source_type,
      industry: formData.industry,
      keywords: splitKeywords(formData.keyword_text),
      target_city: getTargetCityPayload(),
      collect_limit: formData.collect_limit,
      is_qcc_enabled: formData.is_qcc_enabled,
      qcc_limit: formData.qcc_limit,
    });
    emit('created');
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '任务创建失败，请查看系统日志。');
  } finally {
    isTaskSubmitting.value = false;
  }
}

async function submitBatchAutomation() {
  if (isBatchAutomationSubmitting.value) {
    return;
  }
  isBatchAutomationSubmitting.value = true;
  try {
    await createBatchAutomation({
      source_type: formData.source_type,
      industry: formData.industry,
      keywords: splitKeywords(formData.keyword_text),
      target_city: getTargetCityPayload(),
      collect_limit: batchAutomationCollectLimit,
      is_qcc_enabled: formData.is_qcc_enabled,
      qcc_limit: Math.min(formData.qcc_limit, batchAutomationCollectLimit),
      batch_count: Math.max(1, batchAutomationData.batch_count || 1),
      batch_collect_limit: batchAutomationCollectLimit,
      cooldown_seconds: batchAutomationCooldownSeconds,
    });
    emit('created');
  } catch (error) {
    window.alert(error instanceof Error ? error.message : '自动化任务启动失败，请查看系统日志。');
  } finally {
    isBatchAutomationSubmitting.value = false;
  }
}

async function submitTianyanchaEnrichmentTask() {
  if (isTianyanchaEnrichmentSubmitting.value) {
    return;
  }
  if (!tianyanchaEnrichmentData.task_id) {
    window.alert('请先选择要补全的1688采集批次。');
    return;
  }
  isTianyanchaEnrichmentSubmitting.value = true;
  try {
    if (tianyanchaEnrichmentData.provider === 'qixin') {
      await loadQixinApiStatus();
    }
    const createEnrichmentTask =
      tianyanchaEnrichmentData.provider === 'qixin' ? createQixinEnrichmentTask : createTianyanchaEnrichmentTask;
    await createEnrichmentTask({
      task_id: tianyanchaEnrichmentData.task_id,
      limit: Math.max(1, Math.min(300, tianyanchaEnrichmentData.limit || 1)),
      pacing_mode: tianyanchaEnrichmentData.pacing_mode,
    });
    emit('created');
  } catch (error) {
    window.alert(error instanceof Error ? error.message : `${enrichmentProviderName.value}补全任务启动失败，请查看系统日志。`);
  } finally {
    isTianyanchaEnrichmentSubmitting.value = false;
  }
}

async function startBrowserWarmup() {
  isWarmupStarting.value = true;
  warmupMessage.value = '';
  try {
    let result;
    if (isAlibaba1688Source.value) {
      result = await warmupAlibaba1688Browser();
    } else if (isMadeInChinaSource.value) {
      result = await warmupMadeInChinaBrowser();
    } else {
      result = await warmupTianyanchaBrowser();
    }
    warmupMessage.value = result.message;
  } catch (error) {
    const message = error instanceof Error ? error.message : '预登录浏览器启动失败。';
    warmupMessage.value = message;
    window.alert(message);
  } finally {
    isWarmupStarting.value = false;
  }
}
</script>

<template>
  <form class="data-panel task-form" @submit.prevent="submitTask">
    <div class="panel-heading">
      <h2>新建采集任务</h2>
      <SlidersHorizontal :size="17" />
    </div>

    <label>
      <span>采集方向</span>
      <div class="segmented">
        <button
          v-for="sourceButton in sourceButtonList"
          :key="sourceButton.value"
          :class="{ active: formData.source_type === sourceButton.value }"
          type="button"
          @click="formData.source_type = sourceButton.value"
        >
          {{ sourceButton.label }}
        </button>
      </div>
    </label>

    <div class="form-grid">
      <label>
        <span>行业</span>
        <select v-model="formData.industry">
          <option>服装</option>
          <option>3C数码</option>
          <option>美妆个护</option>
          <option>其他</option>
        </select>
      </label>
      <label>
        <span>采集数量</span>
        <input v-model.number="formData.collect_limit" min="1" max="1200" type="number" />
      </label>
    </div>

    <div v-if="usesMultiGuangdongTargetCity" class="field-block">
      <span class="field-label">广东地区（可多选）</span>
      <div class="city-option-grid">
        <label
          v-for="city in guangdongCityOptionList"
          :key="city"
          class="city-option"
          :class="{ active: isTargetCitySelected(city) }"
        >
          <input
            :checked="isTargetCitySelected(city)"
            type="checkbox"
            @change="toggleTargetCity(city)"
          />
          <span>{{ city }}</span>
        </label>
      </div>
    </div>

    <label v-else-if="usesGuangdongTargetCity">
      <span>广东地区</span>
      <select v-model="formData.target_city">
        <option v-for="city in guangdongCityOptionList" :key="city" :value="city">{{ city }}</option>
      </select>
    </label>

    <label>
      <span>关键词</span>
      <textarea v-model="formData.keyword_text" :placeholder="keywordPlaceholder" rows="4" />
    </label>
    <div class="keyword-guide">{{ keywordGuideText }}</div>

    <button
      v-if="canWarmupBrowser"
      class="secondary-button full-width"
      :disabled="props.disabled || isWarmupStarting"
      type="button"
      @click="startBrowserWarmup"
    >
      <ShieldCheck :size="17" />
      {{ warmupButtonText }}
    </button>
    <div v-if="warmupMessage" class="quota-hint">{{ warmupMessage }}</div>

    <div class="form-grid">
      <label class="check-row">
        <input v-model="formData.is_qcc_enabled" :disabled="isPublicWebSource" type="checkbox" />
        <span>调用企业信息核验</span>
      </label>
      <label>
        <span>本任务额度上限</span>
        <input v-model.number="formData.qcc_limit" :disabled="isPublicWebSource" min="0" max="1200" type="number" />
      </label>
    </div>

    <div class="quota-hint" :data-warning="isQuotaInsufficient">
      {{ quotaHintText }}
      <span v-if="isQuotaInsufficient">请降低本任务额度上限，或先充值/调高本地额度。</span>
    </div>

    <div class="automation-section">
      <div class="form-grid automation-grid">
        <label>
          <span>补全渠道</span>
          <select v-model="tianyanchaEnrichmentData.provider">
            <option v-for="option in enrichmentProviderOptionList" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
        <label>
          <span>补全数量</span>
          <input v-model.number="tianyanchaEnrichmentData.limit" min="1" max="300" type="number" />
        </label>
        <label>
          <span>补全批次</span>
          <select v-model="tianyanchaEnrichmentData.task_id">
            <option disabled value="">请选择1688任务</option>
            <option v-for="task in alibaba1688TaskOptionList" :key="task.id" :value="task.id">
              {{ task.gmt_create }} · {{ task.industry }} · {{ task.success_count || task.total_count || 0 }}条
            </option>
          </select>
        </label>
        <label v-if="tianyanchaEnrichmentData.provider !== 'qixin'">
          <span>补全节奏</span>
          <select v-model="tianyanchaEnrichmentData.pacing_mode">
            <option v-for="option in tianyanchaEnrichmentPacingOptionList" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>
      </div>
      <div class="quota-hint">{{ tianyanchaEnrichmentHintText }}</div>
      <div class="quota-hint">{{ tianyanchaEnrichmentPacingHintText }}</div>
      <div
        v-if="tianyanchaEnrichmentData.provider === 'qixin'"
        class="quota-hint qixin-status-row"
        :data-warning="isQixinStatusWarning"
      >
        <span>{{ qixinApiStatusText }}</span>
        <button
          class="icon-button"
          :disabled="isQixinStatusLoading"
          title="刷新启信宝出口 IP"
          type="button"
          @click="loadQixinApiStatus"
        >
          <RefreshCw :class="{ spinning: isQixinStatusLoading }" :size="16" />
        </button>
      </div>
      <button
        class="secondary-button full-width"
        :disabled="props.disabled || !tianyanchaEnrichmentData.task_id || isTianyanchaEnrichmentSubmitting || isAiTaskSubmitting || isTaskSubmitting || isBatchAutomationSubmitting"
        type="button"
        @click="submitTianyanchaEnrichmentTask"
      >
        <SearchCheck :size="17" />
        {{ isTianyanchaEnrichmentSubmitting ? `正在启动${enrichmentProviderName}补全` : `补全${enrichmentProviderName}信息` }}
      </button>
    </div>

    <button
      class="secondary-button full-width"
      :disabled="props.disabled || isKeywordMissing || isAlibabaInternationalKeywordInvalid || isQuotaInsufficient || isAiTaskSubmitting || isTaskSubmitting || isBatchAutomationSubmitting || isTianyanchaEnrichmentSubmitting"
      type="button"
      @click="submitAiLeadDiscoveryTask"
    >
      <Sparkles :size="17" />
      {{ aiLeadDiscoveryButtonText }}
    </button>

    <div class="automation-section">
      <div class="form-grid automation-grid">
        <label>
          <span>自动化轮数</span>
          <input v-model.number="batchAutomationData.batch_count" min="1" max="100" type="number" />
        </label>
        <label>
          <span>每轮数量</span>
          <input :value="batchAutomationCollectLimit" disabled type="number" />
        </label>
      </div>

      <div class="quota-hint" :data-warning="isBatchAutomationQuotaInsufficient">
        {{ batchAutomationHintText }}
        <span v-if="isBatchAutomationQuotaInsufficient">启信宝额度不足，请降低自动化轮数或额度上限。</span>
      </div>

      <button
        class="primary-button full-width"
        :disabled="props.disabled || isKeywordMissing || isAlibabaInternationalKeywordInvalid || isQuotaInsufficient || isBatchAutomationQuotaInsufficient || isBatchAutomationSubmitting || isTaskSubmitting || isAiTaskSubmitting || isTianyanchaEnrichmentSubmitting"
        type="button"
        @click="submitBatchAutomation"
      >
        <Play :size="17" />
        {{ props.disabled ? '任务运行中' : isBatchAutomationSubmitting ? '正在启动自动化' : '开启自动化任务' }}
      </button>
    </div>

    <button
      class="secondary-button full-width"
      :disabled="props.disabled || isKeywordMissing || isAlibabaInternationalKeywordInvalid || isQuotaInsufficient || isTaskSubmitting || isBatchAutomationSubmitting || isAiTaskSubmitting || isTianyanchaEnrichmentSubmitting"
      type="submit"
    >
      <Play :size="17" />
      {{ props.disabled ? '任务运行中' : isTaskSubmitting ? '正在创建单次任务' : '启动单次任务' }}
    </button>
  </form>
</template>
