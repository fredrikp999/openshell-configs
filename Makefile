# Build the images, run the tests and check the files.
#
#   make images     build all images (claude-sandbox, then claude-browser, then claude-hyperframes)
#   make claude-sandbox | claude-browser | claude-hyperframes | opencode-sandbox   one image
#   make test       run all tests (needs the images and the claude provider)
#   make lint       check scripts, JSON, YAML and the provider profiles
#
# Images are built with Podman; set ENGINE=docker to use Docker.
ENGINE ?= podman
# shellcheck from PATH, or else from its official container image. The
# scripts are sent to the container on stdin rather than mounted, so this also
# works when the Podman machine can't see this folder (docs/isolation.md).
SHELLCHECK ?= $(shell command -v shellcheck)
SHELLCHECK_IMAGE := docker.io/koalaman/shellcheck-alpine:stable
IMAGES := claude-sandbox claude-browser claude-hyperframes opencode-sandbox
SCRIPTS := bin/sandbox.sh bin/provider.sh bin/bundle.sh bin/watch-denied.sh bin/vm-clock.sh tests/*/run.sh \
           images/claude-sandbox/claude-start images/claude-sandbox/claude-acp-start \
           images/claude-browser/playwright-mcp-start \
           images/claude-hyperframes/hyperframes-init images/claude-hyperframes/claude-start \
           images/claude-hyperframes/claude-acp-start

.PHONY: images $(IMAGES) test lint

images: $(IMAGES)

$(IMAGES):
	$(ENGINE) build -t $@:latest images/$@

# claude-browser is built FROM claude-sandbox, claude-hyperframes FROM claude-browser.
claude-browser: claude-sandbox
claude-hyperframes: claude-browser

test:
	@for t in tests/*/run.sh; do echo "== $$t"; $$t || exit 1; done

lint:
ifeq ($(SHELLCHECK),)
	COPYFILE_DISABLE=1 tar -cf - $(SCRIPTS) | $(ENGINE) run --rm -i --entrypoint sh $(SHELLCHECK_IMAGE) \
	  -c 'mkdir /tmp/src && cd /tmp/src && tar -xf - && shellcheck "$$@"' sh -S warning $(SCRIPTS)
else
	$(SHELLCHECK) -S warning $(SCRIPTS)
endif
	python3 -m py_compile bin/acp_client.py bin/otel-export.py bin/otel-view.py bin/metrics-view.py
	node --check tests/browser/browser_probe.js
	node --check tests/host-mcp/mcp_probe.js
	@for f in images/*/*.json; do python3 -m json.tool $$f >/dev/null || { echo "invalid JSON: $$f"; exit 1; }; done
	@for f in policies/*.yaml providers/*.yaml tests/*/*.yaml observability/*.yaml; do \
	  ruby -ryaml -e 'YAML.load_file(ARGV[0])' $$f || { echo "invalid YAML: $$f"; exit 1; }; done
