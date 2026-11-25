#!/usr/bin/env python3
"""
HWScope — monitor de hardware para Linux.
Temperaturas e uso em tempo real + informações detalhadas (estilo CPU-Z / GPU-Z).

Estrutura:
  core/  coleta de dados (sysfs, SMART, SPD, rede...), sem dependência de Qt
  ui/    interface gráfica (uma aba por arquivo)
  data/  bancos de IDs (PCI, USB, fabricantes de memória)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
