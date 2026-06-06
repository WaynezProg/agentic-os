use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

pub const REDACTED_SECRET: &str = "[REDACTED]";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesktopSettings {
    pub connection: ConnectionSettings,
    pub local: LocalSettings,
    pub remote: RemoteSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConnectionSettings {
    pub mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalSettings {
    pub api_url: String,
    pub ui_url: String,
}

/// Persisted remote adapter config. Token and pairing codes are never stored here (P12.5: Keychain).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemoteSettings {
    #[serde(alias = "gateway_url")]
    pub remote_gateway: String,
    #[serde(default)]
    pub tunnel_provider: String,
    #[serde(default, alias = "paired_device_id")]
    pub device_id: String,
}

/// Legacy/extra keys absorbed on load and dropped on save.
#[derive(Debug, Default, Deserialize)]
struct RemoteSettingsLegacy {
    #[serde(default, alias = "gateway_url")]
    remote_gateway: String,
    #[serde(default)]
    tunnel_provider: String,
    #[serde(default, alias = "paired_device_id")]
    device_id: String,
    #[serde(default)]
    token: String,
    #[serde(default)]
    pairing_code: String,
    #[serde(default)]
    event_stream_url: String,
}

#[derive(Debug, Deserialize)]
struct DesktopSettingsLegacy {
    #[serde(default)]
    connection: ConnectionSettings,
    #[serde(default)]
    local: LocalSettings,
    #[serde(default)]
    remote: RemoteSettingsLegacy,
}

impl Default for ConnectionSettings {
    fn default() -> Self {
        Self {
            mode: "local".to_string(),
        }
    }
}

impl Default for LocalSettings {
    fn default() -> Self {
        Self {
            api_url: "http://127.0.0.1:8767".to_string(),
            ui_url: "http://127.0.0.1:5173".to_string(),
        }
    }
}

impl Default for RemoteSettings {
    fn default() -> Self {
        Self {
            remote_gateway: String::new(),
            tunnel_provider: String::new(),
            device_id: String::new(),
        }
    }
}

impl Default for DesktopSettings {
    fn default() -> Self {
        Self {
            connection: ConnectionSettings::default(),
            local: LocalSettings::default(),
            remote: RemoteSettings::default(),
        }
    }
}

impl From<RemoteSettingsLegacy> for RemoteSettings {
    fn from(legacy: RemoteSettingsLegacy) -> Self {
        let _token_redacted = (!legacy.token.is_empty()).then_some(REDACTED_SECRET);
        let _ = _token_redacted;
        Self {
            remote_gateway: legacy.remote_gateway,
            tunnel_provider: legacy.tunnel_provider,
            device_id: legacy.device_id,
        }
    }
}

impl From<DesktopSettingsLegacy> for DesktopSettings {
    fn from(legacy: DesktopSettingsLegacy) -> Self {
        Self {
            connection: legacy.connection,
            local: legacy.local,
            remote: legacy.remote.into(),
        }
    }
}

pub fn settings_path() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or_else(|| "home directory not found".to_string())?;
    Ok(home.join(".agentic-os").join("desktop.toml"))
}

pub fn load_settings() -> Result<DesktopSettings, String> {
    let path = settings_path()?;
    if !path.exists() {
        return Ok(DesktopSettings::default());
    }
    let raw = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let legacy: DesktopSettingsLegacy = toml::from_str(&raw).map_err(|error| error.to_string())?;
    Ok(legacy.into())
}

pub fn save_settings(settings: &DesktopSettings) -> Result<(), String> {
    let path = settings_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let raw = toml::to_string_pretty(settings).map_err(|error| error.to_string())?;
    if raw.contains("token") || raw.contains("pairing_code") {
        return Err("refusing to persist secret remote fields in desktop.toml".to_string());
    }
    fs::write(path, raw).map_err(|error| error.to_string())
}

pub fn event_stream_url(remote_gateway: &str) -> String {
    let trimmed = remote_gateway.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        String::new()
    } else {
        format!("{trimmed}/events")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_settings_persist_only_remote_gateway_and_device_id() {
        let settings = DesktopSettings::default();
        let raw = toml::to_string(&settings).unwrap();
        assert!(raw.contains("mode = \"local\""));
        assert!(raw.contains("remote_gateway"));
        assert!(raw.contains("tunnel_provider"));
        assert!(raw.contains("device_id"));
        assert!(!raw.contains("token"));
        assert!(!raw.contains("pairing_code"));
        assert!(!raw.contains("event_stream_url"));
    }

    #[test]
    fn legacy_token_is_redacted_on_load_and_not_persisted() {
        let raw = r#"
[connection]
mode = "remote"

[local]
api_url = "http://127.0.0.1:8767"
ui_url = "http://127.0.0.1:5173"

[remote]
gateway_url = "https://gw.example"
token = "secret-token-value"
paired_device_id = "dev-1"
event_stream_url = "https://gw.example/events"
pairing_code = "123456"
"#;
        let legacy: DesktopSettingsLegacy = toml::from_str(raw).unwrap();
        let settings: DesktopSettings = legacy.into();
        assert_eq!(settings.remote.remote_gateway, "https://gw.example");
        assert_eq!(settings.remote.device_id, "dev-1");
        let saved = toml::to_string(&settings).unwrap();
        assert!(!saved.contains("secret-token-value"));
        assert!(!saved.contains("123456"));
        assert!(saved.contains("remote_gateway = \"https://gw.example\""));
    }

    #[test]
    fn event_stream_url_derived_from_remote_gateway() {
        assert_eq!(
            event_stream_url("https://gw.example/"),
            "https://gw.example/events"
        );
    }
}
