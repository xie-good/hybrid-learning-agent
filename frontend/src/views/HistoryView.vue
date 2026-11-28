<script setup>
// 问答历史页负责分页回看、单条删除确认与清空会话历史；数据来自共享工作区。
import { onActivated, ref } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import { dateLabel, modeLabel, parseAnswerBlocks } from "../lib/presentation.js";

const {
  activeTask,
  noticeMessage,
  runTask,
  currentSessionId,
  historyResult,
  historyOffset,
  isHistoryLoading,
  loadHistory,
  historyClearCount,
  navigate,
} = useWorkspace();

const isClearHistoryConfirmed = ref(false);
const pendingDeleteHistoryId = ref(null);

// KeepAlive 切回历史页时重新拉取一次，确保显示最新问答记录。
onActivated(loadHistory);

function requestDelete(historyId) {
  // 第一次点击仅标记待删除，第二次点击才发送删除请求，防止误点。
  if (pendingDeleteHistoryId.value !== historyId) {
    pendingDeleteHistoryId.value = historyId;
    return;
  }
  pendingDeleteHistoryId.value = null;
  runTask("delete", async () => {
    const encodedId = encodeURIComponent(historyId);
    await request(`/history/${encodedId}?session_id=${currentSessionId}`, {
      method: "DELETE",
    });
    if (historyResult.value.items.length === 1 && historyOffset.value > 0) {
      historyOffset.value -= 10;
    }
    await loadHistory();
    noticeMessage.value = "该问答记录已删除。";
  });
}

function clearHistory() {
  runTask("delete", async () => {
    await request(`/history?session_id=${currentSessionId}`, { method: "DELETE" });
    historyOffset.value = 0;
    isClearHistoryConfirmed.value = false;
    historyClearCount.value += 1;
    await loadHistory();
    noticeMessage.value = "当前会话的问答记录已清空。";
  });
}

function changeHistoryPage(pageDelta) {
  historyOffset.value += pageDelta * 10;
  loadHistory();
}
</script>

<template>
  <section class="panel history-toolbar">
    <div>
      <h3>
        本次会话的问答历史
        <span class="pill">{{ historyResult.total }} 条</span>
      </h3>
      <p>保留当前标签页下的提问、检索模式与原文引用记录。</p>
    </div>
    <button
      class="button secondary"
      :disabled="isHistoryLoading || !!activeTask"
      @click="loadHistory"
    >
      <AppIcon name="refresh" :size="16" /> 刷新记录
    </button>
  </section>

  <div v-if="isHistoryLoading" class="empty-state" role="status">
    <span class="spinner"></span>正在读取会话记录…
  </div>

  <section v-else-if="!historyResult.items.length" class="panel empty-state">
    <span class="placeholder-symbol"><AppIcon name="history" :size="32" /></span>
    <h3>每一次思考，都值得留下</h3>
    <p>向知识库提出第一个问题，你的问答足迹就会出现在这里。</p>
    <a class="button primary" :href="'#qa'" @click.exact.prevent="navigate('qa')">
      去提个问题 <AppIcon name="arrow" :size="16" />
    </a>
  </section>

  <template v-else>
    <details
      v-for="historyItem in historyResult.items"
      :key="historyItem.id"
      class="panel history-item"
    >
      <summary>
        <span class="history-item-icon"><AppIcon name="chat" /></span>
        <span class="history-item-title">
          {{ historyItem.question }}
          <small>
            {{ dateLabel(historyItem.created_at) }} ·
            {{ modeLabel(historyItem.generation_mode) }}
          </small>
        </span>
        <AppIcon name="chevron" :size="18" />
      </summary>
      <div class="history-answer">
        <p v-if="historyItem.insufficient_evidence" class="message warning">
          本条记录的资料证据不足。
        </p>
        <div class="structured-answer">
          <template
            v-for="(blockItem, idx) in parseAnswerBlocks(historyItem.answer)"
            :key="`${historyItem.id}-${idx}`"
          >
            <h4 v-if="blockItem.type === 'heading'" class="answer-heading">{{ blockItem.text }}</h4>
            <ul v-else-if="blockItem.type === 'list'" class="answer-list">
              <li v-for="(listLine, lIdx) in blockItem.items" :key="lIdx">{{ listLine }}</li>
            </ul>
            <pre v-else-if="blockItem.type === 'code'" class="answer-code"><code>{{ blockItem.text }}</code></pre>
            <p v-else class="prose">{{ blockItem.text }}</p>
          </template>
        </div>
        <SourceList :citations="historyItem.citations" />
        <button
          class="text-button danger"
          :disabled="!!activeTask"
          @click="requestDelete(historyItem.id)"
        >
          <AppIcon name="trash" :size="15" />
          {{
            pendingDeleteHistoryId === historyItem.id ? "确认删除这条记录" : "删除这条记录"
          }}
        </button>
        <button
          v-if="pendingDeleteHistoryId === historyItem.id"
          class="text-button"
          :disabled="!!activeTask"
          @click="pendingDeleteHistoryId = null"
        >
          取消
        </button>
      </div>
    </details>

    <div class="history-bottom">
      <div class="pagination">
        <button
          class="button secondary"
          :disabled="historyOffset === 0 || isHistoryLoading || !!activeTask"
          @click="changeHistoryPage(-1)"
        >
          上一页
        </button>
        <span>
          第 {{ historyOffset / 10 + 1 }} /
          {{ Math.max(1, Math.ceil(historyResult.total / 10)) }} 页
        </span>
        <button
          class="button secondary"
          :disabled="
            historyOffset + 10 >= historyResult.total || isHistoryLoading || !!activeTask
          "
          @click="changeHistoryPage(1)"
        >
          下一页
        </button>
      </div>
      <div class="clear-history">
        <label>
          <input v-model="isClearHistoryConfirmed" type="checkbox" />
          确认清空当前会话
        </label>
        <button
          class="text-button danger"
          :disabled="!isClearHistoryConfirmed || !!activeTask"
          @click="clearHistory"
        >
          清空记录
        </button>
      </div>
    </div>
  </template>
</template>
