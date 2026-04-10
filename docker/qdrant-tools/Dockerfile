FROM busybox:1.36.1 AS busybox

FROM qdrant/qdrant:v1.10.1

COPY --from=busybox /bin/busybox /bin/busybox
