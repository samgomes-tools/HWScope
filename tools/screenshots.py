#!/usr/bin/env python3
"""Gera capturas de todas as abas usando o PC simulado dos testes (útil para o README).

Uso:  python3 tools/screenshots.py [pasta_de_saida]
      ex.: python3 tools/screenshots.py docs/img
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tests"))

out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
os.makedirs(out, exist_ok=True)

import fakesys  # noqa: E402

tmp = tempfile.mkdtemp(prefix="hwscope-shots-")
os.environ["HWSCOPE_ROOT"] = fakesys.build(os.path.join(tmp, "root"))
os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
os.environ["HWSCOPE_SCREENSHOT"] = out
os.environ.setdefault("HWSCOPE_SHOT_DELAY", "4500")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.app import main  # noqa: E402

main()
