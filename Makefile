.PHONY: install package test clean release

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PREFIX ?= $(HOME)/.supercli

install:
	@echo "Installing supercli to $(PREFIX)..."
	@mkdir -p $(PREFIX)
	@cp -r supercli lib hooks README.md $(PREFIX)/
	@chmod +x $(PREFIX)/supercli
	@chmod +x $(PREFIX)/hooks/*/*.sh
	@echo "Installed. Add $(PREFIX) to your PATH."

package:
	@mkdir -p dist
	@tar czf "dist/supercli-$(VERSION).tar.gz" \
		supercli lib/ hooks/ README.md install.sh VERSION
	@echo "Packaged: dist/supercli-$(VERSION).tar.gz"

test:
	@bash -n supercli
	@bash -n lib/session.sh
	@for f in hooks/*/*.sh; do bash -n "$$f" || exit 1; done
	@echo "Shell syntax OK"

clean:
	@rm -rf dist/

release: test package
	@echo "Ready for release: dist/supercli-$(VERSION).tar.gz"
