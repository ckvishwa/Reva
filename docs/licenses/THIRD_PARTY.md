# Third-party components (voice)

Status: **a record, not legal advice or an approval.** It lists what the Kokoro voice path uses, the
license each package declares in its own metadata (read from the installed packages on 2026-10-14),
and what that implies. **The decision about bundling any of this into a REVA installer is deferred
to S25** (release packaging). Until then the Kokoro interpreter is installed per machine by the
owner; REVA's own repository contains none of these packages or weights.

Scope: the separate Kokoro interpreter (`REVA_KOKORO_PYTHON`, pinned in
`tools/voice/kokoro-requirements.txt`) and the model files under `REVA_ASSET_ROOT`. Core imports
none of it: Core talks to a worker process over JSON lines.

## What needs attention before anything is bundled

| Component | Version | Declared license | Why it matters |
|---|---|---|---|
| `phonemizer-fork` | 3.3.2 | GNU General Public License (package metadata) | Copyleft. Pulled in by `misaki[en]`. Shipping it inside an installer would carry GPL obligations for what is distributed together with it. |
| espeak-ng, via `espeakng-loader` | loader 0.2.4 | The wheel states **no license** of its own; it bundles the espeak-ng library and data, whose upstream project is GPL-3.0-or-later | Same concern, and the wheel's missing license text is itself a gap to resolve. This row records the upstream project's license from general knowledge; it was **not** verified from a file in the wheel. |
| `num2words` | 0.5.14 | LGPL | Weak copyleft: fine to use as a separate library, with relinking/notice obligations if redistributed. |
| `certifi`, `tqdm` | 2026.7.22, 4.70.1 | MPL-2.0 (tqdm: MPL-2.0 AND MIT) | File-level copyleft; unmodified use is straightforward. |

Options for S25, none chosen here: keep the interpreter a per-machine download the owner installs;
replace the G2P path so neither `phonemizer-fork` nor espeak-ng is needed; or obtain a licensing
decision and ship with the required notices and source offers.

## Model and voice

| Component | Declared license | Notes |
|---|---|---|
| Kokoro-82M v1.0 weights and `af_heart` voice (`hexgrad/Kokoro-82M`, revision `f3ff3571791e39611d31c381e3a41a3af07b4987`) | Apache-2.0 (model card metadata and text) | The card lists CC BY audio in the training set that asks for attribution: Koniwa `tnc` (CC BY 3.0, under 1 h) and SIWIS (CC BY 4.0, under 11 h). The card also says training used public-domain and permissively licensed audio and synthetic audio from closed TTS providers; the terms of those providers were **not** verified here. The card is kept beside the weights (`models/tts/kokoro/1.0/README.md`) for attribution. |
| StyleTTS 2 (`yl4579/StyleTTS2-LJSpeech`) | Named by the card as the base model; its license was not checked | Architecture and base weights Kokoro derives from. |

SHA-256 of each file is in `docs/voice/kokoro-assets.manifest.json`.

## Main packages

| Package | Version | Declared license |
|---|---|---|
| `kokoro` | 0.9.4 | Apache License |
| `misaki` | 0.9.4 | Apache License |
| `torch` | 2.14.1 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT |
| `spacy` | 3.8.16 | MIT |
| `numpy` | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `transformers` | 5.19.0 | Apache 2.0 License |
| `huggingface_hub` | 2.2.0 | Apache-2.0 |
| `soundfile` | 0.14.0 | BSD 3-Clause License |
| `en_core_web_sm` | 3.8.0 | MIT |

## Appendix: every package in the Kokoro interpreter

Generated from the installed packages' own metadata. "not stated in the package" means the metadata
has no license field; it does not mean the package has no license.

| Package | Version | Declared license |
|---|---|---|
| `addict` | 2.4.0 | UNKNOWN |
| `annotated-doc` | 0.0.5 | MIT |
| `annotated-types` | 0.8.0 | MIT |
| `anyio` | 4.15.1 | MIT |
| `attrs` | 26.1.0 | MIT |
| `babel` | 2.18.0 | BSD-3-Clause |
| `blis` | 1.3.3 | BSD |
| `catalogue` | 2.0.10 | MIT |
| `certifi` | 2026.7.22 | MPL-2.0 |
| `cffi` | 2.1.1 | MIT-0 |
| `charset-normalizer` | 3.5.2 | MIT |
| `click` | 8.5.0 | BSD-3-Clause |
| `cloudpathlib` | 0.26.0 | MIT License |
| `cloudpickle` | 3.1.2 | BSD-3-Clause |
| `colorama` | 0.4.6 | BSD License |
| `confection` | 1.3.3 | MIT |
| `csvw` | 4.1.0 | Apache 2.0 |
| `curated-tokenizers` | 0.0.10 | MIT |
| `curated-transformers` | 0.1.1 | MIT |
| `cymem` | 2.0.13 | MIT |
| `dlinfo` | 2.0.0 | MIT |
| `docopt` | 0.6.2 | MIT |
| `en_core_web_sm` | 3.8.0 | MIT |
| `espeakng-loader` | 0.2.4 | not stated in the package |
| `filelock` | 4.1.1 | MIT |
| `fsspec` | 2026.9.0 | BSD-3-Clause |
| `h11` | 0.16.0 | MIT |
| `hf-xet` | 1.7.0 | Apache-2.0 |
| `httpcore` | 1.0.9 | BSD-3-Clause |
| `httpcore2` | 2.13.1 | BSD-3-Clause |
| `httpx` | 0.28.1 | BSD-3-Clause |
| `httpx2` | 2.13.1 | BSD-3-Clause |
| `huggingface_hub` | 2.2.0 | Apache-2.0 |
| `idna` | 3.20 | BSD-3-Clause |
| `isodate` | 0.7.2 | Copyright (c) 2021, Hugo van Kemenade and contributors |
| `Jinja2` | 3.1.6 | BSD License |
| `joblib` | 1.6.0 | BSD-3-Clause |
| `jsonschema` | 4.26.0 | MIT |
| `jsonschema-specifications` | 2025.9.1 | MIT |
| `kokoro` | 0.9.4 | Apache License |
| `language-tags` | 1.3.1 | MIT |
| `loguru` | 0.7.3 | MIT License |
| `markdown-it-py` | 4.2.0 | MIT License |
| `MarkupSafe` | 3.0.4 | BSD-3-Clause |
| `mdurl` | 0.1.2 | MIT License |
| `misaki` | 0.9.4 | Apache License |
| `mpmath` | 1.3.0 | BSD |
| `murmurhash` | 1.0.15 | MIT |
| `networkx` | 3.7 | BSD-3-Clause |
| `num2words` | 0.5.14 | LGPL |
| `numpy` | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |
| `phonemizer-fork` | 3.3.2 | GNU GENERAL PUBLIC LICENSE |
| `pip` | 26.2.1 | MIT |
| `preshed` | 3.0.13 | MIT |
| `pycparser` | 3.11 | BSD-3-Clause |
| `pydantic` | 2.14.1 | MIT |
| `pydantic_core` | 2.50.1 | MIT |
| `Pygments` | 2.21.0 | BSD-2-Clause |
| `pyparsing` | 3.3.3 | MIT |
| `python-dateutil` | 2.9.0.post0 | Dual License |
| `PyYAML` | 6.0.3 | MIT |
| `rdflib` | 7.6.0 | BSD-3-Clause |
| `referencing` | 0.37.0 | MIT |
| `regex` | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| `requests` | 2.34.2 | Apache-2.0 |
| `rfc3986` | 1.5.0 | Apache 2.0 |
| `rich` | 15.0.0 | MIT |
| `rpds-py` | 2026.9.1 | MIT |
| `safetensors` | 0.8.0 | Apache Software License |
| `segments` | 2.4.0 | Apache 2.0 |
| `setuptools` | 84.0.0 | MIT |
| `shellingham` | 1.5.4 | ISC License |
| `six` | 1.17.0 | MIT |
| `smart_open` | 8.0.3 | MIT License |
| `soundfile` | 0.14.0 | BSD 3-Clause License |
| `spacy` | 3.8.16 | MIT |
| `spacy-curated-transformers` | 0.3.1 | MIT |
| `spacy-legacy` | 3.0.12 | MIT |
| `spacy-loggers` | 1.0.5 | MIT |
| `srsly` | 2.5.4 | MIT |
| `sympy` | 1.14.0 | BSD |
| `termcolor` | 3.3.0 | MIT |
| `thinc` | 8.3.13 | MIT |
| `tokenizers` | 0.23.3 | Apache Software License |
| `torch` | 2.14.1 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT |
| `tqdm` | 4.70.1 | MPL-2.0 AND MIT |
| `transformers` | 5.19.0 | Apache 2.0 License |
| `truststore` | 0.10.5 | MIT |
| `typer` | 0.27.3 | MIT |
| `typing-inspection` | 0.4.4 | MIT |
| `typing_extensions` | 4.16.0 | PSF-2.0 |
| `uritemplate` | 4.2.0 | BSD 3-Clause OR Apache-2.0 |
| `urllib3` | 2.8.0 | MIT |
| `wasabi` | 1.1.3 | MIT |
| `weasel` | 1.0.0 | MIT |
| `win32_setctime` | 1.2.0 | MIT license |
| `wrapt` | 2.5.1 | BSD-2-Clause |

## Windows app audio (.NET)

| Component | Version | Declared license | Notes |
|---|---|---|---|
| NAudio (meta-package) and its parts `NAudio.Core`, `NAudio.Wasapi`, `NAudio.WinMM`, `NAudio.Asio`, `NAudio.Midi` | 2.2.1 (released 2023, pinned in `Reva.Desktop.csproj`, hashes in `packages.lock.json`) | MIT (read from the package `.nuspec` files on 2026-10-15; the meta-package ships `license.txt`) | Microphone capture and reply playback on WASAPI (decision recorded in `CLAUDE.md`). Permissive: keep the copyright notice with any redistribution. No native code of its own; it calls Windows audio APIs. |

## Avatar page (avatar/)

| Component | Version | Licence | Notes |
|---|---|---|---|
| three | 0.186.1 (2026-09-24) | MIT | Bundled into `avatar/dist/avatar.js`; no CDN. |
| @pixiv/three-vrm and its parts | 3.5.5 (2026-07-09) | MIT | Loads and animates VRM models. |
| esbuild, ajv, playwright-core | 0.28.2, 8.20.0, 1.63.0 | MIT, MIT, Apache-2.0 | Dev tools only (build and tests); not shipped. |
| `assets/avatar/placeholder.vrm` | VRM1_Constraint_Twist_Sample v1.0.1, SHA-256 `12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2` | VRM Consortium licence 1.0 (`https://vrm.dev/licenses/1.0/`), copyright 2022 pixiv Inc. | Read from the file's own VRM metadata on 2026-10-15: redistribution allowed, modification allowed, commercial use by a corporation allowed, credit notation unnecessary. Taken from the pixiv/three-vrm repository examples. Placeholder only; replaced by the owner's Blender model at F0. |
