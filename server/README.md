# MinuteScript Backend Server

The server is responsible for validating users, making 
changes to user metadata and initiating the transcription process.

## Obtaining certificates
1. Go to [Firebase Console](https://console.firebase.google.com).
2. From `Service accounts` section in the project settings, download Firebase Admin SDK certificate as JSON.
3. Go to [GCP Console](https://console.cloud.google.com).
4. Create a service account with roles `Pub/Sub Publisher` and `Storage Admin`. Download account's certificate as JSON.
5. Put both files in `<repo_dir>/certs`
6. Download, install and configure [Google Cloud SDK](https://cloud.google.com/sdk/downloads)

## Setting up the server
1. Make sure you have Python 3 installed.
2. Install dependencies: `pip install -r requirements.txt`.

### In Bash
3. Run `export $FIREBASE_CERT_PATH=<repo_dir>/certs/<firebase_cert>`.
4. Run `export $GOOGLE_APPLICATION_CREDENTIALS=<repo_dir>/certs/<gcloud_service_account_cert>`.

### In PowerShell
3. Run `$env:FIREBASE_CERT_PATH=<repo_dir>\certs\<firebase_cert>`.
4. Run `$env:GOOGLE_APPLICATION_CREDENTIALS=<repo_dir>\certs\<gcloud_service_account_cert`.

## Configuration
`config.json` file needs to be set up before the server is run.
At the moment, it contains the number of trial minutes user receives upon signup.

A sample file  `config.json.sample` is attached.

## Development run
Run `python server.py`.

## Production run
For production deployment it is recommended to use Gunicorn and a load balancer.
When using Gunicorn, connect it to `wsgi:app` instead of `server.py`.