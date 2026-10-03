.PHONY: status test lint check-leakage data features train backtest report app all

status:
	python -m nasdaq100.cli status

test:
	pytest -m "not needs_data and not slow"

lint:
	ruff check .

check-leakage:
	python -m nasdaq100.cli check-leakage

data:
	python -m nasdaq100.cli ingest
	python -m nasdaq100.cli validate
	python -m nasdaq100.cli build-master
	python -m nasdaq100.cli build-universe
	python -m nasdaq100.cli build-adjusted

features:
	python -m nasdaq100.cli build-labels
	python -m nasdaq100.cli build-features
	python -m nasdaq100.cli regimes

train:
	python -m nasdaq100.cli run-baselines
	python -m nasdaq100.cli tune
	python -m nasdaq100.cli walkforward --family ridge_logit --split dev
	python -m nasdaq100.cli walkforward --family lgbm --split dev

backtest:
	python -m nasdaq100.cli backtest

report:
	python -m nasdaq100.cli evaluate
	python -m nasdaq100.cli explain

app:
	streamlit run dashboard/app.py

all: data features train backtest report
