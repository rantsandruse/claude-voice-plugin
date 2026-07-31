from __future__ import annotations
import subprocess
import threading
import httpx

from ..config import ElevenLabsConfig


class ElevenLabsProvider:
    def __init__(self, config: ElevenLabsConfig, api_key: str):
        self._config = config
        self._api_key = api_key

    def speak(self, text: str) -> subprocess.Popen:
        if not text or not text.strip():
            raise ValueError("empty text")
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/"
            f"{self._config.voice_id}/stream"
        )
        headers = {
            "xi-api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        body = {"text": text, "model_id": self._config.model}

        # Probe with a HEAD-style small request? No — do a streaming GET/POST
        # and raise if the initial response is non-2xx before spawning afplay.
        client = httpx.Client(timeout=60)
        stream_ctx = client.stream("POST", url, headers=headers, json=body)
        resp = stream_ctx.__enter__()
        try:
            if resp.status_code >= 300:
                body_snippet = resp.read()[:200].decode(errors="replace")
                raise RuntimeError(f"ElevenLabs {resp.status_code}: {body_snippet}")
        except RuntimeError:
            resp.close()
            client.close()
            raise

        afplay = subprocess.Popen(["afplay", "-"], stdin=subprocess.PIPE)

        def _pump():
            try:
                for chunk in resp.iter_bytes():
                    if afplay.stdin is None:
                        break
                    try:
                        afplay.stdin.write(chunk)
                    except (BrokenPipeError, ValueError):
                        break
            finally:
                try:
                    if afplay.stdin:
                        afplay.stdin.close()
                except Exception:
                    pass
                resp.close()
                client.close()
                # Keep stream_ctx alive until we're done to prevent GC-triggered close
                _ = stream_ctx

        threading.Thread(target=_pump, daemon=True).start()
        return afplay
