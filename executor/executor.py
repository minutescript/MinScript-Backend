import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import json
import time

# Imports the Google Cloud client library
from google.cloud import speech_v1p1beta1 as speech

from google.gax.errors import GaxError
from google.cloud import pubsub
from google.cloud import storage



FIREBASE_CERT_PATH = os.environ['FIREBASE_CERT_PATH']
cred = credentials.Certificate(FIREBASE_CERT_PATH)
firebase_admin.initialize_app(cred)

BUCKET_NAME = 'minutescript'
RECORDINGS_FOLDER = 'recordings'


PROJECT_ID = 'minutescript-prod'
TOPIC = 'transcription-requests'

# Instantiates a client
client = speech.SpeechClient()
db = firestore.client()
storage_client = storage.Client()


def transcribe(uri, user_id, filename, main_lang, extra_lang, diarize, auto_detect, no_speakers):
    # The name of the audio file to transcribe
    full_recording_file_name = RECORDINGS_FOLDER + '/' + user_id + '/' + filename

    mime_type = storage_client.get_bucket(BUCKET_NAME).get_blob(full_recording_file_name).content_type
    audio = speech.types.RecognitionAudio(uri=uri)
    log.info("MimeType: %s" % mime_type)

    # User ID
    log.info("Processing for user ID: %s" % user_id)
    log.info("Recording URI: %s" % uri)

    # Config
    config = {
        'encoding': speech.enums.RecognitionConfig.AudioEncoding.LINEAR16,
        'sample_rate_hertz': None,
        'language_code': main_lang,
        'alternative_language_codes': extra_lang,
        'enable_word_time_offsets': True,
        'enable_automatic_punctuation': True,
        'max_alternatives': 1,
        'profanity_filter': True,
        'enable_word_confidence': True,
        'enable_speaker_diarization': diarize,
        'audio_channel_count': 1,
        'model': 'video'}

    # handle compatibility for less-supported languages
    if extra_lang or main_lang.lower() != 'en-us':
        config['model'] = 'default'

    # replace with below when Python package updated:
    # diarization_config = {
    #     'enable_speaker_diarization': diarize,
    # }

    if diarize and not auto_detect:
        config['diarization_speaker_count'] = no_speakers
        # diarization_config['min_speaker_count'] = no_speakers - 2
        # diarization_config['max_speaker_count'] = no_speakers + 2

    # config['diarization_config'] = diarization_config

    log.info("Recording config: %s" % config)


    # Fetches ref to user
    doc_ref = db.collection(u'users').document(user_id).collection(u'recordings').document(filename)

    # Detects speech in the audio file
    operation = client.long_running_recognize(config, audio)
    log.info('Speech API operation ID: %s' % operation)

    try:
        _update_transcript_status(doc_ref, 'processing')
        response = operation.result(timeout=3600)
    except GaxError as e:
        _update_transcript_status(doc_ref, 'error: %s' % e)
        sys.exit(-1)

    # Writes transcript to datastore
    log.info("Response received")
    log.debug("Response content: %s" % response)

    full_response_file_name = full_recording_file_name + '_transcript.txt'
    storage_client.get_bucket(BUCKET_NAME) \
        .blob(full_response_file_name) \
        .upload_from_string(
            str(response),
            content_type='text/plain')

    transcript = ""
    for result in response.results:
        transcript += str(result.alternatives[0].transcript) + " \n"

    transcript = str(transcript)

    log.debug("Transcript: %s" % transcript)

    _update_transcript_status(doc_ref, 'success')

    # Writes word timestamps to datastore
    def map_words(word):

        def _get_nanos(timestamp):
            ms = timestamp.nanos / 1000000
            if hasattr(timestamp, 'seconds'):
                ms = timestamp.seconds * 1000 + ms
            if hasattr(timestamp, 'minutes'):
                ms = timestamp.minutes * 60 * 1000 + ms
            if hasattr(timestamp, 'hours'):
                ms = timestamp.hours * 60 * 60 * 1000 + ms

            return ms

        word_dict = {
            u'w': word.word,
            u's': int(_get_nanos(word.start_time)),
            u'e': int(_get_nanos(word.end_time)),
            # added speaker diarization handling
            u'speaker': int(word.speaker_tag)
        }

        return word_dict

    all_words = list()
    # for result in response.results:
    results = response.results

    diarized_result = results[len(results) - 1]
    words = map(lambda word: map_words(word), diarized_result.alternatives[0].words)

    all_words.extend(words)

    doc_ref.update({
        u'transcript': transcript,
        u'word_ts': all_words
    })

    log.info("Transcript and word timestamps written to DB for user ID: %s" % user_id)

    # Updates number of recordings in the admin db
    user_data = db.collection(u'user_metadata').document(user_id)
    user_dict = user_data.get().to_dict()
    num_recordings = user_dict['num_recordings']
    user_data.update({
       u'num_recordings': num_recordings + 1
    })

    log.info("num_recordings for user ID %s changed to %s" % (user_id, num_recordings + 1))


def _update_transcript_status(doc_ref, status):
    doc_ref.update({
        u'transcript_status': str(status)
    })
    log.info("Transcript status updated: %s" % status)


def _setup_custom_logger():
    formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    handler = logging.FileHandler('log.txt', mode='w')
    handler.setFormatter(formatter)
    screen_handler = logging.StreamHandler(stream=sys.stdout)
    screen_handler.setFormatter(formatter)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(screen_handler)
    return logger


if __name__ == '__main__':
    log = _setup_custom_logger()
    subscriber = pubsub.SubscriberClient()
    subscription_path = subscriber.subscription_path(PROJECT_ID, TOPIC)


    def callback(message):
        print('Received message: {}'.format(message))
        message.ack()

        msg_dict = json.loads(message.data.decode("utf-8"))
        uri = msg_dict['uri']
        user_id = msg_dict['user_id']
        filename = msg_dict['filename']
        main_lang = msg_dict['main_lang']
        extra_lang = msg_dict['extra_lang']
        diarize = msg_dict['diarize']
        auto_detect = msg_dict['auto_detect']
        no_speakers = msg_dict['no_speakers']

        transcribe(uri, user_id, filename, main_lang, extra_lang, diarize, auto_detect, no_speakers)


    subscription = subscriber.subscribe(subscription_path, callback=callback)

    log.info('Listening for messages on {}'.format(subscription_path))
    while True:
        time.sleep(60)
