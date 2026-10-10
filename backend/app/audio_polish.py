"""Original, locally synthesized transition sounds. No samples, voices or downloads."""
import math
import random
import struct
import wave

RATE = 24000
LENGTH = .45   # seconds per sound
LEAD = .15     # the sound swells slightly before the cut and peaks on it


def whoosh(seed=7):
    """Soft filtered noise with a rise-and-fall envelope, as 16-bit mono samples."""
    rng = random.Random(seed);count = round(RATE * LENGTH);low = previous = high = 0.0;out = []
    for n in range(count):
        noise = rng.uniform(-1, 1)
        low += .08 * (noise - low)                  # gentle low-pass
        high = low - previous + .995 * high;previous = low  # remove rumble
        x = n / count
        envelope = math.sin(math.pi * min(1, x / .35) / 2) ** 2 * (1 - max(0, (x - .35) / .65)) ** 2
        out.append(max(-32767, min(32767, round(high * envelope * 9000))))
    return struct.pack('<%dh' % len(out), *out)


def write_cues(path, cues, seconds):
    """Write a mono track with a sound at each cue. Silence is streamed, so long programs stay small in memory."""
    sound = whoosh();sound_frames = len(sound) // 2;total = round(seconds * RATE);cursor = 0
    starts = sorted({max(0, round((cue - LEAD) * RATE)) for cue in cues})
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(RATE)
        for start in starts:
            if start < cursor or start >= total:
                continue  # Overlapping cues merge into the sound already playing.
            gap = start - cursor
            while gap:
                chunk = min(gap, RATE * 10);output.writeframes(b'\0\0' * chunk);gap -= chunk
            frames = min(sound_frames, total - start)
            output.writeframes(sound[:frames * 2]);cursor = start + frames
        remaining = total - cursor
        while remaining > 0:
            chunk = min(remaining, RATE * 10);output.writeframes(b'\0\0' * chunk);remaining -= chunk
