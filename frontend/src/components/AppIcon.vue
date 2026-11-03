<script setup>
// name 选择图标，size 控制像素大小；颜色继承父元素，导航/按钮可以共用同一套图标。
defineProps({ name: String, size: { type: [Number, String], default: 20 } });
// SVG 路径是图形坐标，通常不需逐点修改；新增图标时添加一个名称与路径即可。
const paths = {
  book: "M4 4h5a4 4 0 0 1 3 2 4 4 0 0 1 3-2h5v15h-5a4 4 0 0 0-3 2 4 4 0 0 0-3-2H4z M12 6v15",
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  chat: "M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 1 1 17-5Z M8 10h8 M8 14h5",
  summary: "M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7",
  quiz: "M9 4h6v4H9z M9 6H5v15h14V6h-4 M8 14l2 2 5-5",
  history: "M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2",
  arrow: "M4 12h15 M13 6l6 6-6 6",
  chevron: "M9 5l7 7-7 7",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  layers: "m12 3 10 5-10 5L2 8z M2 12l10 5 10-5 M2 16l10 5 10-5",
  check: "m5 12 4 4L19 6",
  spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
  send: "m22 2-7 20-4-9-9-4z M22 2 11 13",
  external: "M14 3h7v7 M21 3 10 14 M10 3H3v18h18v-7",
  trash: "M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7",
  refresh: "M20 7a9 9 0 1 0 1 8 M21 3v5h-5",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  close: "m6 6 12 12 M6 18 18 6",
  info: "M12 11v6 M12 7v.1 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  clock: "M12 7v5l3 2 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
};
</script>

<template>
  <!-- 图标旁已有文字或按钮的 aria-label；图形本身隐藏，避免辅助工具重复朗读。 -->
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- 未识别的名称回退为书本图标，不影响页面上的文字和交互。 -->
    <path :d="paths[name] || paths.book" />
  </svg>
</template>
