.PHONY: install test lint typecheck run-scenarios grade-local clean \
        demos ui-install ui-build serve

install:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

run-scenarios:
	python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json

grade-local:
	python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json

demos:
	python -m langgraph_agent_lab.cli parallel-demo
	python -m langgraph_agent_lab.cli hitl-demo --approve
	python -m langgraph_agent_lab.cli hitl-demo --reject --output outputs/hitl_reject_evidence.txt
	python -m langgraph_agent_lab.cli timetravel-demo
	python -m langgraph_agent_lab.cli crash-demo
	python -m langgraph_agent_lab.cli persist-demo
	python -m langgraph_agent_lab.cli diagram

ui-install:
	cd ui && npm install

ui-build:
	cd ui && npm run build

serve:
	python -m langgraph_agent_lab.cli serve

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build *.egg-info outputs/*.json
