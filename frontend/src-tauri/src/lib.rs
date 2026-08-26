// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::Duration;

use tauri::Manager;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

/// 后端健康检查（TCP 探测 127.0.0.1:8765）。
fn backend_ready() -> bool {
    "127.0.0.1:8765"
        .parse::<std::net::SocketAddr>()
        .map(|addr| TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok())
        .unwrap_or(false)
}

/// 定位 sidecar 二进制：Tauri 在 macOS 上会把它放到 Contents/MacOS 目录，
/// 个别版本放 Resources，两个位置都探测。
fn find_sidecar(app: &tauri::AppHandle) -> Option<PathBuf> {
    // 1. 资源目录
    if let Ok(dir) = app.path().resource_dir() {
        let p = dir.join("multiagent-backend");
        if p.exists() {
            return Some(p);
        }
    }
    // 2. 主可执行同级目录（macOS .app 的 Contents/MacOS）
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let p = dir.join("multiagent-backend");
            if p.exists() {
                return Some(p);
            }
        }
    }
    None
}

/// 启动 sidecar 后端并等待就绪（仅 release 打包运行时调用）。
fn ensure_backend(app: tauri::AppHandle) {
    // 后端已在运行（例如用户手动启动 / 端口被占用）则直接使用
    if backend_ready() {
        return;
    }

    // 日志文件：优先 ~/.multi-agent/backend.log，失败回退 /tmp
    let log_path = app
        .path()
        .app_log_dir()
        .map(|d| {
            let _ = std::fs::create_dir_all(&d);
            d.join("backend.log")
        })
        .unwrap_or_else(|_| PathBuf::from("/tmp/multiagent-backend.log"));

    let sidecar = find_sidecar(&app);

    let mut child: Option<Child> = None;
    if let Some(bin) = sidecar {
        let log_file = std::fs::File::create(&log_path).unwrap_or_else(|_| {
            std::fs::File::create("/tmp/multiagent-backend.log").unwrap()
        });
        match Command::new(&bin)
            .stdout(Stdio::from(log_file.try_clone().unwrap()))
            .stderr(Stdio::from(log_file))
            .spawn()
        {
            Ok(c) => child = Some(c),
            Err(_) => { /* 启动失败：窗口仍会打开，前端会提示后端不可用 */ }
        }
    }

    // 轮询等待后端就绪（最多 20s）
    for _ in 0..40 {
        if backend_ready() {
            return;
        }
        thread::sleep(Duration::from_millis(500));
    }
    // 超时则终止子进程，避免残留
    if let Some(mut c) = child {
        let _ = c.kill();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![greet])
        .setup(|app| {
            // release 打包运行时确保本地后端就绪
            if !cfg!(debug_assertions) {
                ensure_backend(app.handle().clone());
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
