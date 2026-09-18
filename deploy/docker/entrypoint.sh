#!/bin/sh
# Provision the model into the cache volume (if needed) before starting the
# server. Skipped entirely when using the fake engine.
set -eu

if [ "${PRECOG_ENGINE:-timesfm3}" = "timesfm3" ]; then
    precog-download-model
fi

exec "$@"
