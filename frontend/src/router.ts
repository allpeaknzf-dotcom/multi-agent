import { createRouter, createWebHistory } from "vue-router";
import ProjectList from "./views/ProjectList.vue";
import ProjectDetail from "./views/ProjectDetail.vue";
import SessionView from "./views/SessionView.vue";
import AgentsView from "./views/AgentsView.vue";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/projects" },
    { path: "/projects", component: ProjectList },
    { path: "/projects/:id", component: ProjectDetail },
    { path: "/projects/:id/sessions/:sid", component: SessionView },
    { path: "/agents", component: AgentsView },
  ],
});
