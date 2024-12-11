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

def setup_logging():
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

# [Previous code remains the same until EnhancedTrading class]

class EnhancedTrading:
    def __init__(self):
        self.logger = setup_logging()
        self.config = load_config()
        self.setup_exchanges()
        self.token_info_cache = {}
        self.volume_threshold = 10000  # Minimum 24h volume (USDT)
        self.depth_threshold = 1000    # Minimum order depth (USDT)
        self.min_liquidity_score = 7   # Minimum liquidity score (1-10)
        self.notification_handler = NotificationHandler()

    # [Previous methods remain the same until find_arbitrage_opportunities]

    def find_arbitrage_opportunities(self) -> None:
        """Find and notify about the best arbitrage opportunities"""
        try:
            self.logger.info("Starting arbitrage search...")
            
            common_symbols = self.get_common_symbols()
            self.logger.info(f"Found {len(common_symbols)} verified common pairs")
            
            opportunities = []
            for symbol in common_symbols:
                result = self.calculate_arbitrage(symbol)
                if result and \
                   result['best_spread'] > 0 and \
                   result['min_liquidity_score'] >= self.min_liquidity_score and \
                   result['executable_volume'] >= self.depth_threshold:
                    opportunities.append(result)
                time.sleep(self.exchange1.rateLimit / 1000)
            
            # Sort by combined factors
            opportunities.sort(key=lambda x: (
                x['best_spread'] * 
                x['min_liquidity_score'] * 
                min(1, x['executable_volume'] / self.depth_threshold)
            ), reverse=True)
            
            # Get top opportunities
            top_opportunities = opportunities[:5]
            
            # Save to CSV and notify
            if top_opportunities:
                # Save to CSV
                df = pd.DataFrame(top_opportunities)
                filename = f"arbitrage_opportunities_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                df.to_csv(filename, index=False)
                self.logger.info(f"Opportunities saved to {filename}")
                
                # Send notifications for each opportunity
                for opp in top_opportunities:
                    self.notification_handler.send_opportunity(opp)
            
            # Log details
            self.logger.info("\nBest arbitrage opportunities:")
            for opp in top_opportunities:
                self.logger.info(
                    f"\nPair: {opp['symbol']}\n"
                    f"Direction: {opp['direction']}\n"
                    f"Spread: {opp['best_spread']}%\n"
                    f"Bitget price: {opp['bitget_ask']}/{opp['bitget_bid']} "
                    f"(Depth: {opp['bitget_depth']} USDT, "
                    f"24h volume: {opp['bitget_volume_24h']} USDT, "
                    f"Liquidity score: {opp['bitget_liquidity_score']})\n"
                    f"MEXC price: {opp['mexc_ask']}/{opp['mexc_bid']} "
                    f"(Depth: {opp['mexc_depth']} USDT, "
                    f"24h volume: {opp['mexc_volume_24h']} USDT, "
                    f"Liquidity score: {opp['mexc_liquidity_score']})\n"
                    f"Executable volume: {opp['executable_volume']} USDT\n"
                    f"Supported networks: {', '.join(opp['supported_networks'])}"
                )
            
        except Exception as e:
            self.logger.error(f"Error finding arbitrage opportunities: {str(e)}")

def main():
    try:
        print("Starting program...")
        print("Checking environment variables:")
        print(f"Telegram Bot Token exists: {'TELEGRAM_BOT_TOKEN' in os.environ}")
        print(f"Telegram Chat ID exists: {'TELEGRAM_CHAT_ID' in os.environ}")
        
        # Check config file
        if Path('config/config.ini').exists():
            print("Config file exists, contents:")
            with open('config/config.ini', 'r') as f:
                print(f.read())
        else:
            print("Config file not found!")
            
        trader = EnhancedTrading()
        print("Successfully created trader instance")
        
        # Test Telegram notification
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
        print("Sending test notification...")
        trader.notification_handler.send_opportunity(test_message)
        print("Test notification sent")
        
        trader.find_arbitrage_opportunities()
    except Exception as e:
        print(f"Program execution failed: {str(e)}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
