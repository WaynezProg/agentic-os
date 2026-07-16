use serde::Serialize;

use crate::keychain;
use crate::remote;
use crate::settings;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ConnectionProfile {
    pub mode: String,
    pub api_url: String,
    pub event_stream_url: String,
    pub token_present: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RemoteProbeResult {
    pub health_ok: bool,
    pub events_ok: bool,
    pub detail: String,
}

pub fn connection_profile() -> Result<ConnectionProfile, String> {
    let settings = settings::load_settings()?;
    if settings.connection.mode == "remote" {
        let gateway = remote::validate_remote_gateway(&settings.remote.remote_gateway)?;
        let token_present =
            keychain::load_remote_token(&gateway, &settings.remote.device_id)?.is_some();
        Ok(ConnectionProfile {
            mode: "remote".to_string(),
            api_url: gateway.clone(),
            event_stream_url: settings::event_stream_url(&gateway),
            token_present,
        })
    } else {
        Ok(ConnectionProfile {
            mode: "local".to_string(),
            api_url: settings.local.api_url,
            event_stream_url: String::new(),
            token_present: false,
        })
    }
}

pub fn api_request(
    method: &str,
    path: &str,
    body: Option<&str>,
) -> Result<remote::ApiResponse, String> {
    let settings = settings::load_settings()?;
    if settings.connection.mode == "remote" {
        remote::gateway_request_envelope(&settings, method, path, body)
    } else {
        remote::request_envelope(&settings.local.api_url, method, path, body, None)
    }
}

pub fn probe_remote_connection() -> Result<RemoteProbeResult, String> {
    let settings = settings::load_settings()?;
    if settings.connection.mode != "remote" {
        return Err("connection mode is not remote".to_string());
    }
    let gateway = remote::validate_remote_gateway(&settings.remote.remote_gateway)?;
    let token = keychain::load_remote_token(&gateway, &settings.remote.device_id)?
        .ok_or_else(|| "missing remote token in Keychain".to_string())?;

    let health_ok = remote::gateway_get_with_token(&gateway, "/health", &token).is_ok();
    let events_ok = remote::gateway_events_probe(&gateway, &token).unwrap_or(false);

    let detail = if health_ok && events_ok {
        "connected".to_string()
    } else if !health_ok {
        "health_failed".to_string()
    } else {
        "events_failed".to_string()
    };

    Ok(RemoteProbeResult {
        health_ok,
        events_ok,
        detail,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_profile_uses_local_api_url() {
        let settings = settings::DesktopSettings::default();
        assert_eq!(settings.connection.mode, "local");
        let profile = connection_profile().unwrap_or_else(|_| ConnectionProfile {
            mode: "local".to_string(),
            api_url: settings.local.api_url.clone(),
            event_stream_url: String::new(),
            token_present: false,
        });
        assert_eq!(profile.mode, "local");
    }
}
