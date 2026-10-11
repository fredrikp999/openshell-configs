// Minimal MCP client for tests: initialize, then call one tool, and check
// that the call got the expected outcome.
//
//   node mcp_probe.js <url> <tool> <allow|deny>
//
// allow: the call must succeed (HTTP 200 with a JSON-RPC result).
// deny:  OpenShell must block it (HTTP 403 with policy_denied).
// Exit code 0 if the outcome matches, 1 if not.
const [url, tool, expect] = process.argv.slice(2);
const headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"};
const args = {echo: {message: "hi"}, "get-sum": {a: 1, b: 2}}[tool] || {};

async function post(body, extra = {}) {
  const r = await fetch(url, {method: "POST", headers: {...headers, ...extra}, body: JSON.stringify(body)});
  return {status: r.status, session: r.headers.get("mcp-session-id"), text: await r.text()};
}

(async () => {
  let ok = false, detail;
  try {
    const init = await post({jsonrpc: "2.0", id: 1, method: "initialize", params: {
      protocolVersion: "2025-06-18", capabilities: {}, clientInfo: {name: "mcp_probe", version: "1"}}});
    if (init.status !== 200) throw new Error("initialize: HTTP " + init.status + " " + init.text);
    const session = init.session ? {"mcp-session-id": init.session, "mcp-protocol-version": "2025-06-18"} : {};
    await post({jsonrpc: "2.0", method: "notifications/initialized"}, session);
    const call = await post({jsonrpc: "2.0", id: 2, method: "tools/call", params: {name: tool, arguments: args}}, session);
    detail = "HTTP " + call.status + " " + call.text.replace(/\s+/g, " ").slice(0, 150);
    ok = expect === "allow" ? call.status === 200 && call.text.includes('"result"')
                            : call.status === 403 && call.text.includes("policy_denied");
  } catch (e) {
    detail = "error " + (e.cause ? e.cause.code || e.cause.message : e.message);
  }
  console.log("%s %s (expected %s): %s", ok ? "PASS" : "FAIL", tool, expect, detail);
  process.exit(ok ? 0 : 1);
})();
