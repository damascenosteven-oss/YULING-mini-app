#!/bin/sh
# Diagnostic wrapper used only in the disposable, credential-free test host.
/usr/bin/docker-real "$@" 2>/tmp/docker-last-error
result=$?
if [ "$result" -ne 0 ]; then
    printf '%s\n' "$*" >>/tmp/docker-fixture-errors
    cat /tmp/docker-last-error >>/tmp/docker-fixture-errors
fi
cat /tmp/docker-last-error >&2
exit "$result"
