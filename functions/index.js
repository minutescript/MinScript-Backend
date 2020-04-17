'use strict';

const functions = require('firebase-functions');

const SENDGRID_API_KEY = functions.config().sendgrid.api_key;
const sendgrid = require("@sendgrid/mail");
sendgrid.setApiKey(SENDGRID_API_KEY);

const admin = require('firebase-admin');
admin.initializeApp();

const firestore = admin.firestore();
const settings = {timestampsInSnapshots: true};
firestore.settings(settings);


// Your company name to include in the emails
const APP_NAME = 'minutescript.app';
const outboundEmailAddress = 'registration@minutescript.app';

/**
 * Main function
 */
exports.sendWelcomeEmail = functions.auth.user().onCreate((user) => {
  const emailAddress = user.email;
  const displayName = user.displayName;
  const uid = user.uid;
  const userDocRef = firestore.collection('admin').doc('security').collection('registration_uids');

  userDocRef.add({'uid': uid, 'verified': false}).then(writeResult => {
    sendActivationEmail(emailAddress, displayName, uid, writeResult.id);
    sendWelcomeEmail(emailAddress, displayName);
    return 'OK'
  }).catch(error => {
    console.error(error);
    return 'ERROR';
  });
});


// Sends an activation email to us.
function sendActivationEmail(emailAddress, displayName, uid, docId) {
  const link = 'https://api.minutescript.app/registration/' + docId;
  let email = {};

  email.to = 'newusers@minutescript.app';
  email.from = `${APP_NAME} <${outboundEmailAddress}>`;

  email.subject = `New user: ${emailAddress}`;

  email.html = 'New user registered. Email: ' + emailAddress + ' . Name: '
    + displayName + ' . Confirm registration: ' + link;

  return sendgrid.send(email).then((sent) => {
    console.log('New welcome email sent to: ' + email.to);
    return 'OK';
  })
  .catch(error => {
    //Log friendly error
    console.log(error.toString());
    return 'ERROR';
  });
}


// Sends a welcome email to the given user.
function sendWelcomeEmail(emailAddress, displayName) {
  let email = {};

  email.to = emailAddress;
  email.from = `${APP_NAME} <${outboundEmailAddress}>`;
  email.replyTo = 'contact@minutescript.app';

  email.subject = `Welcome to ${APP_NAME}`;

  let text = `Hello ${displayName || ''}! Welcome to ${APP_NAME}. We're excited to have you on board. <br>`;
  text += `You will shortly receive an email, once your account has been activated. <br>`;
  text += `If you have any questions, don't hesitate to contact us by replying to this email. <br>`;
  text += `Thanks, the minutescript team`;
  email.html = text;

  return sendgrid.send(email).then((sent) => {
    console.log('New welcome email sent to: ' + emailAddress);
    return 'OK';
  })
  .catch(error => {
    //Log friendly error
    console.log(error.toString());
    return 'ERROR';
  });
}
