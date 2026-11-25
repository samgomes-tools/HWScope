"""Configuração dos testes: cria o PC simulado ANTES de importar core.hwinfo
(que lê HWSCOPE_ROOT na importação) e isola a pasta de configuração."""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fakesys  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="hwscope-test-")
FAKE_ROOT = fakesys.build(os.path.join(_TMP, "root"))
os.environ["HWSCOPE_ROOT"] = FAKE_ROOT
os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP, "config")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
