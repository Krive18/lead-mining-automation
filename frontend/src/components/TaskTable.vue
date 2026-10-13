<script setup lang="ts">
import { computed } from 'vue';
import { Square } from 'lucide-vue-next';

import type { TaskRecord } from '../types';
import {
  formatSourceType,
  formatTaskName,
  formatTaskCount,
  formatTaskStatus,
  getTaskStagePercent,
  isActiveTaskStatus,
} from '../utils/format';

const props = defineProps<{
  tasks: TaskRecord[];
}>();

const emit = defineEmits<{
  stop: [];
}>();

const hasActiveTask = computed(() => props.tasks.some((task) => isActiveTaskStatus(task.status)));
</script>

<template>
  <div class="data-panel">
    <div class="panel-heading">
      <h2>最近任务</h2>
      <div class="panel-meta">
        <span>{{ tasks.length }} 个</span>
        <button
          class="danger-button panel-action-button"
          :disabled="!hasActiveTask"
          title="停止当前运行中的任务"
          type="button"
          @click="emit('stop')"
        >
          <Square :size="14" />
          停止任务
        </button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>方向</th>
            <th>状态</th>
            <th>数量</th>
            <th>成功</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.id">
            <td>
              <div class="strong-cell">{{ formatTaskName(task.task_name) }}</div>
              <small>{{ task.keyword_text }}</small>
            </td>
            <td>{{ formatSourceType(task.source_type) }}</td>
            <td class="task-stage-cell">
              <span class="status-pill" :data-status="task.status">{{ formatTaskStatus(task.status) }}</span>
              <div class="task-stage-track" :data-status="task.status">
                <span :style="{ width: `${getTaskStagePercent(task.status)}%` }" />
              </div>
            </td>
            <td>{{ formatTaskCount(task.status, task.total_count) }}</td>
            <td>{{ formatTaskCount(task.status, task.success_count) }}</td>
            <td>{{ task.gmt_create }}</td>
          </tr>
          <tr v-if="tasks.length === 0">
            <td colspan="6" class="empty-cell">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
