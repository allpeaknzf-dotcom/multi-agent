document.querySelectorAll(".project-row, .session-row, .recent-row").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".project-row, .session-row, .recent-row").forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");
  });
});

document.querySelector(".send-button").addEventListener("click", () => {
  const input = document.querySelector("textarea");
  if (!input.value.trim()) {
    input.focus();
    return;
  }
  input.value = "";
  input.placeholder = "已发送。继续补充任务、追问结果，或 @ 指定成员…";
});
