"""Processo do Modo administrador: protocolo e validação (roda sem root, sem pkexec)."""
import time

from core import rootbroker


def test_broker_code_compiles():
    compile(rootbroker.broker_code(), "broker", "exec")


def test_broker_validates_requests():
    c = rootbroker.Client()
    c.start(cmd_prefix=())
    for _ in range(100):
        if c.active:
            break
        time.sleep(0.05)
    assert c.active
    try:
        assert c.call("smart", dev="/etc/passwd")["err"] == "dispositivo inválido"
        assert c.call("nao_existe")["err"] == "operação desconhecida"
        assert "data" in c.call("serials")
        rid, q = c.stream_queue("surface", dev="/dev/../etc/shadow", ncell=10, mode="quick")
        item = q.get(timeout=10)
        assert item[0] == "end"
    finally:
        c.stop()
