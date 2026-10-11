"""Spike: analiza un WAV generado (duración real de voz vs. duración total)."""
import sys

import librosa
import numpy as np

path = sys.argv[1]
y, sr = librosa.load(path, sr=None)
intervals = librosa.effects.split(y, top_db=35)
hop = sr // 10
rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
per_second = [round(float(rms[i * 10:(i + 1) * 10].mean()), 3) for i in range(int(len(y) / sr))]
print(f"sr={sr} dur={len(y) / sr:.2f}s voz_hasta={intervals[-1][1] / sr:.2f}s segmentos={len(intervals)}")
print("rms por segundo:", per_second)
