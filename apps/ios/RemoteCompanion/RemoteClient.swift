import Foundation

struct PairingResult: Decodable {
    let deviceId: String
    let authToken: String

    enum CodingKeys: String, CodingKey {
        case deviceId = "device_id"
        case authToken = "auth_token"
    }
}

enum RemoteClientError: LocalizedError {
    case invalidURL
    case insecureGateway
    case httpStatus(Int, String)
    case unauthorized
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid remote gateway URL"
        case .insecureGateway:
            return "Remote gateway must use https; http:// is allowed only for localhost"
        case .httpStatus(let code, let body):
            return "HTTP \(code): \(body)"
        case .unauthorized:
            return "Unauthorized or revoked token"
        case .invalidResponse:
            return "Invalid response from remote gateway"
        }
    }
}

struct RemoteClient {
    let gatewayURL: URL
    private let session: URLSession

    init(gatewayURL: URL, session: URLSession = .shared) {
        self.gatewayURL = gatewayURL
        self.session = session
    }

    func completePairing(pairingCode: String, deviceName: String) async throws -> PairingResult {
        let url = gatewayURL.appendingPathComponent("remote/pairing/complete")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: String] = [
            "pairing_code": pairingCode,
            "device_name": deviceName,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        return try await decode(PairingResult.self, request: request, bearerToken: nil)
    }

    func health(token: String?) async throws -> Bool {
        let url = gatewayURL.appendingPathComponent("health")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw RemoteClientError.invalidResponse
        }
        return (200...299).contains(http.statusCode)
    }

    func eventsProbe(token: String) async throws -> String {
        let url = gatewayURL.appendingPathComponent("events")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 3
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw RemoteClientError.invalidResponse
        }
        if http.statusCode == 401 {
            throw RemoteClientError.unauthorized
        }
        guard (200...299).contains(http.statusCode) else {
            throw RemoteClientError.httpStatus(http.statusCode, "")
        }
        for try await line in bytes.lines {
            guard line.hasPrefix(":") || line.contains("data:") else {
                throw RemoteClientError.invalidResponse
            }
            return line
        }
        throw RemoteClientError.invalidResponse
    }

    private func decode<T: Decodable>(
        _ type: T.Type,
        request: URLRequest,
        bearerToken: String?
    ) async throws -> T {
        var request = request
        if let bearerToken {
            request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw RemoteClientError.invalidResponse
        }
        if http.statusCode == 401 {
            throw RemoteClientError.unauthorized
        }
        guard (200...299).contains(http.statusCode) else {
            throw RemoteClientError.httpStatus(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

func normalizedGatewayURL(_ raw: String) throws -> URL {
    let trimmed = raw
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    guard let url = URL(string: trimmed), let scheme = url.scheme?.lowercased(), let host = url.host?.lowercased() else {
        throw RemoteClientError.invalidURL
    }
    guard scheme == "https" || scheme == "http" else {
        throw RemoteClientError.insecureGateway
    }
    if scheme == "http" && !isLoopbackHost(host) {
        throw RemoteClientError.insecureGateway
    }
    return url
}

private func isLoopbackHost(_ host: String) -> Bool {
    host == "127.0.0.1" || host == "localhost" || host == "::1"
}
