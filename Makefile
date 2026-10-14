PYTHON ?= python
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: regression unit api browser live-smoke

regression: unit api browser

# Legacy tests replace Streamlit in sys.modules; each file needs a fresh process.
unit:
	$(PYTHON) -m pytest "$(ROOT)/tests/test_decision_contract.py" -v
	$(PYTHON) -m pytest "$(ROOT)/tests/test_readable_views.py" -v
	@set -e; for suite in "$(ROOT)"/legacy/streamlit/tests/test_*.py; do \
		$(PYTHON) -m pytest "$$suite" -v; \
	done

api:
	cd "$(ROOT)/services/api" && $(PYTHON) -m pytest tests -v

browser:
	$(PYTHON) -m pytest "$(ROOT)/tests/browser" -v

live-smoke:
	$(PYTHON) -m pytest "$(ROOT)/tests/live" -v -rs
