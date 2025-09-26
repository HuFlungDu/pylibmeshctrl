FROM ghcr.io/ylianst/meshcentral:1.1.50
RUN apk add curl
RUN apk add python3
WORKDIR /opt/meshcentral/
COPY ./scripts/meshcentral ./scripts
COPY ./config/meshcentral/data /opt/meshcentral/meshcentral-data
COPY ./config/meshcentral/overrides /opt/meshcentral/meshcentral
ENTRYPOINT ["python3", "/opt/meshcentral/scripts/create_users.py"]