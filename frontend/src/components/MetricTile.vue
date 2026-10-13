<script setup lang="ts">
defineProps<{
  label: string;
  value: string | number;
  hint?: string;
  tone: 'blue' | 'green' | 'gold' | 'orange';
}>();
</script>

<template>
  <div class="metric-tile" :data-tone="tone">
    <div class="metric-icon">
      <slot name="icon" />
    </div>
    <div>
      <span>{{ label }}</span>
      <small v-if="hint">{{ hint }}</small>
      <strong>{{ value }}</strong>
    </div>
  </div>
</template>
