# MinuteScript Cloud Functions
This directory contains source code for Google Cloud Functions
used by MinuteScript.

The cloud function handles account activation when new account is created

## Deployment
1. Install [Firebase CLI](https://firebase.google.com/docs/cli), if you do not have it already.
2. Initialise project by navigating to the root directory of the repository and running `firebase init`.
3. Make sure you selected `Functions: Configure and deploy Cloud Functions` from the list of features to enable.
4. **DO NOT OVERWRITE** files when asked by Firebase CLI.
5. Agree to install npm packages.
6. After initialisation finished, navigate to `functions` directory.
7. Install Sendgrid with `npm install @sendgrid/mail`.
8. Deploy functions to the cloud by running `firebase deploy`.

## Development
The source code for the functions is in `functions/index.js`. Any npm commands should be executed within `functions` directory.