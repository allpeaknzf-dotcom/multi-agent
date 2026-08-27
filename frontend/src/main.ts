import { createApp } from "vue";
import { createPinia } from "pinia";
import naive, { createDiscreteApi } from "naive-ui";
import App from "./App.vue";
import router from "./router";
import "./styles.css";

// 全局 message（供 App.vue 侧边栏等非 n-message-provider 后代组件使用）
const { message } = createDiscreteApi(["message"]);
window.$message = message;

createApp(App).use(createPinia()).use(router).use(naive).mount("#app");
