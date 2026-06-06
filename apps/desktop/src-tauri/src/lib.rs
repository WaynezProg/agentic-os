mod daemon;
mod remote;
mod settings;

use settings::DesktopSettings;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent};

#[tauri::command]
fn daemon_status() -> Result<String, String> {
    daemon::run_script("desktop-daemon.sh", "status")
}

#[tauri::command]
fn daemon_start() -> Result<String, String> {
    daemon::run_script("desktop-daemon.sh", "start")
}

#[tauri::command]
fn daemon_stop() -> Result<String, String> {
    daemon::run_script("desktop-daemon.sh", "stop")
}

#[tauri::command]
fn ui_status() -> Result<String, String> {
    daemon::run_script("desktop-ui.sh", "status")
}

#[tauri::command]
fn ui_start() -> Result<String, String> {
    daemon::run_script("desktop-ui.sh", "start")
}

#[tauri::command]
fn ui_stop() -> Result<String, String> {
    daemon::run_script("desktop-ui.sh", "stop")
}

#[tauri::command]
fn get_desktop_settings() -> Result<DesktopSettings, String> {
    settings::load_settings()
}

#[tauri::command]
fn save_desktop_settings(settings: DesktopSettings) -> Result<(), String> {
    settings::save_settings(&settings)
}

#[tauri::command]
fn start_remote_pairing() -> Result<String, String> {
    remote::post_json("/remote/pairing/start", None)
}

#[tauri::command]
fn list_remote_devices() -> Result<String, String> {
    remote::get_json("/remote/devices")
}

#[tauri::command]
fn revoke_remote_device(device_id: String) -> Result<String, String> {
    remote::delete_json(&format!("/remote/devices/{device_id}"))
}

fn tray_title_from_status(status_json: &str) -> String {
    let health = serde_json::from_str::<serde_json::Value>(status_json)
        .ok()
        .and_then(|value| value.get("health").and_then(|item| item.as_str()).map(str::to_string))
        .unwrap_or_else(|| "unknown".to_string());
    format!("agentic-os · agentd: {health}")
}

fn refresh_tray_title(app: &AppHandle) {
    let Ok(status) = daemon_status() else {
        return;
    };
    let title = tray_title_from_status(&status);
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_title(Some(title));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            daemon_status,
            daemon_start,
            daemon_stop,
            ui_status,
            ui_start,
            ui_stop,
            get_desktop_settings,
            save_desktop_settings,
            start_remote_pairing,
            list_remote_devices,
            revoke_remote_device,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            daemon::init_bundle_root(app.handle());
            daemon::reconcile_stack();
            daemon::start_stack();

            let daemon_start_item =
                MenuItem::with_id(app, "daemon_start", "Start daemon", true, None::<&str>)?;
            let daemon_stop_item =
                MenuItem::with_id(app, "daemon_stop", "Stop daemon", true, None::<&str>)?;
            let settings_item = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(
                app,
                &[
                    &daemon_start_item,
                    &daemon_stop_item,
                    &settings_item,
                    &quit_item,
                ],
            )?;

            let icon = app
                .default_window_icon()
                .cloned()
                .expect("default window icon");
            let handle = app.handle().clone();
            TrayIconBuilder::with_id("main")
                .icon(icon)
                .title("agentic-os · agentd: starting")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "daemon_start" => {
                        let _ = daemon_start();
                        refresh_tray_title(app);
                    }
                    "daemon_stop" => {
                        let _ = daemon_stop();
                        refresh_tray_title(app);
                    }
                    "settings" => {
                        if let Some(window) = app.get_webview_window("settings") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        } else {
                            let _ = tauri::WebviewWindowBuilder::new(
                                app,
                                "settings",
                                tauri::WebviewUrl::App("desktop-settings.html".into()),
                            )
                            .title("Desktop Settings")
                            .inner_size(480.0, 420.0)
                            .build();
                        }
                    }
                    "quit" => {
                        daemon::stop_stack();
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            let poll_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    refresh_tray_title(&poll_handle);
                    tokio::time::sleep(std::time::Duration::from_secs(5)).await;
                }
            });

            refresh_tray_title(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, event| {
        if let RunEvent::Exit = event {
            daemon::stop_stack();
        }
    });
}
