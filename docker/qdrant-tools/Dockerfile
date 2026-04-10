FROM busybox:latest AS busybox

FROM qdrant/qdrant:latest

COPY --from=busybox /bin/busybox /bin/busybox
