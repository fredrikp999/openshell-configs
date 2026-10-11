#!/usr/bin/env python3
"""Show the OpenShell gateway's metrics as a short summary in the terminal.

  bin/metrics-view.py [-w [SEC]] [--url URL]

  bin/metrics-view.py            # once
  bin/metrics-view.py -w         # refresh every 5 seconds, Ctrl-C to stop
  bin/metrics-view.py -w 2       # every 2 seconds

Reads the gateway's Prometheus endpoint, by default
http://127.0.0.1:9464/metrics (or $OPENSHELL_METRICS_URL), and shows the
connected sandboxes, the relays into sandboxes (exec, connect, SSH, port
forwards), and the gateway API calls per method with latency and errors.
With -w, /MIN is the rate since the previous refresh. Latency covers recent
calls only, so it shows - for methods that weren't called lately.

The endpoint is off by default; see docs/logging.md#gateway-metrics.
Python 3.8+, standard library only.
"""
import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = os.environ.get("OPENSHELL_METRICS_URL", "http://127.0.0.1:9464/metrics")
LINE = re.compile(r"^([a-zA-Z_:][\w:]*)(?:\{(.*)\})?\s+(\S+)")
LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def scrape(url):
    """[(name, {labels}, value)] from a Prometheus text endpoint."""
    with urllib.request.urlopen(url, timeout=5) as r:
        text = r.read().decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            try:
                out.append((m[1], dict(LABEL.findall(m[2] or "")), float(m[3])))
            except ValueError:
                pass
    return out


def total(samples, name, **match):
    return sum(v for n, l, v in samples if n == name and all(l.get(k) == x for k, x in match.items()))


def fmt(n):
    return f"{n:.0f}" if n == int(n) else f"{n:.1f}"


def ms(seconds):
    # The gateway's quantiles only cover recent calls; 0 means none lately.
    return "-" if not seconds else f"{seconds * 1000:.1f}"


def render(samples, prev, elapsed, url):
    lines = [f"OpenShell gateway - {url} - {time.strftime('%H:%M:%S')}", ""]
    p = "openshell_server_"

    lines.append(f"Sandboxes connected  {fmt(total(samples, p + 'supervisor_sessions'))}")
    lines.append(f"Relays pending       {fmt(total(samples, p + 'relay_pending'))} / "
                 f"{fmt(total(samples, p + 'relay_pending_capacity'))}"
                 f"     rejected {fmt(total(samples, p + 'relay_rejected_total'))}"
                 f"   expired {fmt(total(samples, p + 'relay_expired_total'))}")
    relays = []
    for kind in ("ssh", "tcp"):
        ok = total(samples, p + "routed_request_attempts_total", operation="relay", relay_kind=kind, outcome="success")
        bad = sum(v for n, l, v in samples if n == p + "routed_request_attempts_total"
                  and l.get("operation") == "relay" and l.get("relay_kind") == kind and l.get("outcome") != "success")
        relays.append(f"{kind} {fmt(ok)} ok" + (f", {fmt(bad)} failed" if bad else ""))
    lines.append(f"Relays opened        {'   '.join(relays)}")
    count = total(samples, p + "relay_claim_duration_seconds_count")
    if count:
        avg = total(samples, p + "relay_claim_duration_seconds_sum") / count * 1000
        lines.append(f"Relay pickup         {avg:.1f} ms average")

    # API calls per method: total, rate, p50/p99 latency, non-OK responses.
    methods = {}
    for n, l, v in samples:
        m = l.get("method")
        if not m:
            continue
        d = methods.setdefault(m, {"total": 0, "errors": 0, "p50": None, "p99": None})
        if n == p + "grpc_requests_total":
            d["total"] += v
            if l.get("code") != "0":
                d["errors"] += v
        elif n == p + "grpc_request_duration_seconds" and l.get("code") == "0":
            if l.get("quantile") == "0.5":
                d["p50"] = v
            elif l.get("quantile") == "0.99":
                d["p99"] = v
    lines += ["", f"{'API CALLS':<32} {'TOTAL':>7} {'/MIN':>7} {'P50 MS':>8} {'P99 MS':>8} {'ERRORS':>7}"]
    for m, d in sorted(methods.items(), key=lambda kv: -kv[1]["total"]):
        rate = ""
        if prev is not None and elapsed > 0:
            rate = fmt((d["total"] - prev.get(m, 0)) / elapsed * 60)
        lines.append(f"{m[:32]:<32} {fmt(d['total']):>7} {rate:>7} {ms(d['p50']):>8} {ms(d['p99']):>8} "
                     f"{fmt(d['errors']):>7}")
    if not methods:
        lines.append("(no calls yet)")
    return lines, {m: d["total"] for m, d in methods.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("-w", "--watch", nargs="?", const=5.0, type=float, metavar="SEC",
                   help="refresh every SEC seconds (default 5)")
    p.add_argument("--url", default=DEFAULT_URL, help=f"metrics endpoint (default {DEFAULT_URL})")
    args = p.parse_args()

    prev, last = None, None
    try:
        while True:
            try:
                samples = scrape(args.url)
            except (urllib.error.URLError, OSError) as e:
                sys.exit(f"metrics-view: can't read {args.url}: {getattr(e, 'reason', e)}\n"
                         "Is the gateway's metrics endpoint on? See docs/logging.md#gateway-metrics")
            now = time.monotonic()
            lines, totals = render(samples, prev, (now - last) if last else 0, args.url)
            if args.watch and sys.stdout.isatty():
                sys.stdout.write("\033[H\033[J")
            print("\n".join(lines), flush=True)
            if not args.watch:
                break
            prev, last = totals, now
            time.sleep(args.watch)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
