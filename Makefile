# Self-check targets. The core engine is stdlib-only, so `make test` works with a
# bare Python install; `make lint` needs ruff (`pip install ruff`).

PY ?= python3

.PHONY: build test lint check demo report card clean

build:
	$(PY) -m py_compile $$(find src tests -name '*.py')

test:
	$(PY) -m unittest discover -s tests -t . -p 'test_*.py'

lint:
	$(PY) -m ruff check src tests

check: build test lint

demo:
	PYTHONPATH=src $(PY) -m qlab.cli backtest --symbol DEMO

report:
	PYTHONPATH=src $(PY) -m qlab.cli report --symbol DEMO --out-dir artifacts

card:
	PYTHONPATH=src $(PY) -m qlab.cli card --symbol DEMO --model --walk-forward --out-dir artifacts

clean:
	rm -rf artifacts .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
