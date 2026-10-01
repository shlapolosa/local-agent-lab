"""The voiceprint model as a service, and the two adapters that use it.

  service  — the MODEL behind a bearer-guarded HTTP endpoint: WAV clips in, unit vectors out. It holds
             no data and no credential beyond the shared secret, and ships in its OWN image so the
             model's runtime (PyTorch, ~1 GB) never weighs on the image every other service pulls.
  client   — `HttpEmbedder`, the `SpeakerEmbedder` port as speech-mcp reaches that service.
  gallery  — `PostgresGallery`, the `VoiceprintGallery` port: vectors only, never audio.

The RULES — what is suggested, what may be kept — are pure domain code in `lab.core.speech.voiceprint`.
"""
