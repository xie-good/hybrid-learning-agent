<script setup>
// 知识库管理页：新建知识库、上传多格式文档、管理已入库文件并在右侧抽屉预览切片。
import { computed, onActivated, onMounted, ref, watch } from "vue";
import AppIcon from "../components/AppIcon.vue";
import { useWorkspace } from "../composables/useWorkspace.js";
import { request } from "../lib/api.js";
import { dateLabel } from "../lib/presentation.js";

const {
  knowledgeBases,
  selectedKbId,
  activeKb,
  activeTask,
  errorMessage,
  noticeMessage,
  runTask,
  loadKnowledgeBases,
  selectKnowledgeBase,
  navigate,
} = useWorkspace();

const showCreateForm = ref(false);
const showMoreUpload = ref(false);
const newKnowledgeBaseName = ref("");
const newKnowledgeBaseDesc = ref("");
const documentList = ref([]);
const selectedDocument = ref(null);
const drawerTab = ref("chunks");
const chunkList = ref([]);
const totalChunks = ref(0);
const chunkOffset = ref(0);
const isDraggingFile = ref(false);
const fileInputElement = ref(null);
const confirmDeleteKb = ref(false);

const isBuiltinKb = computed(() => selectedKbId.value === "hello_agents");
// 自定义知识库还没有文档时默认展示大上传区；已有文档时优先展示“已就绪 · 去提问”，按需再展开继续上传。
const showUploadDropzone = computed(() => {
  if (isBuiltinKb.value) return false;
  if (documentList.value.length === 0) return true;
  return showMoreUpload.value;
});

async function loadDocumentList() {
  if (!selectedKbId.value) return;
  try {
    const encodedKbId = encodeURIComponent(selectedKbId.value);
    const response = await request(`/kbs/${encodedKbId}/documents`);
    documentList.value = response.items || [];
  } catch (err) {
    errorMessage.value = err.message;
  }
}

async function loadSelectedDocumentChunks() {
  if (!selectedDocument.value) return;
  try {
    const encodedKbId = encodeURIComponent(selectedKbId.value);
    const encodedChapterId = encodeURIComponent(selectedDocument.value.chapter_id);
    const url = `/kbs/${encodedKbId}/chunks?limit=15&offset=${chunkOffset.value}&chapter_id=${encodedChapterId}`;
    const response = await request(url);
    chunkList.value = response.items || [];
    totalChunks.value = response.total || 0;
  } catch (err) {
    errorMessage.value = err.message;
  }
}

onMounted(async () => {
  await loadKnowledgeBases();
  await loadDocumentList();
});

onActivated(async () => {
  await loadKnowledgeBases();
  await loadDocumentList();
});

watch(selectedKbId, () => {
  selectedDocument.value = null;
  chunkList.value = [];
  confirmDeleteKb.value = false;
  showMoreUpload.value = false;
  loadDocumentList();
});

function openDocumentDrawer(documentItem) {
  selectedDocument.value = documentItem;
  drawerTab.value = "chunks";
  chunkOffset.value = 0;
  loadSelectedDocumentChunks();
}

function createKnowledgeBase() {
  const cleanedName = newKnowledgeBaseName.value.trim();
  if (!cleanedName) {
    errorMessage.value = "请填写知识库名称。";
    return;
  }
  runTask("kb-create", async () => {
    const createdKb = await request("/kbs", {
      method: "POST",
      body: {
        name: cleanedName,
        description: newKnowledgeBaseDesc.value.trim(),
      },
    });
    newKnowledgeBaseName.value = "";
    newKnowledgeBaseDesc.value = "";
    showCreateForm.value = false;
    await selectKnowledgeBase(createdKb.kb_id);
    await loadDocumentList();
    noticeMessage.value = `已创建知识库「${createdKb.name}」，请拖放或选择文件上传。`;
  });
}

function deleteCurrentKnowledgeBase() {
  if (isBuiltinKb.value) return;
  if (!confirmDeleteKb.value) {
    confirmDeleteKb.value = true;
    return;
  }
  confirmDeleteKb.value = false;
  runTask("kb-delete", async () => {
    const encodedKbId = encodeURIComponent(selectedKbId.value);
    await request(`/kbs/${encodedKbId}`, { method: "DELETE" });
    await selectKnowledgeBase("hello_agents");
    await loadDocumentList();
    noticeMessage.value = "自定义知识库已删除。";
  });
}

async function uploadSelectedFiles(rawFileList) {
  const filesToUpload = Array.from(rawFileList || []);
  if (!filesToUpload.length) return;

  await runTask("kb-upload", async () => {
    const encodedKbId = encodeURIComponent(selectedKbId.value);
    for (const fileItem of filesToUpload) {
      const formData = new FormData();
      formData.append("file", fileItem);
      await request(`/kbs/${encodedKbId}/documents`, {
        method: "POST",
        body: formData,
        timeout: 180000,
      });
    }
    showMoreUpload.value = false;
    await selectKnowledgeBase(selectedKbId.value);
    await loadDocumentList();
    noticeMessage.value = `已成功导入 ${filesToUpload.length} 份文档并完成混合检索索引构建。`;
  });
}

function onFileInputChange(event) {
  uploadSelectedFiles(event.target.files);
  event.target.value = "";
}

function onFileDrop(event) {
  isDraggingFile.value = false;
  uploadSelectedFiles(event.dataTransfer?.files);
}

function deleteDocument(docId) {
  runTask("kb-doc-delete", async () => {
    const encodedKbId = encodeURIComponent(selectedKbId.value);
    const encodedDocId = encodeURIComponent(docId);
    await request(`/kbs/${encodedKbId}/documents/${encodedDocId}`, { method: "DELETE" });
    if (selectedDocument.value?.doc_id === docId) {
      selectedDocument.value = null;
    }
    await selectKnowledgeBase(selectedKbId.value);
    await loadDocumentList();
    noticeMessage.value = "已移除文档并更新混合检索索引。";
  });
}

function changeChunkPage(pageDelta) {
  chunkOffset.value = Math.max(0, chunkOffset.value + pageDelta * 15);
  loadSelectedDocumentChunks();
}
</script>

<template>
  <div class="kb-page">
    <div class="kb-top-bar">
      <div class="kb-top-title">
        <h2>知识库管理</h2>
        <p>{{ activeKb?.description || "仅支持 PDF、Word (.docx) 与 Markdown (.md) 结构化切块及混合检索。" }}</p>
      </div>
      <div class="kb-top-actions">
        <select
          :value="selectedKbId"
          aria-label="选择知识库"
          class="kb-switcher-select"
          :disabled="!!activeTask"
          @change="selectKnowledgeBase($event.target.value)"
        >
          <option v-for="kbItem in knowledgeBases" :key="kbItem.kb_id" :value="kbItem.kb_id">
            {{ kbItem.name }}（{{ kbItem.chunk_count }} 切片）
          </option>
        </select>
        <button
          type="button"
          class="button primary"
          :disabled="!!activeTask"
          @click="showCreateForm = !showCreateForm"
        >
          <AppIcon name="plus" :size="16" /> 新建知识库
        </button>
        <button
          v-if="!isBuiltinKb"
          type="button"
          class="button secondary danger"
          :disabled="!!activeTask"
          @click="deleteCurrentKnowledgeBase"
        >
          <AppIcon name="trash" :size="15" />
          {{ confirmDeleteKb ? "确认删除" : "删除库" }}
        </button>
      </div>
    </div>

    <form v-if="showCreateForm" class="kb-create-card" @submit.prevent="createKnowledgeBase">
      <div class="kb-create-grid">
        <label>
          知识库名称
          <input
            v-model="newKnowledgeBaseName"
            name="kb-name"
            autocomplete="off"
            maxlength="80"
            placeholder="如：操作系统课程讲义"
            :disabled="!!activeTask"
          />
        </label>
        <label>
          简介（可选）
          <input
            v-model="newKnowledgeBaseDesc"
            name="kb-desc"
            autocomplete="off"
            maxlength="200"
            placeholder="存放课程 PDF、实验笔记等资料"
            :disabled="!!activeTask"
          />
        </label>
        <button class="button primary" :disabled="!!activeTask || !newKnowledgeBaseName.trim()">
          创建并切换
        </button>
      </div>
    </form>

    <div v-if="isBuiltinKb" class="panel action-panel">
      <div>
        <h3>当前为系统预置课程《Hello-Agents》</h3>
        <p>包含第 1—12 章教材正文与离线双路索引；如需上传个人资料，请先新建自定义知识库。</p>
      </div>
      <div class="kb-top-actions">
        <button type="button" class="button secondary" @click="showCreateForm = true">
          <AppIcon name="plus" :size="15" /> 新建个人知识库
        </button>
        <a class="button primary" href="#qa" @click.exact.prevent="navigate('qa')">
          去提问 <AppIcon name="arrow" :size="15" />
        </a>
      </div>
    </div>

    <div v-else-if="documentList.length > 0" class="panel action-panel">
      <div>
        <h3>
          当前知识库已就绪：{{ activeKb?.name || "自定义知识库" }}
          <span class="pill">可检索</span>
        </h3>
        <p>已入库 {{ documentList.length }} 份文档、共 {{ activeKb?.chunk_count || 0 }} 个切片，可直接提问或继续追加新文档。</p>
      </div>
      <div class="kb-top-actions">
        <button
          type="button"
          class="button secondary"
          :disabled="!!activeTask"
          @click="showMoreUpload = !showMoreUpload"
        >
          <AppIcon name="upload" :size="15" />
          {{ showMoreUpload ? "收起上传区" : "继续添加文档" }}
        </button>
        <a class="button primary" href="#qa" @click.exact.prevent="navigate('qa')">
          去 AI 问答 <AppIcon name="arrow" :size="15" />
        </a>
      </div>
    </div>

    <div
      v-if="showUploadDropzone"
      class="upload-card"
      :class="{ dragging: isDraggingFile }"
      @dragover.prevent="isDraggingFile = true"
      @dragleave.prevent="isDraggingFile = false"
      @drop.prevent="onFileDrop"
    >
      <input
        ref="fileInputElement"
        type="file"
        class="sr-only"
        multiple
        accept=".pdf,.docx,.md,.markdown"
        :disabled="!!activeTask"
        @change="onFileInputChange"
      />
      <div class="upload-icon-circle"><AppIcon name="upload" :size="24" /></div>
      <h3>{{ documentList.length ? "继续追加学习文档" : "拖拽文件到此处，或点击上传第一份文档" }}</h3>
      <p>仅支持 PDF、Word (.docx)、Markdown (.md) 格式；上传后自动切块并建立 BM25 + 向量混合索引。</p>
      <button
        type="button"
        class="button primary"
        :disabled="!!activeTask"
        @click="fileInputElement?.click()"
      >
        选择文件上传
      </button>
      <div v-if="activeTask === 'kb-upload'" class="upload-busy">
        <span class="spinner"></span> 正在解析文档并构建混合索引…
      </div>
    </div>

    <div class="doc-section-head">
      <h3>
        已入库文档 <span class="pill">{{ documentList.length }}</span>
      </h3>
      <span class="muted">点击任意文档卡片可查看切分片段</span>
    </div>

    <div v-if="!documentList.length" class="panel empty-state">
      <p>当前知识库还没有文档，请点击上方按钮上传学习资料。</p>
    </div>

    <div v-else class="doc-list">
      <article
        v-for="docItem in documentList"
        :key="docItem.doc_id"
        class="doc-card"
        @click="openDocumentDrawer(docItem)"
      >
        <span class="doc-card-icon"><AppIcon name="summary" :size="18" /></span>
        <div class="doc-info">
          <strong>{{ docItem.filename }}</strong>
          <small>
            可检索 · {{ docItem.chunk_count }} 个切片 · {{ docItem.page_count }} 页/段 ·
            {{ dateLabel(docItem.uploaded_at) }}
          </small>
        </div>
        <div class="doc-actions" @click.stop>
          <button
            type="button"
            class="text-button"
            @click="openDocumentDrawer(docItem)"
          >
            切片详情
          </button>
          <a
            class="text-button"
            :href="`/api/kbs/${encodeURIComponent(selectedKbId)}/documents/${encodeURIComponent(docItem.doc_id)}/source`"
            target="_blank"
            rel="noopener"
          >
            原文 <AppIcon name="external" :size="14" />
          </a>
          <button
            v-if="!docItem.builtin"
            type="button"
            class="icon-button danger"
            aria-label="删除文档"
            :disabled="!!activeTask"
            @click="deleteDocument(docItem.doc_id)"
          >
            <AppIcon name="trash" :size="16" />
          </button>
        </div>
      </article>
    </div>

    <div
      v-if="selectedDocument"
      class="drawer-backdrop"
      @click.self="selectedDocument = null"
    >
      <aside class="side-drawer" aria-label="文档切片详情">
        <div class="side-drawer-header">
          <h3>{{ selectedDocument.filename }}</h3>
          <button
            type="button"
            class="icon-button"
            aria-label="关闭文档详情"
            @click="selectedDocument = null"
          >
            <AppIcon name="close" :size="18" />
          </button>
        </div>
        <div class="side-drawer-tabs">
          <button
            type="button"
            :class="{ active: drawerTab === 'chunks' }"
            @click="drawerTab = 'chunks'"
          >
            文档片段 ({{ totalChunks }})
          </button>
          <button
            type="button"
            :class="{ active: drawerTab === 'info' }"
            @click="drawerTab = 'info'"
          >
            文档详情
          </button>
        </div>
        <div class="side-drawer-body">
          <template v-if="drawerTab === 'chunks'">
            <article v-for="(chunkItem, idx) in chunkList" :key="chunkItem.chunk_id" class="chunk-card">
              <div class="chunk-head">
                <span class="pill">#{{ chunkOffset + idx + 1 }}</span>
                <strong v-if="chunkItem.section_title">{{ chunkItem.section_title }}</strong>
                <span>第 {{ chunkItem.page_start }} 页/段 · {{ chunkItem.char_count }} 字</span>
              </div>
              <p class="chunk-text">{{ chunkItem.text }}</p>
            </article>
            <div v-if="totalChunks > 15" class="pagination">
              <button
                class="button secondary"
                :disabled="chunkOffset === 0"
                @click="changeChunkPage(-1)"
              >
                上一页
              </button>
              <span>第 {{ chunkOffset / 15 + 1 }} / {{ Math.ceil(totalChunks / 15) }} 页</span>
              <button
                class="button secondary"
                :disabled="chunkOffset + 15 >= totalChunks"
                @click="changeChunkPage(1)"
              >
                下一页
              </button>
            </div>
          </template>
          <div v-else class="doc-info">
            <p class="prose"><strong>文件名：</strong>{{ selectedDocument.filename }}</p>
            <p class="prose"><strong>章节名称：</strong>{{ selectedDocument.chapter_title }}</p>
            <p class="prose"><strong>页数 / 段落：</strong>{{ selectedDocument.page_count }}</p>
            <p class="prose"><strong>切分块数：</strong>{{ selectedDocument.chunk_count }}</p>
            <a
              class="button secondary"
              :href="`/api/kbs/${encodeURIComponent(selectedKbId)}/documents/${encodeURIComponent(selectedDocument.doc_id)}/source`"
              target="_blank"
              rel="noopener"
            >
              打开原始文件 <AppIcon name="external" :size="15" />
            </a>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>
