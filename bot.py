from telethon.sync import TelegramClient
from telethon import events
import librosa
import numpy as np
import os
import tempfile
import logging
import hashlib
import asyncio

# Настройки
API_ID = '23394165'
API_HASH = '20f2e730713df85dee458ebe8665c1cd'
BOT_TOKEN = '8346690749:AAGeVgyJD0DarEENVZjGWq0D3nKMvoZ4BcE'
ALLOWED_FORMATS = ['audio/mpeg', 'audio/wav', 'audio/flac', 'audio/x-flac', 'audio/x-wav', 'audio/wave']
MAX_DURATION_SECONDS = 60
TRIM_MS_MP3 = 20
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_CACHE_SIZE = 1000

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Инициализация
client = TelegramClient('bot_session', API_ID, API_HASH)
client.start(bot_token=BOT_TOKEN)

cache = {}

async def analyze_audio(audio_path, file_hash, mime_type):
    if file_hash in cache:
        return cache[file_hash]
    
    def sync_analyze():
        y, sr = librosa.load(audio_path, sr=None, mono=True, duration=MAX_DURATION_SECONDS)
        logging.info(f"Анализ с частотой дискретизации: {sr} Гц")
        
        if mime_type == 'audio/mpeg':
            trim_samples = int(0.020 * sr)
            y = y[trim_samples:]
            logging.info(f"Обрезано 20 мс ({trim_samples} сэмплов) для MP3")
        
        if len(y) < sr:
            return f"Аудио слишком короткое ({len(y)/sr:.2f} сек)."
        
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        
        fractional_part = tempo % 1
        if fractional_part < 0.25:
            bpm_display = int(tempo)
        elif fractional_part < 0.75:
            bpm_display = int(tempo) + 0.5
        else:
            bpm_display = int(tempo) + 1
        
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        key_profiles = {
            'C': [0.181, 0.061, 0.104, 0.068, 0.148, 0.053, 0.099, 0.122, 0.051, 0.083, 0.053, 0.077],
            'A♭': [0.077, 0.181, 0.061, 0.104, 0.068, 0.148, 0.053, 0.099, 0.122, 0.051, 0.083, 0.053]
        }
        correlations = {key: np.corrcoef(np.mean(chroma, axis=1), profile)[0, 1] for key, profile in key_profiles.items()}
        key = max(correlations, key=correlations.get)
        scale = 'major'
        
        result = f"BPM: {bpm_display}\nТональность: {key} {scale}"
        
        if len(cache) >= MAX_CACHE_SIZE:
            cache.pop(list(cache.keys())[0])
        cache[file_hash] = result
        return result
    
    return await asyncio.to_thread(sync_analyze)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.respond("Отправьте MP3, WAV или FLAC (до 50 МБ) для анализа BPM и тональности.")

@client.on(events.NewMessage)
async def handle_audio(event):
    if event.message.media and event.message.media.document:
        mime_type = event.message.media.document.mime_type
        file_size = event.message.media.document.size
        logging.info(f"MIME-тип: {mime_type}, Размер файла: {file_size/1024/1024:.2f} МБ")
        
        if file_size > MAX_FILE_SIZE:
            await event.respond(f"Файл слишком большой ({file_size/1024/1024:.2f} МБ). Максимум 50 МБ.")
            return
        
        if mime_type not in ALLOWED_FORMATS:
            await event.respond(f"Отправьте MP3, WAV или FLAC файл. Получен MIME-тип: {mime_type}")
            return
        
        try:
            file_hash = hashlib.md5(str(event.message.media.document.id).encode()).hexdigest()
            if file_hash in cache:
                await event.respond(cache[file_hash])
                return
            
            suffix = '.flac' if mime_type in ['audio/flac', 'audio/x-flac'] else \
                     '.wav' if mime_type in ['audio/wav', 'audio/x-wav', 'audio/wave'] else '.mp3'
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                await client.download_media(event.message.media, tmp_file)
                audio_path = tmp_file.name
            
            result = await analyze_audio(audio_path, file_hash, mime_type)
            await event.respond(result)
            
            os.unlink(audio_path)
            
        except Exception as e:
            await event.respond(f"Ошибка: {str(e)}")

print("Бот запущен...")
client.run_until_disconnected()