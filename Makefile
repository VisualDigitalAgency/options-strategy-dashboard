# Shortcuts for the server. Each line is a plain docker compose command you can run by hand.
.PHONY: up down logs migrate ps admin secrets

secrets:            ## random passwords into ./secrets (never overwrites)
	python3 scripts/make_secrets.py

up:                 ## build and start everything
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:               ## follow logs of every service
	docker compose logs -f --tail=100

migrate:            ## apply database migrations now (also runs on every `up`)
	docker compose run --rm migrate

admin:              ## set the admin's password: make admin EMAIL=you@example.com
	docker compose exec api python scripts/set_admin.py $(EMAIL)
