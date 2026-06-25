FROM rust:1.79-alpine AS builder

RUN apk add --no-cache musl-dev openssl-dev pkgconfig

WORKDIR /app
COPY Cargo.toml ./
COPY src ./src

RUN cargo build --release

FROM alpine:3.20
RUN apk add --no-cache libgcc openssl ca-certificates
COPY --from=builder /app/target/release/signal-bus /usr/local/bin/signal-bus
EXPOSE 7700
CMD ["signal-bus"]
