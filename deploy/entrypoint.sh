#!/bin/sh
set -eu
umask 077
python scripts/init_platform.py
exec "$@"
