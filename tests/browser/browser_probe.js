// Minimal MCP client for tests: start Playwright MCP over stdio, open one URL
// with browser_navigate, and check that the page loaded or was blocked.
//
//   node browser_probe.js <url> <allow|deny> [server command...]
//
// The server command defaults to playwright-mcp-start (see images/claude-browser).
// allow: the page must load (the result has no error and shows the page).
// deny:  the page must not load (the browser reports a network error).
// Exit code 0 if the outcome matches, 1 if not.
const {spawn} = require("child_process");
const [url, expect, ...cmd] = process.argv.slice(2);

const mcp = spawn(cmd[0] || "playwright-mcp-start", cmd.slice(1), {stdio: ["pipe", "pipe", "inherit"]});
const pending = new Map();
let buf = "";
mcp.stdout.on("data", d => {
  buf += d;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i); buf = buf.slice(i + 1);
    if (!line.trim()) continue;
    const msg = JSON.parse(line);
    if (pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  }
});
let id = 0;
function send(method, params) {
  const msg = {jsonrpc: "2.0", method, params};
  if (method.startsWith("notifications/")) { mcp.stdin.write(JSON.stringify(msg) + "\n"); return; }
  msg.id = ++id;
  mcp.stdin.write(JSON.stringify(msg) + "\n");
  return new Promise(r => pending.set(msg.id, r));
}

(async () => {
  let ok = false, detail;
  try {
    await send("initialize", {protocolVersion: "2025-06-18", capabilities: {},
      clientInfo: {name: "browser_probe", version: "1"}});
    send("notifications/initialized");
    const r = await send("tools/call", {name: "browser_navigate", arguments: {url}});
    const text = (r.result?.content || []).map(c => c.text || "").join(" ");
    const failed = !!r.error || r.result?.isError || /net::ERR_/.test(text);
    detail = (r.error ? JSON.stringify(r.error) : text).replace(/\s+/g, " ").slice(0, 200);
    ok = expect === "allow" ? !failed : failed && /net::ERR_/.test(text);
  } catch (e) {
    detail = "error " + e.message;
  }
  console.log("%s %s (expected %s): %s", ok ? "PASS" : "FAIL", url, expect, detail);
  mcp.kill();
  process.exit(ok ? 0 : 1);
})();
