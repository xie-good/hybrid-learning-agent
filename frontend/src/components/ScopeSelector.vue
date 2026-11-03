<script setup>
import AppIcon from "./AppIcon.vue";
import { useWorkspace } from "../composables/useWorkspace.js";

// 三个学习页面共用章/节选择；只有问答页允许在全部课程中检索。
defineProps({ allowAll: Boolean });
const { chapters, chapterId, sectionId, selectedChapter, loading, busy } =
  useWorkspace();
</script>

<template>
  <div class="panel scope-panel">
    <div class="panel-title"><AppIcon name="book" /> 学习范围</div>
    <div class="form-grid">
      <label
        >选择章节<select v-model="chapterId" :disabled="loading || !!busy">
          <option v-if="allowAll" value="">全部课程</option>
          <option
            v-for="chapter in chapters"
            :key="chapter.chapter_id"
            :value="chapter.chapter_id"
          >
            {{ chapter.title }}
          </option>
        </select></label
      >
      <label
        >选择小节<select v-model="sectionId" :disabled="!chapterId || !!busy">
          <option value="">全部小节</option>
          <option
            v-for="section in selectedChapter?.sections || []"
            :key="section.section_id"
            :value="section.section_id"
          >
            {{ section.title }}
          </option>
        </select></label
      >
    </div>
  </div>
</template>
