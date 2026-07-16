use std::io::Read;

use serde::Serialize;

const GATEWAY_TRANSPORT_ERROR: &str =
    "remote gateway must use https; http:// is allowed only for localhost";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ApiResponse {
    pub status: u16,
    pub body: String,
}

impl ApiResponse {
    fn is_success(&self) -> bool {
        (200..300).contains(&self.status)
    }
}

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

fn envelope_error(response: &ApiResponse) -> String {
    if response.body.trim().is_empty() {
        response.status.to_string()
    } else {
        response.body.clone()
    }
}

pub fn request_envelope(
    base_url: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> Result<ApiResponse, String> {
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
    let status = response.status().as_u16();
    let body = response.text().map_err(|error| error.to_string())?;
    Ok(ApiResponse { status, body })
}

pub fn request(
    base_url: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    bearer: Option<&str>,
) -> Result<String, String> {
    let response = request_envelope(base_url, method, path, body, bearer)?;
    if !response.is_success() {
        return Err(envelope_error(&response));
    }
    Ok(response.body)
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

pub fn gateway_request_envelope(
    settings: &crate::settings::DesktopSettings,
    method: &str,
    path: &str,
    body: Option<&str>,
) -> Result<ApiResponse, String> {
    let gateway = gateway_url(settings)?;
    let token = crate::keychain::load_remote_token(&gateway, &settings.remote.device_id)?
        .ok_or_else(|| "missing remote token in Keychain".to_string())?;
    gateway_request_with_token_envelope(&gateway, method, path, body, &token)
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

fn gateway_request_with_token_envelope(
    gateway: &str,
    method: &str,
    path: &str,
    body: Option<&str>,
    token: &str,
) -> Result<ApiResponse, String> {
    let gateway = validate_remote_gateway(gateway)?;
    request_envelope(&gateway, method, path, body, Some(token))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::TcpListener;
    use std::thread;

    fn capture_request(method: &str, body: Option<&str>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut raw = Vec::new();
            let mut buffer = [0_u8; 4096];
            loop {
                let count = stream.read(&mut buffer).unwrap();
                if count == 0 {
                    break;
                }
                raw.extend_from_slice(&buffer[..count]);
                let text = String::from_utf8_lossy(&raw);
                let Some(header_end) = text.find("\r\n\r\n") else {
                    continue;
                };
                let content_length = text[..header_end]
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .and_then(|value| value.trim().parse::<usize>().ok())
                    })
                    .unwrap_or(0);
                if raw.len() >= header_end + 4 + content_length {
                    break;
                }
            }
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
                .unwrap();
            String::from_utf8(raw).unwrap()
        });

        let response = request(
            &format!("http://{address}"),
            method,
            "transport",
            body,
            Some("desktop-secret"),
        )
        .unwrap();
        assert_eq!(response, "{}");
        server.join().unwrap()
    }

    fn response_envelope(status: &str, body: &str) -> ApiResponse {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0_u8; 1024];
            let _ = stream.read(&mut buffer).unwrap();
            stream.write_all(response.as_bytes()).unwrap();
        });

        let envelope = request_envelope(
            &format!("http://{address}"),
            "GET",
            "/contract",
            None,
            Some("desktop-secret"),
        )
        .unwrap();
        server.join().unwrap();
        envelope
    }

    #[test]
    fn supported_methods_include_put_and_patch() {
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"] {
            assert!(is_supported_method(method));
        }
        assert!(!is_supported_method("TRACE"));
    }

    #[test]
    fn request_dispatches_all_supported_methods_with_bearer() {
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"] {
            let body = matches!(method, "POST" | "PUT" | "PATCH").then_some(r#"{"ok":true}"#);
            let raw = capture_request(method, body);
            assert!(raw.starts_with(&format!("{method} /transport HTTP/1.1\r\n")));
            assert!(raw.contains("authorization: Bearer desktop-secret\r\n"));
            if body.is_some() {
                assert!(raw.ends_with(r#"{"ok":true}"#));
            }
        }
    }

    #[test]
    fn request_envelope_preserves_non_success_status_and_body() {
        for (status_line, expected_status) in [
            ("401 Unauthorized", 401),
            ("403 Forbidden", 403),
            ("409 Conflict", 409),
            ("422 Unprocessable Entity", 422),
        ] {
            let body = format!(r#"{{"detail":"status-{expected_status}"}}"#);
            let response = response_envelope(status_line, &body);

            assert_eq!(response.status, expected_status);
            assert_eq!(response.body, body);
        }
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
