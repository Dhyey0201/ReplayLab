PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := $(CURDIR)/python
OPAM := $(CURDIR)/.tools/opam
export OPAMROOT := $(CURDIR)/.opam-root
DUNE := $(OPAM) exec --switch=$(CURDIR) -- dune
.PHONY: setup build test check test-python demo test-deep demo-crash demo-shrink bench
setup:
	sh scripts/setup.sh
build:
	$(DUNE) build --root .
test-python:
	$(PYTHON) -m unittest discover -s test -p 'test_*.py' -v
test: build test-python
	$(DUNE) runtest --root .
check: test
	.venv/bin/ruff format --check python test scripts
	.venv/bin/ruff check python test scripts
	$(DUNE) build --root . @fmt
demo: build
	$(PYTHON) -m replaylab_tools demo
test-deep: test
	$(PYTHON) scripts/deep_check.py
demo-crash: build
	$(PYTHON) -m replaylab_tools demo-crash
demo-shrink: build
	$(PYTHON) -m replaylab_tools demo-shrink
bench:
	$(DUNE) build --root . --profile release
	REPLAYLAB_BUILD_PROFILE=release $(PYTHON) scripts/run_bench.py
format:
	.venv/bin/ruff format python test scripts
	$(DUNE) fmt --root .
clean-check:
	$(PYTHON) scripts/clean_check.py
