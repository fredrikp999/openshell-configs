# Build the images, run the tests and check the files.
#
#   make images     build all images (claude-sandbox, then claude-browser, then claude-hyperframes)
#   make claude-sandbox | claude-browser | claude-hyperframes | opencode-sandbox | agy-sandbox | agy-hyperframes | agy-node | agy-python
#                   one image
#   make update     rebuild all images from scratch, with the latest agents and base images
#   make test       run all tests (needs the images and the claude provider)
#   make lint       check scripts, Python, JavaScript, JSON, YAML, the doc links and,
#                   when a gateway is running, the provider profiles
#   make doctor     check that this machine is ready to run sandboxes
#   make html       build openshell-configs.html, the docs and examples as one page (needs pandoc)
#
# Images are built with Podman; set ENGINE=docker to use Docker.
ENGINE ?= podman
# shellcheck from PATH, or else from its official container image. The
# scripts are sent to the container on stdin rather than mounted, so this also
# works when the Podman machine can't see this folder (docs/isolation.md).
SHELLCHECK ?= $(shell command -v shellcheck)
SHELLCHECK_IMAGE := docker.io/koalaman/shellcheck-alpine:stable
IMAGES := claude-sandbox claude-browser claude-hyperframes opencode-sandbox agy-sandbox agy-hyperframes agy-node agy-python
# Images built FROM a registry image, as opposed to FROM one of ours.
BASE_IMAGES := claude-sandbox opencode-sandbox agy-sandbox agy-node
SCRIPTS := bin/sandbox.sh bin/provider.sh bin/bundle.sh bin/watch-denied.sh bin/vm-clock.sh bin/doctor.sh \
           tests/*/run.sh \
           images/claude-sandbox/claude-start images/claude-sandbox/claude-acp-start \
           images/claude-browser/playwright-mcp-start \
           images/claude-hyperframes/hyperframes-init images/claude-hyperframes/claude-start \
           images/claude-hyperframes/claude-acp-start \
           images/agy-sandbox/agy-acp-start images/agy-node/agy-acp-start images/agy-hyperframes/agy-init images/agy-hyperframes/agy-start \
           images/agy-hyperframes/agy-acp-start
PYTHON := bin/acp_client.py bin/otel-export.py bin/otel-view.py bin/metrics-view.py bin/check-links.py bin/build-html.py

.PHONY: images $(IMAGES) update test lint doctor html

images: $(IMAGES)

# BUILD_FLAGS and PULL_FLAGS are empty for `make images`, so unchanged build
# steps come from the cache, and set by `make update` below.
$(IMAGES):
	$(ENGINE) build $(BUILD_FLAGS) $(if $(filter $@,$(BASE_IMAGES)),$(PULL_FLAGS)) -t $@:latest images/$@

# claude-browser is built FROM claude-sandbox, claude-hyperframes FROM claude-browser,
# agy-hyperframes FROM claude-hyperframes, agy-python FROM agy-sandbox.
claude-browser: claude-sandbox
claude-hyperframes: claude-browser
agy-hyperframes: claude-hyperframes
agy-python: agy-sandbox

# Without the cache, so `npm install` and the like fetch the latest versions,
# and with a newer base image if the registry has one. The variables are passed
# on to the image targets.
update: BUILD_FLAGS := --no-cache
update: PULL_FLAGS := $(if $(filter docker,$(ENGINE)),--pull,--pull=newer)
update: images

test:
	@for t in tests/*/run.sh; do echo "== $$t"; $$t || exit 1; done

lint:
ifeq ($(SHELLCHECK),)
	COPYFILE_DISABLE=1 tar -cf - $(SCRIPTS) | $(ENGINE) run --rm -i --entrypoint sh $(SHELLCHECK_IMAGE) \
	  -c 'mkdir /tmp/src && cd /tmp/src && tar -xf - && shellcheck "$$@"' sh -S warning $(SCRIPTS)
else
	$(SHELLCHECK) -S warning $(SCRIPTS)
endif
	python3 -m py_compile $(PYTHON)
	node --check tests/browser/browser_probe.js
	node --check tests/host-mcp/mcp_probe.js
	@for f in images/*/*.json; do python3 -m json.tool $$f >/dev/null || { echo "invalid JSON: $$f"; exit 1; }; done
	@for f in policies/*.yaml providers/*.yaml tests/*/*.yaml observability/*.yaml; do \
	  ruby -ryaml -e 'YAML.load_file(ARGV[0])' $$f || { echo "invalid YAML: $$f"; exit 1; }; done
	python3 bin/check-links.py
# The provider profiles, with the gateway's own check. It refuses a profile
# whose id is already imported, so each one is checked as a copy with another
# id. Needs a running gateway, so it's skipped without one (e.g. in CI).
	@if command -v openshell >/dev/null 2>&1 && openshell status 2>/dev/null | grep -q 'Status: Connected'; then \
	  tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	  for f in providers/*.yaml; do \
	    sed 's/^id: */id: lint-check-/' $$f > "$$tmp/profile.yaml" && \
	    openshell provider profile lint -f "$$tmp/profile.yaml" >/dev/null 2>&1 || \
	      { openshell provider profile lint -f "$$tmp/profile.yaml"; echo "invalid provider profile: $$f"; exit 1; }; \
	  done && echo "provider profiles: ok"; \
	else echo "provider profiles: skipped, no gateway running"; fi

doctor:
	@bin/doctor.sh

html:
	bin/build-html.py
