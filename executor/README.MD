# MinuteScript Executor
Executor takes care of the orderly transcription of recordings
submitted by the server.
## Setup
### Common steps
1. Install libs: `pip install -r requirements.txt`
1. Download 2 cert files (for GC and Firebase)
2. Put them in `<repo_dir>/creds`
3. Download, install and configure Google Cloud SDK: https://cloud.google.com/sdk/downloads

### In Bash
1. Run `export $FIREBASE_CERT_PATH=<firebase_cert_path>/<firebase_cert_filename>`
2. Run `export $GOOGLE_APPLICATION_CREDENTIALS=<gcloud_sevice_account_cert_path>/<gcloud_service_account_cert_filename>`

### In Powershell
1. Run `$env:FIREBASE_CERT_PATH=<firebase_cert_path>\<firebase_cert_filename>`
2. Run `$env:GOOGLE_APPLICATION_CREDENTIALS=<gcloud_sevice_account_cert_path>\<gcloud_service_account_cert_filename>`
