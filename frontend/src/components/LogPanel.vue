<script setup lang="ts">
import type { TaskEvent } from '../types';

defineProps<{
  events: TaskEvent[];
}>();
</script>

<template>
  <div class="data-panel">
    <div class="panel-heading">
      <h2>任务日志</h2>
      <span>{{ events.length }} 条</span>
    </div>
    <div class="event-list">
      <div v-for="event in events" :key="event.id" class="event-row">
        <span class="event-level" :data-level="event.event_level">{{ event.event_level }}</span>
        <span class="event-message">{{ event.event_message }}</span>
        <time>{{ event.gmt_create }}</time>
      </div>
      <div v-if="events.length === 0" class="empty-state">暂无日志</div>
    </div>
  </div>
</template>
