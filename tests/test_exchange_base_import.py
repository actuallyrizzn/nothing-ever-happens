from bot.exchange.base import ExchangeClient


def test_exchange_client_protocol_is_importable() -> None:
    assert ExchangeClient.__name__ == "ExchangeClient"
