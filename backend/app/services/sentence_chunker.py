"""Incremental sentence splitter for streamed LLM tokens.

Feed token deltas as they arrive; get back complete sentences as soon as a
sentence boundary is seen, so each can be synthesized while the rest streams.
MVP quality: regex-based, may over-split on abbreviations.
"""
from __future__ import annotations

import re

# A sentence ends at . ! ? (optionally followed by a closing quote/bracket),
# then whitespace; or at a newline.
_BOUNDARY = re.compile(r'(.+?(?:[.!?]+["\')\]]?(?=\s)|\n))', re.DOTALL)

# Don't emit trivially short fragments (e.g. a lone "1." ) — keep buffering.
_MIN_SENTENCE_CHARS = 2


class SentenceChunker:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Add a text delta; return any newly-completed sentences."""
        self._buffer += delta
        sentences: list[str] = []
        while True:
            match = _BOUNDARY.match(self._buffer)
            if not match:
                break
            chunk = match.group(1)
            self._buffer = self._buffer[match.end():]
            stripped = chunk.strip()
            if len(stripped) >= _MIN_SENTENCE_CHARS:
                sentences.append(stripped)
            elif stripped:
                # Too short to be its own utterance; re-attach to the buffer.
                self._buffer = stripped + " " + self._buffer
                break
        return sentences

    def flush(self) -> str:
        """Return whatever text remains (the final, unterminated sentence)."""
        remainder = self._buffer.strip()
        self._buffer = ""
        return remainder
