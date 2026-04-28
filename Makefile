.PHONY: help dry-run up status tunnel client down

help:
	@echo "make dry-run   # show cheapest matching offer (no rent)"
	@echo "make up        # rent GPU + auto git-clone + install + serve"
	@echo "make status    # tail onstart.log and probe /v1/models"
	@echo "make tunnel    # ssh -L tunnel: localhost:SERVE_PORT -> instance"
	@echo "make client    # run local OCR web UI on http://127.0.0.1:5000"
	@echo "make down      # destroy the rented instance"

dry-run:
	python scripts/create_instance.py --dry-run

up:
	python scripts/create_instance.py

status:
	bash scripts/status.sh

tunnel:
	bash scripts/tunnel.sh

client:
	python client/app.py

down:
	python scripts/destroy_instance.py
