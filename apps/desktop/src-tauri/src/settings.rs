use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteSettings {
    pub gateway_url: String,
    pub event_stream_url: String,
    #[serde(default, skip_serializing)]
    pub pairing_code: String,
    pub paired_device_id: String,
}

impl Default for DesktopSettings {
    fn default() -> Self {
        Self {
            connection: ConnectionSettings {
                mode: "local".to_string(),
            },
            local: LocalSettings {
                api_url: "http://127.0.0.1:8767".to_string(),
                ui_url: "http://127.0.0.1:5173".to_string(),
            },
            remote: RemoteSettings {
                gateway_url: String::new(),
                event_stream_url: String::new(),
                pairing_code: String::new(),
                paired_device_id: String::new(),
            },
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
    toml::from_str(&raw).map_err(|error| error.to_string())
}

pub fn save_settings(settings: &DesktopSettings) -> Result<(), String> {
    let path = settings_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let raw = toml::to_string_pretty(settings).map_err(|error| error.to_string())?;
    fs::write(path, raw).map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_settings_serialize() {
        let settings = DesktopSettings::default();
        let raw = toml::to_string(&settings).unwrap();
        assert!(raw.contains("mode = \"local\""));
        assert!(raw.contains("api_url = \"http://127.0.0.1:8767\""));
        assert!(!raw.contains("token"));
    }
}
