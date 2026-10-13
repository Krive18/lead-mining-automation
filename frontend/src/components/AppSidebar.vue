<script setup lang="ts">
import { BadgeCheck, BarChart3, ClipboardList, Database, KeyRound, ScrollText, SearchCheck, ShieldCheck } from 'lucide-vue-next';

const props = defineProps<{
  activePage: string;
}>();

const emit = defineEmits<{
  change: [value: string];
}>();

const menuItems = [
  { key: 'tasks', label: '任务中心', icon: ClipboardList },
  { key: 'leads', label: '线索库', icon: Database },
  { key: '1688-existence', label: '1688反证', icon: SearchCheck },
  { key: 'tianyancha-verification', label: '天眼查反证', icon: ShieldCheck },
  { key: 'qixin-verification', label: '启信宝反证', icon: BadgeCheck },
  { key: 'usage', label: '额度管理', icon: KeyRound },
  { key: 'logs', label: '系统日志', icon: ScrollText },
];
</script>

<template>
  <aside class="sidebar">
    <div class="brand-row">
      <div class="brand-mark">
        <BarChart3 :size="20" />
      </div>
      <div>
        <strong>精准客户采集</strong>
        <span>Local Console</span>
      </div>
    </div>

    <nav class="side-nav">
      <button
        v-for="item in menuItems"
        :key="item.key"
        :class="{ active: props.activePage === item.key }"
        type="button"
        @click="emit('change', item.key)"
      >
        <component :is="item.icon" :size="17" />
        <span>{{ item.label }}</span>
      </button>
    </nav>
  </aside>
</template>
