# Shortcuts for the server. Each line is a plain docker compose command you can run by hand.
.PHONY: up down logs migrate ps admin secrets test

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

# Integration tests (tests/run.py) in throwaway Postgres + Redis containers; removed afterwards.
# Frontend tests: npm --prefix frontend test
TEST_NET = theta-test
test:               ## run the backend integration tests in Docker
	docker build -q --target app -t theta-desk-test . >/dev/null
	docker network create $(TEST_NET) >/dev/null
	docker run -d --rm --name theta-test-pg --network $(TEST_NET) -e POSTGRES_USER=theta_owner 	  -e POSTGRES_PASSWORD=test-owner -e POSTGRES_DB=theta postgres:16-alpine >/dev/null
	docker run -d --rm --name theta-test-redis --network $(TEST_NET) redis:7-alpine >/dev/null
	docker run --rm --network $(TEST_NET) -e DB_HOST=theta-test-pg -e OWNER_DB_PASSWORD=test-owner 	  -e DB_APP_PASSWORD=test-app -e REDIS_URL=redis://theta-test-redis:6379/0 	  -v "$(CURDIR)/tests:/app/tests:ro" theta-desk-test python tests/run.py; 	status=$$?; docker rm -f theta-test-pg theta-test-redis >/dev/null; docker network rm $(TEST_NET) >/dev/null; exit $$status
