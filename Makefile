.PHONY: install package test clean release

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PREFIX ?= $(HOME)/.super

install:
	@echo "Installing super to $(PREFIX)..."
	@mkdir -p $(PREFIX)
	@cp -r super lib hooks README.md VERSION super.config.yaml $(PREFIX)/
	@chmod +x $(PREFIX)/super
	@chmod +x $(PREFIX)/hooks/*/*.sh
	@echo "Installed. Add $(PREFIX) to your PATH."

package:
	@mkdir -p dist
	@tar czf "dist/super-$(VERSION).tar.gz" \
		super lib/ hooks/ README.md install.sh VERSION super.config.yaml
	@echo "Packaged: dist/super-$(VERSION).tar.gz"

test:
	@bash -n super
	@bash -n lib/session.sh
	@for f in hooks/*/*.sh; do bash -n "$$f" || exit 1; done
	@echo "Shell syntax OK"

clean:
	@rm -rf dist/

release: test package
	@echo "Ready for release: dist/super-$(VERSION).tar.gz"
