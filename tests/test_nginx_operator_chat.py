from pathlib import Path


def test_operator_chat_proxy_has_upload_rate_and_websocket_rules():
    source = Path("conf.d/default.conf").read_text(encoding="utf-8")
    assert "zone=operator_chat_rest:10m rate=10r/s" in source
    assert "zone=operator_chat_ws:10m rate=5r/s" in source
    assert "location = /api_v1/chat/operator/ws" in source
    assert "location ^~ /api_v1/chat/operator/" in source
    assert "client_max_body_size 205m" in source
    assert "limit_req zone=operator_chat_rest burst=20 nodelay" in source
    assert "limit_req zone=operator_chat_ws burst=10 nodelay" in source
    assert "proxy_set_header Upgrade $http_upgrade" in source
