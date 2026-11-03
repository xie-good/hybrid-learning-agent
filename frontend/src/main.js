// 浏览器执行入口：载入 Vue 根组件及公共样式，再把页面挂到 index.html 的 #app 容器。
import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
