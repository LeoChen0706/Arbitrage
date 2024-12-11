import ccxt
import time
import logging
import os
import traceback
from pathlib import Path
import configparser
from typing import List, Dict, Tuple, Optional
import pandas as pd
from datetime import datetime
import numpy as np
from .notification import NotificationHandler

def load_config():
    """Load configuration from config file"""
    config = configparser.ConfigParser()
    config_path = 'config/config.ini'
    if not Path(config_path).exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    config.read(config_path)
    return config

def setup_logging():
    """Setup logging configuration"""
    Path("logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/trading.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

class EnhancedTrading:
    def __init__(self):
        self.logger = setup_logging()
        print("Starting program...")
        print("Checking environment variables:")
        print(f"Telegram Bot Token exists: {'TELEGRAM_BOT_TOKEN' in os.environ}")
        print(f"Telegram Chat ID exists: {'TELEGRAM_CHAT_ID' in os.environ}")
        
        # Load config and check its contents
        self.config = load_config()
        print("Config file exists, contents:")
        if Path('config/config.ini').exists():
            with open('config/config.ini', 'r') as f:
                print(f.read())
        
        self.setup_exchanges()
        self.token_info_cache = {}
        self.volume_threshold = 10000  # Minimum 24h volume (USDT)
        self.depth_threshold = 1000    # Minimum order depth (USDT)
        self.min_liquidity_score = 7   # Minimum liquidity score (1-10)
        self.notification_handler = NotificationHandler()
        
        # Send test notification
        print("Sending test notification...")
        test_message = {
            'symbol': 'TEST/USDT',
            'direction': 'Test',
            'best_spread': 1.0,
            'executable_volume': 1000,
            'supported_networks': ['TEST'],
            'bitget_ask': 1.0,
            'bitget_bid': 1.0,
            'mexc_ask': 1.0,
            'mexc_bid': 1.0
        }
        self.notification_handler.send_opportunity(test_message)
        print("Test notification sent")

    # [Rest of your EnhancedTrading class methods remain the same]

def main():
    try:
        trader = EnhancedTrading()
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
