# Desktop Operator Experience and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fifteen top-level tabs with six daily-use areas, add Environment and Change views, preserve mature subviews, and ship a verified macOS package.

**Architecture:** A small navigation module maps six areas to existing and new panels. No frontend framework or build system is introduced. Environment and Change modules consume the new normalized APIs; existing modules remain responsible for their detailed editors and session tools.

**Tech Stack:** Static HTML, vanilla JavaScript, CSS, FastAPI JSON APIs, Tauri 2, pytest static contracts, headless Chrome visual QA, cargo/pnpm release build.

## Global Constraints

- Sidebar areas are Home, Environments, Sessions, Capabilities, Changes, Settings.
- There is no hidden legacy top-level navigation mode.
- Chat is a Sessions subview.
- Existing DOM IDs needed by mature modules remain stable until their code is migrated.
- UI is Traditional Chinese; technical terms may remain English.
- Keyboard focus, loading, empty, degraded, error, and narrow-width states are mandatory.
- No React, Vue, Svelte, Vite, Webpack, or Web package manifest.

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/web/ui/navigation.js` | Six-area route/subview state and loader dispatch |
| `apps/web/ui/data-cache.js` | In-flight request deduplication and short snapshot cache |
| `apps/web/ui/environment-manager.js` | Environment list/detail/actions |
| `apps/web/ui/change-center.js` | Plan preview/apply/verification/history/rollback |
| `apps/web/index.html` | New sidebar, area headers, view switchers, panel placement |
| `apps/web/app.js` | Bootstrap and compatibility loader exports |
| `apps/web/api.js` | New Environment/Change endpoint map |
| `apps/web/styles.css` | Six-area layout, cards, status, responsive/focus states |
| `apps/web/i18n.js` | New zh-TW labels and statuses |
| `tests/test_web.py` | Navigation, endpoint, accessibility, and no-build contracts |
| `scripts/smoke-product.sh` | Environment/Change behavior smoke |
| `README.md` | Daily-use and package verification |

### Task 1: Six-area navigation shell

**Interfaces:**

- Produces: `Ao.Navigation.init()`, `show(area, view)`, `current()`.
- Consumes: existing loader functions exposed by `app.js` and UI modules.

- [x] **Step 1: Replace the old tab-count test**

Update `tests/test_web.py`:

```python
def test_six_operator_areas_are_present() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.count('data-area="') == 6
    for area, label in [
        ("home", "首頁"),
        ("environments", "環境"),
        ("sessions", "工作階段"),
        ("capabilities", "能力"),
        ("changes", "變更"),
        ("settings", "設定"),
    ]:
        assert f'data-area="{area}"' in html
        assert label in html
    assert html.count('role="tab"') != 15
```

Add:

```python
def test_navigation_module_is_loaded_before_app() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.index('src="ui/navigation.js"') < html.index('src="app.js"')
```

- [x] **Step 2: Verify failure**

```bash
rtk uv run pytest tests/test_web.py -k "six_operator_areas or navigation_module" -q
```

- [x] **Step 3: Create navigation module**

Create `apps/web/ui/navigation.js`:

```javascript
"use strict";

(() => {
  const Ao = window.AgenticOs;
  const AREA_VIEWS = Object.freeze({
    home: ["overview"],
    environments: ["environment-list", "tools", "agentic", "agents", "harnesses", "fleet"],
    sessions: ["chat", "vibe-coding", "sessions", "logs", "memory"],
    capabilities: ["skills", "catalog"],
    changes: ["change-center", "approvals", "audit"],
    settings: ["settings-home"],
  });
  let activeArea = "home";
  let activeView = "overview";

  function show(area, view = AREA_VIEWS[area]?.[0]) {
    if (!AREA_VIEWS[area] || !AREA_VIEWS[area].includes(view)) {
      throw new Error(`Unknown navigation target: ${area}/${view}`);
    }
    activeArea = area;
    activeView = view;
    document.querySelectorAll("[data-area]").forEach((button) => {
      const selected = button.dataset.area === area;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-current", selected ? "page" : "false");
    });
    document.querySelectorAll("[data-view]").forEach((panel) => {
      panel.hidden = panel.dataset.view !== view;
    });
    document.dispatchEvent(
      new CustomEvent("agentic-os:navigation", { detail: { area, view } })
    );
  }

  function init() {
    document.querySelectorAll("[data-area]").forEach((button) => {
      button.addEventListener("click", () => show(button.dataset.area));
    });
    document.querySelectorAll("[data-open-view]").forEach((button) => {
      button.addEventListener("click", () => {
        show(button.dataset.openArea, button.dataset.openView);
      });
    });
    show(activeArea, activeView);
  }

  function current() {
    return { area: activeArea, view: activeView };
  }

  Ao.Navigation = { AREA_VIEWS, init, show, current };
})();
```

- [x] **Step 4: Refactor markup without deleting mature panels**

Replace sidebar buttons with six `data-area` buttons. Convert existing
`panel-*` sections to `data-view="<old-id>"`; retain their IDs and controls.
Add subview switchers inside Environments, Sessions, Capabilities, and Changes.

Initialize `Ao.Navigation` from `DOMContentLoaded`. Replace direct `showTab()`
calls with a compatibility function mapping old view IDs to the correct area.

- [x] **Step 5: Verify syntax and contracts**

```bash
node --check apps/web/ui/navigation.js
node --check apps/web/app.js
rtk uv run pytest tests/test_web.py -q
```

- [x] **Step 6: Commit**

```bash
git add apps/web/index.html apps/web/app.js apps/web/ui/navigation.js tests/test_web.py
git commit -m "feat: replace sidebar with six operator areas"
```

### Task 2: Shared page data cache

**Interfaces:**

- Produces: `Ao.DataCache.get(key, loader, ttlMs)`, `invalidate(prefix)`.
- Used by Home, Environment, provider switchboard, and dashboards.

- [x] **Step 1: Add static contract tests**

Assert `data-cache.js` is loaded and dashboard modules call
`Ao.DataCache.get()` for sessions, approvals, fleet, and workspace dashboard.

- [x] **Step 2: Create module**

Create `apps/web/ui/data-cache.js`:

```javascript
"use strict";

(() => {
  const cache = new Map();
  const inflight = new Map();

  async function get(key, loader, ttlMs = 1000) {
    const now = Date.now();
    const current = cache.get(key);
    if (current && now - current.createdAt <= ttlMs) {
      return current.value;
    }
    if (inflight.has(key)) {
      return inflight.get(key);
    }
    const request = Promise.resolve(loader())
      .then((value) => {
        cache.set(key, { value, createdAt: Date.now() });
        return value;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, request);
    return request;
  }

  function invalidate(prefix = "") {
    for (const key of cache.keys()) {
      if (key.startsWith(prefix)) cache.delete(key);
    }
  }

  window.AgenticOs.DataCache = { get, invalidate };
})();
```

- [x] **Step 3: Rewire repeated reads**

Use stable keys:

- `workspace-dashboard`
- `sessions`
- `approvals-pending`
- `fleet-health`
- `fleet-capacity`
- `environments`
- `changes`

Invalidate relevant prefixes after mutation actions.

- [x] **Step 4: Verify**

```bash
node --check apps/web/ui/data-cache.js
node --check apps/web/ui/daily-dashboard.js
node --check apps/web/ui/dashboard-v2.js
rtk uv run pytest tests/test_web.py -q
```

- [x] **Step 5: Commit**

```bash
git add apps/web/ui/data-cache.js apps/web/ui/daily-dashboard.js apps/web/ui/dashboard-v2.js apps/web/ui/provider-switchboard.js apps/web/index.html tests/test_web.py
git commit -m "refactor: deduplicate desktop data loading"
```

### Task 3: Environment list and detail

**Interfaces:**

- Consumes: `GET /environments`, detail, refresh routes.
- Produces: Environment area list, detail, status cards, action links.

- [x] **Step 1: Add endpoint map and Web tests**

In `api.js` add:

```javascript
environments: "/environments",
environmentDetail: "/environments/{environment_id}",
environmentsRefresh: "/environments/refresh",
environmentRefresh: "/environments/{environment_id}/refresh",
```

Add static tests for:

- `id="environment-list"`
- `id="environment-detail"`
- separate CLI/config/runtime surface labels;
- action-required copy;
- no innerHTML insertion of raw evidence values.

- [x] **Step 2: Implement module**

Create `apps/web/ui/environment-manager.js` with:

- `renderList(environments)`;
- `renderDetail(environment)`;
- `refreshAll()`;
- `refreshOne(id)`;
- delegated click handling for detail and refresh.

Every untrusted value passes through `Ao.escapeHtml`. Status labels map:

```javascript
const STATUS_LABELS = Object.freeze({
  healthy: "正常",
  degraded: "需處理",
  missing: "未安裝",
  configured_only: "僅有設定",
  auth_required: "需要登入",
  stale: "資料過期",
  unsupported: "不支援",
  unknown: "未知",
});
```

- [x] **Step 3: Add markup and styles**

Environment list uses rows/cards with name, overall status, CLI version,
configured surfaces, sessions, pending changes, and primary action. Detail uses
one surface card per observation with proof source and observed time.

- [x] **Step 4: Verify**

```bash
node --check apps/web/ui/environment-manager.js
rtk uv run pytest tests/test_web.py tests/test_api.py -k "environment or web" -q
```

- [x] **Step 5: Commit**

```bash
git add apps/web/api.js apps/web/index.html apps/web/styles.css apps/web/i18n.js apps/web/ui/environment-manager.js tests/test_web.py
git commit -m "feat: add desktop environment manager"
```

### Task 4: Change center

**Interfaces:**

- Consumes: `/changes` APIs.
- Produces: pending plans, verification, restart requirements, history, rollback.

- [x] **Step 1: Add endpoint map and contracts**

Add:

```javascript
changes: "/changes",
changePreview: "/changes/preview",
changeDetail: "/changes/{change_id}",
changeApply: "/changes/{change_id}/apply",
changeRollback: "/changes/{change_id}/rollback",
```

Static tests assert `change-center.js`, pending/history sections, verification
details, and no apply control for stale plans.

- [x] **Step 2: Implement module**

Create `apps/web/ui/change-center.js`. Render plan cards with:

- operation/environment;
- status;
- target surfaces;
- redacted diff;
- validation;
- restart requirements;
- verification checks;
- backup reference;
- apply or rollback action when allowed.

Apply is available only for `previewed`; rollback only for `verified` or
`partial` with a backup.

- [x] **Step 3: Connect existing editors**

After existing MCP/config/profile/registry dry-run calls return a `change_id`,
open the Change center detail. Existing confirm buttons call the unified apply
endpoint instead of the old direct apply request.

- [x] **Step 4: Verify**

```bash
node --check apps/web/ui/change-center.js
node --check apps/web/ui/tool-discovery.js
node --check apps/web/ui/config-editor.js
node --check apps/web/ui/profile-editor.js
node --check apps/web/ui/registry-editor.js
rtk uv run pytest tests/test_web.py tests/test_api.py -k "change or patch or rollback" -q
```

- [x] **Step 5: Commit**

```bash
git add apps/web/api.js apps/web/index.html apps/web/styles.css apps/web/i18n.js apps/web/ui/change-center.js apps/web/ui/tool-discovery.js apps/web/ui/config-editor.js apps/web/ui/profile-editor.js apps/web/ui/registry-editor.js tests/test_web.py
git commit -m "feat: add verified change center"
```

### Task 5: Group mature subviews under the six areas

- [x] **Step 1: Map all legacy views**

Use exactly:

```javascript
const LEGACY_VIEW_AREA = Object.freeze({
  overview: "home",
  tools: "environments",
  agentic: "environments",
  agents: "environments",
  harnesses: "environments",
  fleet: "environments",
  chat: "sessions",
  "vibe-coding": "sessions",
  sessions: "sessions",
  logs: "sessions",
  memory: "sessions",
  skills: "capabilities",
  catalog: "capabilities",
  approvals: "changes",
  audit: "changes",
});
```

Remove the old advanced-navigation group.

- [x] **Step 2: Settings home**

Add a Settings panel linking to:

- connection and paired devices;
- workspace selection;
- profiles/provider/model;
- run templates;
- diagnostics/log bundle;
- setup import/export;
- version and update status.

Reuse current controls and Tauri settings window; do not duplicate their write
logic.

- [x] **Step 3: Home attention model**

Home prioritizes:

1. failed/degraded environments;
2. stale or partial changes;
3. pending approvals;
4. active sessions;
5. recent verified changes.

Use cached endpoints and link each item to its owning area/view.

- [x] **Step 4: Verify reachability**

Extend `tests/test_web.py` to assert every old panel ID appears in
`LEGACY_VIEW_AREA` or is directly owned by Home/Settings. No feature may become
unreachable.

- [x] **Step 5: Commit**

```bash
git add apps/web/index.html apps/web/app.js apps/web/ui/navigation.js apps/web/ui/daily-dashboard.js apps/web/styles.css tests/test_web.py
git commit -m "refactor: group desktop features by operator workflow"
```

### Task 6: Accessibility and responsive QA

- [ ] **Step 1: Add static accessibility contracts**

Assert:

- sidebar has `aria-label`;
- active area uses `aria-current`;
- view switchers have accessible names;
- status is not color-only;
- every icon action has text or `aria-label`;
- main content has one visible `h1`;
- skip link targets main content.

- [ ] **Step 2: Add CSS**

Implement:

- `:focus-visible` outline with 3:1 contrast;
- 44×44 minimum primary action hit target;
- responsive two-column collapse below 1100 px;
- table overflow containers;
- no horizontal page overflow at 960 px;
- reduced-motion media query.

- [ ] **Step 3: Run headless visual checks**

Start local services, then capture:

```bash
chrome --headless=new --window-size=1440,1000 --screenshot=/tmp/agentic-os-home.png http://127.0.0.1:5173
chrome --headless=new --window-size=960,700 --screenshot=/tmp/agentic-os-narrow.png http://127.0.0.1:5173
```

Inspect Home, Environment detail, Sessions, Capabilities, Changes, and Settings.
Repair clipped content, hidden actions, broken focus order, or unreadable status.

- [ ] **Step 4: Verify**

```bash
node --check apps/web/app.js
for file in apps/web/ui/*.js; do node --check "$file"; done
rtk uv run pytest tests/test_web.py -q
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/index.html apps/web/styles.css apps/web/app.js apps/web/ui tests/test_web.py
git commit -m "fix: complete desktop accessibility and responsive states"
```

### Task 7: Product smoke and packaged macOS release proof

- [ ] **Step 1: Extend product smoke**

Update `scripts/smoke-product.sh` to verify:

- `/environments` returns adapters;
- one environment detail includes separate surfaces;
- change preview is non-mutating;
- apply verifies target;
- rollback verifies restoration;
- sessions and approvals remain operational.

- [ ] **Step 2: Run all automated gates**

```bash
rtk uv run pytest -q
rtk uv run ruff check .
cd apps/desktop/src-tauri && cargo test
cd /Users/waynetu/bootstrap/agentic-os
bash scripts/smoke-product.sh
bash scripts/smoke-remote-client.sh
pnpm desktop:build
```

- [ ] **Step 3: Inspect package artifact**

Verify:

```bash
test -d apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app
find apps/desktop/src-tauri/target/release/bundle -maxdepth 3 -type f | sort
codesign -dv --verbose=4 apps/desktop/src-tauri/target/release/bundle/macos/agentic-os.app
```

If no Developer ID identity exists, record that the build is locally signed or
unsigned and do not claim notarization.

- [ ] **Step 4: Lifecycle smoke**

Open the packaged app, verify health, quit from tray, and assert:

```bash
lsof -nP -iTCP:8767 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

Both commands must return no managed listeners after Quit. Relaunch and repeat.

- [ ] **Step 5: Signing/notarization/updater audit**

Check:

```bash
security find-identity -v -p codesigning
xcrun notarytool history --keychain-profile agentic-os
```

Only run notarization or publish an updater manifest when valid credentials and
an update endpoint are present. Otherwise add exact blockers to README and
`decision_log.md`.

- [ ] **Step 6: Final documentation and commit**

Update README daily-use instructions, phase table, test evidence, package path,
and release blockers. Append final architecture and verification evidence to
`decision_log.md`.

```bash
git add README.md CHANGELOG.md decision_log.md scripts/smoke-product.sh
git commit -m "docs: complete desktop release verification"
```

## Self-Review

- Spec coverage: Environment UI Task 3; Change center Task 4; six-area IA Tasks
  1 and 5; data consistency Task 2; accessibility Task 6; package/release Task 7.
- No frontend framework, dynamic adapter, workflow builder, or second runtime is
  introduced.
- All existing feature panels remain reachable through one navigation model.
- Signing/notarization/updater claims require exercised credentials.
