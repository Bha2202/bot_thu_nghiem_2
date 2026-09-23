from storage.market_store import MarketStore


store = MarketStore()

store.save(
    symbol="FPT",
    price=150.5,
    volume=100000,
    bid=150.4,
    ask=150.6,
    data_type="test"
)

print(store.get_latest("FPT"))