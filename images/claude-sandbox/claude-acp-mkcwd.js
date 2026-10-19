#!/usr/bin/env node
// Transparent ACP stdio proxy that auto-creates a requested `cwd` before the
// real claude-agent-acp sees it.
//
// Kiro Crew (and any ACP client assuming the agent shares its own filesystem)
// sends a `cwd` for session/new and session/load that exists on the CLIENT's
// machine. When the agent actually runs in an OpenShell sandbox, that path
// does not exist there, and claude-agent-acp refuses with "cwd does not exist
// on the machine running the agent". This proxy sits between the client and
// the real adapter: for every line it forwards, it looks for a string value
// at a "cwd" key anywhere in the parsed JSON and `mkdir -p`s it first, inside
// the sandbox, then forwards the ORIGINAL bytes unchanged. A path the
// sandbox's own filesystem policy refuses still fails exactly as before --
// this only creates directories the sandbox could already write to.
//
// Wire format: ACP over stdio is newline-delimited JSON (confirmed against
// @agentclientprotocol/sdk's LineBuffer), so splitting on "\n" is correct and
// does not need the Content-Length framing other protocols (e.g. LSP) use.
"use strict";
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

function findCwds(value, out) {
  if (value === null || typeof value !== "object") return;
  if (typeof value.cwd === "string") out.push(value.cwd);
  for (const key of Object.keys(value)) findCwds(value[key], out);
}

// Walks *target* one component at a time, creating any missing plain
// directory, and following a symlink it meets by its raw link text rather
// than fs.realpath -- realpath requires the target to already exist, and a
// baked-in symlink (e.g. images/claude-kirocrew-backend's /Users/.../kirocrew
// -> /sandbox/kirocrew-workspace) is exactly the case where it doesn't yet.
// fs.mkdirSync(cwd, {recursive: true}) cannot do this: given an existing
// symlink whose target is missing, it treats the symlink itself as "the
// parent is there", never creates what it points to, and the final mkdir
// still fails with ENOENT.
function ensurePath(target, depth = 0) {
  // A symlink's target can itself be missing (see the caller's comment) and can
  // in principle chain to another symlink, so a resolved target is ensured by
  // recursing into this same function -- bounded the way the kernel bounds
  // ELOOP, well past any real baked-image chain.
  if (depth > 40) {
    process.stderr.write(`claude-acp-mkcwd: too many symlink hops resolving ${target}\n`);
    return;
  }
  const parts = target.split("/").filter(Boolean);
  let current = "/";
  for (const part of parts) {
    const next = path.join(current, part);
    let stat;
    try {
      stat = fs.lstatSync(next);
    } catch {
      stat = null;
    }
    if (stat && stat.isSymbolicLink()) {
      const link = fs.readlinkSync(next);
      const resolved = path.isAbsolute(link) ? link : path.join(current, link);
      ensurePath(resolved, depth + 1);
      current = resolved;
      continue;
    }
    if (!stat) {
      try {
        fs.mkdirSync(next);
      } catch (err) {
        // Left to the real adapter's own validateCwd error -- same failure the
        // client would have seen without this proxy, just not pre-empted here.
        process.stderr.write(`claude-acp-mkcwd: could not create ${next}: ${err.code || err.message}\n`);
        return;
      }
    }
    current = next;
  }
}

function ensureCwds(line) {
  let parsed;
  try {
    parsed = JSON.parse(line);
  } catch {
    return; // not JSON (e.g. a blank line) -- forward as-is, nothing to do
  }
  const cwds = [];
  findCwds(parsed, cwds);
  for (const cwd of cwds) ensurePath(cwd);
}

const child = spawn(process.argv[2], process.argv.slice(3), {
  stdio: ["pipe", "inherit", "inherit"],
});
child.on("error", (err) => {
  process.stderr.write(`claude-acp-mkcwd: failed to start ${process.argv[2]}: ${err.message}\n`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  process.exit(signal ? 1 : (code ?? 1));
});

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line) => {
  ensureCwds(line);
  child.stdin.write(line + "\n");
});
rl.on("close", () => child.stdin.end());
