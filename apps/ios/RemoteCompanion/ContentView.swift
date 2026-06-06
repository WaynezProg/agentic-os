import SwiftUI

enum ConnectionState: String {
    case disconnected
    case connected
    case unauthorized
    case revoked
    case error
}

struct ContentView: View {
    @AppStorage("remote_gateway") private var remoteGateway = ""
    @AppStorage("device_id") private var deviceId = ""
    @State private var pairingCode = ""
    @State private var deviceName = ""
    @State private var statusText = "disconnected"
    @State private var eventsLine = ""
    @State private var isBusy = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Remote gateway") {
                    TextField("https://example.tailnet.ts.net", text: $remoteGateway)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    TextField("Device name", text: $deviceName)
                    TextField("Pairing code", text: $pairingCode)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section("Status") {
                    Text("State: \(statusText)")
                    if !deviceId.isEmpty {
                        Text("Device ID: \(deviceId)")
                            .font(.caption.monospaced())
                    }
                    if !eventsLine.isEmpty {
                        Text("SSE: \(eventsLine)")
                            .font(.caption.monospaced())
                    }
                }

                Section {
                    Button(isBusy ? "Working…" : "Pair") {
                        Task { await pair() }
                    }
                    .disabled(isBusy || remoteGateway.isEmpty || pairingCode.isEmpty || deviceName.isEmpty)

                    Button("Test /health + /events") {
                        Task { await probe() }
                    }
                    .disabled(isBusy || remoteGateway.isEmpty || deviceId.isEmpty)

                    Button("Forget token", role: .destructive) {
                        forgetToken()
                    }
                    .disabled(deviceId.isEmpty)
                }
            }
            .navigationTitle("agentic-os")
        }
    }

    private func pair() async {
        isBusy = true
        defer { isBusy = false }
        do {
            let gateway = try normalizedGatewayURL(remoteGateway)
            let client = RemoteClient(gatewayURL: gateway)
            let result = try await client.completePairing(
                pairingCode: pairingCode.trimmingCharacters(in: .whitespacesAndNewlines),
                deviceName: deviceName.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            try KeychainTokenStore.save(
                remoteGateway: remoteGateway,
                deviceId: result.deviceId,
                token: result.authToken
            )
            deviceId = result.deviceId
            pairingCode = ""
            statusText = ConnectionState.connected.rawValue
            try await probe()
        } catch RemoteClientError.unauthorized {
            statusText = ConnectionState.unauthorized.rawValue
        } catch {
            statusText = ConnectionState.error.rawValue
            eventsLine = error.localizedDescription
        }
    }

    private func probe() async {
        isBusy = true
        defer { isBusy = false }
        do {
            let gateway = try normalizedGatewayURL(remoteGateway)
            guard let token = KeychainTokenStore.load(remoteGateway: remoteGateway, deviceId: deviceId) else {
                statusText = ConnectionState.disconnected.rawValue
                eventsLine = "No token in Keychain"
                return
            }
            let client = RemoteClient(gatewayURL: gateway)
            let healthy = try await client.health(token: token)
            guard healthy else {
                statusText = ConnectionState.error.rawValue
                return
            }
            let line = try await client.eventsProbe(token: token)
            eventsLine = line
            statusText = ConnectionState.connected.rawValue
        } catch RemoteClientError.unauthorized {
            statusText = ConnectionState.revoked.rawValue
            eventsLine = "401 unauthorized"
        } catch {
            statusText = ConnectionState.error.rawValue
            eventsLine = error.localizedDescription
        }
    }

    private func forgetToken() {
        KeychainTokenStore.delete(remoteGateway: remoteGateway, deviceId: deviceId)
        deviceId = ""
        pairingCode = ""
        eventsLine = ""
        statusText = ConnectionState.disconnected.rawValue
    }
}

#Preview {
    ContentView()
}
