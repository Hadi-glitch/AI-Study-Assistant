# AI Study Assistant

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and paste your key from https://aistudio.google.com/apikey
3. Test the AI part alone: `python gemini_helper.py`
4. Run the app: `python main.py`

## Package as .exe
```
pip install pyinstaller
pyinstaller --onefile --windowed --collect-all customtkinter main.py
```
Put your `.env` file next to `dist/main.exe`.

## Notes
- Never share or upload `.env`.
- Free tier has rate limits: avoid clicking buttons repeatedly.
- Notes are trimmed to 30,000 characters (see MAX_CHARS in gemini_helper.py).
