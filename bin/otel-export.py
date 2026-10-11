#!/usr/bin/env python3
"""Export OpenShell sandbox logs as OpenTelemetry (OTLP) logs.

  bin/otel-export.py --out FILE        [--sandbox NAME] [--since DUR] [--follow]
  bin/otel-export.py --endpoint URL    [--header K=V ...] [--sandbox NAME] [--since DUR] [--follow]

  bin/otel-export.py --out sandboxes.otlp.jsonl              # everything so far, to a file
  bin/otel-export.py --out - --since 1h --sandbox my-task    # last hour of one sandbox, to stdout
  bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # live, to a collector

The source is OpenShell's OCSF JSON export, which must be switched on once:

  openshell settings set --global --key ocsf_json_enabled --value true --yes

With the Podman driver, the sandbox supervisor prints each event as an
`OCSF-JSON {...}` line on its container output (not the file in /var/log that
the OpenShell docs describe), so this reads `podman logs` of every
`openshell-supervisor-*` container, i.e. all sandboxes, running or stopped.
With --follow it keeps streaming, and picks up new sandboxes every 10 seconds.

Each OCSF event becomes one OTLP log record:
  * resource: service.name=openshell-sandbox, openshell.sandbox.name/.id,
    container.image.name, host.name - one resource per sandbox
  * time from the event, severity from OCSF severity_id (text kept as OCSF's)
  * body: the event's message
  * attributes: the whole event flattened as ocsf.* (ocsf.action,
    ocsf.dst_endpoint.domain, ocsf.actor.process.name, ...), plus event.name,
    server.address/server.port and process.executable.path/process.pid

--out writes OTLP/JSON, one ExportLogsServiceRequest per line: the format of
the Collector's file exporter, readable by its otlpjsonfile receiver.
--endpoint POSTs the same JSON to an OTLP/HTTP logs endpoint (a Collector,
Grafana Alloy, or a vendor's OTLP intake; --header for auth). Both may be given.

Exit codes: 0 ok, 1 export failed, 2 bad usage.
Python 3.8+, standard library only.
"""
import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

ENGINE = os.environ.get("ENGINE", "podman")
MARKER = " OCSF-JSON "
# openshell-<workspace>--<sandbox>-<uuid> is the sandbox container,
# openshell-supervisor-<uuid> its supervisor.
SANDBOX_CONTAINER = re.compile(r"^openshell-.+?--(?P<name>.+)-(?P<uid>[0-9a-f]{8}-[0-9a-f-]{27})$")
SUPERVISOR_CONTAINER = re.compile(r"^openshell-supervisor-(?P<uid>[0-9a-f]{8}-[0-9a-f-]{27})$")
RESCAN = 10       # seconds between looking for new sandboxes (--follow)
BATCH = 500       # records per export request
FLUSH = 2.0       # seconds before a partial batch is sent

# OCSF severity_id -> OTel SeverityNumber
SEVERITY = {0: 0, 1: 9, 2: 10, 3: 13, 4: 17, 5: 21, 6: 21, 99: 0}


def die(msg, code=2):
    print(f"otel-export: {msg}", file=sys.stderr)
    sys.exit(code)


def supervisors():
    """{uid: (supervisor container, sandbox name)} for every OpenShell sandbox."""
    try:
        out = subprocess.run([ENGINE, "ps", "-a", "--format", "{{.Names}}"],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        die(f"can't list containers with {ENGINE}: {e}", 1)
    names, sups = {}, {}
    for line in out.split():
        if m := SUPERVISOR_CONTAINER.match(line):
            sups[m["uid"]] = line
        elif m := SANDBOX_CONTAINER.match(line):
            names[m["uid"]] = m["name"]
    return {uid: (c, names.get(uid, uid)) for uid, c in sups.items()}


PROCS = []        # the `podman logs` processes, stopped on exit


def read_events(container, since, follow, out):
    """Put every OCSF event from one supervisor's log on the queue."""
    cmd = [ENGINE, "logs"] + (["--follow"] if follow else []) + (["--since", since] if since else [])
    p = subprocess.Popen(cmd + [container], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace")
    PROCS.append(p)
    for line in p.stdout:
        i = line.find(MARKER)
        if i < 0:
            continue
        try:
            out.put(json.loads(line[i + len(MARKER):]))
        except json.JSONDecodeError:
            pass
    p.wait()


# --- OCSF event -> OTLP/JSON -------------------------------------------------

def any_value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}          # int64 is a string in OTLP/JSON
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [any_value(x) for x in v]}}
    if isinstance(v, dict):
        return {"kvlistValue": {"values": attrs(v)}}
    return {"stringValue": str(v)}


def attrs(d):
    return [{"key": k, "value": any_value(v)} for k, v in d.items() if v is not None]


def flatten(v, prefix, out):
    """{"a": {"b": 1}} -> {"ocsf.a.b": 1}; lists stay values."""
    if isinstance(v, dict):
        for k, x in v.items():
            flatten(x, f"{prefix}.{k}", out)
    else:
        out[prefix] = v
    return out


def log_record(ev):
    a = flatten(ev, "ocsf", {})
    a["event.name"] = "openshell.ocsf." + re.sub(r"\W+", "_", ev.get("type_name", "event")).strip("_").lower()
    dst = ev.get("dst_endpoint") or {}
    if dst.get("domain") or dst.get("ip"):
        a["server.address"] = dst.get("domain") or dst.get("ip")
    if "port" in dst:
        a["server.port"] = dst["port"]
    proc = (ev.get("actor") or {}).get("process") or {}
    if proc.get("name"):
        a["process.executable.path"] = proc["name"]
    if "pid" in proc:
        a["process.pid"] = proc["pid"]
    sev = ev.get("severity_id", 0)
    return {
        "timeUnixNano": str(int(ev.get("time", time.time() * 1000)) * 1_000_000),
        "observedTimeUnixNano": str(time.time_ns()),
        "severityNumber": SEVERITY.get(sev, 0),
        "severityText": ev.get("severity", ""),
        "body": {"stringValue": ev.get("message", "")},
        "attributes": attrs(a),
    }


def request(events):
    """One ExportLogsServiceRequest, one resource per sandbox."""
    by_sandbox = {}
    for ev in events:
        c = ev.get("container") or {}
        by_sandbox.setdefault(c.get("uid") or c.get("name"), []).append(ev)
    resource_logs = []
    for evs in by_sandbox.values():
        first = evs[0]
        c = first.get("container") or {}
        meta = first.get("metadata") or {}
        product = meta.get("product") or {}
        resource_logs.append({
            "resource": {"attributes": attrs({
                "service.name": "openshell-sandbox",
                "service.version": product.get("version"),
                "openshell.sandbox.name": c.get("name"),
                "openshell.sandbox.id": c.get("uid"),
                "container.image.name": (c.get("image") or {}).get("name"),
                "host.name": (first.get("device") or {}).get("hostname"),
            })},
            "scopeLogs": [{
                "scope": {"name": "openshell.ocsf", "version": meta.get("version", "")},
                "logRecords": [log_record(ev) for ev in evs],
            }],
        })
    return {"resourceLogs": resource_logs}


# --- Sinks --------------------------------------------------------------------

class FileSink:
    def __init__(self, path):
        self.f = sys.stdout if path == "-" else open(path, "a", encoding="utf-8")

    def send(self, req):
        self.f.write(json.dumps(req, separators=(",", ":")) + "\n")
        self.f.flush()


class HttpSink:
    def __init__(self, url, headers):
        self.url = url
        self.headers = {"Content-Type": "application/json", **headers}

    def send(self, req):
        body = json.dumps(req, separators=(",", ":")).encode()
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        self.url, data=body, headers=self.headers, method="POST"), timeout=10):
                    return
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429:
                    die(f"{self.url} rejected the export: HTTP {e.code} {e.read()[:300]!r}", 1)
                err = f"HTTP {e.code}"
            except (urllib.error.URLError, OSError) as e:
                err = str(getattr(e, "reason", e))
            time.sleep(2 ** attempt)
        die(f"can't export to {self.url}: {err}", 1)


def on_term(*_):
    raise KeyboardInterrupt


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("--out", metavar="FILE", help="append OTLP/JSON lines to FILE (- for stdout)")
    p.add_argument("--endpoint", metavar="URL", help="OTLP/HTTP logs endpoint, e.g. http://localhost:4318/v1/logs")
    p.add_argument("--header", action="append", default=[], metavar="K=V", help="HTTP header for --endpoint (repeatable)")
    p.add_argument("-s", "--sandbox", metavar="NAME", help="only this sandbox (default: all)")
    p.add_argument("--since", metavar="DUR", help="only events from this long ago, e.g. 30m (default: all)")
    p.add_argument("-f", "--follow", action="store_true", help="keep streaming new events")
    args = p.parse_args()
    if not (args.out or args.endpoint):
        p.error("give --out FILE and/or --endpoint URL")
    headers = {}
    for h in args.header:
        k, sep, v = h.partition("=")
        if not sep:
            p.error(f"--header needs K=V, got {h!r}")
        headers[k.strip()] = v.strip()
    sinks = ([FileSink(args.out)] if args.out else []) + \
            ([HttpSink(args.endpoint, headers)] if args.endpoint else [])

    events = queue.Queue()
    readers = {}

    def start_new():
        for uid, (container, name) in supervisors().items():
            if uid in readers or (args.sandbox and name != args.sandbox):
                continue
            t = threading.Thread(target=read_events, daemon=True,
                                 args=(container, args.since, args.follow, events))
            t.start()
            readers[uid] = t

    # Ctrl-C and kill both end the loop below, which sends what is left.
    signal.signal(signal.SIGTERM, on_term)
    start_new()
    if not readers:
        if not args.follow:
            die(f"no sandbox {args.sandbox!r}" if args.sandbox else "no OpenShell sandboxes found")
        print("otel-export: no sandboxes yet, waiting", file=sys.stderr)

    batch, sent, last_flush, last_scan = [], 0, time.monotonic(), time.monotonic()

    def flush():
        nonlocal batch, sent, last_flush
        if batch:
            req = request(batch)
            for s in sinks:
                s.send(req)
            sent += len(batch)
            batch = []
        last_flush = time.monotonic()

    try:
        while True:
            try:
                batch.append(events.get(timeout=0.5))
            except queue.Empty:
                if not args.follow and not any(t.is_alive() for t in readers.values()) and events.empty():
                    break
            if len(batch) >= BATCH or time.monotonic() - last_flush >= FLUSH:
                flush()
            if args.follow and time.monotonic() - last_scan >= RESCAN:
                start_new()
                last_scan = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in PROCS:
            proc.terminate()
    flush()
    print(f"otel-export: {sent} events exported", file=sys.stderr)


if __name__ == "__main__":
    main()
