import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

// mode 区分开发与生产构建；这里只配置前端编译及本地 API 转发，不启动 Python 服务。
export default defineConfig(({ mode }) => {
  // 只读取后端地址，模型凭据不会进入浏览器构建产物。
  const env = loadEnv(mode, process.cwd(), "BACKEND_URL");
  // 浏览器访问 /api，Vite 转发给 FastAPI；这样本地开发不必让浏览器跨端口请求。
  const proxy = {
    "/api": {
      target: env.BACKEND_URL || "http://127.0.0.1:8000",
      changeOrigin: true,
    },
  };
  return {
    plugins: [vue()],
    // strictPort 在端口被占用时直接报错，避免悄悄换端口导致用户打开旧地址。
    server: { port: 5173, strictPort: true, proxy },
    // preview 只检查构建后的页面；生产部署仍需由 Web 服务另配 /api 反向代理。
    preview: { port: 4173, strictPort: true, proxy },
  };
});
