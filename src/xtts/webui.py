from pathlib import Path

import gradio as gr
import json
import logging
import subprocess
import signal
import sys
import requests
import os
import time
import atexit

refresh_symbol = '🔄'


def create_refresh_button(refresh_component, refresh_method, refreshed_args, elem_class, interactive=True):
    """
    Copied from https://github.com/AUTOMATIC1111/stable-diffusion-webui
    """

    def refresh():
        refresh_method()
        args = refreshed_args() if callable(refreshed_args) else refreshed_args

        return gr.update(**(args or {}))

    refresh_button = gr.Button(refresh_symbol, elem_classes=elem_class, interactive=interactive)
    refresh_button.click(
        fn=lambda: {k: tuple(v) if type(k) is list else v for k, v in refresh().items()},
        inputs=[],
        outputs=[refresh_component]
    )

    return refresh_button


######################################
#### ALLTALK ALLOWED STARTUP TIME ####
######################################
startup_wait_time = 30

# Store the current disable level
current_disable_level = logging.getLogger().manager.disable


# load config file in and get settings
def load_config(file_path):
    with open(file_path, "r") as config_file:
        config = json.load(config_file)
    return config


# TODO: check deepspeed config update

def params_update(key):
    params.update(key)
    with open(config_file_path, "w") as config_file:
        json.dump(params, config_file)


#################################################################
#### LOAD PARAMS FROM confignew.json - REQUIRED FOR BRANDING ####
#################################################################
# STARTUP VARIABLE - Create "this_dir" variable as the current script directory
this_dir = Path(__file__).parent.resolve()
config_file_path = this_dir / "confignew.json"
# Load the params dictionary from the confignew.json file
params = load_config(config_file_path)
# Get venv for tts_server
venv = this_dir / "venv" / "Scripts" / "python.exe"

##############################################
#### Update any changes to confignew.json ####
##############################################

update_config_path = this_dir / "system" / "config" / "at_configupdate.json"
downgrade_config_path = this_dir / "system" / "config" / "at_configdowngrade.json"

# Suppress logging
logging.disable(logging.ERROR)
try:
    import deepspeed

    deepspeed_installed = True
except ImportError:
    deepspeed_installed = False
# Restore previous logging level
logging.disable(current_disable_level)


########################
#### STARTUP CHECKS ####
########################
# STARTUP Checks routine
def check_required_files():
    this_dir = Path(__file__).parent.resolve()
    download_script_path = this_dir / "modeldownload.py"
    subprocess.run([venv, str(download_script_path)])


# STARTUP Call Check routine
check_required_files()

##################################################
#### Check to see if a finetuned model exists ####
##################################################
# Set the path to the directory
trained_model_directory = this_dir / "models" / "trainedmodel"
# Check if the directory "trainedmodel" exists
finetuned_model = trained_model_directory.exists()
# If the directory exists, check for the existence of the required files
# If true, this will add a extra option in the Gradio interface for loading Xttsv2 FT
if finetuned_model:
    required_files = ["model.pth", "config.json", "vocab.json"]
    finetuned_model = all(
        (trained_model_directory / file).exists() for file in required_files
    )
if finetuned_model:
    print(f"[{params['branding']}Startup] \033[92mFinetuned model        :\033[93m Detected\033[0m")

####################################################
#### SET GRADIO BUTTONS BASED ON confignew.json ####
####################################################

if params["tts_method_api_tts"]:
    gr_modelchoice = "API TTS"
elif params["tts_method_api_local"]:
    gr_modelchoice = "API Local"
elif params["tts_method_xtts_local"]:
    gr_modelchoice = "XTTSv2 Local"


# Gather the voice files
def get_available_voices():
    return sorted([voice.name for voice in Path(f"{this_dir}/voices").glob("*.wav")])


######################################
#### SUBPROCESS/WEBSERVER STARTUP ####
######################################
base_url = f"http://{params['ip_address']}:{params['port_number']}"
params_update({"base_url": base_url})


##################
#### LOW VRAM ####
##################
# LOW VRAM - Gradio Checkbox handling
def send_lowvram_request(low_vram):
    try:
        params["tts_model_loaded"] = False
        if low_vram:
            audio_path = this_dir / "system" / "at_sounds" / "lowvramenabled.wav"
        else:
            audio_path = this_dir / "system" / "at_sounds" / "lowvramdisabled.wav"
        url = f"{base_url}/api/lowvramsetting?new_low_vram_value={low_vram}"
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, headers=headers)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        json_response = response.json()
        # Check if the low VRAM request was successful
        if json_response.get("status") == "lowvram-success":
            # Update any relevant variables or perform other actions on success
            params["tts_model_loaded"] = True
        return f'<audio src="file/{audio_path}" controls autoplay></audio>'
    except requests.exceptions.RequestException as e:
        # Handle the HTTP request error
        print(f"[{params['branding']}Server] \033[91mWarning\033[0m Error during request to webserver process: {e}")
        return {"status": "error", "message": str(e)}


#####################################
#### MODEL LOADING AND UNLOADING ####
#####################################
# MODEL - Swap model based on Gradio selection API TTS, API Local, XTTSv2 Local
def send_reload_request(tts_method):
    global tts_method_xtts_ft
    try:
        params["tts_model_loaded"] = False
        url = f"{base_url}/api/reload"
        payload = {"tts_method": tts_method}
        response = requests.post(url, params=payload)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        json_response = response.json()
        # Check if the reload operation was successful
        if json_response.get("status") == "model-success":
            # Update tts_tts_model_loaded to True if the reload was successful
            params["tts_model_loaded"] = True
            # Update local script parameters based on the tts_method
            if tts_method == "API TTS":
                params["tts_method_api_local"] = False
                params["tts_method_xtts_local"] = False
                params["tts_method_api_tts"] = True
                params["deepspeed_activate"] = False
                audio_path = this_dir / "system" / "at_sounds" / "apitts.wav"
                tts_method_xtts_ft = False
            elif tts_method == "API Local":
                params["tts_method_api_tts"] = False
                params["tts_method_xtts_local"] = False
                params["tts_method_api_local"] = True
                params["deepspeed_activate"] = False
                audio_path = this_dir / "system" / "at_sounds" / "apilocal.wav"
                tts_method_xtts_ft = False
            elif tts_method == "XTTSv2 Local":
                params["tts_method_api_tts"] = False
                params["tts_method_api_local"] = False
                params["tts_method_xtts_local"] = True
                audio_path = this_dir / "system" / "at_sounds" / "xttslocal.wav"
                tts_method_xtts_ft = False
            elif tts_method == "XTTSv2 FT":
                params["tts_method_api_tts"] = False
                params["tts_method_api_local"] = False
                params["tts_method_xtts_local"] = False
                audio_path = this_dir / "system" / "at_sounds" / "xttsfinetuned.wav"
                tts_method_xtts_ft = True
        return f'<audio src="file/{audio_path}" controls autoplay></audio>'
    except requests.exceptions.RequestException as e:
        # Handle the HTTP request error
        print(f"[{params['branding']}Server] \033[91mWarning\033[0m Error during request to webserver process: {e}")
        return {"status": "error", "message": str(e)}


###################
#### DeepSpeed ####
###################
# DEEPSPEED - Reload the model when DeepSpeed checkbox is enabled/disabled
def send_deepspeed_request(deepspeed_param):
    try:
        params["tts_model_loaded"] = False
        if deepspeed_param:
            audio_path = this_dir / "system" / "at_sounds" / "deepspeedenabled.wav"
        else:
            audio_path = this_dir / "system" / "at_sounds" / "deepspeeddisabled.wav"
        url = f"{base_url}/api/deepspeed?new_deepspeed_value={deepspeed_param}"
        headers = {"Content-Type": "application/json"}
        response = requests.post(url, headers=headers)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        json_response = response.json()
        # Check if the deepspeed request was successful
        if json_response.get("status") == "deepspeed-success":
            # Update any relevant variables or perform other actions on success
            params["tts_model_loaded"] = True
        return f'<audio src="file/{audio_path}" controls autoplay></audio>'
    except requests.exceptions.RequestException as e:
        # Handle the HTTP request error
        print(f"[{params['branding']}Server] \033[91mWarning\033[0m Error during request to webserver process: {e}")
        return {"status": "error", "message": str(e)}


######################################
#### SUBPROCESS/WEBSERVER STARTUP ####
######################################
script_path = this_dir / "tts_server.py"


def signal_handler(sig, frame):
    print(f"[{params['branding']}Shutdown] \033[94mReceived Ctrl+C, terminating subprocess\033[92m")
    if process.poll() is None:
        process.terminate()
        process.wait()  # Wait for the subprocess to finish
    sys.exit(0)


# Attach the signal handler to the SIGINT signal (Ctrl+C)
signal.signal(signal.SIGINT, signal_handler)
# Check if we're running in docker
if os.path.isfile("/.dockerenv"):
    print(
        f"[{params['branding']}Startup] \033[94mRunning in Docker. Please wait.\033[0m"
    )
else:
    # Start the subprocess
    process = subprocess.Popen([venv, script_path])
    # Check if the subprocess has started successfully
    if process.poll() is None:
        print(f"[{params['branding']}Startup] \033[92mTTS Subprocess         :\033[93m Starting up\033[0m")
        # print(f"[{params['branding']}Startup]")
        # print(
        #     f"[{params['branding']}Startup] \033[94m{params['branding']}Settings & Documentation:\033[00m",
        #     f"\033[92mhttp://{params['ip_address']}:{params['port_number']}\033[00m",
        # )
        # print(f"[{params['branding']}Startup]")
    else:
        print(f"[{params['branding']}Startup] \033[91mWarning\033[0m TTS Subprocess Webserver failing to start process")
        print(f"[{params['branding']}Startup] \033[91mWarning\033[0m It could be that you have something on port:",
              params["port_number"], )
        print(
            f"[{params['branding']}Startup] \033[91mWarning\033[0m Or you have not started in a Python environement "
            f"with all the necesssary bits installed")
        print(
            f"[{params['branding']}Startup] \033[91mWarning\033[0m Check you are starting Text-generation-webui with "
            f"either the start_xxxxx file or the Python environment with cmd_xxxxx file.")
        print(
            f"[{params['branding']}Startup] \033[91mWarning\033[0m xxxxx is the type of OS you are on e.g. windows, "
            f"linux or mac.")
        print(
            f"[{params['branding']}Startup] \033[91mWarning\033[0m Alternatively, you could check no other Python "
            f"processes are running that shouldnt be e.g. Restart your computer is the simple way.")
        # Cleanly kill off this script, but allow text-generation-webui to keep running, albeit without this alltalk_tts
        sys.exit(1)

    timeout = startup_wait_time  # Gather timeout setting from startup_wait_time

    # Introduce a delay before starting the check loop
    time.sleep(26)  # Wait 26 secs before checking if the tts_server.py has started up.
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{base_url}/ready")
            if response.status_code == 200:
                break
        except requests.RequestException as e:
            # Print the exception for debugging purposes
            print(
                f"[{params['branding']}Startup] \033[91mWarning\033[0m TTS Subprocess has NOT started up yet, "
                f"Will keep trying for {timeout} seconds maximum. Please wait "
                f"{max(timeout - int(time.time() - start_time), 5)} seconds.")
        time.sleep(5)
    else:
        print(
            f"\n[{params['branding']}Startup] Startup timed out. Full help available here \033["
            f"92mhttps://github.com/erew123/alltalk_tts#-help-with-problems\033[0m")
        print(
            f"[{params['branding']}Startup] On older system you may wish to open and edit \033[94mscript.py\033[0m "
            f"with a text editor and changing the")
        print(
            f"[{params['branding']}Startup] \033[94mstartup_wait_time = 120\033[0m setting to something like \033["
            f"94mstartup_wait_time = 240\033[0m as this will allow")
        print(
            f"[{params['branding']}Startup] AllTalk more time to try load the model into your VRAM. Otherise please "
            f"visit the Github for")
        print(f"[{params['branding']}Startup] a list of other possible troubleshooting options.")

# DEEPSPEED - Display DeepSpeed Checkbox Yes or No
deepspeed_condition = params["tts_method_xtts_local"] == "True" and deepspeed_installed


def ui():
    # Low vram enable, Deepspeed enable, Remove trailing dots
    with gr.Row():
        low_vram = gr.Checkbox(
            value=params["low_vram"], label="Enable Low VRAM Mode"
        )
        low_vram_play = gr.HTML(visible=False)
        deepspeed_checkbox = gr.Checkbox(
            value=params["deepspeed_activate"],
            label="Enable DeepSpeed",
            visible=deepspeed_installed,
        )
        deepspeed_checkbox_play = gr.HTML(visible=False)
        remove_trailing_dots = gr.Checkbox(
            value=params["remove_trailing_dots"], label='Remove trailing "."'
        )

    # TTS method, Character voice selection
    with gr.Row():
        model_loader_choices = ["API TTS", "API Local", "XTTSv2 Local"]
        if finetuned_model:
            model_loader_choices.append("XTTSv2 FT")
        tts_radio_buttons = gr.Radio(
            choices=model_loader_choices,
            label="TTS Method (Each method sounds slightly different)",
            value=gr_modelchoice,  # Set the default value
        )
        tts_radio_buttons_play = gr.HTML(visible=False)
        with gr.Row():
            available_voices = get_available_voices()
            default_voice = params[
                "voice"
            ]  # Check if the default voice is in the list of available voices

            if default_voice not in available_voices:
                default_voice = available_voices[
                    0
                ]  # Choose the first available voice as the default
            # Add allow_custom_value=True to the Dropdown
            voice = gr.Dropdown(
                available_voices,
                label="Character Voice",
                value=default_voice,
                allow_custom_value=True,
            )
            create_refresh_button(
                voice,
                lambda: None,
                lambda: {
                    "choices": get_available_voices(),
                    "value": params["voice"],
                },
                "refresh-button",
            )

    # Temperature, Repetition Penalty
    with gr.Row():
        local_temperature_gr = gr.Slider(
            minimum=0.05,
            maximum=1,
            step=0.05,
            label="Temperature",
            value=params["local_temperature"],
        )
        local_repetition_penalty_gr = gr.Slider(
            minimum=0.5,
            maximum=20,
            step=0.5,
            label="Repetition Penalty",
            value=params["local_repetition_penalty"],
        )

    # Event functions to update the parameters in the backend
    low_vram.change(lambda x: params_update({"low_vram": x}), low_vram, None)
    low_vram.change(lambda x: send_lowvram_request(x), low_vram, low_vram_play, None)
    tts_radio_buttons.change(
        send_reload_request, tts_radio_buttons, tts_radio_buttons_play, None
    )
    deepspeed_checkbox.change(
        send_deepspeed_request, deepspeed_checkbox, deepspeed_checkbox_play, None
    )
    remove_trailing_dots.change(
        lambda x: params_update({"remove_trailing_dots": x}), remove_trailing_dots, None
    )
    voice.change(lambda x: params_update({"voice": x}), voice, None)

    # TSS Settings
    local_temperature_gr.change(
        lambda x: params_update({"local_temperature": x}), local_temperature_gr, None
    )
    local_repetition_penalty_gr.change(
        lambda x: params_update({"local_repetition_penalty": x}),
        local_repetition_penalty_gr,
        None,
    )


################################
#### SUBPORCESS TERMINATION ####
################################
# Register the termination code to be executed at exit
atexit.register(lambda: process.terminate() if process.poll() is None else None)
