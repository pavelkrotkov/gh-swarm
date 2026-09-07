PYTHON ?= python3

.PHONY: check test shellcheck qualify-swarm-quality qualify-swarm-host qualify-swarm-dispatcher

check:
	$(PYTHON) tools/ci_validate.py

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_swarm*.py' -v

shellcheck:
	bash -n skills/github-project-swarm/scripts/bootstrap.sh

qualify-swarm-quality:
	$(PYTHON) tools/swarm_v7_quality.py --qualification

qualify-swarm-host:
	$(PYTHON) tools/qualify_swarm_v7_host.py

qualify-swarm-dispatcher:
	$(PYTHON) tools/qualify_swarm_v7_host.py --dispatcher-only
