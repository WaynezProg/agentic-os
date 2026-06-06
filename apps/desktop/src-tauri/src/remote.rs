use std::io::Read;

pub fn local_api_url() -> String {
    std::env::var("AGENTIC_OS_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8767".to_string())
}

fn response_error(response: reqwest::blocking::Response) -> String {
    let status = response.status();
    response.text().unwrap_or_else(|_| status.to_string())
}

pub fn post_json(path: &str, body: Option<&str>) -> Result<String, String> {
    let url = format!("{}{}", local_api_url().trim_end_matches('/'), path);
    let client = reqwest::blocking::Client::new();
    let mut request = client.post(&url);
    if let Some(raw) = body {
        request = request
            .header("Content-Type", "application/json")
            .body(raw.to_string());
    }
    let response = request.send().map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response_error(response));
    }
    response.text().map_err(|error| error.to_string())
}

pub fn get_json(path: &str) -> Result<String, String> {
    let url = format!("{}{}", local_api_url().trim_end_matches('/'), path);
    let response = reqwest::blocking::Client::new()
        .get(&url)
        .send()
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response_error(response));
    }
    response.text().map_err(|error| error.to_string())
}

pub fn delete_json(path: &str) -> Result<String, String> {
    let url = format!("{}{}", local_api_url().trim_end_matches('/'), path);
    let response = reqwest::blocking::Client::new()
        .delete(&url)
        .send()
        .map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response_error(response));
    }
    response.text().map_err(|error| error.to_string())
}

pub fn complete_pairing(pairing_code: &str, device_name: &str) -> Result<String, String> {
    let body = serde_json::json!({
        "pairing_code": pairing_code,
        "device_name": device_name,
    });
    post_json(
        "/remote/pairing/complete",
        Some(&body.to_string()),
    )
}

fn gateway_url(settings: &crate::settings::DesktopSettings) -> Result<String, String> {
    let gateway = settings.remote.remote_gateway.trim().trim_end_matches('/');
    if gateway.is_empty() {
        return Err("remote_gateway is required".to_string());
    }
    Ok(gateway.to_string())
}

pub fn gateway_request(
    settings: &crate::settings::DesktopSettings,
    method: &str,
    path: &str,
    body: Option<&str>,
) -> Result<String, String> {
    let gateway = gateway_url(settings)?;
    let token = crate::keychain::load_remote_token(&gateway, &settings.remote.device_id)?
        .ok_or_else(|| "missing remote token in Keychain".to_string())?;
    gateway_request_with_token(&gateway, method, path, body, &token)
}

pub fn gateway_get_with_token(gateway: &str, path: &str, token: &str) -> Result<String, String> {
    gateway_request_with_token(gateway, "GET", path, None, token)
}

pub fn gateway_events_probe(gateway: &str, token: &str) -> Result<bool, String> {
    let url = format!("{}{}", gateway.trim_end_matches('/'), "/events");
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()
        .map_err(|error| error.to_string())?;
    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|error| error.to_string())?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Ok(false);
    }
    if !response.status().is_success() {
        return Err(response_error(response));
    }
    let mut body = String::new();
    let mut reader = response;
    let mut buffer = [0_u8; 64];
    loop {
        match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => {
                body.push_str(&String::from_utf8_lossy(&buffer[..count]));
                if body.contains('\n') {
                    break;
                }
            }
            Err(error) => return Err(error.to_string()),
        }
    }
    Ok(body.starts_with(':') || body.contains("data:"))
}

fn gateway_request_with_token(
    gateway: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    token: &str,
) -> Result<String, String> {
    let normalized_path = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    let url = format!("{}{}", gateway.trim_end_matches('/'), normalized_path);
    let client = reqwest::blocking::Client::new();
    let mut request = match method.to_uppercase().as_str() {
        "GET" => client.get(&url),
        "POST" => client.post(&url),
        "DELETE" => client.delete(&url),
        other => return Err(format!("unsupported method: {other}")),
    };
    request = request.header("Authorization", format!("Bearer {token}"));
    if let Some(raw) = body {
        request = request
            .header("Content-Type", "application/json")
            .body(raw.to_string());
    }
    let response = request.send().map_err(|error| error.to_string())?;
    if !response.status().is_success() {
        return Err(response_error(response));
    }
    response.text().map_err(|error| error.to_string())
}
