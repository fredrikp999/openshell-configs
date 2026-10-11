# Build the images, run the tests and check the files.
#
#   make images     build all images (claude-sandbox before claude-browser)
#   make claude-sandbox | claude-browser | opencode-sandbox   one image
#   make test       run all tests (needs the images and the claude provider)
#   make lint       check scripts, JSON, YAML and the provider profiles
#
# Images are built with Podman; set ENGINE=docker to use Docker.
ENGINE ?= podman
# shellcheck from PATH, or else from its official container image.
SHELLCHECK ?= $(shell command -v shellcheck || echo "$(ENGINE) run --rm -v $(CURDIR):/mnt:ro -w /mnt docker.io/koalaman/shellcheck:stable")
IMAGES := claude-sandbox claude-browser opencode-sandbox
SCRIPTS := bin/sandbox.sh bin/provider.sh bin/bundle.sh bin/watch-denied.sh tests/*/run.sh \
           images/claude-sandbox/claude-start images/claude-sandbox/claude-acp-start \
           images/claude-browser/playwright-mcp-start

.PHONY: images $(IMAGES) test lint

images: $(IMAGES)

$(IMAGES):
	$(ENGINE) build -t $@:latest images/$@

# claude-browser is built FROM claude-sandbox.
claude-browser: claude-sandbox

test:
	@for t in tests/*/run.sh; do echo "== $$t"; $$t || exit 1; done

lint:
	$(SHELLCHECK) -S warning $(SCRIPTS)
	python3 -m py_compile bin/acp_client.py bin/otel-export.py
	node --check tests/browser/browser_probe.js
	node --check tests/host-mcp/mcp_probe.js
	@for f in images/*/*.json; do python3 -m json.tool $$f >/dev/null || { echo "invalid JSON: $$f"; exit 1; }; done
	@for f in policies/*.yaml providers/*.yaml tests/*/*.yaml; do \
	  ruby -ryaml -e 'YAML.load_file(ARGV[0])' $$f || { echo "invalid YAML: $$f"; exit 1; }; done
