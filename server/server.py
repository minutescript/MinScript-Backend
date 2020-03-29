from flask import Flask, request, jsonify, abort, make_response
from flask_cors import cross_origin

import os
import firebase_admin
from firebase_admin import auth, credentials, firestore
from google.cloud import storage
from google.cloud import pubsub
import json

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
    uid = _verify_auth()

    request_json = _get_json()

    # retrieve file name
    if not request_json.get('file_name'):
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))

    file_name = request_json['file_name']

    full_file_name = RECORDINGS_FOLDER + '/' + uid + '/' + file_name

    if not storage_client.get_bucket(BUCKET_NAME).get_blob(full_file_name).exists():
        abort(make_response(jsonify({'status': 'FILE_NOT_FOUND'}), 404))

    # retrieve main language
    if not request_json.get('main_lang'):
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))
    else:
        main_lang = request_json['main_lang']

    # retrieve additional languages
    # by default no extra languages needed, so no abort procedure implemented
    extra_lang = []

    if request_json.get('extra_lang'):
        extra_lang = request_json['extra_lang']

    # check if diarization enabled
    if not request_json.get('diarize'):
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))
    else:
        diarize = True if request_json['diarize'].lower() == 'true' else False

    # check if speakers auto-detect enabled
    if not request_json.get('auto_detect'):
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))
    else:
        auto_detect = True if request_json['auto_detect'].lower() == 'true' else False

    # retrieve number of speakers
    if not request_json.get('no_speakers') and not auto_detect:
        abort(make_response(jsonify({'status': 'BAD_REQUEST'}), 400))
    else:
        no_speakers = int(request_json['no_speakers'])

    # check if user has credits left
    _verify_user_against_db(uid)

    # start new executor process given GCS URI
    gs_uri = 'gs://' + BUCKET_NAME + '/' + full_file_name

    msg_dict = {
        'uri': gs_uri,
        'user_id': uid,
        'filename': file_name,
        'main_lang': main_lang,
        'extra_lang': extra_lang,
        'diarize': diarize,
        'auto_detect': auto_detect,
        'no_speakers': no_speakers
    }

    if not auto_detect:
        msg_dict['no_speakers'] = int(no_speakers)
    
    if request_json.get('sample_rate_hertz'):
        msg_dict['sample_rate_hertz'] = int(request_json['sample_rate_hertz'])

    msg_str = json.dumps(msg_dict)
    data = msg_str.encode('utf-8')

    publisher.publish(topic_path, data=data)
    app.logger.info("Message: %s successfully published" % data)

    return jsonify({'status': 'PROCESS_STARTED'})


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
