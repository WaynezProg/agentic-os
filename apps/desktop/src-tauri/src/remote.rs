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
