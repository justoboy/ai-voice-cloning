@echo off
:: Set up virtual environment with Python 3.11
py -3.11 -m venv .\src\xtts\venv
call .\src\xtts\venv\Scripts\activate.bat

:: Upgrade pip and install required packages
python -m pip install --upgrade pip
python -m pip install -r .\src\xtts\requirements.txt
python -m pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 --index-url https://download.pytorch.org/whl/cu121

set download_deepspeed=https://huggingface.co/Jmica/rvc/resolve/main/deepspeed-0.14.0-cp311-cp311-win_amd64.whl?download=true
set fileds_name=deepspeed-0.14.0-cp311-cp311-win_amd64.whl

if not exist "%fileds_name%" (
    echo Downloading %fileds_name%...
    curl -L -O "%download_deepspeed%"
    if errorlevel 1 (
        echo Download failed. Please check your internet connection or the URL and try again.
        exit /b 1
    )
) else (
    echo File %fileds_name% already exists, skipping download.
)
python -m pip install deepspeed-0.14.0-cp311-cp311-win_amd64.whl