<script setup>
// 历史页负责分页、删除与清空确认；会话和记录快照来自共享工作区。
import { onActivated, ref } from "vue";
import AppIcon from "../components/AppIcon.vue";
import SourceList from "../components/SourceList.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import {dateLabel, modeLabel, displayLearningText} from "../lib/presentation.js";

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

// KeepAlive 重新激活页面也要刷新，避免从问答页返回后仍停留在旧的记录列表。
onActivated(loadHistory);

function requestDelete(historyId) {
  // 首次点击仅进入确认态，再次点击才真正删除，避免误触。
  if (pendingDeleteHistoryId.value !== historyId) {
    pendingDeleteHistoryId.value = historyId;
    return;
  }
  pendingDeleteHistoryId.value = null;
  runTask("delete", async () => {
    await request(`/history/${encodeURIComponent(historyId)}?session_id=${currentSessionId}`, {
      method: "DELETE",
    });
    // 删除当前页最后一条时退回上一页，避免仍有历史却显示空白分页。
    if (historyResult.value.items.length === 1 && historyOffset.value > 0)
      historyOffset.value -= 10;
    await loadHistory();
    noticeMessage.value = "该问答记录已删除。";
  });
}

function clearHistory() {
  runTask("delete", async () => {
    await request(`/history?session_id=${currentSessionId}`, { method: "DELETE" });
    historyOffset.value = 0;
    isClearHistoryConfirmed.value = false;
    // 用共享通知清除问答页旧结果，不越过组件边界直接操作它的局部状态。
    historyClearCount.value += 1;
    await loadHistory();
    noticeMessage.value = "当前会话的问答记录已清空。";
  });
}

// 后端接收跳过的记录条数；界面的上一页/下一页换算成十条的增减。
function changeHistoryPage(pageDelta) {
  historyOffset.value += pageDelta * 10;
  loadHistory();
}
</script>

<template>
  <!-- 加载、空列表和实际记录互斥显示，清空操作需要显式勾选确认。 -->
  <section class="panel history-toolbar">
    <div>
      <h3>
        本次会话的学习足迹
        <span class="pill">{{ historyResult.total }} 条</span>
      </h3>
      <p>仅保存当前标签页的问答；总结与练习不计入历史。</p>
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
    <span class="placeholder-symbol"
      ><AppIcon name="history" :size="32"
    /></span>
    <h3>每一次思考，都值得留下</h3>
    <p>向教材提出第一个问题，你的学习足迹就会出现在这里。</p>
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
          本条记录的教材证据不足。
        </p>
        <p class="prose">{{ displayLearningText(historyItem.answer) }}</p>
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
