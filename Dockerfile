FROM python:3.14.3-slim-bookworm AS development
ENV OPAMROOTISOK=1 OPAMJOBS=4 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git m4 pkg-config rsync unzip libgmp-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work/replaylab
COPY Makefile ./
COPY scripts/setup.sh scripts/setup.sh
COPY python/requirements-dev.lock python/requirements-dev.lock
RUN make setup > /opt/replaylab-setup.log 2>&1 || (cat /opt/replaylab-setup.log; exit 1)
ENV PYTHONPATH=/work/replaylab/python
COPY . .
CMD ["make", "check"]

FROM development AS validation
RUN mkdir -p /evidence && cp /opt/replaylab-setup.log /evidence/setup.log \
    && uname -a > /evidence/environment.txt && df -T . >> /evidence/environment.txt \
    && (make check > /evidence/check.log 2>&1 || (cat /evidence/check.log; exit 1)) \
    && echo checks-passed \
    && (.venv/bin/python scripts/deep_check.py > /evidence/deep.log 2>&1 || (cat /evidence/deep.log; exit 1)) \
    && echo deep-corpus-passed \
    && (make demo demo-crash demo-shrink clean-check > /evidence/demos-clean.log 2>&1 || (cat /evidence/demos-clean.log; exit 1)) \
    && echo demos-and-clean-build-passed \
    && (make bench > /evidence/bench.log 2>&1 || (cat /evidence/bench.log; exit 1)) \
    && tar -czf /evidence/artifacts.tar.gz artifacts benchmarks/results \
    && echo 'All Linux validation gates passed' > /evidence/result.txt

FROM scratch AS evidence
COPY --from=validation /evidence/ /
