# Use the official image as a parent image.
FROM python:3.8.3-slim

# Set the working directory.
WORKDIR /usr/src/executor

# Copy everything from your host to your current location.
COPY . .

# Set up environment variables.
ENV FIREBASE_CERT_PATH ./certs/firebase-cert.json
ENV GOOGLE_APPLICATION_CREDENTIALS ./certs/executor-cert.json

# Install dependencies.
RUN python -m pip install -r requirements.txt
RUN apt update && apt install ffmpeg -y

# Run executor.
CMD [ "python", "executor.py" ]
