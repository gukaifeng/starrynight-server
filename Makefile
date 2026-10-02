.PHONY: build test integration check openapi dev-up dev-down run migrate
build:
	go build -trimpath -o bin/starry-api ./cmd/api
	go build -trimpath -o bin/starry-admin ./cmd/admin
	go build -trimpath -o bin/starry-migrate ./cmd/migrate
	go build -trimpath -o bin/starry-publish-release ./cmd/publish-release
test:
	go test -race ./...
integration:
	STARRY_INTEGRATION=1 go test -race -count=1 ./internal/api ./internal/admin -v
check:
	go vet ./...
	go test -race ./...
openapi:
	go run ./cmd/api -openapi api/openapi.json
migrate:
	go run ./cmd/migrate
run:
	go run ./cmd/api
dev-up:
	bash scripts/dev.sh up
dev-down:
	bash scripts/dev.sh down
