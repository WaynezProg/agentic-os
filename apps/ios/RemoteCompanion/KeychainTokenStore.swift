import Foundation
import Security

enum KeychainTokenStore {
    static let service = "agentic-os"

    static func account(remoteGateway: String, deviceId: String) -> String {
        let gateway = remoteGateway.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let device = deviceId.trimmingCharacters(in: .whitespacesAndNewlines)
        return "\(gateway):\(device)"
    }

    static func save(remoteGateway: String, deviceId: String, token: String) throws {
        let account = account(remoteGateway: remoteGateway, deviceId: deviceId)
        let data = Data(token.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var insert = query
        insert[kSecValueData as String] = data
        let status = SecItemAdd(insert as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.operationFailed(status)
        }
    }

    static func load(remoteGateway: String, deviceId: String) -> String? {
        let account = account(remoteGateway: remoteGateway, deviceId: deviceId)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    static func delete(remoteGateway: String, deviceId: String) {
        let account = account(remoteGateway: remoteGateway, deviceId: deviceId)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}

enum KeychainError: LocalizedError {
    case operationFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .operationFailed(let status):
            return "Keychain operation failed (\(status))"
        }
    }
}
