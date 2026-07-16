from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_JS = ROOT / "apps/web/api.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_desktop_transport_preserves_http_errors_and_reserves_status_zero() -> None:
    script = f"""
const fs = require("fs");
const vm = require("vm");
globalThis.window = {{
  AgenticOs: {{}},
  __TAURI__: {{ core: {{ invoke: async () => ({{ status: 200, body: "{{}}" }}) }} }},
}};
globalThis.document = {{ getElementById: () => null }};
vm.runInThisContext(fs.readFileSync({str(API_JS)!r}, "utf8"));
const Ao = window.AgenticOs;
Ao.setConnectionProfile({{ mode: "remote" }});

(async () => {{
  for (const status of [401, 403, 409, 422, 500]) {{
    window.__TAURI__.core.invoke = async () => ({{
      status,
      body: JSON.stringify({{ detail: `status-${{status}}` }}),
    }});
    try {{
      await Ao.apiFetch("/contract");
      throw new Error(`status ${{status}} did not reject`);
    }} catch (error) {{
      if (error.status !== status) throw error;
      if (error.payload.detail !== `status-${{status}}`) throw error;
    }}
  }}

  window.__TAURI__.core.invoke = async () => {{
    throw new Error("offline");
  }};
  try {{
    await Ao.apiFetch("/contract");
    throw new Error("transport failure did not reject");
  }} catch (error) {{
    if (error.status !== 0) throw error;
  }}
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
