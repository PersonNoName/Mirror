FROM python:3.12.13-slim

WORKDIR /srv/opencode-stub

COPY docker/opencode-stub/server.py /srv/opencode-stub/server.py

EXPOSE 4096

CMD ["python", "/srv/opencode-stub/server.py"]
