# Use the official image as a parent image.
FROM python:3.8.3-slim

# Set the working directory.
ENV APP_HOME /server
WORKDIR $APP_HOME

# Copy everything from your host to your current location.
COPY . .

# Set up environment variables.
ENV FIREBASE_CERT_PATH ./certs/firebase-cert.json
ENV GOOGLE_APPLICATION_CREDENTIALS ./certs/server-cert.json

# Install dependencies.
RUN python -m pip install -r requirements.txt

# Run executor.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 wsgi:app
