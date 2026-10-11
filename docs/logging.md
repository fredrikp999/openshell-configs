# Logging
What happens in a sandbox is logged by its OpenShell supervisor: every connection it allows or denies, HTTP requests checked by a rule, SSH sessions, policy and setting changes. This page shows how to read those logs, watch the denials live, and export everything to OpenTelemetry.

| You want to | Use |
|---|---|
| Look at a sandbox's log now | [`openshell logs`](#reading-the-logs) |
| See what's being blocked, live, across all sandboxes | [`bin/watch-denied.sh`](#watching-denials) |
| Keep the events, or send them to a log backend | [`bin/otel-export.py`](#export-as-opentelemetry) |
| Look through exported events in the terminal | [`bin/otel-view.py`](#viewing-the-events) |

## Two kinds of logs
* **The shorthand log** - one human-readable line per event, always on. This is what `openshell logs` shows, and what `bin/watch-denied.sh` reads.
* **OCSF JSON** - the same events as complete structured records in the [OCSF](https://schema.ocsf.io/) schema, off by default. This is what `bin/otel-export.py` reads. See [OCSF JSON](#ocsf-json).

## Reading the logs
```bash
openshell logs my-task                       # the last 200 lines
openshell logs my-task --since 30m -n 1000   # more, from the last 30 minutes
openshell logs my-task --tail                # follow live
openshell logs my-task --level warn          # warnings and errors only
openshell logs my-task | grep DENIED         # what was blocked
```
* Without a name, `openshell logs` uses the last-used sandbox. `--source sandbox` or `--source gateway` shows only one side.
* **Line format:** `[time] [source] [level] [component] message`, with the time in Unix seconds. Security events have the component `[ocsf]`, an event type and an outcome:
```
[1791703672.439] [sandbox] [OCSF ] [ocsf] NET:REFUSE [MED] DENIED github.com [reason:policy_dns_ineligible]
[1791703672.552] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /usr/lib/git-core/git-remote-http(0) -> github.com:443 [reason:transparent_tcp_policy_denied]
```
* **One blocked connection is two lines:** `NET:REFUSE` when the name lookup is refused, and `NET:OPEN` when the connection is denied. The second one shows the binary that tried, by its real path. That path is what a profile's `binaries` list or a rule needs (see [Network rules](customizing.md#network-rules)).
* Requests that a rule checks at HTTP level are logged with the method and URL, e.g. `HTTP:GET [INFO] ALLOWED GET http://api.anthropic.com:443/api/... [policy:_provider_claude engine:l7]`.

## Watching denials
[bin/watch-denied.sh](../bin/watch-denied.sh) shows the denied connections of all sandboxes as a table that updates live: one row per sandbox and host, with how often it was denied, when last, and which binaries tried.
```bash
bin/watch-denied.sh                      # all sandboxes, including ones created later
bin/watch-denied.sh --sandbox my-task    # only my-task (-s for short)
bin/watch-denied.sh --since 1h           # start with the last hour (default 1m)
bin/watch-denied.sh --all                # also show the known harmless denials
bin/watch-denied.sh --raw                # the DENIED lines themselves, with full binary paths
```
```
Denied connections - all sandboxes - since 3h - Ctrl-C to stop

SANDBOX        HOST                                     COUNT  LAST      BINARIES
cl1            www.aos.se:443                               4  10:12:38  bash
claudebrowser  github.com:443                               1  09:27:52  git-remote-http
claudebrowser  www.example.com:443                          1  09:29:09  chrome-headless-shell
```
* Use it while you reproduce a problem or try a new task, then allow what's needed by [reviewing the proposed rules](customizing.md#network-rules).
* When the output isn't a terminal, it prints one `[sandbox] new denial: host (binary)` line per new row instead, for piping.

### Known harmless denials
These show up in the logs but need no rule, so `bin/watch-denied.sh` hides them unless `--all` is given:
* **Chromium** tries `www.google.com` and `update.googleapis.com` at start ([headless browser](extras.md#allowing-sites)).
* **VS Code Server** tries `main.vscode-cdn.net` and `mobile.events.data.microsoft.com` (telemetry) ([VS Code](working-in-sandboxes.md#vs-code)).
* **Claude Code** asks every MCP server for `prompts/list` and `resources/list`, which a rule with an explicit method list denies ([MCP servers](customizing.md#example-policy-with-network-rules)).

## OCSF JSON
Turn it on once, for all sandboxes. It applies within 10 seconds, without a restart:
```bash
openshell settings set --global --key ocsf_json_enabled --value true --yes
openshell settings set --global --key ocsf_json_enabled --value false --yes   # off again
openshell settings get my-task | grep ocsf                                     # check
```
* **Where it goes:** with the Podman driver, OpenShell 0.1.3 doesn't write the `/var/log/openshell-ocsf.*.log` file [its docs](https://docs.nvidia.com/openshell/latest/observability/ocsf-json-export) describe. The supervisor container prints each event as an `OCSF-JSON {...}` line instead, so the records are in `podman logs openshell-supervisor-<sandbox id>`. `bin/otel-export.py` reads them from there.
* **Only from then on:** events before the setting was turned on have no JSON record. The records are gone when the sandbox is deleted, so export what you want to keep.
* **A record** carries the sandbox (`container.name`), the outcome (`action`, `disposition`), the destination (`dst_endpoint`), the process (`actor.process`), the rule that decided (`firewall_rule`) and a severity.
* **Schema version:** v1.8.0 by default. `ocsf_schema_version` set to `1.1` or `1.3` downgrades the records for tools that need an older one (lossy, see the OpenShell docs).

## Export as OpenTelemetry
[bin/otel-export.py](../bin/otel-export.py) sends the sandboxes' security events (every allowed and denied connection, HTTP request, SSH session and config change) to any OpenTelemetry backend as OTLP logs. OpenShell has no OTel export of its own; its structured log is [OCSF JSON](https://docs.nvidia.com/openshell/latest/observability/ocsf-json-export), which the script converts.

1. **Turn on [OCSF JSON](#ocsf-json)**, once:
```bash
openshell settings set --global --key ocsf_json_enabled --value true --yes
```
2. **Export to a file, or push to a collector:**
```bash
bin/otel-export.py --out sandboxes.otlp.jsonl                          # all events so far
bin/otel-export.py --out - --since 1h --sandbox my-task                # last hour of one sandbox
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # live
bin/otel-export.py --endpoint https://otlp.example.com/v1/logs --header "Authorization=Bearer $TOKEN" --follow
```

* **Where the events come from:** the script reads the [OCSF JSON](#ocsf-json) records with `podman logs` of every `openshell-supervisor-*` container: all sandboxes, running or stopped. With `--follow` it picks up new sandboxes every 10 seconds. Events only start once the setting is on, and are gone when the sandbox is deleted.
* **What a record looks like:** one resource per sandbox (`service.name=openshell-sandbox`, `openshell.sandbox.name`, `openshell.sandbox.id`, `container.image.name`). Each event keeps its own time, gets an OTel severity from the OCSF one, has the event's message as body, and carries the whole event flattened as `ocsf.*` attributes (`ocsf.action`, `ocsf.dst_endpoint.domain`, `ocsf.actor.process.name`, ...), plus `event.name`, `server.address`/`server.port` and `process.executable.path`. Filter denials on `ocsf.action = Denied`.
* **File format:** one OTLP/JSON `ExportLogsServiceRequest` per line, the format of the Collector's file exporter. A Collector reads it back with the [`otlpjsonfile`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/otlpjsonfilereceiver) receiver.
* **Don't double-send:** `--follow` starts with all events still in the logs. When restarting a live export, pass e.g. `--since 5m`.
* **The events say what the agent did:** URLs, hosts and process names. Treat the export like the sandbox's contents when choosing where to send it.

## Viewing the events
[bin/otel-view.py](../bin/otel-view.py) is a minimal viewer for the terminal: one line per event (time, sandbox, severity, action, target, message), denials in red.
```bash
bin/otel-export.py --out - --follow | bin/otel-view.py                 # live
bin/otel-view.py sandboxes.otlp.jsonl                                  # a file
bin/otel-view.py --where ocsf.action=Denied sandboxes.otlp.jsonl       # only denials
bin/otel-view.py --where openshell.sandbox.name=my-task -v ...         # one sandbox, every attribute
bin/otel-view.py --listen                                              # OTLP/HTTP endpoint on 127.0.0.1:4318
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # ...which this sends to
```
```
10:22:55  cl3            Medium        Denied  www.example.org:443 (node)          Transparent TCP denied before relay: ...
10:28:18  cl3            Informational Allowed                                     SSH connection accepted on supervisor Unix socket
```
* `--where K=V` matches an attribute of the record or its resource. Give it several times to require all of them.
* `--listen` accepts OTLP's JSON encoding only, not protobuf. Senders other than `bin/otel-export.py` need their JSON setting.
* The events contain what an agent controls (hosts, URLs), so the viewer removes terminal control characters before printing.
* For search, graphs and history, send the events to a real backend instead. For a local one, the [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) image runs a Collector, Loki and Grafana in one container and takes OTLP on port 4318:
```bash
podman run -d --name otel-lgtm -p 127.0.0.1:3000:3000 -p 127.0.0.1:4318:4318 docker.io/grafana/otel-lgtm:latest
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow   # then Grafana on http://localhost:3000
```
