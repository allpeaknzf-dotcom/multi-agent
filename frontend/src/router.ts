import { createRouter, createWebHistory } from "vue-router";
import HomeView from "./views/HomeView.vue";
import ProjectDetail from "./views/ProjectDetail.vue";
import SessionView from "./views/SessionView.vue";
import AgentsView from "./views/AgentsView.vue";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: HomeView },
    { path: "/projects", redirect: "/" },
    { path: "/projects/:id", component: ProjectDetail },
    { path: "/projects/:id/sessions/:sid", component: SessionView },
    { path: "/sessions/:sid", component: SessionView },
    { path: "/agents", component: AgentsView },
  ],
});
