FROM python:3.13
WORKDIR /usr/local/app

# Install the application dependencies
# COPY requirements.txt ./


# Copy in the source code
COPY scripts/client ./scripts
RUN pip install --no-cache-dir -r ./scripts/requirements.txt
EXPOSE 5000

# Setup an app user so the container doesn't run as the root user
RUN useradd app
USER app
WORKDIR /usr/local/app/scripts

CMD ["python3", "-m", "flask", "--app", "agent_server", "run", "--host=0.0.0.0", "--debug"]