use std::io::Read;

const GATEWAY_TRANSPORT_ERROR: &str =
    "remote gateway must use https; http:// is allowed only for localhost";

pub fn is_supported_method(method: &str) -> bool {
    matches!(
        method.to_ascii_uppercase().as_str(),
        "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
    )
}

fn normalize_path(path: &str) -> String {
    if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    }
}

pub fn validate_remote_gateway(gateway: &str) -> Result<String, String> {
    let normalized = gateway.trim().trim_end_matches('/');
    if normalized.is_empty() {
        return Err("remote_gateway is required".to_string());
    }

    let (scheme, host) = parse_gateway_scheme_and_host(normalized)?;
    if scheme == "http" && !is_loopback_host(&host) {
        return Err(GATEWAY_TRANSPORT_ERROR.to_string());
    }
    if scheme != "http" && scheme != "https" {
        return Err(GATEWAY_TRANSPORT_ERROR.to_string());
    }

    Ok(normalized.to_string())
}

fn parse_gateway_scheme_and_host(gateway: &str) -> Result<(String, String), String> {
    let lower = gateway.to_ascii_lowercase();
    let (scheme, rest) = if let Some(rest) = lower.strip_prefix("https://") {
        ("https", rest)
    } else if let Some(rest) = lower.strip_prefix("http://") {
        ("http", rest)
    } else {
        return Err(GATEWAY_TRANSPORT_ERROR.to_string());
    };

    let authority = rest.split('/').next().unwrap_or(rest);
    let host_port = authority.rsplit('@').next().unwrap_or(authority);
    let host = if host_port.starts_with('[') {
        let close = host_port
            .find(']')
            .ok_or_else(|| GATEWAY_TRANSPORT_ERROR.to_string())?;
        host_port[1..close].to_string()
    } else {
        host_port.split(':').next().unwrap_or(host_port).to_string()
    };

    Ok((scheme.to_string(), host))
}

fn is_loopback_host(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "localhost" | "::1")
}

pub fn local_api_url() -> String {
    std::env::var("AGENTIC_OS_API_URL").unwrap_or_else(|_| "http://127.0.0.1:8767".to_string())
}

fn response_error(response: reqwest::blocking::Response) -> String {
    let status = response.status();
    response.text().unwrap_or_else(|_| status.to_string())
}

pub fn request(
    base_url: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> Result<String, String> {
    if !is_supported_method(method) {
        return Err(format!(
            "unsupported method: {}",
            method.to_ascii_uppercase()
        ));
    }
    let request_method = reqwest::Method::from_bytes(method.to_ascii_uppercase().as_bytes())
        .map_err(|error| error.to_string())?;
    let url = format!(
        "{}{}",
        base_url.trim().trim_end_matches('/'),
        normalize_path(path)
    );
    let client = reqwest::blocking::Client::new();
    let mut request = client.request(request_method, &url);
    if let Some(token) = bearer {
        request = request.header("Authorization", format!("Bearer {token}"));
    }
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

pub fn post_json(path: &str, body: Option<&str>) -> Result<String, String> {
    request(&local_api_url(), "POST", path, body, None)
}

pub fn get_json(path: &str) -> Result<String, String> {
    request(&local_api_url(), "GET", path, None, None)
}

pub fn delete_json(path: &str) -> Result<String, String> {
    request(&local_api_url(), "DELETE", path, None, None)
}

pub fn complete_pairing(pairing_code: &str, device_name: &str) -> Result<String, String> {
    let body = serde_json::json!({
        "pairing_code": pairing_code,
        "device_name": device_name,
    });
    post_json("/remote/pairing/complete", Some(&body.to_string()))
}

fn gateway_url(settings: &crate::settings::DesktopSettings) -> Result<String, String> {
    validate_remote_gateway(&settings.remote.remote_gateway)
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
    let gateway = validate_remote_gateway(gateway)?;
    let url = format!("{gateway}/events");
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
    let gateway = validate_remote_gateway(gateway)?;
    request(&gateway, method, path, body, Some(token))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supported_methods_include_put_and_patch() {
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"] {
            assert!(is_supported_method(method));
        }
        assert!(!is_supported_method("TRACE"));
    }

    #[test]
    fn normalize_path_adds_one_leading_slash() {
        assert_eq!(normalize_path("health"), "/health");
        assert_eq!(normalize_path("/health"), "/health");
    }

    #[test]
    fn validate_rejects_cleartext_non_loopback() {
        let error = validate_remote_gateway("http://evil.example").unwrap_err();
        assert!(error.contains("https"));
        assert!(validate_remote_gateway("http://0.0.0.0:8443").is_err());
    }

    #[test]
    fn validate_accepts_https_remote() {
        assert_eq!(
            validate_remote_gateway("https://gw.example/").unwrap(),
            "https://gw.example"
        );
    }

    #[test]
    fn validate_accepts_http_localhost() {
        assert_eq!(
            validate_remote_gateway("http://127.0.0.1:8443").unwrap(),
            "http://127.0.0.1:8443"
        );
        assert_eq!(
            validate_remote_gateway("http://localhost:8443").unwrap(),
            "http://localhost:8443"
        );
        assert_eq!(
            validate_remote_gateway("http://[::1]:8443").unwrap(),
            "http://[::1]:8443"
        );
    }

    #[test]
    fn validate_rejects_missing_scheme() {
        assert!(validate_remote_gateway("gw.example").is_err());
    }
}
