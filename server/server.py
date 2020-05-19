from flask import Flask, request, jsonify, abort, make_response
from flask_cors import cross_origin

import os
import firebase_admin
from firebase_admin import auth, credentials, firestore
from google.cloud import storage
from google.cloud import pubsub
import json
import logging

CONF_FILE = 'config.json'

with open(CONF_FILE) as cfg:
    CONFIG_JSON = json.load(cfg)

TRIAL_MINUTES = CONFIG_JSON['trial_minutes']

app = Flask(__name__)
storage_client = storage.Client()

FIREBASE_CERT_PATH = os.environ['FIREBASE_CERT_PATH']
cred = credentials.Certificate(FIREBASE_CERT_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

BUCKET_NAME = 'minutescript'
RECORDINGS_FOLDER = 'recordings'

PROJECT_ID = 'minutescript-prod'
TOPIC = 'transcription-requests'

publisher = pubsub.PublisherClient()
topic_path = publisher.topic_path(PROJECT_ID, TOPIC)


@app.route('/transcription', methods=['POST'])
@cross_origin()
def transcription():
    # fetch uid and request body
    uid = _verify_auth()

    app.logger.info('Received request from %s' % uid)

    # check if user has credits left
    _verify_user_against_db(uid)

    # if positively verified, start processing the request
    request_json = _get_json()

    app.logger.debug('Request content:\n%s' % request_json)

    # check if requests meets the minimum specification
    app.logger.info('Checking whether the request is correct')

    # retrieve file name
    file_name = _abort_if_not_present('file_name')
    full_file_name = RECORDINGS_FOLDER + '/' + uid + '/' + file_name

    # check if provided file exists
    if not storage_client.get_bucket(BUCKET_NAME).get_blob(full_file_name).exists():
        abort(make_response(jsonify({'status': 'FILE_NOT_FOUND'}), 404))

    # retrieve main language
    main_lang = _abort_if_not_present('main_lang')

    # build skeleton message for the executor
    gs_uri = 'gs://' + BUCKET_NAME + '/' + full_file_name

    msg_dict = {
        'uri': gs_uri,
        'user_id': uid,
        'filename': file_name,
        'main_lang': main_lang
    }

    # now checking for optional fields
    # retrieve additional languages
    msg_dict = _add_if_present('extra_lang', msg_dict)

    # check if diarization enabled
    msg_dict = _add_if_present('diarize', msg_dict, is_bool=True)

    # check for sample rate
    msg_dict = _add_if_present('sample_rate_hertz', msg_dict)

    # collect number of speakers for diarization
    # otherwise, check if auto-detect present
    # NOTE: auto-detect and no_speakers used only for legacy spec
    if msg_dict['diarize']:
        msg_dict = _add_if_present('no_speakers_min', msg_dict)
        msg_dict = _add_if_present('no_speakers_max', msg_dict)

        # make it more foolproof
        if ('no_speakers_min' not in msg_dict) and ('no_speakers_max' in msg_dict):
            msg_dict['no_speakers_min'] = msg_dict['no_speakers_max']
        if ('no_speakers_max' not in msg_dict) and ('no_speakers_min' in msg_dict):
            msg_dict['no_speakers_max'] = msg_dict['no_speakers_min']

        # fallback to legacy API if min and max not present
        if ('no_speakers_min' not in msg_dict) and ('no_speakers_max' not in msg_dict) and 'no_speakers' in request_json:
            msg_dict['no_speakers_min'] = request_json['no_speakers']
            msg_dict['no_speakers_max'] = request_json['no_speakers']

        # fallback to legacy auto-detect, if needed
        if ('no_speakers_min' not in msg_dict) and ('no_speakers_max' not in msg_dict):
            msg_dict = _add_if_present('auto_detect', msg_dict, is_bool=True)

    msg_str = json.dumps(msg_dict)
    data = msg_str.encode('utf-8')

    publisher.publish(topic_path, data=data)
    app.logger.info("Message: %s successfully published" % data)

    return jsonify({'status': 'PROCESS_STARTED'})


# verify if preperty present in the request body
def _abort_if_not_present(field):
    req = _get_json()

    if not req.get(field):
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))
    else:
        return req[field]


# add to message if present
def _add_if_present(field, msg, is_bool=False):
    req = _get_json()

    if req.get(field):
        # as errors known for bools in requests, bool values passed to server as strings
        # parsing is done below
        if is_bool:
            msg[field] = True if req[field].lower() == 'true' else False
        else:
            msg[field] = req[field]
    
    return msg


def _verify_auth():
    #verify token
    if not request.headers.get('Authorization'):
        abort(make_response(jsonify({'status': 'UNAUTHORIZED'}), 401))

    id_token = request.headers['Authorization']
    try:
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
    except Exception:
        abort(make_response(jsonify({'status': 'UNAUTHORIZED'}), 401))

    return uid


def _get_json():
    if not request.is_json:
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))

    json = request.get_json()

    return json


def _verify_user_against_db(user_id):
    user_data = db.collection('user_metadata').document(user_id)

    user_doc = user_data.get()
    if user_doc:
        user_dict = user_doc.to_dict()

        if user_dict['enabled'] == True:
            if user_dict['used_minutes'] >= user_dict['assigned_minutes']:
                abort(make_response(jsonify({'status': 'RECORDING_LIMIT_REACHED: %s'
                 % user_dict['assigned_minutes']}), 402))

            # check file length here
        else:
            abort(make_response(jsonify({'status': 'ACCOUNT_DISABLED'}), 403))

    else:
        abort(make_response(jsonify({'status': 'ACCOUNT_INACTIVE'}), 403))



@app.route('/registration/<req_id>', methods=['GET'])
@cross_origin()
def registration_verification(req_id):
    reg_doc = db.collection('admin').document('security').collection('registration_uids').document(req_id).get()
    if reg_doc:
        reg_doc_dict = reg_doc.to_dict()
        if not reg_doc_dict['verified']:
            user_doc = {'enabled': True, 'used_minutes': 0, 'assigned_minutes': TRIAL_MINUTES}
            db.collection('user_metadata').document(reg_doc_dict['uid']).set(user_doc)
            db.collection('admin').document('security').collection('registration_uids') \
                .document(req_id).update({'verified': True})

            app.logger.info("User successfully activated %s" % reg_doc_dict['uid'])

            return jsonify({'status': 'REGISTRATION_VERIFIED'})

        else:
            abort(make_response(jsonify({'status': 'ACCOUNT_ALREADY_VERIFIED'}), 400))
    else:
        abort(make_response(jsonify({'status': 'REQ_ID_NOT_FOUND'}), 404))



@app.route('/tcs', methods=['POST'])
@cross_origin()
def tcs_acceptance():
    uid = _verify_auth()

    user_metadata_doc = db.collection('user_metadata').document(uid)
    user_metadata = user_metadata_doc.get().to_dict()

    if (user_metadata.get('accepted_tcs')):
        abort(make_response(jsonify({'status': 'TCS_ALREADY_ACCEPTED'}), 400))

    user_metadata_doc.update({'accepted_tcs': firestore.SERVER_TIMESTAMP})

    return jsonify({'status': 'TCS_SUCCESSFULLY_ACCEPTED'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

# attach Flask logging to gunicorn
if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)