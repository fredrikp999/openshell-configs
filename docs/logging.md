# Logging and metrics
What happens in a sandbox is logged by its OpenShell supervisor: every connection it allows or denies, HTTP requests checked by a rule, SSH sessions, policy and setting changes. This page shows how to read those logs, watch the denials live, export everything to OpenTelemetry, and get the gateway's own metrics.

| You want to | Use |
|---|---|
| Look at a sandbox's log now | [`openshell logs`](#reading-the-logs) |
| See what's being blocked, live, across all sandboxes | [`bin/watch-denied.sh`](#watching-denials) |
| Keep the events, or send them to a log backend | [`bin/otel-export.py`](#export-as-opentelemetry) |
| Look through exported events in the terminal | [`bin/otel-view.py`](#viewing-the-events) |
| Monitor the gateway itself | [`bin/metrics-view.py`](#viewing-the-metrics), or [Prometheus](#prometheus) |
| Send metrics and events to an OpenTelemetry backend together | [observability/collector.yaml](#metrics-as-opentelemetry) |
| Browse and graph metrics and events locally | [Grafana](#viewing-in-grafana) |

## Two kinds of logs
* **The shorthand log** - one human-readable line per event, always on. This is what `openshell logs` shows, and what `bin/watch-denied.sh` reads.
* **OCSF JSON** - the same events as complete structured records in the [OCSF](https://schema.ocsf.io/) schema, off by default. This is what `bin/otel-export.py` reads. See [OCSF JSON](#ocsf-json).

## Reading the logs
* The last 200 lines: `openshell logs my-task`
* More, from the last 30 minutes: `openshell logs my-task --since 30m -n 1000`
* Follow live: `openshell logs my-task --tail`
* Warnings and errors only: `openshell logs my-task --level warn`
* What was blocked: `openshell logs my-task | grep DENIED`
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
* All sandboxes, including ones created later: `bin/watch-denied.sh`
* Only `my-task` (`-s` for short): `bin/watch-denied.sh --sandbox my-task`
* Start with the last hour (default 1m): `bin/watch-denied.sh --since 1h`
* Also show the known harmless denials: `bin/watch-denied.sh --all`
* The DENIED lines themselves, with full binary paths: `bin/watch-denied.sh --raw`

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
```
* Check: `openshell settings get my-task | grep ocsf`
* Off again: `openshell settings set --global --key ocsf_json_enabled --value false --yes`
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
   * All events so far: `bin/otel-export.py --out sandboxes.otlp.jsonl`
   * The last hour of one sandbox: `bin/otel-export.py --out - --since 1h --sandbox my-task`
   * Live: `bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow`
   * To a backend that needs a token: `bin/otel-export.py --endpoint https://otlp.example.com/v1/logs --header "Authorization=Bearer $TOKEN" --follow`

* **Where the events come from:** the script reads the [OCSF JSON](#ocsf-json) records with `podman logs` of every `openshell-supervisor-*` container: all sandboxes, running or stopped. With `--follow` it picks up new sandboxes every 10 seconds. Events only start once the setting is on, and are gone when the sandbox is deleted.
* **What a record looks like:** one resource per sandbox (`service.name=openshell-sandbox`, `openshell.sandbox.name`, `openshell.sandbox.id`, `container.image.name`). Each event keeps its own time, gets an OTel severity from the OCSF one, has the event's message as body, and carries the whole event flattened as `ocsf.*` attributes (`ocsf.action`, `ocsf.dst_endpoint.domain`, `ocsf.actor.process.name`, ...), plus `event.name`, `server.address`/`server.port` and `process.executable.path`. Filter denials on `ocsf.action = Denied`.
* **File format:** one OTLP/JSON `ExportLogsServiceRequest` per line, the format of the Collector's file exporter. A Collector reads it back with the [`otlpjsonfile`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/otlpjsonfilereceiver) receiver.
* **Don't double-send:** `--follow` starts with all events still in the logs. When restarting a live export, pass e.g. `--since 5m`.
* **The events say what the agent did:** URLs, hosts and process names. Treat the export like the sandbox's contents when choosing where to send it.

## Viewing the events
[bin/otel-view.py](../bin/otel-view.py) is a minimal viewer for the terminal: one line per event (time, sandbox, severity, action, target, message), denials in red.
* Live: `bin/otel-export.py --out - --follow | bin/otel-view.py`
* A file: `bin/otel-view.py sandboxes.otlp.jsonl`
* Only denials: `bin/otel-view.py --where ocsf.action=Denied sandboxes.otlp.jsonl`
* One sandbox, every attribute: `bin/otel-view.py --where openshell.sandbox.name=my-task -v ...`
* As an OTLP/HTTP endpoint on 127.0.0.1:4318, which the exporter then sends to:
```bash
bin/otel-view.py --listen
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow
```

Example output:
```
10:22:55  cl3            Medium        Denied  www.example.org:443 (node)          Transparent TCP denied before relay: ...
10:28:18  cl3            Informational Allowed                                     SSH connection accepted on supervisor Unix socket
```
* `--where K=V` matches an attribute of the record or its resource. Give it several times to require all of them.
* `--listen` accepts OTLP's JSON encoding only, not protobuf. Senders other than `bin/otel-export.py` need their JSON setting.
* The events contain what an agent controls (hosts, URLs), so the viewer removes terminal control characters before printing.
* For search, graphs and history, send the events to a real backend instead. For a local one, the [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) image runs a Collector, Loki and Grafana in one container and takes OTLP on port 4318. Then open Grafana on http://localhost:3000:
```bash
podman run -d --name otel-lgtm -p 127.0.0.1:3000:3000 -p 127.0.0.1:4318:4318 docker.io/grafana/otel-lgtm:latest
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow
```

## Gateway metrics
The gateway has a Prometheus endpoint, off by default. Its metrics are about the gateway: connected sandboxes, API calls, and the relays that carry `exec`, `connect`, SSH and port forwards into sandboxes. They don't count what agents do (use the [OCSF events](#export-as-opentelemetry) for denials per sandbox or host) or how much CPU and memory a sandbox uses (use `podman stats`).

* **Turn it on** with the Homebrew service: put the port in `~/.config/openshell/gateway.env`, which the service loads at start, and restart the gateway. The restart may drop open sessions (agents in a terminal, VS Code, SSH); the sandboxes keep running and reconnect to the gateway.
```bash
echo 'OPENSHELL_METRICS_PORT=9464' >> ~/.config/openshell/gateway.env
brew services restart openshell
curl -s http://127.0.0.1:9464/metrics
```
   Without Homebrew, start the gateway with `--metrics-port 9464` or the same environment variable. Delete the line and restart to turn it off. The endpoint listens on `127.0.0.1` only (`--bind-address` changes that for all listeners).

| Metric | Type | What it tells you |
|---|---|---|
| `openshell_server_supervisor_sessions` | gauge | Sandboxes connected to the gateway |
| `openshell_server_grpc_requests_total{method,code}` | counter | Gateway API calls by method (`ExecSandbox`, `ListSandboxes`, `GetSandboxConfig`, ...) and gRPC status code |
| `openshell_server_grpc_request_duration_seconds{method,code}` | summary | API call latency |
| `openshell_server_routed_request_attempts_total{operation,route,relay_kind,outcome,grpc_code}` | counter | Relays into sandboxes (`relay_kind` `ssh` or `tcp`) and other routed calls, with `outcome` `success`, `local_error` or `remote_error` |
| `openshell_server_relay_claim_duration_seconds` | histogram | How fast a sandbox picks up a relay |
| `openshell_server_relay_pending`, `openshell_server_relay_pending_capacity` | gauge | Relays waiting for a sandbox, and the limit (256) |
| `openshell_server_relay_rejected_total{reason}` | counter | Relays refused at the limit (`sandbox_capacity`, `replica_capacity`) |
| `openshell_server_relay_expired_total` | counter | Relays dropped because the sandbox didn't connect back in time |

* Some series appear only after the first matching event, e.g. `relay_claim_duration_seconds` after the first `exec`.

### Viewing the metrics
[bin/metrics-view.py](../bin/metrics-view.py) shows them as a short summary, without Prometheus. `bin/metrics-view.py` prints it once, and `-w` refreshes it every 5 seconds (`-w 2` for every 2):
```bash
bin/metrics-view.py -w
```
```
OpenShell gateway - http://127.0.0.1:9464/metrics - 10:49:19

Sandboxes connected  4
Relays pending       0 / 256     rejected 0   expired 0
Relays opened        ssh 4 ok   tcp 0 ok
Relay pickup         3.3 ms average

API CALLS                          TOTAL    /MIN   P50 MS   P99 MS  ERRORS
ReportProviderReadiness              216    79.7      1.4      2.6       0
GetSandboxConfig                     116    79.7      3.3      5.6       0
RelayStream                            4    59.8      0.7      0.7       0
```
* `/MIN` is the rate since the previous refresh, so it's empty on the first one. Latency covers recent calls only, and shows `-` for methods that weren't called lately.
* A different endpoint: `--url`, or `OPENSHELL_METRICS_URL`.

### Prometheus
For history and graphs, scrape the endpoint with Prometheus in a container. From a Podman container, the gateway is at `host.containers.internal`:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: openshell
    scrape_interval: 15s
    static_configs:
      - targets: ["host.containers.internal:9464"]
```
```bash
podman run -d --name prometheus -p 127.0.0.1:9090:9090 \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" docker.io/prom/prometheus:latest
```
   Then, on http://localhost:9090: `openshell_server_supervisor_sessions` for connected sandboxes, `sum by (method) (rate(openshell_server_grpc_requests_total[5m]))` for API calls per method, `rate(openshell_server_routed_request_attempts_total{outcome!="success"}[5m])` for failing relays.

### Metrics as OpenTelemetry
OpenShell's own OTLP export covers traces only, so the metrics reach OTel through a Collector. [observability/collector.yaml](../observability/collector.yaml) scrapes the gateway's metrics endpoint and also takes the events from `bin/otel-export.py`, so one Collector sends both to your backend:
```bash
podman run -d --name otel-collector -p 127.0.0.1:4318:4318 \
  -v "$PWD/observability/collector.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  docker.io/otel/opentelemetry-collector-contrib:latest
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow
podman logs -f otel-collector
```
* The Collector logs a line per batch, e.g. `"metrics": 14, "log records": 59, ...`
* **Needs** the [metrics endpoint](#gateway-metrics) on port 9464. The Collector scrapes it every 15 seconds at `host.containers.internal:9464`.
* **Out of the box** everything goes to the `debug` exporter, which only prints to the Collector's log. To send to a backend, uncomment `otlphttp` in the file, set its `endpoint` (the backend's OTLP/HTTP base URL, without `/v1/...`), switch both pipelines to `[otlphttp]`, and pass the token with `podman run -e OTLP_TOKEN ...`.
* **What arrives:** one resource with `service.name=openshell-gateway` and `service.instance.id=host.containers.internal:9464`. Counters become cumulative sums, gauges stay gauges, `grpc_request_duration_seconds` is a summary and `relay_claim_duration_seconds` a histogram. The scrape adds `up`, `scrape_duration_seconds` and a few more about itself; `up` is a simple "is the gateway reachable" signal.
* **Port 4318** is also the default of `bin/otel-view.py --listen`; only one of them can have it. Publish the Collector on another port (`-p 127.0.0.1:4320:4318`) and point `--endpoint` there to run both.
* **To look at it locally**, use [observability/collector-grafana.yaml](../observability/collector-grafana.yaml) instead, see below.

### Viewing in Grafana
The [grafana/otel-lgtm](https://github.com/grafana/docker-otel-lgtm) image has an OTLP intake, Prometheus, Loki and Grafana in one container. [observability/collector-grafana.yaml](../observability/collector-grafana.yaml) is the Collector config above with that as its backend.
```bash
podman network create otel
podman run -d --name otel-lgtm --network otel -p 127.0.0.1:3000:3000 \
  docker.io/grafana/otel-lgtm:latest
podman run -d --name otel-collector --network otel -p 127.0.0.1:4318:4318 \
  -v "$PWD/observability/collector-grafana.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  docker.io/otel/opentelemetry-collector-contrib:latest
bin/otel-export.py --endpoint http://localhost:4318/v1/logs --follow
```
Open http://localhost:3000 (no login from your machine). Metrics show up within 15 seconds, events as soon as `bin/otel-export.py` sends them.

* **Metrics:** Explore, data source **Prometheus**, or Drilldown, Metrics to browse them. The names are the gateway's:
```
openshell_server_supervisor_sessions                                          # connected sandboxes
sum by (method) (rate(openshell_server_grpc_requests_total[5m]))              # API calls per method
rate(openshell_server_routed_request_attempts_total{outcome!="success"}[5m])  # failing relays
up{job="openshell-gateway"}                                                   # gateway reachable
```
* **Events:** Explore, data source **Loki**. Attribute names have `_` instead of `.`:
```
{service_name="openshell-sandbox"} | ocsf_action="Denied"
{service_name="openshell-sandbox"} | openshell_sandbox_name="my-task"
sum by (openshell_sandbox_name) (count_over_time({service_name="openshell-sandbox"} | ocsf_action="Denied" [1h]))
```
* **The two containers share the `otel` network,** so the Collector reaches `otel-lgtm` by name, and the intake needs no host port.
* **Nothing is kept:** the data is gone when the `otel-lgtm` container is removed. Stop everything with `podman rm -f otel-collector otel-lgtm && podman network rm otel`.
