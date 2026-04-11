.PHONY: install package test clean release

VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
PREFIX ?= $(HOME)/.super

install:
	@echo "Installing super to $(PREFIX)..."
	@mkdir -p $(PREFIX)
	@cp -r super lib hooks tests README.md VERSION super.config.yaml $(PREFIX)/
	@chmod +x $(PREFIX)/super
	@chmod +x $(PREFIX)/hooks/*/*.sh
	@chmod +x $(PREFIX)/tests/*.sh
	@echo "Installed. Add $(PREFIX) to your PATH."

package:
	@mkdir -p dist
	@tar czf "dist/super-$(VERSION).tar.gz" \
		super lib/ hooks/ tests/ README.md install.sh VERSION super.config.yaml
	@echo "Packaged: dist/super-$(VERSION).tar.gz"

test:
	@bash -n super
	@bash -n lib/session.sh
	@bash -n lib/config.sh
	@bash -n lib/security.sh
	@bash -n lib/validators.sh
	@for f in hooks/*/*.sh; do bash -n "$$f" || exit 1; done
	@echo "Shell syntax OK"
	@echo ""
	@echo "Running unit tests..."
	@bash tests/test_cli_selection.sh
	@bash tests/test_installed_detection.sh
	@bash tests/test_integration.sh
	@bash tests/test_resume_catchup.sh
	@bash tests/test_all_agents_resume.sh

clean:
	@rm -rf dist/

release: test package
	@echo "Ready for release: dist/super-$(VERSION).tar.gz"
