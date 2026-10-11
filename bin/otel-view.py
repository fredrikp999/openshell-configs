#!/usr/bin/env python3
"""Extremely simple OpenTelemetry log viewer for the terminal.

  bin/otel-view.py [FILE|-] [--where K=V ...] [-v]
  bin/otel-view.py --listen [PORT] [--where K=V ...] [-v]

  bin/otel-view.py sandboxes.otlp.jsonl                       # a file from otel-export.py --out
  bin/otel-export.py --out - --follow | bin/otel-view.py      # live
  bin/otel-view.py --where ocsf.action=Denied sandboxes.otlp.jsonl
  bin/otel-view.py --listen                                   # OTLP/HTTP on 127.0.0.1:4318
  bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow

Prints one line per log record: time, sandbox (or service.name), severity,
action, target and message. -v adds every attribute under the line.
--where keeps only records where an attribute (of the record or its resource)
equals a value; give it several times to require all of them.

Input is OTLP/JSON: one ExportLogsServiceRequest per line, as written by
otel-export.py --out or the Collector's file exporter. --listen accepts the
same JSON POSTed to /v1/logs, on 127.0.0.1 only. It doesn't speak protobuf, so
other OTLP senders need their JSON encoding (e.g. http/json).

Python 3.8+, standard library only.
"""
import argparse
import http.server
import json
import os
import re
import sys
import time

# The records describe what an agent did (hosts, URLs, process names), so they
# are untrusted: terminal control characters are removed before printing.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")
COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def clean(s):
    return _UNSAFE.sub("", str(s))


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def value(v):
    """OTLP AnyValue -> Python value."""
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "boolValue" in v:
        return v["boolValue"]
    if "arrayValue" in v:
        return [value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {kv["key"]: value(kv["value"]) for kv in v["kvlistValue"].get("values", [])}
    return ""


def attrs(kvs):
    return {kv["key"]: value(kv.get("value", {})) for kv in kvs or []}


def records(req):
    """(resource attributes, record attributes, record) for each log record."""
    for rl in req.get("resourceLogs", []):
        res = attrs(rl.get("resource", {}).get("attributes"))
        for sl in rl.get("scopeLogs", []):
            for r in sl.get("logRecords", []):
                yield res, attrs(r.get("attributes")), r


def show(req, where, verbose):
    for res, a, r in records(req):
        both = {**res, **a}
        if any(str(both.get(k)) != v for k, v in where):
            continue
        t = int(r.get("timeUnixNano") or r.get("observedTimeUnixNano") or 0) / 1e9
        who = res.get("openshell.sandbox.name") or res.get("service.name", "")
        sev = r.get("severityText") or str(r.get("severityNumber", ""))
        action = a.get("ocsf.action", "")
        target = a.get("server.address", "")
        if target and "server.port" in a:
            target += f":{a['server.port']}"
        if a.get("process.executable.path"):
            target += f" ({os.path.basename(a['process.executable.path'])})"
        body = value(r.get("body", {}))
        line = (f"{time.strftime('%H:%M:%S', time.localtime(t))}  {clean(who)[:14]:<14} "
                f"{clean(sev)[:13]:<13} {clean(action)[:7]:<7} {clean(target)[:45]:<45} {clean(body)}")
        if action == "Denied":
            line = paint(line, "31")
        elif r.get("severityNumber", 0) and r["severityNumber"] < 13 and not verbose:
            line = paint(line, "2")
        print(line)
        if verbose:
            for k, v in sorted(a.items()):
                print(paint(f"    {clean(k)} = {clean(v)}", "2"))
    sys.stdout.flush()


def show_line(line, where, verbose):
    line = line.strip()
    if not line:
        return
    try:
        show(json.loads(line), where, verbose)
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        print(paint("(skipped a line that isn't OTLP/JSON)", "33"), file=sys.stderr)


def listen(port, where, verbose):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path != "/v1/logs" or "json" not in self.headers.get("Content-Type", ""):
                self.send_response(415 if self.path == "/v1/logs" else 404)
                self.end_headers()
                return
            show_line(body.decode("utf-8", "replace"), where, verbose)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"listening on http://127.0.0.1:{port}/v1/logs (OTLP/HTTP JSON), Ctrl-C to stop",
          file=sys.stderr)
    server.serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("file", nargs="?", default="-", help="OTLP/JSON lines (default: stdin)")
    p.add_argument("--listen", nargs="?", const=4318, type=int, metavar="PORT",
                   help="receive OTLP/HTTP JSON instead (default port 4318)")
    p.add_argument("--where", action="append", default=[], metavar="K=V",
                   help="only records with this attribute value (repeatable)")
    p.add_argument("-v", "--verbose", action="store_true", help="show every attribute")
    args = p.parse_args()
    where = []
    for w in args.where:
        k, sep, v = w.partition("=")
        if not sep:
            p.error(f"--where needs K=V, got {w!r}")
        where.append((k, v))
    try:
        if args.listen:
            listen(args.listen, where, args.verbose)
        else:
            f = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
            for line in f:
                show_line(line, where, args.verbose)
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        sys.stderr.close()


if __name__ == "__main__":
    main()
