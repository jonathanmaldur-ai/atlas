"""Reconhece a voz do dono: so ela comanda o Atlas (ignora audio de WhatsApp, videos, outras pessoas)."""
from pathlib import Path

import numpy as np
import sherpa_onnx

BASE = Path(__file__).parent
ARQ_DONO = BASE / "voz_dono.npy"          # impressao digital da voz (fica so no PC, fora do git)
LIMIAR = 0.30                             # similaridade minima para aceitar como o dono

_extrator = sherpa_onnx.SpeakerEmbeddingExtractor(
    sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(BASE / "modelos-voz" / "speaker.onnx"), num_threads=2))
_amostras: list[np.ndarray] = []


def _embedding(pcm: np.ndarray) -> np.ndarray:
    s = _extrator.create_stream()
    s.accept_waveform(16000, pcm)
    s.input_finished()
    e = np.array(_extrator.compute(s), dtype=np.float32)
    return e / (np.linalg.norm(e) + 1e-9)


def cadastrado() -> bool:
    return ARQ_DONO.exists()


def adicionar_amostra(pcm: np.ndarray, ultima: bool) -> int:
    """Junta amostras da voz do dono; na ultima, salva a media como referencia."""
    if len(pcm) < 16000:
        return len(_amostras)
    _amostras.append(_embedding(pcm))
    if ultima and _amostras:
        media = np.mean(_amostras, axis=0)
        np.save(ARQ_DONO, media / np.linalg.norm(media))
        _amostras.clear()
    return len(_amostras)


def similaridade(pcm: np.ndarray) -> float:
    """0 a 1: quanto o audio parece a voz do dono. Sem cadastro, aceita tudo (1.0)."""
    if not cadastrado() or len(pcm) < 8000:
        return 1.0
    return float(np.dot(_embedding(pcm), np.load(ARQ_DONO)))


def apagar():
    ARQ_DONO.unlink(missing_ok=True)
    _amostras.clear()
