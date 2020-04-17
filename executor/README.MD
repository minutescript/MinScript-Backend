# MinuteScript Executor
Executor takes care of the orderly transcription of recordings
submitted by the server.

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
At the moment, it contains the log file location and [logging level](https://docs.python.org/3/library/logging.html#logging-levels) required.

A sample file `config.json.sample` is attached.

## Running the executor
Run `python executor.py`.
