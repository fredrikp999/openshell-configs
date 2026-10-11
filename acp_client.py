#!/usr/bin/env python3
"""Minimal ACP (Agent Client Protocol) client for agents in OpenShell sandboxes.

  ./acp_client.py list
  ./acp_client.py connect <sandbox> [--agent opencode|claude] [--model M]
                                    [--cwd DIR] [--timeout SEC] [-v]

`connect` starts the agent's ACP server in the sandbox with
`openshell sandbox exec` and talks JSON-RPC over its stdin and stdout. Type a
prompt and press Enter to send it.

  /help   show the commands        /quit   leave (also Ctrl-D)
  /models [FILTER]   list the models the agent offers (current one marked)
  /model ID          switch model for this session
  /commands          list the agent's own slash commands (e.g. /init, /review)
  Ctrl-C  cancel the running prompt (when idle: leave)

Tool permission requests are asked on the terminal. The client advertises no fs
or terminal capability, so the agent uses its own tools inside the sandbox and
never touches the host. With -v, JSON-RPC traffic and the agent's stderr are
shown; otherwise stderr is only shown when something fails.

Exit codes: 0 ok, 1 error talking to the agent, 2 bad usage or sandbox.
Python 3.8+, standard library only.
"""
import argparse
import collections
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

DEFAULT_MODEL = "openrouter/nvidia/nemotron-3.5-lightning:free"
AGENT_CMD = {
    "opencode": ["opencode", "acp"],
    "claude": ["claude-acp-start"],
}
INIT_TIMEOUT = 60  # seconds to wait for initialize / session/new

USE_COLOR = sys.stderr.isatty() and sys.stdout.isatty() and "NO_COLOR" not in os.environ


# Everything the agent sends is untrusted. Terminal control characters in it
# (escape sequences, carriage returns, C1 controls) could rewrite what is on
# screen, e.g. disguise a permission prompt, or reach terminal features such as
# OSC 52 clipboard writes. Bidi overrides could reorder displayed text. They are
# removed from every agent message and log line before anything is printed.
_UNSAFE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def clean(v):
    """Strip terminal control characters from a string, or from all strings in a JSON value."""
    if isinstance(v, str):
        return _UNSAFE.sub("", v)
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {clean(k): clean(x) for k, x in v.items()}
    return v


def style(text, code):
    return "\033[%sm%s\033[0m" % (code, text) if USE_COLOR else text


def info(msg):
    print(style(msg, "2"), file=sys.stderr)


def warn(msg):
    print(style("warning: " + msg, "33"), file=sys.stderr)


def die(msg, code=2):
    print(style("error: ", "31;1") + msg, file=sys.stderr)
    sys.exit(code)


class AgentError(Exception):
    """The agent process failed, exited, or did not answer."""


# --- openshell --------------------------------------------------------------

def run_openshell(*args):
    if not shutil.which("openshell"):
        die("`openshell` not found in PATH. See README 'Install OpenShell'.")
    try:
        r = subprocess.run(["openshell"] + list(args), capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        die("`openshell %s` timed out after 30s. Is the gateway running? Try `openshell status`."
            % " ".join(args), 1)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip() or "exit code %d" % r.returncode
        die("`openshell %s` failed:\n%s\nTry `openshell status`." % (" ".join(args), msg), 1)
    return r.stdout


def sandboxes():
    """Return [(name, phase)] parsed from `openshell sandbox list`."""
    rows = [l.split() for l in run_openshell("sandbox", "list").splitlines()[1:] if l.strip()]
    return [(r[0], r[-1]) for r in rows]


def list_sandboxes():
    out = run_openshell("sandbox", "list")
    print(out, end="")
    if len(out.strip().splitlines()) <= 1:
        info("No sandboxes. Create one with ./sandbox.sh <claude|opencode> [name].")
    else:
        info("Connect with: ./acp_client.py connect <name>")


def check_sandbox(name):
    found = dict(sandboxes())
    if name not in found:
        names = ", ".join(sorted(found)) or "none"
        die("no sandbox named '%s' (existing: %s).\nCreate it with ./sandbox.sh <agent> %s"
            % (name, names, name))
    if found[name] != "Ready":
        die("sandbox '%s' is %s, not Ready. Wait for it, or delete it with "
            "`openshell sandbox delete %s` and create it again." % (name, found[name], name))


# --- ACP over a subprocess --------------------------------------------------

class Acp:
    """JSON-RPC over the agent process's stdin/stdout, one JSON object per line."""

    def __init__(self, cmd, verbose):
        self.verbose = verbose
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1)
        except OSError as e:
            raise AgentError("cannot start %s: %s" % (cmd[0], e))
        self.inbox = queue.Queue()
        self.stderr_tail = collections.deque(maxlen=15)  # shown when something fails
        self.next_id = 0
        self.config_options = []   # session config (model, mode, ...) as sent by the agent
        self.commands = []         # agent slash commands from available_commands_update
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = clean(json.loads(line))
            except ValueError:
                # Something other than JSON-RPC on stdout, e.g. a banner or a pty-mangled line.
                line = clean(line)
                self.stderr_tail.append("(stdout, not JSON) " + line)
                if self.verbose:
                    warn("agent stdout is not JSON: " + line)
                continue
            if self.verbose:
                info("<- " + clean(line))
            self.inbox.put(msg)
        self.inbox.put(None)  # EOF: the agent exited

    def _read_stderr(self):
        for line in self.proc.stderr:
            line = clean(line.rstrip())
            self.stderr_tail.append(line)
            if self.verbose:
                info("[agent] " + line)

    def _send(self, msg):
        msg["jsonrpc"] = "2.0"
        line = json.dumps(msg)
        if self.verbose:
            info("-> " + line)
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise self._exited()

    def _exited(self):
        """Build the error for a dead agent, with its last stderr lines and a hint."""
        try:
            code = self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            code = None
        time.sleep(0.2)  # let the stderr thread drain
        tail = "\n".join("  " + l for l in self.stderr_tail)
        text = "the agent process exited" + (" (code %s)" % code if code is not None else "")
        if tail:
            text += ". Last output:\n" + tail
        low = tail.lower()
        if "not found" in low or "no such file" in low or "executable file" in low:
            text += "\nHint: the agent command is missing from the sandbox image (see README 'ACP')."
        elif code is None or not tail:
            text += "\nHint: check `openshell status`, and try with -v."
        return AgentError(text)

    def notify(self, method, params):
        self._send({"method": method, "params": params})

    def request(self, method, params, timeout=None):
        """Send a request and wait for its response, handling agent messages meanwhile.

        Ctrl-C while waiting cancels the session (for session/prompt) and keeps waiting
        for the agent's answer, so the request/response stay in step.
        """
        self.next_id += 1
        rid = self.next_id
        self._send({"id": rid, "method": method, "params": params})
        deadline = time.time() + timeout if timeout else None
        cancelled = False
        while True:
            try:
                wait = max(0.1, deadline - time.time()) if deadline else None
                msg = self.inbox.get(timeout=wait)
            except queue.Empty:
                raise AgentError("no answer to %s after %ds.%s" % (
                    method, timeout, self._tail_text()))
            except KeyboardInterrupt:
                if method == "session/prompt" and not cancelled:
                    cancelled = True
                    print(style("\n[cancelling...]", "33"))
                    self.notify("session/cancel", {"sessionId": params["sessionId"]})
                    continue
                raise
            if msg is None:
                raise self._exited()
            if msg.get("id") == rid and "method" not in msg:
                if "error" in msg:
                    raise RpcError(method, msg["error"])
                return msg.get("result") or {}
            self._handle(msg)

    def _tail_text(self):
        return ("\nLast agent output:\n" + "\n".join("  " + l for l in self.stderr_tail)
                if self.stderr_tail else "")

    def _handle(self, msg):
        method = msg.get("method")
        if method == "session/update":
            u = msg.get("params", {}).get("update", {})
            if u.get("sessionUpdate") == "available_commands_update":
                self.commands = u.get("availableCommands", [])
            elif u.get("sessionUpdate") == "config_option_update":
                self.config_options = u.get("configOptions", self.config_options)
            show_update(u, self.verbose)
        elif method == "session/request_permission":
            self._send({"id": msg["id"], "result": ask_permission(msg.get("params", {}))})
        elif "id" in msg and method:
            # Anything else the agent asks of us (fs/*, terminal/*) is refused.
            info("refused agent request: " + method)
            self._send({"id": msg["id"],
                        "error": {"code": -32601, "message": "not supported: " + method}})

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class RpcError(Exception):
    """The agent answered a request with a JSON-RPC error."""

    def __init__(self, method, err):
        self.method, self.err = method, err if isinstance(err, dict) else {"message": str(err)}
        super().__init__(self.describe())

    def describe(self):
        msg = self.err.get("message", "unknown error")
        data = self.err.get("data")
        text = "%s failed: %s (code %s)" % (self.method, msg, self.err.get("code", "?"))
        if data:
            text += " " + json.dumps(data)
        low = msg.lower()
        if "cannot connect to api" in low or "unable to connect" in low:
            text += ("\nHint: the model's API host is probably blocked by the sandbox policy, or the "
                     "model is wrong. Try another --model, or check the provider (README 'Network rules').")
        elif "auth" in low or "401" in low or "api key" in low:
            text += "\nHint: the provider credential is missing or wrong (README 'Credentials in .env')."
        return text


# --- output -----------------------------------------------------------------

def show_update(u, verbose):
    kind = u.get("sessionUpdate")
    if kind == "agent_message_chunk":
        c = u.get("content", {})
        if c.get("type") == "text":
            sys.stdout.write(c["text"])
            sys.stdout.flush()
    elif kind == "agent_thought_chunk":
        c = u.get("content", {})
        if verbose and c.get("type") == "text":
            sys.stdout.write(style(c["text"], "2"))
            sys.stdout.flush()
    elif kind == "tool_call":
        print(style("\n[tool] %s (%s)" % (u.get("title") or u.get("toolCallId"),
                                          u.get("status", "pending")), "36"))
    elif kind == "tool_call_update" and u.get("status") in ("completed", "failed"):
        colour = "32" if u["status"] == "completed" else "31"
        print(style("[tool] %s %s" % (u.get("title") or u.get("toolCallId"), u["status"]), colour))
    elif kind == "plan":
        for e in u.get("entries", []):
            print(style("[plan] %s %s" % (e.get("status", ""), e.get("content", "")), "36"))
    elif verbose:
        info("[update] " + str(kind))


def ask_permission(params):
    tool = params.get("toolCall", {})
    options = params.get("options", [])
    # The title is the agent's own description, so also show what the tool will
    # actually do: its kind and raw input (e.g. the command line or file path).
    print(style("\n[permission] the agent wants to: %s" % (tool.get("title") or tool.get("toolCallId")), "33;1"))
    print("  kind:  %s" % (tool.get("kind") or "unknown"))
    raw = tool.get("rawInput")
    if raw not in (None, {}, ""):
        text = json.dumps(raw, indent=2, ensure_ascii=False) if not isinstance(raw, str) else raw
        lines = text.splitlines()
        print("  input: " + "\n         ".join(lines[:20]))
        if len(lines) > 20:
            print("         ... (%d more lines, see -v)" % (len(lines) - 20))
    else:
        print("  input: (not given by the agent; the title above is all there is)")
    for loc in tool.get("locations") or []:
        print("  path:  %s" % loc.get("path"))
    if not options:
        return {"outcome": {"outcome": "cancelled"}}
    for i, o in enumerate(options):
        print("  %d) %s (%s)" % (i + 1, o.get("name"), o.get("kind")))
    while True:
        try:
            choice = input("choose [1-%d, empty = deny/cancel]: " % len(options)).strip()
        except (EOFError, KeyboardInterrupt):
            choice = ""
        if not choice:
            return {"outcome": {"outcome": "cancelled"}}
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return {"outcome": {"outcome": "selected",
                                "optionId": options[int(choice) - 1]["optionId"]}}
        print("  not a valid choice")


HELP = ("Type a prompt and press Enter. Commands: /models, /model ID, /commands, /help, /quit "
        "(or Ctrl-D). Ctrl-C cancels a running prompt.")


def model_option(acp):
    for o in acp.config_options:
        if o.get("category") == "model" or o.get("id") == "model":
            return o
    return None


def cmd_models(acp, flt):
    o = model_option(acp)
    if not o:
        print("The agent did not offer a model list. Use --model at startup instead.")
        return
    cur = o.get("currentValue")
    rows = [x for x in o.get("options", []) if flt.lower() in (x["value"] + x.get("name", "")).lower()]
    for x in rows:
        print("%s %s" % ("*" if x["value"] == cur else " ", x["value"]))
    print(style("%d of %d models%s. Current: %s (*). Switch with /model ID."
                % (len(rows), len(o.get("options", [])), " matching '%s'" % flt if flt else "", cur), "2"))


def cmd_model(acp, session, value):
    o = model_option(acp)
    if not value:
        print("Usage: /model ID   (see /models)")
        return
    if o and value not in [x["value"] for x in o.get("options", [])]:
        print("Unknown model '%s'. List them with /models [FILTER]." % value)
        return
    try:
        res = acp.request("session/set_config_option", {
            "sessionId": session, "configId": o["id"] if o else "model", "value": value}, timeout=30)
    except RpcError as e:
        print(style("error: " + str(e), "31"), file=sys.stderr)
        return
    acp.config_options = res.get("configOptions", acp.config_options)
    print(style("Model is now %s" % value, "32"))


def cmd_commands(acp):
    if not acp.commands:
        print("The agent has not announced any slash commands.")
    for c in acp.commands:
        print("/%-18s %s" % (c.get("name"), (c.get("description") or "")[:80]))
    print(style("Agent commands are sent to the agent as a prompt, e.g. '/init'.", "2"))


def connect(args):
    check_sandbox(args.sandbox)
    cmd = ["openshell", "sandbox", "exec", args.sandbox, "--no-tty", "--no-login-shell",
           "--workdir", args.cwd]
    if args.agent == "opencode":
        # `opencode acp` has no -m flag; pick the model through its config env.
        cmd += ["--env", "OPENCODE_CONFIG_CONTENT=" + json.dumps({"model": args.model})]
    cmd += ["--"] + AGENT_CMD[args.agent]
    if args.verbose:
        info("$ " + " ".join(cmd))

    info("Starting %s in sandbox %s..." % (args.agent, args.sandbox))
    try:
        acp = Acp(cmd, args.verbose)
    except AgentError as e:
        die(str(e), 1)
    try:
        init = acp.request("initialize", {
            "protocolVersion": 1, "clientCapabilities": {},
            "clientInfo": {"name": "acp_client.py", "version": "0.2"}}, timeout=args.timeout)
        agent = init.get("agentInfo", {})
        new = acp.request("session/new", {"cwd": args.cwd, "mcpServers": []},
                          timeout=args.timeout)
        session = new.get("sessionId")
        acp.config_options = new.get("configOptions", [])
        if not session:
            raise AgentError("session/new returned no sessionId")
        print(style("Connected to %s %s" % (agent.get("name", args.agent), agent.get("version", "")), "32;1"))
        info("sandbox %s, directory %s%s, session %s" % (
            args.sandbox, args.cwd,
            ", model " + args.model if args.agent == "opencode" else "", session))
        info(HELP)

        while True:
            try:
                raw = input(style("\n> ", "1"))
                text = raw.strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/help":
                info(HELP)
                continue
            if text == "/models" or text.startswith("/models "):
                cmd_models(acp, text[7:].strip())
                continue
            if text == "/model" or text.startswith("/model "):
                cmd_model(acp, session, text[6:].strip())
                continue
            if text == "/commands":
                cmd_commands(acp)
                continue
            word = text.split()[0]
            if word.startswith("/") and not raw.startswith(" ") and word[1:] not in [c.get("name") for c in acp.commands]:
                # Not a client command and not announced by the agent: it would only reach the
                # model as plain text, which looks like "no answer".
                print("Unknown command %s. See /help, or /commands for the agent's own. "
                      "To send it as plain text, start with a space." % word)
                continue
            start = time.time()
            try:
                result = acp.request("session/prompt", {
                    "sessionId": session, "prompt": [{"type": "text", "text": text}]})
            except RpcError as e:
                # The agent is alive but this prompt failed. Keep the session.
                print(style("\nerror: " + str(e), "31"), file=sys.stderr)
                continue
            reason = result.get("stopReason", "?")
            note = "" if reason == "end_turn" else ", " + reason
            print(style("\n[done in %.1fs%s]" % (time.time() - start, note), "2"))
            if reason == "refusal":
                warn("the agent refused the request")
    except AgentError as e:
        print(style("\nerror: ", "31;1") + str(e), file=sys.stderr)
        return 1
    except RpcError as e:
        print(style("\nerror: ", "31;1") + str(e), file=sys.stderr)
        return 1
    finally:
        acp.close()
    return 0


EXAMPLES = """\
Typical use:
  ./acp_client.py list                          1. see which sandboxes exist
  ./acp_client.py connect opencode-agent1       2. chat with the agent in one

A sandbox must exist and be Ready first. Create one with:
  ./sandbox.sh opencode [name]                  (or: ./sandbox.sh claude [name])
Then type a prompt at the '>' and press Enter. /help shows the commands.
See README, section 'ACP (Agent Client Protocol)'.
"""


def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__.split("\n\n")[0].split("\n")[0],
        epilog=EXAMPLES)
    sub = p.add_subparsers(dest="cmd", metavar="{list,connect}", title="commands")
    sub.add_parser("list", help="show the sandboxes you can connect to")
    c = sub.add_parser("connect", help="chat with the agent in a sandbox over ACP",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog=EXAMPLES)
    c.add_argument("sandbox")
    c.add_argument("--agent", choices=sorted(AGENT_CMD), default="opencode")
    c.add_argument("--model", default=os.environ.get("OPENCODE_MODEL", DEFAULT_MODEL),
                   help="OpenCode model (default: $OPENCODE_MODEL or %s)" % DEFAULT_MODEL)
    c.add_argument("--cwd", default="/sandbox", help="working directory inside the sandbox")
    c.add_argument("--timeout", type=int, default=INIT_TIMEOUT,
                   help="seconds to wait for the agent to start (default %d)" % INIT_TIMEOUT)
    c.add_argument("-v", "--verbose", action="store_true",
                   help="show JSON-RPC traffic, the agent's stderr and its thoughts")
    args = p.parse_args()
    if args.cmd is None:
        p.print_help(sys.stderr)
        return 2
    if args.cmd == "list":
        list_sandboxes()
        return 0
    return connect(args)


if __name__ == "__main__":
    sys.exit(main())
