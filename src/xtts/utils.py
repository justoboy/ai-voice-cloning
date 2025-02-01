import html
import json
import os.path
import subprocess
import requests
import threading

import shutil
from pathlib import Path
from datetime import datetime, timedelta
import logging

this_dir = Path(__file__).parent.resolve()
config_file_path = this_dir / "confignew.json"

#########################################
#### Continue on with Startup Checks ####
#########################################

# Required for sentence splitting
# try:
#     from TTS.api import TTS
#     from TTS.utils.synthesizer import Synthesizer
# except ModuleNotFoundError:
#     # Inform the user about the missing module and suggest next steps
#     print(
#         f"[]\033[91mWarning\033[0m Could not find the TTS module. Make sure to install the requirements for the "
#         f"extension.")
#     print(
#         f"[]\033[91mWarning\033[0m Please use the ATSetup utility or check the Github installation instructions.")
#     # Re-raise the ModuleNotFoundError to stop the program and print the traceback
#     raise

###########################
#### STARTUP VARIABLES ####
###########################
# Create a global lock
process_lock = threading.Lock()
# Base setting for a possible FineTuned model existing and the loader being available
tts_method_xtts_ft = False

# Set the default for Narrated text without asterisk or quotes to be Narrator
non_quoted_text_is = True


#############################################################
#### TTS STRING CLEANING & PROCESSING PRE SENDING TO TTS ####
#############################################################
# def new_split_into_sentences(self, text):
#     sentences = self.seg.segment(text)
#     if params["remove_trailing_dots"]:
#         sentences_without_dots = []
#         for sentence in sentences:
#             if sentence.endswith(".") and not sentence.endswith("..."):
#                 sentence = sentence[:-1]
#
#             sentences_without_dots.append(sentence)
#
#         return sentences_without_dots
#     else:
#         return sentences
#
#
# Synthesizer.split_into_sentences = new_split_into_sentences


# Check model is loaded and string isnt empty, before sending a TTS request.
def before_audio_generation(params):
    # Check Model is loaded into cuda or cpu and error if not
    if not params["tts_model_loaded"]:
        print(
            f"[{params['branding']}Model] \033[91mWarning\033[0m Model is still loading, please wait before trying to "
            f"generate TTS")
        return
    string = html.unescape(params['text'])
    if string == "":
        return "*Empty string*"
    return string


# PREVIEW VOICE- Generate TTS Function
def voice_preview(params, output_folder, progress=None):
    with open(config_file_path, "r") as config_file:
        config = json.load(config_file)
    config['text'] = params['text']
    if progress is not None:
        progress(f"Loading voice: {config['voice']}")
    print(f"[{config['branding']}TTSGen] Loading voice: {config['voice']}")
    output_file = os.path.join(output_folder, config['voice'])
    # Clean the string, capture model not loaded, and move model to cuda if needed
    cleaned_string = before_audio_generation(config)
    if cleaned_string is None:
        return None
    string = cleaned_string
    # Generate the audio
    if progress is not None:
        progress(f"Generating line...")
    # Lock before making the generate request
    with process_lock:
        generate_response = send_generate_request(
            string,
            config,
            output_file,
        )
    # Check if lock is already acquired
    if process_lock.locked():
        print(
            f"[{config['branding']}Model] \033[91mWarning\033[0m Audio generation is already in progress. Please wait.")
        return
    if generate_response.get("status") == "generate-success":
        return [output_file]
    else:
        # Handle the case where audio generation was not successful
        print(f"[{config['branding']}Server] Audio generation failed: {generate_response.get('message')}")
        return {'error': generate_response.get('message')}


###############################################
#### SEND GENERATION REQUEST TO TTS ENGINE ####
###############################################
def send_generate_request(
        text, params, output_file
):
    url = f"{params['base_url']}/api/generate"
    payload = {
        "text": text,
        "voice": params["voice"],
        "language": "en",
        "temperature": params["local_temperature"],
        "repetition_penalty": params["local_repetition_penalty"],
        "output_file": output_file,
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)
    return response.json()
