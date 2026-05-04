FROM python:3.12-slim

ARG GH_VERSION=2.45.0
ARG TARGETARCH=amd64

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git openssl \
    && curl -fsSL -o /tmp/gh.deb "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH}.deb" \
    && apt-get install -y --no-install-recommends /tmp/gh.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/gh.deb

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

ENV PORT=8080
EXPOSE 8080

CMD ["build-release-mcp-service"]
