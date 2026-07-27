.PHONY: prepare test clean docs daily_graph_sync_test daily_graph_sync_unit_test

prepare:
	python3 -m venv venv
	. venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -r requirements.txt
	echo "install ckb"
	python3 -m download
	python3 -m download_fiber
	sh prepare.sh

prepare_develop_testnet:
	python3 -m venv venv
	. venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -r requirements.txt
	echo "install ckb"
	python3 -m download

	echo "install fiber"
	python3 -m download_fiber
	cp download/0.202.0/ckb-cli ./source/ckb-cli
	bash develop_fiber.sh


develop_prepare:
	python3 -m venv venv
	. venv/bin/activate
	python3 -m pip install --upgrade pip
	pip install -r requirements.txt
	echo "install ckb"
	python3 -m download

	python3 -m download_ckb_light_client
	echo "install ckb cli"
	bash develop_prepare.sh

test_cases := \
    test_cases/replace_rpc \
    test_cases/ckb_cli \
    test_cases/ckb2023 \
    test_cases/contracts \
    test_cases/example \
    test_cases/framework \
    test_cases/light_client \
    test_cases/mocking \
    test_cases/node_compatible \
    test_cases/rpc \
    test_cases/soft_fork \
    test_cases/issue \
    test_cases/tx_pool_refactor \
    test_cases/feature \
    test_cases/config \
    test_cases/miner \
    test_cases/get_fee_rate_statistics


fiber_test_cases := \
    test_cases/fiber/devnet/open_channel \
	test_cases/fiber/devnet/accept_channel \
	test_cases/fiber/devnet/cancel_invoice \
	test_cases/fiber/devnet/connect_peer \
	test_cases/fiber/devnet/disconnect_peer \
	test_cases/fiber/devnet/get_invoice \
	test_cases/fiber/devnet/graph_channels \
	test_cases/fiber/devnet/graph_nodes \
	test_cases/fiber/devnet/list_channels \
	test_cases/fiber/devnet/new_invoice \
	test_cases/fiber/devnet/send_payment \
	test_cases/fiber/devnet/shutdown_channel \
	test_cases/fiber/devnet/update_channel \
	test_cases/fiber/devnet/issue \
	test_cases/fiber/devnet/migration \
	test_cases/fiber/devnet/security \
	test_cases/fiber/devnet/watch_tower \
	test_cases/fiber/devnet/fee_stats \
	test_cases/fiber/devnet/fnn-cli

fiber_testnet_cases := \
	test_cases/fiber/testnet


fiber_mainnet_cases := \
	test_cases/fiber/mainnet



test:
	@failed_cases=; \
    for test_case in $(test_cases); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi


fiber_testnet_test:
	@failed_cases=; \
    for test_case in $(fiber_testnet_cases); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi

fiber_mainnet_test:
	@failed_cases=; \
    for test_case in $(fiber_mainnet_cases); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi

fiber_test:
	@failed_cases=; \
    for test_case in $(fiber_test_cases); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi

fiber_test_demo:
	@failed_cases=; \
	echo "Running tests for $$FIBER_TEST_DEMO"; \
    for test_case in $(FIBER_TEST_DEMO); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi

develop_test:
	@failed_cases=; \
    for test_case in $(TestCases); do \
        echo "Running tests for $$test_case"; \
        if ! bash test.sh "$$test_case"; then \
            echo "$$test_case" >> failed_test_cases.txt; \
        fi \
    done; \
    if [ -s failed_test_cases.txt ]; then \
        echo "Some test cases failed: $$(cat failed_test_cases.txt)"; \
        rm -f failed_test_cases.txt; \
        exit 1; \
    fi

# Standalone daily graph-sync benchmark (mainnet / testnet).
# Independent from the devnet/testnet/mainnet suites: it starts its own fnn node
# with trace-level gossip logging and does not need `make prepare`.
# The benchmark is opt-in (skipped unless DAILY_SYNC_ENABLED is set), so this
# target sets it automatically. Configure the rest via env vars, e.g.:
#   DAILY_SYNC_NETWORK=testnet DAILY_SYNC_FNN=/path/to/fnn \
#   DAILY_SYNC_CONFIG=/path/to/config.yml make daily_graph_sync_test
daily_graph_sync_test:
	DAILY_SYNC_ENABLED=1 python3 -u -m pytest -vv test_cases/fiber/daily/test_daily_graph_sync.py

# Deterministic, no-network unit tests for the daily graph-sync engine.
# Safe to run anywhere (no fnn binary, no CKB, no public network) and fast, so
# it runs in the Lint-and-Format workflow on every push/PR and again in the
# daily workflow before the long E2E. Not gated behind DAILY_SYNC_ENABLED.
daily_graph_sync_unit_test:
	python3 -u -m pytest -vv test_cases/fiber/daily/test_daily_graph_sync_unit.py



clean:
	- pkill ckb
	- pkill fnn
	- rm -rf tmp
	- rm -rf report

docs:
	python -m pytest --docs=docs/soft.md --doc-type=md test_cases/soft_fork
