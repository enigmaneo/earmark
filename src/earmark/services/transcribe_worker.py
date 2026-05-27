"""Standalone faster-whisper transcription worker.

Invoked as a subprocess from the alignment pipeline so the heavy native
buffers (ctranslate2 model weights, onnxruntime VAD session, PyAV decoder
state) live in a short-lived child process and are reclaimed by the OS
when it exits. The FastAPI parent process never imports ``faster_whisper``.

The worker reads its arguments from argparse, transcribes each audio
chunk, writes per-chunk word lists to ``chunk_cache_dir/<idx>.json``, and
emits one JSON object per line on stdout for the parent's progress drain.
Stderr carries normal log output and tracebacks on failure.
"""
import argparse
import gc
import json
import logging
import math
import shutil
import sys
import tempfile
from pathlib import Path

import ffmpeg

logger = logging.getLogger("earmark.transcribe_worker")


def _probe_duration_sync(audio_path: Path) -> float:
    info = ffmpeg.probe(str(audio_path))
    return float(info["format"]["duration"])


def _extract_chunk_sync(
    src: Path, start_s: float, duration_s: float, out_path: Path
) -> None:
    (
        ffmpeg.input(str(src), ss=start_s, t=duration_s)
        .output(str(out_path), ar=16000, ac=1, acodec="pcm_s16le")
        .overwrite_output()
        .run(quiet=True)
    )


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _chunk_words_from_cache(chunk_cache_dir: Path, idx: int) -> list[dict] | None:  # type: ignore[type-arg]
    path = chunk_cache_dir / f"{idx:04d}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["words"]
    except Exception:
        return None


def _write_chunk_cache(chunk_cache_dir: Path, idx: int, words: list[dict]) -> None:  # type: ignore[type-arg]
    path = chunk_cache_dir / f"{idx:04d}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"words": words}), encoding="utf-8")
    tmp.replace(path)


def run(
    audio_path: Path,
    model_name: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
    language: str,
    chunk_seconds: int,
    chunk_cache_dir: Path,
) -> int:
    from faster_whisper import WhisperModel

    total_duration = _probe_duration_sync(audio_path)
    n_chunks = max(1, math.ceil(total_duration / chunk_seconds))
    chunk_cache_dir.mkdir(parents=True, exist_ok=True)

    _emit({"event": "start", "n_chunks": n_chunks, "total_duration": total_duration})

    def _emit_progress(chunk_idx: int, chunk_pct: float) -> None:
        overall = (chunk_idx + max(0.0, min(100.0, chunk_pct)) / 100.0) / n_chunks * 100.0
        _emit({"event": "progress", "percent": overall})

    model_kwargs: dict = {"device": device, "compute_type": compute_type}
    if device == "cpu":
        model_kwargs["cpu_threads"] = cpu_threads

    model = None
    work_dir = Path(tempfile.mkdtemp(prefix="earmark_chunk_"))
    try:
        for i in range(n_chunks):
            start_offset = i * chunk_seconds
            cached = _chunk_words_from_cache(chunk_cache_dir, i)
            if cached is not None:
                logger.info("Using cached chunk %d/%d (%d words)", i + 1, n_chunks, len(cached))
                _emit({"event": "chunk_done", "idx": i, "words": len(cached), "cached": True})
                _emit_progress(i, 100.0)
                continue

            if model is None:
                model = WhisperModel(model_name, **model_kwargs)

            dur = min(float(chunk_seconds), total_duration - start_offset)
            chunk_path = work_dir / f"chunk_{i:04d}.wav"
            _extract_chunk_sync(audio_path, start_offset, dur, chunk_path)

            segments, _info = model.transcribe(
                str(chunk_path),
                beam_size=1,
                best_of=1,
                language=language,
                word_timestamps=True,
                vad_filter=True,
            )

            chunk_words: list[dict] = []
            for segment in segments:
                if segment.end and dur > 0:
                    _emit_progress(i, float(segment.end) / dur * 100.0)
                for w in segment.words or []:
                    if w.start is None or w.end is None or not w.word:
                        continue
                    chunk_words.append({
                        "word": str(w.word).strip(),
                        "start": float(w.start) + start_offset,
                        "end": float(w.end) + start_offset,
                    })

            _write_chunk_cache(chunk_cache_dir, i, chunk_words)
            _emit({"event": "chunk_done", "idx": i, "words": len(chunk_words), "cached": False})
            _emit_progress(i, 100.0)

            try:
                chunk_path.unlink()
            except OSError:
                pass
            gc.collect()

        return 0
    finally:
        del model
        gc.collect()
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    p = argparse.ArgumentParser(description="faster-whisper transcription worker")
    p.add_argument("--audio-path", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--device", required=True)
    p.add_argument("--compute-type", required=True)
    p.add_argument("--cpu-threads", type=int, required=True)
    p.add_argument("--language", required=True)
    p.add_argument("--chunk-seconds", type=int, required=True)
    p.add_argument("--chunk-cache-dir", type=Path, required=True)
    args = p.parse_args()

    try:
        return run(
            audio_path=args.audio_path,
            model_name=args.model,
            device=args.device,
            compute_type=args.compute_type,
            cpu_threads=args.cpu_threads,
            language=args.language,
            chunk_seconds=args.chunk_seconds,
            chunk_cache_dir=args.chunk_cache_dir,
        )
    except Exception:
        logger.exception("transcription failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
