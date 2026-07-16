mod connection;
mod daemon;
mod keychain;
mod remote;
mod settings;
mod supervisor;

use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};

use settings::DesktopSettings;
use supervisor::{ConnectionStatePayload, ConnectionStateStore, SupervisorHandle, SupervisorState};
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

fn show_desktop_settings(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("settings") {
        window.show().map_err(|error| error.to_string())?;
        window.set_focus().map_err(|error| error.to_string())?;
        return Ok(());
    }
    tauri::WebviewWindowBuilder::new(
        app,
        "settings",
        tauri::WebviewUrl::App("desktop-settings.html".into()),
    )
    .title("Desktop Settings")
    .inner_size(480.0, 420.0)
    .build()
    .map(|_| ())
    .map_err(|error| error.to_string())
}

#[tauri::command]
fn open_desktop_settings(app: AppHandle) -> Result<(), String> {
    show_desktop_settings(&app)
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
) -> Result<remote::ApiResponse, String> {
    connection::api_request(&method, &path, body.as_deref())
}

#[tauri::command]
fn probe_remote_connection() -> Result<connection::RemoteProbeResult, String> {
    connection::probe_remote_connection()
}

#[tauri::command]
fn retry_daemon(state: tauri::State<SupervisorHandle>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|error| error.to_string())?;
    *guard = SupervisorState::reset();
    Ok(())
}

#[tauri::command]
fn get_initial_connection_state(
    state: tauri::State<ConnectionStateStore>,
) -> Result<ConnectionStatePayload, String> {
    state
        .0
        .lock()
        .map(|payload| payload.clone())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn open_daemon_log() -> Result<(), String> {
    let path = daemon::daemon_log_path();
    std::process::Command::new("/usr/bin/open")
        .arg(path)
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
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

pub(crate) fn refresh_tray_title(app: &AppHandle) {
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
            open_desktop_settings,
            start_remote_pairing,
            complete_remote_pairing,
            list_remote_devices,
            revoke_remote_device,
            remote_token_status,
            get_connection_profile,
            connection_api_fetch,
            probe_remote_connection,
            retry_daemon,
            get_initial_connection_state,
            open_daemon_log,
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
            let reconcile_result = daemon::reconcile_stack();
            if reconcile_result.detail != "ok" {
                log::warn!(
                    "desktop stack reconcile failed: {}",
                    reconcile_result.detail
                );
            }
            let start_result = daemon::start_stack();
            let status = daemon::status().ok();
            let api_url = status
                .as_ref()
                .map(|status| status.api_url.clone())
                .filter(|value| !value.is_empty())
                .unwrap_or_else(|| DesktopSettings::default().local.api_url);
            let pid = status.as_ref().and_then(|status| status.pid).or_else(|| {
                start_result
                    .detail
                    .strip_prefix("port_occupied:")
                    .and_then(|value| value.parse().ok())
            });
            let initial_payload = supervisor::startup_payload(&start_result, api_url, pid);
            app.manage(ConnectionStateStore(Mutex::new(initial_payload.clone())));
            supervisor::emit_connection_state(app.handle(), initial_payload);

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
                        if let Some(handle) = app.try_state::<SupervisorHandle>() {
                            if let Ok(mut guard) = handle.0.lock() {
                                *guard = SupervisorState::reset();
                            }
                        }
                        refresh_tray_title(app);
                    }
                    "daemon_stop" => {
                        let _ = daemon_stop();
                        refresh_tray_title(app);
                    }
                    "settings" => {
                        let _ = show_desktop_settings(app);
                    }
                    "quit" => {
                        supervisor::SHUTDOWN.store(true, Ordering::SeqCst);
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

            let shared = Arc::new(Mutex::new(SupervisorState::reset()));
            app.manage(SupervisorHandle(shared.clone()));
            let supervisor_handle = handle.clone();
            std::thread::spawn(move || supervisor::run_supervisor(supervisor_handle, shared));

            refresh_tray_title(app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|_app_handle, event| {
        if let RunEvent::Exit = event {
            supervisor::SHUTDOWN.store(true, Ordering::SeqCst);
            daemon::stop_stack();
        }
    });
}
