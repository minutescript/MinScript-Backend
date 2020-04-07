import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore
import logging
import json
import time
import math

# Imports the Google Cloud client library
from google.cloud import speech_v1p1beta1 as speech

from google.gax.errors import GaxError
from google.cloud import pubsub
from google.cloud import storage

CONF_FILE = 'config.json'

with open(CONF_FILE) as cfg:
    CONFIG_JSON = json.load(cfg)

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

# launches file conversion if needed
def convertFile(uri, user_id, filename):
    full_recording_file_name = RECORDINGS_FOLDER + '/' + user_id + '/' + filename
    sample_rate_hertz = 48000

    # get the file name prefix
    prefix = filename.split('.')[0]
    # set the extension
    extension = '.ogg'
    # get the destination path
    output_file_name = prefix + extension
    output_file_path = '/tmp/' + output_file_name

    full_new_recording_file_name = RECORDINGS_FOLDER + '/' + user_id + '/' + output_file_name
    
    # download locally
    download_destination = '/tmp/' + filename

    blob = storage_client.get_bucket(BUCKET_NAME).get_blob(full_recording_file_name)
    blob.download_to_filename(download_destination)

    # run conversion
    subprocess.run(
        ['ffmpeg', '-i', download_destination, 
        '-c:a', 'libopus', '-ar', str(sample_rate_hertz), '-ac', '1', 
        output_file_path])
    
    # upload
    blob = storage_client.get_bucket(BUCKET_NAME).blob(full_new_recording_file_name)

    blob.upload_from_filename(filename=output_file_path, content_type='audio/opus')

    # Fetches ref to user
    doc_ref = db.collection(u'users').document(user_id).collection(u'recordings').document(filename)

    # copy old document to the new location
    file_metadata = doc_ref.get().to_dict()
    new_doc_ref = db.collection(u'users').document(user_id).collection(u'recordings').document(output_file_name)
    new_doc_ref.set(file_metadata)

    # delete old document
    doc_ref.delete()

    # delete redundant cloud files too
    blob = storage_client.get_bucket(BUCKET_NAME).blob(full_recording_file_name)
    blob.delete()

    # prepare metadata update
    new_uri = 'gs://' + BUCKET_NAME + '/' + full_new_recording_file_name
    
    update_dict = {
        u'file_name': output_file_name,
        u'format': 'audio/opus',
        u'sample_rate_hertz': sample_rate_hertz,
        u'uri': new_uri
    }

    # update metadata
    new_doc_ref.update(update_dict)

    # delete local temp files
    os.remove(download_destination)
    os.remove(output_file_path)

    # return:
    return new_uri, output_file_name, sample_rate_hertz

# function called after message processed
def transcribe(uri, user_id, filename, main_lang, extra_lang, diarize, auto_detect, no_speakers, sample_rate_hertz=None):
    # The name of the audio file to transcribe
    full_recording_file_name = RECORDINGS_FOLDER + '/' + user_id + '/' + filename

    mime_type = storage_client.get_bucket(BUCKET_NAME).get_blob(full_recording_file_name).content_type

    # if submitted file is an mp4, convert and try again
    if mime_type == 'audio/mp4':
        new_uri, new_filename, new_sample_rate_hertz = convertFile(uri, user_id, filename)
        return transcribe(new_uri, user_id, new_filename, main_lang, extra_lang, diarize, auto_detect, no_speakers, new_sample_rate_hertz)

    audio = speech.types.RecognitionAudio(uri=uri)
    log.info("MimeType: %s" % mime_type)

    # User ID
    log.info("Processing for user ID: %s" % user_id)
    log.info("Recording URI: %s" % uri)

    # Config
    config = {
        'sample_rate_hertz': sample_rate_hertz,
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

    if mime_type == 'audio/wave':
        config['encoding'] = speech.enums.RecognitionConfig.AudioEncoding.LINEAR16
    
    if mime_type == 'audio/opus':
        config['encoding'] = speech.enums.RecognitionConfig.AudioEncoding.OGG_OPUS

    # handle compatibility for less-supported languages
    if extra_lang or main_lang.lower() != 'en-us':
        config['model'] = 'default'

    if main_lang.lower() != 'en-us':
        config['enable_speaker_diarization'] = False

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
    used_minutes = user_dict['used_minutes']

    audio_metadata = doc_ref.get().to_dict()
    duration = audio_metadata['length']
    duration_min = math.floor(duration / 60)
    
    user_data.update({
       u'used_minutes': used_minutes + duration_min
    })

    log.info("used_minutes for user ID %s changed to %s" % (user_id, used_minutes + duration_min))


def _update_transcript_status(doc_ref, status):
    doc_ref.update({
        u'transcript_status': str(status)
    })
    log.info("Transcript status updated: %s" % status)


def _setup_custom_logger():
    formatter = logging.Formatter(fmt='%(asctime)s %(levelname)-8s %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')
    handler = logging.FileHandler(CONFIG_JSON['log_output'], mode='w')
    handler.setFormatter(formatter)
    screen_handler = logging.StreamHandler(stream=sys.stdout)
    screen_handler.setFormatter(formatter)
    logger = logging.getLogger(__name__)
    logger.setLevel(CONFIG_JSON['log_level'])
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
        
        if ('sample_rate_hertz' in msg_dict):
            sample_rate_hertz = msg_dict['sample_rate_hertz']
            transcribe(uri, user_id, filename, main_lang, extra_lang, diarize, auto_detect, no_speakers, sample_rate_hertz)
        else:
            transcribe(uri, user_id, filename, main_lang, extra_lang, diarize, auto_detect, no_speakers)


    subscription = subscriber.subscribe(subscription_path, callback=callback)

    log.info('Listening for messages on {}'.format(subscription_path))
    while True:
        time.sleep(60)
