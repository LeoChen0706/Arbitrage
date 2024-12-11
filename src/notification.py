from notification import NotificationHandler
import time

def main():
    print("Starting notification test...")
    handler = NotificationHandler()
    
    test_message = {
        'symbol': 'TEST/USDT',
        'direction': 'Test',
        'best_spread': 1.0,
        'executable_volume': 1000,
        'supported_networks': ['TEST'],
        'bitget_ask': 1.0,
        'bitget_bid': 1.0,
        'mexc_ask': 1.0,
        'mexc_bid': 1.0,
        'min_liquidity_score': 8.0
    }
    
    print("Waiting 5 seconds before sending...")
    time.sleep(5)
    handler.send_opportunity(test_message)
    print("Test complete")

if __name__ == "__main__":
    main()
