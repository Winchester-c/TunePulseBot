from telethon.sync import TelegramClient
from telethon import events
import essentia.standard as es
import os
import tempfile
import logging
import hashlib
import asyncio
from collections import Counter

# Настройки
API_ID = '23394165'
API_HASH = '20f2e730713df85dee458ebe8665c1cd'
BOT_TOKEN = '8346690749:AAGeVgyJD0DarEENVZjGWq0D3nKMvoZ4BcE'
ALLOWED_FORMATS = ['audio/mpeg', 'audio/wav', 'audio/flac', 'audio/x-flac', 'audio/x-wav', 'audio/wave']
MAX_DURATION_SECONDS = 30
TRIM_MS_MP3 = 20
MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1 ГБ
MAX_CACHE_SIZE = 1000

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

client = TelegramClient('bot_session', API_ID, API_HASH)
client.start(bot_token=BOT_TOKEN)

cache = {}

async def analyze_audio(audio_path, file_hash, mime_type):
    if file_hash in cache:
        return cache[file_hash]
    
    def sync_analyze():
        loader = es.MonoLoader(filename=audio_path)
        audio = loader()
        sample_rate = 44100
        logging.info(f"Анализ с частотой дискретизации файла (автоопределение)")
        
        if mime_type == 'audio/mpeg':
            trim_samples = int(0.020 * sample_rate)
            audio = audio[trim_samples:]
            logging.info(f"Обрезано 20 мс ({trim_samples} сэмплов) для MP3")
        
        max_samples = int(MAX_DURATION_SECONDS * sample_rate)
        audio = audio[:min(len(audio), max_samples)]
        
        if len(audio) < sample_rate:
            return f"Аудио слишком короткое ({len(audio)/sample_rate:.2f} сек)."
        
        # BPM
        rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
        bpm, _, _, _, _ = rhythm_extractor(audio)
        
        fractional_part = bpm % 1
        if fractional_part < 0.25:
            bpm_display = int(bpm)
        elif fractional_part < 0.75:
            bpm_display = int(bpm) + 0.5
        else:
            bpm_display = int(bpm) + 1
        
        # Тональность (усреднение по 3 сегментам по 20 секунд)
        segment_duration = int(20 * sample_rate)  # 20 секунд
        segments = [audio[i:i + segment_duration] for i in range(0, len(audio), segment_duration)][:3]
        keys = []
        key_extractor = es.KeyExtractor(profileType='temperley')
        
        for i, seg in enumerate(segments):
            if len(seg) >= sample_rate:
                key, scale, _ = key_extractor(seg)
                keys.append((key, scale))
                logging.info(f"Сегмент {i+1}: Тональность {key} {scale}")
        
        if not keys:
            key, scale, _ = key_extractor(audio)
            keys.append((key, scale))
            logging.info(f"Полное аудио: Тональность {key} {scale}")
        
        # Выбор наиболее частой тональности
        key, scale = Counter(keys).most_common(1)[0][0]
        logging.info(f"Итоговая тональность: {key} {scale}")
        
        result = f"BPM: {bpm_display}\nТональность: {key} {scale}"
        
        if len(cache) >= MAX_CACHE_SIZE:
            cache.pop(list(cache.keys())[0])
        cache[file_hash] = result
        return result
    
    return await asyncio.to_thread(sync_analyze)

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply("Отправьте MP3, WAV или FLAC (до 1 ГБ) для анализа BPM и тональности.")

@client.on(events.NewMessage(incoming=True, func=lambda e: e.message.media and e.message.media.document and e.message.media.document.mime_type in ALLOWED_FORMATS))
async def handle_audio(event):
    mime_type = event.message.media.document.mime_type
    file_size = event.message.media.document.size
    logging.info(f"MIME-тип: {mime_type}, Размер файла: {file_size/1024/1024:.2f} МБ")
    
    if file_size > MAX_FILE_SIZE:
        await event.reply(f"Файл слишком большой ({file_size/1024/1024/1024:.2f} ГБ). Максимум 1 ГБ.")
        return
    
    try:
        file_hash = hashlib.md5(str(event.message.media.document.id).encode()).hexdigest()
        if file_hash in cache:
            await event.reply(cache[file_hash])
            return
        
        suffix = '.flac' if mime_type in ['audio/flac', 'audio/x-flac'] else \
                 '.wav' if mime_type in ['audio/wav', 'audio/x-wav', 'audio/wave'] else '.mp3'
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            await client.download_media(event.message.media, tmp_file, part_size=1024*1024)
            audio_path = tmp_file.name
        
        result = await analyze_audio(audio_path, file_hash, mime_type)
        await event.reply(result)
        
        os.unlink(audio_path)
        
    except Exception as e:
        await event.reply(f"Ошибка: {str(e)}")

print("Бот запущен...")
client.run_until_disconnected()