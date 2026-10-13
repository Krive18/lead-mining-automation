<script setup lang="ts">
import { computed } from 'vue';
import { Search, Trash2 } from 'lucide-vue-next';

import type { LeadQueryParams, LeadRecord } from '../types';
import { formatSourceType, formatVerificationStatus, getVerificationStatusTitle } from '../utils/format';

const props = defineProps<{
  leads: LeadRecord[];
  total: number;
  page: number;
  pageSize: number;
  filters: LeadQueryParams;
}>();

const emit = defineEmits<{
  clear: [];
  filter: [payload: Partial<LeadQueryParams>];
  page: [page: number];
}>();

const sourceGroupDefinitionList = [
  { key: 'all', label: '全部线索' },
  { key: 'qixin', label: '启信宝' },
  { key: 'tianyancha', label: '天眼查' },
  { key: 'ai_web', label: 'AI 1688搜企' },
  { key: 'douyin', label: '抖音+企查查' },
  { key: 'alibaba_tianyancha', label: '1688采集' },
  { key: 'alibaba_international', label: '阿里国际站' },
  { key: 'made_in_china', label: '中国制造网+天眼查' },
  { key: 'alibaba', label: '1688普通页面' },
];

const cityOptionList = ['广州', '东莞', '佛山', '深圳', '中山', '惠州', '珠海', '汕头', '其他'];

const currentPage = computed(() => props.page || 1);
const pageSize = computed(() => props.pageSize || 50);
const pageCount = computed(() => Math.max(Math.ceil(props.total / pageSize.value), 1));
const pageStart = computed(() => (props.total === 0 ? 0 : (currentPage.value - 1) * pageSize.value + 1));
const pageEnd = computed(() => Math.min(currentPage.value * pageSize.value, props.total));

function updateKeyword(event: Event) {
  const target = event.target as HTMLInputElement;
  emit('filter', { keyword: target.value });
}

function updateAssignmentStatus(event: Event) {
  const target = event.target as HTMLSelectElement;
  emit('filter', { assignment_status: target.value });
}

function updateCity(event: Event) {
  const target = event.target as HTMLSelectElement;
  emit('filter', { city: target.value });
}

function updateSourceGroup(sourceGroup: string) {
  emit('filter', { source_group: sourceGroup });
}

function formatAssignmentStatus(status: string) {
  return status === 'assigned' ? '已分配' : '未分配';
}

function getDisplayCompanyName(lead: LeadRecord) {
  if (lead.source_type === 'alibaba_international') {
    return lead.company_name_en || lead.company_name || lead.suspected_company_name || '-';
  }
  return lead.company_name || lead.suspected_company_name || '-';
}

function getDisplayCompanySubtitle(lead: LeadRecord) {
  if (lead.source_type === 'alibaba_international') {
    return lead.company_name || lead.suspected_company_name;
  }
  return lead.suspected_company_name;
}
</script>

<template>
  <div class="data-panel">
    <div class="panel-heading lead-heading">
      <div>
        <h2>线索列表</h2>
        <span>按采集链路分模块管理，当前显示 {{ pageStart }}-{{ pageEnd }} / {{ total }} 条</span>
      </div>
      <button
        class="danger-button panel-action-button"
        :disabled="total === 0"
        title="清空全部线索库"
        type="button"
        @click="emit('clear')"
      >
        <Trash2 :size="15" />
        清空线索
      </button>
    </div>

    <div class="lead-source-tabs" role="tablist" aria-label="线索来源筛选">
      <button
        v-for="sourceGroup in sourceGroupDefinitionList"
        :key="sourceGroup.key"
        :class="{ active: (filters.source_group || 'all') === sourceGroup.key }"
        type="button"
        role="tab"
        :aria-selected="(filters.source_group || 'all') === sourceGroup.key"
        @click="updateSourceGroup(sourceGroup.key)"
      >
        <span>{{ sourceGroup.label }}</span>
      </button>
    </div>

    <div class="lead-filter-bar">
      <label class="lead-search-box">
        <Search :size="16" />
        <input
          :value="filters.keyword"
          placeholder="搜索公司、产品、电话或关键词"
          type="search"
          @change="updateKeyword"
          @keydown.enter.prevent="updateKeyword"
        />
      </label>
      <label class="compact-filter">
        <span>分发状态</span>
        <select :value="filters.assignment_status" @change="updateAssignmentStatus">
          <option value="">全部</option>
          <option value="unassigned">未分配</option>
          <option value="assigned">已分配</option>
        </select>
      </label>
      <label class="compact-filter">
        <span>城市</span>
        <select :value="filters.city" @change="updateCity">
          <option value="">全部</option>
          <option v-for="city in cityOptionList" :key="city" :value="city">{{ city }}</option>
        </select>
      </label>
    </div>

    <div class="table-wrap">
      <table class="lead-table">
        <thead>
          <tr>
            <th>线索等级</th>
            <th>评分</th>
            <th>分发</th>
            <th>公司</th>
            <th>城市</th>
            <th>企业地址</th>
            <th>统一社会信用代码</th>
            <th>行业</th>
            <th>产品</th>
            <th>店铺等级</th>
            <th>联系人</th>
            <th>电话</th>
            <th>来源</th>
            <th>核验</th>
            <th>风险</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lead in leads" :key="lead.id">
            <td><span class="level-badge" :data-level="lead.level">{{ lead.level }}</span></td>
            <td>{{ lead.score }}</td>
            <td>
              <span class="assignment-badge" :data-status="lead.assignment_status">
                {{ formatAssignmentStatus(lead.assignment_status) }}
              </span>
            </td>
            <td>
              <div class="strong-cell">{{ getDisplayCompanyName(lead) }}</div>
              <small>{{ getDisplayCompanySubtitle(lead) }}</small>
            </td>
            <td>
              <div>{{ lead.city || '待确认' }}</div>
              <small>{{ lead.district || lead.city_source }}</small>
            </td>
            <td class="wide-cell">{{ lead.registered_address || '-' }}</td>
            <td class="wide-cell">{{ lead.unified_social_credit_code || '-' }}</td>
            <td>{{ lead.industry }}</td>
            <td class="wide-cell">{{ lead.product_name }}</td>
            <td>{{ lead.shop_level || '-' }}</td>
            <td>
              <div>{{ lead.contact_name || lead.legal_person || '-' }}</div>
              <small v-if="lead.contact_name && lead.legal_person && lead.contact_name !== lead.legal_person">
                负责人：{{ lead.legal_person }}
              </small>
            </td>
            <td>
              <div>{{ lead.phone || '未公开' }}</div>
              <small>{{ lead.phone_source }}</small>
            </td>
            <td>
              <a v-if="lead.profile_url" :href="lead.profile_url" target="_blank">{{ formatSourceType(lead.source_type) }}</a>
              <span v-else>{{ formatSourceType(lead.source_type) }}</span>
              <small>{{ lead.source_keyword }}</small>
            </td>
            <td>
              <span
                class="verify-badge"
                :data-status="lead.verification_status"
                :title="getVerificationStatusTitle(lead.verification_status)"
              >
                {{ formatVerificationStatus(lead.verification_status) }}
              </span>
            </td>
            <td>{{ lead.risk_tag || '无' }}</td>
          </tr>
          <tr v-if="leads.length === 0">
            <td colspan="15" class="empty-cell">当前模块暂无线索</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="lead-pagination">
      <span>第 {{ currentPage }} / {{ pageCount }} 页</span>
      <div>
        <button class="secondary-button" :disabled="currentPage <= 1" type="button" @click="emit('page', currentPage - 1)">
          上一页
        </button>
        <button
          class="secondary-button"
          :disabled="currentPage >= pageCount"
          type="button"
          @click="emit('page', currentPage + 1)"
        >
          下一页
        </button>
      </div>
    </div>
  </div>
</template>
