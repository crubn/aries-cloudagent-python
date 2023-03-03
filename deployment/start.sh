#!/usr/bin/env bash
set -e

aca-py start --inbound-transport http 0.0.0.0 11020 --outbound-transport http --admin 0.0.0.0 11021 &

nginx -c "/etc/nginx/conf.d/default.conf" &

wait -n