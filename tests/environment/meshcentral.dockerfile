FROM ghcr.io/ylianst/meshcentral:latest
RUN apk add curl
RUN apk add python3
WORKDIR /opt/meshcentral/
COPY ./scripts/meshcentral ./scripts
COPY ./config/meshcentral/data /opt/meshcentral/meshcentral-data
CMD ["python3", "/opt/meshcentral/scripts/create_users.py"]