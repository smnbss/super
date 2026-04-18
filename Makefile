.PHONY: install package test clean release

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PREFIX ?= $(HOME)/.super

install:
	@echo "Installing super to $(PREFIX)..."
	@mkdir -p $(PREFIX)
	@cp -r super super.mjs lib hooks skills references tests README.md VERSION super.config.yaml package.json package-lock.json $(PREFIX)/
	@chmod +x $(PREFIX)/super
	@chmod +x $(PREFIX)/hooks/*/*.sh
	@chmod +x $(PREFIX)/skills/*/*.sh 2>/dev/null || true
	@chmod +x $(PREFIX)/skills/*/bin/* 2>/dev/null || true
	@echo "Installed. Add $(PREFIX) to your PATH."

package:
	@mkdir -p dist
	@tar czf "dist/super-$(VERSION).tar.gz" \
		super super.mjs lib/ hooks/ skills/ references/ tests/ README.md install.sh VERSION super.config.yaml package.json package-lock.json
	@echo "Packaged: dist/super-$(VERSION).tar.gz"

test:
	@bash -n super
	@for f in hooks/*/*.sh; do bash -n "$$f" || exit 1; done
	@echo "Shell syntax OK"
	@echo ""
	@npm test

clean:
	@rm -rf dist/

release: test package
	@echo "Ready for release: dist/super-$(VERSION).tar.gz"
