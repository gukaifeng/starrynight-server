FROM golang:1.27.1-bookworm AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/starry-api ./cmd/api && \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/starry-migrate ./cmd/migrate
FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/ /usr/local/bin/
USER nonroot:nonroot
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/starry-api"]
