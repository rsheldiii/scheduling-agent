"""Tests for src.voices."""

from src.voices import DEFAULT_VOICE, VOICES, is_valid_voice, list_voices


class TestVoices:
    def test_default_voice_in_voices(self):
        assert DEFAULT_VOICE in VOICES

    def test_is_valid_voice_known(self):
        assert is_valid_voice("alloy") is True
        assert is_valid_voice("cedar") is True

    def test_is_valid_voice_case_insensitive(self):
        assert is_valid_voice("ALLOY") is True
        assert is_valid_voice("Cedar") is True

    def test_is_valid_voice_unknown(self):
        assert is_valid_voice("nonexistent") is False

    def test_list_voices_returns_all(self):
        result = list_voices()
        assert len(result) == len(VOICES)
        ids = {v["id"] for v in result}
        assert ids == set(VOICES.keys())

    def test_list_voices_structure(self):
        for entry in list_voices():
            assert "id" in entry
            assert "description" in entry
            assert isinstance(entry["description"], str)
