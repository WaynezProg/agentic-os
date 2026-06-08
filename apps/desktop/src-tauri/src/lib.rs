mod connection;
mod daemon;
mod keychain;
mod remote;
mod settings;
mod supervisor;

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
fn remote_token_status(remote_gateway: String, device_id: String) -> Result<bool, String> {
    Ok(keychain::load_remote_token(&remote_gateway, &device_id)?.is_some())
}

#[tauri::command]
fn complete_remote_pairing(pairing_code: String, device_name: String) -> Result<String, String> {
    let settings = settings::load_settings()?;
    let gateway = remote::validate_remote_gateway(&settings.remote.remote_gateway)?;
    if device_name.trim().is_empty() {
        return Err("device_name is required".to_string());
    }

    let raw = remote::complete_pairing(&pairing_code, device_name.trim())?;
    let payload: serde_json::Value =
        serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    let device_id = payload
        .get("device_id")
        .and_then(|value| value.as_str())
        .ok_or_else(|| "pairing response missing device_id".to_string())?;
    let auth_token = payload
        .get("auth_token")
        .and_then(|value| value.as_str())
        .ok_or_else(|| "pairing response missing auth_token".to_string())?;

    keychain::save_remote_token(&gateway, device_id, auth_token)?;

    let mut updated = settings;
    updated.remote.device_id = device_id.to_string();
    settings::save_settings(&updated)?;

    Ok(serde_json::json!({ "device_id": device_id }).to_string())
}

#[tauri::command]
fn get_connection_profile() -> Result<connection::ConnectionProfile, String> {
    connection::connection_profile()
}

#[tauri::command]
fn connection_api_fetch(
    method: String,
    path: String,
    body: Option<String>,
) -> Result<String, String> {
    connection::api_request(&method, &path, body.as_deref())
}

#[tauri::command]
fn probe_remote_connection() -> Result<connection::RemoteProbeResult, String> {
    connection::probe_remote_connection()
}

#[tauri::command]
fn revoke_remote_device(device_id: String) -> Result<String, String> {
    let settings = settings::load_settings()?;
    let result = remote::delete_json(&format!("/remote/devices/{device_id}"))?;
    if !settings.remote.remote_gateway.trim().is_empty() {
        let _ = keychain::delete_remote_token(&settings.remote.remote_gateway, &device_id);
    }
    if settings.remote.device_id == device_id {
        let mut updated = settings;
        updated.remote.device_id.clear();
        settings::save_settings(&updated)?;
    }
    Ok(result)
}

fn tray_title_from_health(health: &str, mode: &str) -> String {
    format!("agentic-os · {mode}: {health}")
}

fn refresh_tray_title(app: &AppHandle) {
    let title = match connection::connection_profile() {
        Ok(profile) if profile.mode == "remote" => {
            match connection::probe_remote_connection() {
                Ok(probe) if probe.health_ok && probe.events_ok => {
                    tray_title_from_health("connected", "remote")
                }
                Ok(probe) if probe.health_ok => {
                    tray_title_from_health("health ok", "remote")
                }
                Ok(_) => tray_title_from_health("degraded", "remote"),
                Err(_) => tray_title_from_health("unreachable", "remote"),
            }
        }
        _ => {
            let Ok(status) = daemon_status() else {
                return;
            };
            let health = serde_json::from_str::<serde_json::Value>(&status)
                .ok()
                .and_then(|value| {
                    value
                        .get("health")
                        .and_then(|item| item.as_str())
                        .map(str::to_string)
                })
                .unwrap_or_else(|| "unknown".to_string());
            tray_title_from_health(&health, "agentd")
        }
    };
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
            complete_remote_pairing,
            list_remote_devices,
            revoke_remote_device,
            remote_token_status,
            get_connection_profile,
            connection_api_fetch,
            probe_remote_connection,
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
