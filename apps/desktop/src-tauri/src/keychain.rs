use keyring::Entry;

pub const KEYCHAIN_SERVICE: &str = "agentic-os";

/// Keychain account: `{remote_gateway}:{device_id}` under service `agentic-os`.
pub fn token_account(remote_gateway: &str, device_id: &str) -> String {
    let gateway = remote_gateway.trim().trim_end_matches('/');
    let device = device_id.trim();
    format!("{gateway}:{device}")
}

fn entry(remote_gateway: &str, device_id: &str) -> Result<Entry, String> {
    Entry::new(KEYCHAIN_SERVICE, &token_account(remote_gateway, device_id))
        .map_err(|error| error.to_string())
}

pub fn save_remote_token(
    remote_gateway: &str,
    device_id: &str,
    token: &str,
) -> Result<(), String> {
    if remote_gateway.trim().is_empty() {
        return Err("remote_gateway is required".to_string());
    }
    if device_id.trim().is_empty() {
        return Err("device_id is required".to_string());
    }
    if token.trim().is_empty() {
        return Err("token is required".to_string());
    }
    entry(remote_gateway, device_id)?
        .set_password(token)
        .map_err(|error| error.to_string())
}

pub fn load_remote_token(remote_gateway: &str, device_id: &str) -> Result<Option<String>, String> {
    if remote_gateway.trim().is_empty() || device_id.trim().is_empty() {
        return Ok(None);
    }
    match entry(remote_gateway, device_id)?.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(error.to_string()),
    }
}

pub fn delete_remote_token(remote_gateway: &str, device_id: &str) -> Result<(), String> {
    if remote_gateway.trim().is_empty() || device_id.trim().is_empty() {
        return Ok(());
    }
    match entry(remote_gateway, device_id)?.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(error.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_account_normalizes_gateway_trailing_slash() {
        assert_eq!(
            token_account("https://gw.example/", "dev-1"),
            "https://gw.example:dev-1"
        );
    }

    #[test]
    fn token_account_trims_whitespace() {
        assert_eq!(
            token_account(" https://gw.example ", " dev-1 "),
            "https://gw.example:dev-1"
        );
    }
}
