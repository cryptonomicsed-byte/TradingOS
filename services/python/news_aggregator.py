import os

class NewsAggregator:
    """
    Intelligence News Aggregator.
    """
    def fetch_latest_news(self):
        print("🗞️ Fetching news from CoinDesk, Decrypt, and The Block...")
        # Mocking news feed
        return [
            {"source": "CoinDesk", "title": "SOL Surges 10%", "sentiment": 0.8},
            {"source": "Decrypt", "title": "New ETF Approved", "sentiment": 0.9}
        ]

if __name__ == "__main__":
    aggregator = NewsAggregator()
    print(aggregator.fetch_latest_news())
