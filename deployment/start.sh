#!/usr/bin/env bash
set -e

nginx -c "/etc/nginx/conf.d/default.conf" &

aca-py start --inbound-transport http 0.0.0.0 11020 --outbound-transport http --admin 0.0.0.0 11021 &

ping(){
    url="http://localhost:11021/status/ready"
    local resp=$(curl -s --write-out '%{http_code}' --output /dev/null ${url})
    if [ $resp -eq 200 ]; then
        return 0
    else
        return 1
    fi
}

wait_for_cloud_agent(){
    COUNT=${WAIT_SECOND:-60} # seconds
    printf "waiting for cloud agent"
    while ! ping ; do
        printf "."
        if [ $COUNT -eq 0 ];then
          echo "\nThe Cloud agent failed to start within ${duration} seconds.\n"
          exit 1
        fi
        ((COUNT=COUNT-1))
        sleep 1
    done
    printf "\n"
}

healthcheck(){
    while ping ; do
        sleep ${HEALTH_CHECK_PERIOD_SECOND:-300} # second
    done
    echo "\nAca-py is down"
    exit 1
}

wait_for_cloud_agent

healthcheck