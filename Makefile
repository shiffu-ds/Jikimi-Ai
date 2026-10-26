# Jikimi AI - har kaam ek command (plan Section 7.20). `make help` lists everything.
# Paths stay relative: the repository folder may contain spaces.

PROFILE ?= laptop
COMPOSE  = docker compose --env-file .env -f deploy/compose/docker-compose.$(PROFILE).yml
WEB      = apps/dashboard
EDGE_CFG ?= edge/config/site.demo.yaml

.DEFAULT_GOAL := help
.PHONY: help setup env web web-dev types seed demo server edge test test-fast replay calibrate evaluate-fa \
        ruvr shadow voice research setup-wizard discover \
        lint fmt typecheck bench up down logs net-cut net-restore sms-reply merkle docs openapi clean-clips clean doctor

help: ## Saare commands
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

setup: ## Python (uv) + web (npm) dependencies
	uv sync --all-packages
	npm --prefix $(WEB) install --no-audit --no-fund
	-uv run pre-commit install

env: ## .env banao (random secrets)
	uv run python scripts/init_env.py

web: types ## Dashboard static build -> apps/dashboard/out (served by the API)
	NEXT_TELEMETRY_DISABLED=1 npm --prefix $(WEB) run build

web-dev: ## Dashboard hot-reload on :3000 (proxies /v1 to :8000)
	npm --prefix $(WEB) run dev

types: ## Pydantic contracts -> TypeScript
	uv run python scripts/gen_contract_types.py

seed: env ## Tenant, site, cameras, demo users, edge device + token
	uv run python -m jikimi_server seed --edge-config $(EDGE_CFG)

demo: seed ## Lite demo: API + dashboard + 2 simulated cameras (http://localhost:8000)
	uv run python scripts/dev.py demo

live: ## Live demo: API + dashboard + one simulated camera + this laptop's webcam (http://localhost:8000)
	uv run python -m jikimi_server seed --edge-config edge/config/site.live.yaml
	uv run python scripts/dev.py live

server: ## Only the API (+ dashboard)
	uv run python scripts/dev.py server

edge: ## Only the edge runtime
	uv run python -m jikimi_edge --config $(EDGE_CFG) run

test: ## Unit + API + contract tests (fast)
	uv run pytest -m "not slow and not chaos"
	uv run python scripts/gen_contract_types.py --check
	npm --prefix $(WEB) run typecheck
	npm --prefix $(WEB) test

test-fast: ## Python tests only
	uv run pytest -m "not slow and not chaos" -x -q

replay: ## Golden scenarios -> expected alerts (slow)
	uv run pytest -m slow eval/tests -q

calibrate: ## Conformal calibration from simulated normal traffic and street life (demo only)
	uv run python -m jikimi_edge --config $(EDGE_CFG) calibrate --hours 4
	uv run python -m jikimi_edge --config $(EDGE_CFG) calibrate --hours 10 --scenario street_life

evaluate-fa: ## Empirical false alarms / camera-hour on held-out normal traffic
	uv run python -m jikimi_edge --config $(EDGE_CFG) evaluate-fa --hours 2

lint: ## ruff + mypy (shared packages) + tsc
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	npm --prefix $(WEB) run typecheck

fmt: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

ruvr: ## Roman Urdu search benchmark on simulated scenes (Recall@10, MRR)
	uv run python -m eval.ruvr_sim --scenes 4

shadow: ## Snatch scorers side by side: B1 heuristic vs ST-GCN on the same pairs
	uv run python -m eval.shadow_snatch

voice: ## Guard voice replies (F12): intent accuracy + Whisper on spoken test clips
	uv run python -m eval.voice_check --tts

research: ## Tier 2/3 evaluations: cross-camera, agent, hotspots, low light, VLM (slow), see docs/results.md
	uv run python -m jikimi_ml.train.train_trajectory
	uv run python -m eval.agent_check
	uv run python -m eval.hotspot_check
	uv run python -m eval.lowlight_check
	uv run python -m eval.vlm_check

setup-wizard: ## Urdu camera setup wizard on the LAN, opened from a phone (F20; prints a PIN)
	uv run python -m jikimi_edge --config $(EDGE_CFG) setup

discover: ## Find ONVIF cameras / DVRs on the LAN and their RTSP streams (F20)
	uv run python -m jikimi_edge --config $(EDGE_CFG) discover

bench: ## Laptop/edge benchmark (pipeline fps, model latency if models exist)
	./scripts/benchmark_laptop.sh

up: ## Compose stack (PROFILE=laptop|server|edge-cpu)
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

net-cut: ## Demo: edge ka internet "kaat do" (alerts go by SMS)
	@mkdir -p data/edge && touch data/edge/OFFLINE && echo "edge link: DOWN (SMS fallback active)"

net-restore: ## Demo: internet wapas
	@rm -f data/edge/OFFLINE && echo "edge link: UP (outbox will sync)"

sms-reply: ## Demo: guard SMS reply, e.g. make sms-reply TEXT="1 A7F2"
	@mkdir -p data/edge/sms && printf '{"from": "%s", "text": "%s"}\n' "$${FROM:-+923001234567}" "$(TEXT)" >> data/edge/sms/inbox.jsonl && echo "queued reply: $(TEXT)"

merkle: ## Close today's Merkle batch now (normally 00:05)
	uv run python -m jikimi_server merkle-close

openapi: ## Export docs/api/openapi.json
	uv run python -m jikimi_server openapi --out docs/api/openapi.json

docs: ## MkDocs preview
	uv run --with mkdocs-material mkdocs serve -f docs/mkdocs.yml

doctor: ## Check the edge environment
	uv run python -m jikimi_edge --config $(EDGE_CFG) doctor

clean-clips: ## Dev clips older than 7 days
	uv run python -m jikimi_edge.privacy.retention --data-dir data/edge --older-than-days 7

clean: ## Remove local demo data (data/), builds and caches
	rm -rf data $(WEB)/out $(WEB)/.next .pytest_cache .ruff_cache .mypy_cache
