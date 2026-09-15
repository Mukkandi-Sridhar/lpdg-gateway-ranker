PYTHON ?= .venv/bin/python
# The pinned pandas/numpy/pyarrow ship wheels for Python 3.11 and 3.12 only.
BOOTSTRAP ?= python3.12
DATA ?= data
PORT ?= 8000

.PHONY: install predict validate api run test coverage lint compare docker

install:  ## create .venv with Python 3.12 (make install BOOTSTRAP=python3.11 also works)
	$(BOOTSTRAP) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

predict:  ## rank every week: writes predictions.csv and output/results.json
	$(PYTHON) -m gateway_ranker.cli predict --data $(DATA)

validate:  ## check predictions.csv with LPDG's validator
	$(PYTHON) validate_submission.py predictions.csv

api:  ## serve the API on http://localhost:$(PORT)
	DATA_DIR=$(DATA) $(PYTHON) -m uvicorn api.main:create_app --factory --port $(PORT) --no-access-log

run: predict validate api  ## everything without Docker

test:  ## all tests; the one test needing the real dataset skips if ./data is absent
	$(PYTHON) -m pytest -q

coverage:  ## tests with a line-coverage report
	$(PYTHON) -m pytest -q --cov --cov-report=term-missing

lint:  ## style and bug-pattern checks
	$(PYTHON) -m ruff check .

compare:  ## run the official baseline and show how our picks differ
	$(PYTHON) baseline_3sigma.py --data $(DATA) --out predictions_baseline.csv
	$(PYTHON) scripts/compare_to_baseline.py --data $(DATA)

docker:  ## everything in Docker
	docker compose up --build
