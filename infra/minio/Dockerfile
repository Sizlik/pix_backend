FROM golang:1.24.8-alpine3.22 AS build

ARG MINIO_REF=RELEASE.2025-10-15T17-29-55Z
RUN apk add --no-cache git
RUN git clone --depth 1 --branch "${MINIO_REF}" https://github.com/minio/minio.git /src/minio
WORKDIR /src/minio
RUN CGO_ENABLED=0 go build -trimpath -o /out/minio .

FROM alpine:3.22.1
RUN apk add --no-cache ca-certificates curl \
    && addgroup -S minio \
    && adduser -S -G minio minio \
    && mkdir -p /data \
    && chown minio:minio /data
COPY --from=build /out/minio /usr/local/bin/minio
USER minio
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
